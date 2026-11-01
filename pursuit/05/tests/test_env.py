import numpy as np

from pursuit05 import screen
from pursuit05.cells import CellRegistry
from pursuit05.env import (
    CultivationAbort,
    binomial_masses,
    rollout_loaded,
    scripted_actions,
)

CHUNK = 256


def _roll_all(pre, p, ath, fth, use_obs=False):
    t = pre["T"]
    l1 = pre["L1"]
    n2 = len(pre["fw2"])
    trajs = [(1, r) for r in range(l1)] + [(2, r) for r in range(n2)]
    trajs += [(0, 0), (0, 0)]
    env = CultivationAbort(pre, p, num_agents=CHUNK)

    def act_fn(obs, s, w, rows):
        if use_obs:
            return scripted_actions(obs, ath, fth, t)
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
    ret = np.array([o[3] for o in outs])
    return spent, acc, log, ret


def _aggregate(pre, p, spent, acc, log):
    l1 = pre["L1"]
    n2 = len(pre["fw2"])
    vf = pre["Vf"]
    a1f = float(acc[:l1].mean())
    v1 = float(spent[:l1].mean())
    a2f = float(acc[l1 : l1 + n2].mean()) if n2 else 1.0
    v2 = float(spent[l1 : l1 + n2].mean()) if n2 else vf
    l2f = float(log[l1 : l1 + n2].mean()) if n2 else 0.0
    p0, p1, p2, pt = binomial_masses(l1, p)
    pacc = p0 + p1 * a1f + p2 * a2f
    e = p0 * vf + p1 * v1 + p2 * v2 + pt * vf
    return e / pacc - vf, (p1 * a1f + p2 * l2f) / pacc


def _check_accounting(pre, p, cid, use_obs):
    t = pre["T"]
    vf = pre["Vf"]
    for ath, fth in (
        ([99] * (t - 1), 0),
        ([0] * (t - 1), 0),
        ([1] * (t - 1), 1),
    ):
        spent, acc, log, ret = _roll_all(pre, p, ath, fth, use_obs)
        w0 = slice(len(spent) - 2, len(spent))
        assert bool(acc[w0].all())
        assert bool((spent[w0] == vf).all())
        assert not bool(log[w0].any())
        closed = -spent / vf + acc.astype(float) - 5000.0 * log.astype(float)
        assert bool((abs(ret - closed) <= 1e-3).all()), (cid, ath, fth)
        w, inf = _aggregate(pre, p, spent, acc, log)
        want = screen.eval_policy(pre, ath, fth, p)
        assert abs(w - want["W"]) <= 1e-12, (cid, ath, fth)
        assert abs(inf - want["inf"]) <= 1e-12, (cid, ath, fth)


def test_env_episode_accounting_matches_eval_exact():
    reg = CellRegistry()
    for cid in ("6/0.001/1", "9/0.002/3", "12/0.005/5"):
        cell = reg.find(cid)
        _check_accounting(reg.pre(cell), cell.p, cid, False)


def test_env_obs_actor_matches_eval_exact():
    reg = CellRegistry()
    for cid in ("6/0.001/1", "9/0.002/3", "12/0.005/5"):
        cell = reg.find(cid)
        _check_accounting(reg.pre(cell), cell.p, cid, True)


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


def test_env_masks_all_zero_to_match_scorer():
    reg = CellRegistry()
    cell = reg.find("12/0.002/1")
    pre = reg.pre(cell)
    t = pre["T"]
    env = CultivationAbort(pre, cell.p, num_agents=4)
    env.load_episodes(np.zeros(4, dtype=np.int64), np.zeros(4, dtype=np.int64))
    for s in range(t - 1):
        _, _, term, _, _ = env.step(np.ones(4, dtype=np.int64))
        assert not bool(term.any()), s
    _, _, term, _, infos = env.step(np.zeros(4, dtype=np.int64))
    assert bool(term.all())
    assert all(i["accepted"] for i in infos)
    r0 = int(np.nonzero(pre["cw1"][:, 0] == 0)[0][0])
    env.load_episodes(np.array([1, 1, 1, 1]), np.array([r0, r0, r0, r0]))
    _, _, term, _, _ = env.step(np.ones(4, dtype=np.int64))
    assert not bool(term.any())


def test_env_obs_values_match_prefixes():
    from pursuit05.policy import obs_row

    reg = CellRegistry()
    for cid in ("6/0.001/1", "12/0.002/1"):
        cell = reg.find(cid)
        pre = reg.pre(cell)
        t = pre["T"]
        env = CultivationAbort(
            pre, cell.p, stage_id=cell.stage_idx, rate_id=cell.rate_idx,
            num_agents=1,
        )
        seen = set()
        for cw, w in ((pre["cw1"], 1), (pre["cw2"], 2)):
            for k in range(t - 1):
                uniq, first = np.unique(
                    cw[:, : k + 1], axis=0, return_index=True
                )
                for u, r in zip(uniq, first):
                    vals = tuple(int(v) for v in u)
                    if (k, vals) in seen:
                        continue
                    seen.add((k, vals))
                    env.load_episodes(np.array([w]), np.array([r]))
                    for _ in range(k):
                        env.step(np.zeros(1, dtype=np.int64))
                    want = np.asarray(
                        obs_row(k, vals, cell.stage_idx, cell.rate_idx, t),
                        dtype=np.float32,
                    )
                    assert np.array_equal(env.observations[0], want), (cid, k, vals)
        env.load_episodes(np.array([0]), np.array([0]))
        assert np.array_equal(
            env.observations[0],
            np.asarray(
                [0.0, 0.0, 0.0, 0.0, cell.stage_idx, cell.rate_idx, t],
                dtype=np.float32,
            ),
        )


def test_cw_last_equals_fw_all_cells():
    reg = CellRegistry()
    for cell in reg.all_cells():
        pre = reg.pre(cell)
        assert bool((pre["cw1"][:, -1] == pre["fw1"]).all()), cell.cell_id
        assert bool((pre["cw2"][:, -1] == pre["fw2"]).all()), cell.cell_id
