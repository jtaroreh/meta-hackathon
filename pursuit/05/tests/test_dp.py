import numpy as np
import torch
from torch import nn

from pursuit05 import dp, exact, screen
from pursuit05.cells import CellRegistry
from pursuit05.policy import decision_table, fit_final_threshold, table_decider


def test_best_history_at_least_best_static():
    reg = CellRegistry()
    for cell in reg.all_cells():
        pre = reg.pre(cell)
        f = screen.run_F(pre, cell.p)
        bound = f["inf"] * (1.0 + screen.INF_REL) + screen.INF_ABS
        s = exact.best_static(pre, cell.p, f["inf"])
        h = dp.best_history(pre, cell.p, f["inf"])
        assert h.result.inf <= bound + 1e-12, cell.cell_id
        assert h.result.W <= s.result.W + 1e-12, cell.cell_id
        assert h.result.arm == "H"
        assert not h.fallback, cell.cell_id
        assert h.nodes <= 100_000, cell.cell_id
        assert all(pt.gap >= 0.0 for pt in h.pareto), cell.cell_id


def _node_index(pre):
    nodes = []
    pos = {}
    for k in range(pre["T"] - 1):
        for cw in (pre["cw1"], pre["cw2"]):
            for row in np.unique(cw[:, : k + 1], axis=0):
                vals = tuple(int(v) for v in row)
                if any(vals) and (k, vals) not in pos:
                    pos[(k, vals)] = len(nodes)
                    nodes.append((k, vals))
    paths = []
    for cw in (pre["cw1"], pre["cw2"]):
        mat = np.full((cw.shape[0], pre["T"] - 1), -1)
        for k in range(pre["T"] - 1):
            for r in range(cw.shape[0]):
                vals = tuple(int(v) for v in cw[r, : k + 1])
                if any(vals):
                    mat[r, k] = pos[(k, vals)]
        paths.append(mat)
    return nodes, paths


def _brute_force_min(pre, p, bound):
    nodes, (u1, u2) = _node_index(pre)
    nassign = 2 ** len(nodes)
    bits = (np.arange(nassign)[:, None] >> np.arange(len(nodes))[None, :]) & 1
    bits = bits.astype(bool)
    best = float("inf")
    n1 = u1.shape[0]
    n2 = u2.shape[0]
    big_l = float(pre["L1"])
    p0 = (1.0 - p) ** big_l
    p1 = big_l * p * (1.0 - p) ** (big_l - 1.0)
    p2 = (big_l * (big_l - 1.0) / 2.0) * p**2 * (1.0 - p) ** (big_l - 2.0)
    pt = max(0.0, 1.0 - p0 - p1 - p2)
    vf = pre["Vf"]
    for fth in (0, 1, 2):
        for lo in range(0, nassign, 4096):
            bb = bits[lo : lo + 4096]
            outs = []
            for u, fw, nt in (
                (u1, pre["fw1"], None),
                (u2, pre["fw2"], pre["nt2"]),
            ):
                n = u.shape[0]
                aborted = np.full((bb.shape[0], n), -1)
                alive = np.ones((bb.shape[0], n), dtype=bool)
                for k in range(pre["T"] - 1):
                    uk = u[:, k]
                    known = uk >= 0
                    hit = np.zeros((bb.shape[0], n), dtype=bool)
                    hit[:, known] = bb[:, uk[known]]
                    hit &= alive
                    aborted[hit] = k
                    alive[hit] = False
                sp = np.where(
                    aborted >= 0, pre["spent"][np.maximum(aborted, 0)], vf
                )
                acc = (aborted < 0) & (fw[None, :] <= fth)
                outs.append((acc.mean(axis=1), sp.mean(axis=1), acc, nt))
            (a1f, v1, _, _), (a2f, v2, acc2, nt2) = outs
            l2f = (acc2 & nt2[None, :]).mean(axis=1) if n2 else np.zeros_like(a2f)
            pacc = p0 + p1 * a1f + p2 * a2f
            e = p0 * vf + p1 * v1 + p2 * v2 + pt * vf
            w = e / pacc - vf
            inf = (p1 * a1f + p2 * l2f) / pacc
            feas = w[inf <= bound]
            if len(feas):
                best = min(best, float(feas.min()))
    assert n1 == pre["L1"]
    return best


def test_best_history_matches_brute_force_on_tiny():
    tiny = screen.build_cell(6, tiny=True, drop=())
    pre = screen.precompute(tiny, list(range(tiny["C"])), 3)
    for p in screen.P_ERRS:
        f = screen.run_F(pre, p)
        bound = f["inf"] * (1.0 + screen.INF_REL) + screen.INF_ABS
        h = dp.best_history(pre, p, f["inf"])
        floor = _brute_force_min(pre, p, bound)
        assert abs(h.result.W - floor) <= 1e-9, p


class _StaticPolicy(nn.Module):
    def __init__(self, ath, fth, t):
        super().__init__()
        self.ath = tuple(ath)
        self.fth = fth
        self.t = t
        self.dummy = nn.Parameter(torch.zeros(1))

    def forward_eval(self, obs, state=None):
        k = obs[:, 0].long()
        final = k == self.t - 1
        abort = torch.zeros(obs.shape[0], dtype=torch.bool)
        mid = ~final
        if bool(mid.any()):
            kk = k[mid]
            cw = obs[mid][:, 1:4][torch.arange(int(mid.sum())), kk]
            th = torch.as_tensor(self.ath, dtype=obs.dtype)[kk]
            abort[mid] = cw > th
        if bool(final.any()):
            abort[final] = obs[final][:, self.t - 1] <= self.fth
        yes = torch.zeros(obs.shape[0], 2)
        yes[torch.arange(obs.shape[0]), abort.long()] = 10.0
        return yes, torch.zeros(obs.shape[0], 1)


def test_table_decider_reproduces_static_policy():
    reg = CellRegistry()
    cell = reg.find("6/0.001/1")
    pre = reg.pre(cell)
    for ath, fth in [([0, 0], 0), ([1, 2], 1), ([99, 99], 0)]:
        policy = _StaticPolicy(ath, fth, pre["T"])
        table = decision_table(
            policy, pre, stage_id=cell.stage_idx, rate_id=cell.rate_idx
        )
        got_fth = fit_final_threshold(table, pre, cell.p)
        got = exact.eval_exact(
            table_decider(table, fth=got_fth), pre, cell.p
        )
        want = screen.eval_policy(pre, ath, fth, cell.p)
        assert abs(got["W"] - want["W"]) <= 1e-12, (ath, fth)
        assert abs(got["inf"] - want["inf"]) <= 1e-12, (ath, fth)
