from __future__ import annotations

import time
from typing import NamedTuple

import numpy as np

from pursuit05 import exact, screen
from pursuit05.exact import ArmResult
from pursuit05.policy import PrefixTable, table_decider

LAM_GRID = (0, 500, 1000, 2000, 5000, 10000, 1e9)
FTH_GRID = (0, 1, 2)
NODE_CAP = 100_000
DINKELBACH_CAP = 100
DINKELBACH_TOL = 1e-12


class ParetoPoint(NamedTuple):
    lam: float
    fth: int
    W: float
    inf: float
    pacc: float
    iters: int
    gap: float


class HistoryBest(NamedTuple):
    table: PrefixTable
    fth: int
    result: ArmResult
    lam: float
    iters: int
    gap: float
    nodes: int
    fallback: bool
    pareto: tuple


class _Tree(NamedTuple):
    keys: list
    level_members: list
    children: list
    allzero: np.ndarray
    mass: np.ndarray
    row_nodes: list
    q1: float
    q2: float


def _build_tree(pre: dict, p: float) -> _Tree:
    t = pre["T"]
    l1 = pre["L1"]
    big_l = float(l1)
    p1 = big_l * p * (1.0 - p) ** (big_l - 1.0) if l1 else 0.0
    p2 = (
        (big_l * (big_l - 1.0) / 2.0) * p**2 * (1.0 - p) ** (big_l - 2.0)
        if l1 >= 2
        else 0.0
    )
    key_to_idx: dict = {}
    node_k: list = []
    node_az: list = []
    row_nodes: list = []
    for cw in (pre["cw1"], pre["cw2"]):
        rn = np.zeros((cw.shape[0], t - 1), dtype=np.int64)
        for k in range(t - 1):
            uniq, inv = np.unique(cw[:, : k + 1], axis=0, return_inverse=True)
            loc = np.zeros(len(uniq), dtype=np.int64)
            for u, row in enumerate(uniq):
                key = (k, tuple(int(v) for v in row))
                idx = key_to_idx.get(key)
                if idx is None:
                    idx = len(node_k)
                    key_to_idx[key] = idx
                    node_k.append(k)
                    node_az.append(not row.any())
                loc[u] = idx
            rn[:, k] = loc[inv]
        row_nodes.append(rn)
    n = len(node_k)
    keys = [None] * n
    for key, idx in key_to_idx.items():
        keys[idx] = key
    children: list = [[] for _ in range(n)]
    for idx, (k, vals) in enumerate(keys):
        if k > 0:
            children[key_to_idx[(k - 1, vals[:k])]].append(idx)
    level_members: list = [[] for _ in range(t - 1)]
    for idx, k in enumerate(node_k):
        level_members[k].append(idx)
    n2 = row_nodes[1].shape[0]
    q1 = p1 / l1 if l1 else 0.0
    q2 = p2 / n2 if n2 else 0.0
    mass = np.zeros(n)
    for q, rn in zip((q1, q2), row_nodes):
        for k in range(t - 1):
            mass += q * np.bincount(rn[:, k], minlength=n)
    return _Tree(keys, level_members, children, np.asarray(node_az),
                 mass, row_nodes, q1, q2)


def _solve_inner(tree: _Tree, pre: dict, theta: float, lam: float,
                 fth: int) -> PrefixTable:
    t = pre["T"]
    vf = pre["Vf"]
    opt = np.zeros(len(tree.keys))
    abort = np.zeros(len(tree.keys), dtype=bool)
    acc1 = pre["fw1"] <= fth
    acc2 = pre["fw2"] <= fth
    c1 = np.where(acc1, lam - theta, vf).astype(float)
    c2 = np.where(acc2, lam * pre["nt2"].astype(float) - theta, vf)
    leaf = np.bincount(tree.row_nodes[0][:, t - 2], weights=c1 * tree.q1,
                       minlength=len(tree.keys))
    leaf = leaf + np.bincount(tree.row_nodes[1][:, t - 2], weights=c2 * tree.q2,
                              minlength=len(tree.keys))
    for k in range(t - 2, -1, -1):
        for v in tree.level_members[k]:
            if k == t - 2:
                cont = leaf[v]
            else:
                cont = sum(opt[c] for c in tree.children[v])
            ab = pre["spent"][k] * tree.mass[v]
            if ab < cont and not tree.allzero[v]:
                abort[v] = True
                opt[v] = ab
            else:
                opt[v] = cont
    table = {}
    for v, key in enumerate(tree.keys):
        if not tree.allzero[v]:
            table[key] = bool(abort[v])
    return table


def _ratio(out: dict, vf: float, lam: float) -> tuple:
    num = out["E"] - vf * out["pacc"] + lam * out["inf"] * out["pacc"]
    return num, out["pacc"], num / out["pacc"]


def _dinkelbach(tree: _Tree, pre: dict, p: float, lam: float,
                fth: int) -> tuple:
    vf = pre["Vf"]
    open_table = {key: False for key in tree.keys if any(key[1])}
    out = exact.eval_exact(table_decider(open_table, fth=fth), pre, p)
    _, _, theta = _ratio(out, vf, lam)
    best = (open_table, out, theta)
    prev_sig = None
    gap = float("inf")
    iters = 0
    for _ in range(DINKELBACH_CAP):
        table = _solve_inner(tree, pre, theta, lam, fth)
        out = exact.eval_exact(table_decider(table, fth=fth), pre, p)
        num, den, ratio = _ratio(out, vf, lam)
        gap = num - theta * den
        iters += 1
        if ratio < best[2]:
            best = (table, out, ratio)
        sig = frozenset(k for k, v in table.items() if v)
        if sig == prev_sig:
            break
        if abs(gap) <= DINKELBACH_TOL * max(1.0, abs(theta * den)):
            prev_sig = sig
            theta = ratio
            break
        prev_sig = sig
        theta = ratio
    table, out, _ = best
    point = ParetoPoint(lam, fth, out["W"], out["inf"], out["pacc"], iters,
                        abs(gap))
    return table, point


def _static_table(ath: tuple, keys: list) -> PrefixTable:
    return {(k, vals): vals[k] > ath[k] for (k, vals) in keys
            if any(vals)}


def best_history(pre: dict, p: float, f_inf: float) -> HistoryBest:
    """Constrained history-dependent optimum over prefix abort tables.

    Returns the lowest-W feasible point over exact per-(lam, fth)
    Dinkelbach solutions plus every static policy. Static policies
    are prefix policies, so H never scores above S.
    """
    bound = f_inf * (1.0 + screen.INF_REL) + screen.INF_ABS
    start = time.perf_counter()
    tree = _build_tree(pre, p)
    nodes = len(tree.keys)
    if nodes > NODE_CAP:
        print(f"best_history fallback to S: {nodes} prefixes exceed cap")
        s = exact.best_static(pre, p, f_inf)
        cost = time.perf_counter() - start
        return HistoryBest(
            table=_static_table(s.ath, tree.keys),
            fth=s.fth,
            result=ArmResult("H", s.result.W, s.result.inf, s.result.pacc,
                             s.result.n_evaluated, cost),
            lam=-1.0,
            iters=0,
            gap=0.0,
            nodes=nodes,
            fallback=True,
            pareto=(),
        )
    cands: list = []
    pareto: list = []
    for lam in LAM_GRID:
        for fth in FTH_GRID:
            table, point = _dinkelbach(tree, pre, p, float(lam), fth)
            pareto.append(point)
            cands.append((point.W, point.inf, point.pacc, table, fth,
                          float(lam), point.iters, point.gap))
    n_static = 0
    for ath, fth in screen.all_threshold_policies(pre["T"]):
        out = exact.eval_exact(exact.static_decider(ath, fth), pre, p)
        n_static += 1
        cands.append((out["W"], out["inf"], out["pacc"],
                      _static_table(tuple(ath), tree.keys), fth,
                      -1.0, 0, 0.0))
    feas = [c for c in cands if c[1] <= bound]
    w, inf, pacc, table, fth, lam, iters, gap = min(
        feas, key=lambda c: (c[0], c[1]))
    cost = time.perf_counter() - start
    return HistoryBest(
        table=table,
        fth=fth,
        result=ArmResult("H", w, inf, pacc, len(pareto) + n_static, cost),
        lam=lam,
        iters=iters,
        gap=gap,
        nodes=nodes,
        fallback=False,
        pareto=tuple(pareto),
    )
