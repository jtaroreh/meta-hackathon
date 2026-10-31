import numpy as np

from pursuit05 import screen
from pursuit05.cells import CellRegistry
from pursuit05.env import CultivationAbort, rollout_loaded

CHUNK = 256


def _roll_all(pre, p, ath, fth):
    t = pre["T"]
    l1 = pre["L1"]
    n2 = len(pre["fw2"])
    trajs = [(1, r) for r in range(l1)] + [(2, r) for r in range(n2)]
    trajs += [(0, 0), (0, 0)]
    env = CultivationAbort(pre, p, num_agents=CHUNK)

    def act_fn(obs, s, w, rows):
        act = np.zeros(CHUNK, dtype=np.int64)
        for a in range(CHUNK):
            c, r = (w[a], rows[a])
            if s < t - 1:
                cw = 0
                if c == 1:
                    cw = pre["cw1"][r, s]
                elif c == 2:
                    cw = pre["cw2"][r, s]
                act[a] = 1 if cw > ath[s] else 0
            else:
                fw = 0
                if c == 1:
                    fw = pre["fw1"][r]
                elif c == 2:
                    fw = pre["fw2"][r]
                act[a] = 1 if fw <= fth else 0
        return act

    outs = rollout_loaded(
        env,
        np.array([c[0] for c in trajs]),
        np.array([c[1] for c in trajs]),
        act_fn,
    )
    spent = np.array([o[0] for o in outs])
    acc = np.array([o[1] for o in outs])
    log = np.array([o[2] for o in outs])
    return spent, acc, log


def _aggregate(pre, p, spent, acc, log):
    l1 = pre["L1"]
    n2 = len(pre["fw2"])
    vf = pre["Vf"]
    a1f = float(acc[:l1].mean())
    v1 = float(spent[:l1].mean())
    a2f = float(acc[l1 : l1 + n2].mean()) if n2 else 1.0
    v2 = float(spent[l1 : l1 + n2].mean()) if n2 else vf
    l2f = float(log[l1 : l1 + n2].mean()) if n2 else 0.0
    big_l = float(l1)
    p0 = (1.0 - p) ** big_l
    p1 = big_l * p * (1.0 - p) ** (big_l - 1.0) if l1 else 0.0
    p2 = (
        (big_l * (big_l - 1.0) / 2.0) * p**2 * (1.0 - p) ** (big_l - 2.0)
        if l1 >= 2
        else 0.0
    )
    pt = max(0.0, 1.0 - p0 - p1 - p2)
    pacc = p0 + p1 * a1f + p2 * a2f
    e = p0 * vf + p1 * v1 + p2 * v2 + pt * vf
    return e / pacc - vf, (p1 * a1f + p2 * l2f) / pacc


def test_env_episode_accounting_matches_eval_exact():
    reg = CellRegistry()
    for cid in ("6/0.001/1", "9/0.002/3", "12/0.005/5"):
        cell = reg.find(cid)
        pre = reg.pre(cell)
        t = pre["T"]
        for ath, fth in (
            ([99] * (t - 1), 0),
            ([0] * (t - 1), 0),
            ([1] * (t - 1), 1),
        ):
            spent, acc, log = _roll_all(pre, cell.p, ath, fth)
            w0 = slice(len(spent) - 2, len(spent))
            assert bool(acc[w0].all())
            assert bool((spent[w0] == pre["Vf"]).all())
            assert not bool(log[w0].any())
            w, inf = _aggregate(pre, cell.p, spent, acc, log)
            want = screen.eval_policy(pre, ath, fth, cell.p)
            assert abs(w - want["W"]) <= 1e-12, (cid, ath, fth)
            assert abs(inf - want["inf"]) <= 1e-12, (cid, ath, fth)


def test_env_reset_is_seeded():
    reg = CellRegistry()
    pre = reg.pre(reg.find("12/0.002/1"))
    env = CultivationAbort(pre, 0.002, num_agents=64)
    o1, _ = env.reset(seed=7)
    o1 = o1.copy()
    o2, _ = env.reset(seed=7)
    o2 = o2.copy()
    assert np.array_equal(o1, o2)
    o3, _ = env.reset(seed=8)
    assert not np.array_equal(o1, o3.copy())
