"""Screen 20 payload: photonic fusion routing, from-scratch stochastic sim.

Screen-authored cluster-growth simulator (numpy + stdlib only): N
microclusters of M photons; fusion attempts join components with success
probability P_FUSION when both photons survive loss (1-p_loss) and decay
(DECAY**age). Arms: F static raster, B largest-component-first,
C B + age-cutoff discard, R random-pair control. Terminal metrics:
largest-component photon count (yield) and fusion attempts (cost).
Bounded-exact outcome enumeration on a tiny config validates Monte Carlo;
the same enumeration cap-hits on a target-scale config (limit-expiry).
Writes ALL output under cwd (the attempt work dir): results.json +
witnesses/. Deterministic given seeds. Verdict is always
unresolved-with-reason; classification is coordinator-side.
"""

import argparse
import json
import math
import os
import time

import numpy as np

SIZES = (16, 36, 64)
LOSS_RATES = (0.05, 0.075, 0.10)
P_FUSION = 0.5
M_PHOTONS = 6
SEEDS = (1, 2, 3, 4, 5)
N_MC = 1000
DECAY = 0.99
AGE_CUT = 40
ROUNDS_FACTOR = 6
WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0
TINY_N = 3
TINY_M = 2
TINY_ROUNDS = 6
TINY_LOSS = 0.05
ENUM_CAP = 50000
TARGET_ENUM_N = 16
ARMS = ("F", "B", "C")


def arms_of():
    return ARMS


def live_comps(comps):
    return [i for i, c in enumerate(comps) if c]


def youngest_idx(comp):
    bi = 0
    for i in range(1, len(comp)):
        if comp[i] > comp[bi]:
            bi = i
    return bi


def drop_stale(comps, t, age_cut):
    for c in comps:
        keep = [b for b in c if t - b <= age_cut]
        del c[:]
        c.extend(keep)


def raster_pairs(n):
    return [(i, j) for i in range(n) for j in range(i + 1, n)]


def pick_pair(policy, comps, live, t, rng, raster, ptr, age_cut):
    if policy == "C":
        drop_stale(comps, t, age_cut)
        live = live_comps(comps)
    if len(live) < 2:
        return None, ptr
    if policy == "F":
        m = len(raster)
        for k in range(m):
            i, j = raster[(ptr + k) % m]
            if comps[i] and comps[j]:
                return (i, j), (ptr + k + 1) % m
        return None, ptr
    if policy in ("B", "C"):
        order = sorted(live, key=lambda i: (-len(comps[i]), i))
        return (order[0], order[1]), ptr
    for _ in range(64):
        i = live[int(rng.integers(len(live)))]
        j = live[int(rng.integers(len(live)))]
        if i != j:
            return (i, j), ptr
    return None, ptr


def surv_prob(p_loss, age):
    return (1.0 - p_loss) * (DECAY ** age)


def trial(policy, n, m, p_loss, p_fusion, rng, age_cut, rounds_cap,
          stop=None):
    comps = [[0] * m for _ in range(n)]
    raster = raster_pairs(n)
    ptr = 0
    attempts = 0
    t = 0
    stopped = False
    while attempts < rounds_cap:
        if stop is not None and attempts % 32 == 0 and stop():
            stopped = True
            break
        live = live_comps(comps)
        if len(live) < 2:
            break
        pair, ptr = pick_pair(policy, comps, live, t, rng, raster, ptr,
                              age_cut)
        if pair is None:
            break
        i, j = pair
        bi = youngest_idx(comps[i])
        bj = youngest_idx(comps[j])
        ai = t - comps[i][bi]
        aj = t - comps[j][bj]
        del comps[i][bi]
        del comps[j][bj]
        ok = (float(rng.random()) < surv_prob(p_loss, ai) and
              float(rng.random()) < surv_prob(p_loss, aj) and
              float(rng.random()) < p_fusion)
        if ok:
            comps[i] = comps[i] + comps[j]
            comps[j] = []
        attempts += 1
        t += 1
    yld = 0
    for c in comps:
        if len(c) > yld:
            yld = len(c)
    return {"yield": int(yld), "attempts": int(attempts),
            "stopped": bool(stopped)}


def exact_expected(policy, n, m, p_loss, p_fusion, age_cut, rounds_cap,
                   cap, stop=None):
    raster = raster_pairs(n)
    memo = {}
    nodes = [0]
    capped = [False]
    stopped = [False]

    def key_of(comps):
        return tuple(tuple(c) for c in comps)

    def current_yield(comps):
        yld = 0
        for c in comps:
            if len(c) > yld:
                yld = len(c)
        return yld

    def rec(comps, ptr, t):
        if capped[0]:
            return None
        nodes[0] += 1
        if nodes[0] > cap:
            capped[0] = True
            return None
        if stop is not None and nodes[0] % 512 == 0 and stop():
            stopped[0] = True
            return None
        live = [i for i in range(n) if comps[i]]
        if policy == "C":
            comps = [tuple(b for b in c if t - b <= age_cut)
                     for c in comps]
            live = [i for i in range(n) if comps[i]]
        if t >= rounds_cap or len(live) < 2:
            return (float(current_yield(comps)), 0.0)
        if policy == "F":
            found = None
            mlen = len(raster)
            for k in range(mlen):
                i, j = raster[(ptr + k) % mlen]
                if comps[i] and comps[j]:
                    found = ((i, j), (ptr + k + 1) % mlen)
                    break
            if found is None:
                return (float(current_yield(comps)), 0.0)
            (i, j), ptr2 = found
        elif policy in ("B", "C"):
            order = sorted(live, key=lambda s: (-len(comps[s]), s))
            i, j = order[0], order[1]
            ptr2 = ptr
        else:
            raise ValueError("exact supports only F/B/C")
        bi = 0
        for q in range(1, len(comps[i])):
            if comps[i][q] > comps[i][bi]:
                bi = q
        bj = 0
        for q in range(1, len(comps[j])):
            if comps[j][q] > comps[j][bj]:
                bj = q
        ai = t - comps[i][bi]
        aj = t - comps[j][bj]
        qa = surv_prob(p_loss, ai)
        qb = surv_prob(p_loss, aj)
        p_merge = qa * qb * p_fusion
        nxt = [list(c) for c in comps]
        del nxt[i][bi]
        del nxt[j][bj]
        merged = [list(c) for c in nxt]
        merged[i] = merged[i] + merged[j]
        merged[j] = []
        key = (key_of(merged), ptr2, t + 1)
        if key not in memo:
            memo[key] = rec(merged, ptr2, t + 1)
        key2 = (key_of(nxt), ptr2, t + 1)
        if key2 not in memo:
            memo[key2] = rec([list(c) for c in nxt], ptr2, t + 1)
        r1 = memo[key]
        r2 = memo[key2]
        if r1 is None or r2 is None:
            return None
        ey = p_merge * r1[0] + (1.0 - p_merge) * r2[0]
        ea = 1.0 + p_merge * r1[1] + (1.0 - p_merge) * r2[1]
        return (ey, ea)

    init = tuple(tuple([0] * m) for _ in range(n))
    out = rec([list(c) for c in init], 0, 0)
    if stopped[0]:
        return {"status": "stopped-guard", "nodes": nodes[0],
                "exp_yield": None, "exp_attempts": None, "cap": cap}
    if capped[0] or out is None:
        return {"status": "cap-hit", "nodes": nodes[0],
                "exp_yield": None, "exp_attempts": None, "cap": cap}
    return {"status": "solved", "nodes": nodes[0],
            "exp_yield": float(out[0]), "exp_attempts": float(out[1]),
            "cap": cap}


def pooled_stats(vals):
    a = np.asarray(vals, dtype=float)
    if a.size == 0:
        return {"n": 0, "mean": None, "std": None, "se": None}
    m = float(a.mean())
    if a.size < 2:
        return {"n": int(a.size), "mean": m, "std": 0.0, "se": None}
    sd = float(a.std(ddof=1))
    return {"n": int(a.size), "mean": m, "std": sd,
            "se": sd / math.sqrt(a.size)}


def spread_win(pools, ok):
    keys = sorted(pools)
    if ok and all(pools[a]["se"] is not None for a in keys):
        se = math.sqrt(sum(pools[a]["se"] ** 2 for a in keys)
                       / len(keys))
        means = [pools[a]["mean"] for a in keys]
        spread = max(means) - min(means)
        return se, spread, spread > 2.0 * se
    return None, None, False


def self_tests():
    out = {"ran": True, "failed": []}
    try:
        r1 = trial("B", 8, M_PHOTONS, 0.05, P_FUSION,
                   np.random.default_rng(0), AGE_CUT,
                   ROUNDS_FACTOR * 8, None)
        r2 = trial("B", 8, M_PHOTONS, 0.05, P_FUSION,
                   np.random.default_rng(0), AGE_CUT,
                   ROUNDS_FACTOR * 8, None)
        if r1 != r2:
            out["failed"].append("determinism")
        for pol in ("F", "B", "C"):
            ex = exact_expected(pol, TINY_N, TINY_M, TINY_LOSS,
                                P_FUSION, AGE_CUT, TINY_ROUNDS,
                                ENUM_CAP, None)
            if ex["status"] != "solved" or ex["exp_yield"] is None:
                out["failed"].append("tiny-exact-%s" % pol)
        rng = np.random.default_rng(1)
        ys = [trial("F", TINY_N, TINY_M, TINY_LOSS, P_FUSION, rng,
                    AGE_CUT, TINY_ROUNDS, None)["yield"]
              for _ in range(200)]
        m = float(np.mean(ys))
        se = float(np.std(np.asarray(ys), ddof=1) / math.sqrt(200))
        ex = exact_expected("F", TINY_N, TINY_M, TINY_LOSS, P_FUSION,
                            AGE_CUT, TINY_ROUNDS, ENUM_CAP, None)
        if abs(m - ex["exp_yield"]) > 3.0 * se:
            out["failed"].append("mc-exact-agree")
        comps = [[0, 0, 0], [0] * 6, [0], []]
        pair, _ = pick_pair("B", comps, live_comps(comps), 0,
                            np.random.default_rng(0),
                            raster_pairs(4), 0, AGE_CUT)
        if set(pair) != {0, 1}:
            out["failed"].append("largest-first")
        comps2 = [[0], [50]]
        drop_stale(comps2, 50, AGE_CUT)
        if comps2[0] != [] or comps2[1] != [50]:
            out["failed"].append("age-cutoff")
    except Exception as ex:
        out["failed"].append("raise: %r" % ex)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--attempt", required=True)
    ap.add_argument("--data", required=True)
    ap.parse_args()
    outdir = os.getcwd()
    witdir = os.path.join(outdir, "witnesses")
    os.makedirs(witdir, exist_ok=True)
    t0 = time.perf_counter()

    def elapsed():
        return time.perf_counter() - t0

    def over():
        return elapsed() > WALL_GUARD_S

    cells = {}
    cellrecs = []
    skipped = []
    gate3tiny = {"arms": {}, "solved": 0, "total": 0, "match": 0}
    gate3targets = []
    selftest = self_tests()
    with open(os.path.join(witdir, "selftest.json"), "w") as f:
        json.dump(selftest, f, indent=1, default=str)

    def checkpoint(tag):
        try:
            with open(os.path.join(witdir, "checkpoint-%s.json" % tag),
                      "w") as f:
                json.dump({"tag": tag, "wall_s": elapsed(),
                           "cells": {("%d/%.3f/%d" % k): v
                                     for k, v in cells.items()},
                           "gate3tiny": gate3tiny,
                           "gate3targets": gate3targets,
                           "n_skipped": len(skipped),
                           "verdict": "unresolved-with-reason: partial "
                                      "checkpoint"}, f, indent=1,
                          default=str)
        except Exception:
            pass

    def cell_rng(size, loss, seed, salt):
        return np.random.default_rng(
            (int(size * 1009 + round(loss * 100000) * 101 +
                 seed * 10007 + salt) % (2 ** 63 - 1)))

    def run_cell(size, loss, seed):
        rec = {"size": size, "loss": loss, "seed": seed, "arms": {}}
        for ai, arm in enumerate(("F", "B", "C", "R")):
            if over():
                rec["blocked"] = "wall-guard"
                return rec
            rng = cell_rng(size, loss, seed, 100 + ai)
            ys, cs, nstop = [], [], 0
            for _ in range(N_MC):
                out = trial(arm, size, M_PHOTONS, loss, P_FUSION, rng,
                            AGE_CUT, ROUNDS_FACTOR * size, over)
                if out["stopped"]:
                    nstop += 1
                    break
                ys.append(out["yield"])
                cs.append(out["attempts"])
            if nstop:
                rec["blocked"] = "stopped-guard"
                return rec
            rec["arms"][arm] = {
                "n": len(ys),
                "yield": pooled_stats(ys),
                "attempts": pooled_stats(cs)}
        return rec

    def record_cell(rec):
        if rec.get("blocked") is None and all(
                rec["arms"].get(a, {}).get("n") == N_MC
                for a in ("F", "B", "C", "R")):
            for a in ("F", "B", "C", "R"):
                key = (rec["size"], rec["loss"], rec["seed"], a)
                cells.setdefault(key, {"yield": [], "attempts": []})
                cells[key]["yield"].append(
                    rec["arms"][a]["yield"]["mean"])
                cells[key]["attempts"].append(
                    rec["arms"][a]["attempts"]["mean"])
            return True
        skipped.append({"what": "cell %d/%.3f/%d" % (
            rec["size"], rec["loss"], rec["seed"]),
            "reason": rec.get("blocked", "arm-incomplete")})
        return False

    for pol in ("F", "B", "C"):
        if over():
            gate3tiny["arms"][pol] = {"status": "skipped-guard"}
            skipped.append({"what": "tiny-exact-%s" % pol,
                            "reason": "wall-guard"})
            continue
        ex = exact_expected(pol, TINY_N, TINY_M, TINY_LOSS, P_FUSION,
                            AGE_CUT, TINY_ROUNDS, ENUM_CAP, over)
        gate3tiny["arms"][pol] = ex
        gate3tiny["total"] += 1
        if ex["status"] == "solved":
            gate3tiny["solved"] += 1
    with open(os.path.join(witdir, "gate3_tiny.json"), "w") as f:
        json.dump(gate3tiny, f, indent=1, default=str)

    for pol in ("F", "B", "C"):
        ex = gate3tiny["arms"].get(pol, {})
        if ex.get("status") != "solved":
            continue
        if over():
            skipped.append({"what": "tiny-mc-%s" % pol,
                            "reason": "wall-guard"})
            continue
        rng = cell_rng(TINY_N, TINY_LOSS, 0, 300 + ord(pol))
        ys = [trial(pol, TINY_N, TINY_M, TINY_LOSS, P_FUSION, rng,
                    AGE_CUT, TINY_ROUNDS, over)["yield"]
              for _ in range(N_MC)]
        m = float(np.mean(np.asarray(ys)))
        se = float(np.std(np.asarray(ys), ddof=1) / math.sqrt(N_MC))
        agree = abs(m - ex["exp_yield"]) <= 3.0 * se
        gate3tiny["arms"][pol]["mc_mean"] = m
        gate3tiny["arms"][pol]["mc_se"] = se
        gate3tiny["arms"][pol]["mc_agree"] = bool(agree)
        if agree:
            gate3tiny["match"] += 1
    with open(os.path.join(witdir, "gate3_tiny.json"), "w") as f:
        json.dump(gate3tiny, f, indent=1, default=str)
    checkpoint("tiny")

    if over():
        gate3targets.append({"status": "skipped-guard"})
        skipped.append({"what": "target-enum",
                        "reason": "wall-guard"})
    else:
        tex = exact_expected("B", TARGET_ENUM_N, M_PHOTONS, 0.075,
                             P_FUSION, AGE_CUT,
                             ROUNDS_FACTOR * TARGET_ENUM_N,
                             ENUM_CAP, over)
        gate3targets.append(tex)
    with open(os.path.join(witdir, "gate3_targets.json"), "w") as f:
        json.dump(gate3targets, f, indent=1, default=str)
    checkpoint("targets")

    plan = [(size, loss, seed) for size in SIZES for loss in LOSS_RATES
            for seed in SEEDS]
    idx = 0
    while idx < len(plan):
        if over():
            for (s2, l2, sd2) in plan[idx:]:
                skipped.append({"what": "cell %d/%.3f/%d" % (s2, l2, sd2),
                                "reason": "wall-guard"})
            break
        size, loss, seed = plan[idx]
        rec = run_cell(size, loss, seed)
        cellrecs.append(rec)
        record_cell(rec)
        idx += 1
        if seed == SEEDS[-1]:
            checkpoint("%d-%.3f" % (size, loss))
    with open(os.path.join(witdir, "cells.json"), "w") as f:
        json.dump(cellrecs, f, indent=1, default=str)
    checkpoint("corpus")

    def cell_list(size, loss, seed, arm, field):
        return cells.get((size, loss, seed, arm),
                         {"yield": [], "attempts": []})[field]

    def pool(size, arm, field):
        vals = []
        for loss in LOSS_RATES:
            for seed in SEEDS:
                vals.extend(cell_list(size, loss, seed, arm, field))
        return pooled_stats(vals), len(vals) == len(LOSS_RATES) * len(SEEDS)

    g1_cells, g1_ok = [], True
    for size in SIZES:
        for loss in LOSS_RATES:
            for seed in SEEDS:
                mf = cells.get((size, loss, seed, "F"),
                               {"yield": []})["yield"]
                mr = cells.get((size, loss, seed, "R"),
                               {"yield": []})["yield"]
                ok = (len(mf) == 1 and len(mr) == 1 and mf[0] > mr[0])
                g1_cells.append({"cell": "%d/%.3f/%d" % (size, loss, seed),
                                 "mean_F": mf[0] if mf else None,
                                 "mean_R": mr[0] if mr else None,
                                 "pass": bool(ok)})
                if not ok:
                    g1_ok = False

    g2_sizes, g2_n = [], 0
    g2c_sizes, g2c_n = [], 0
    win_sizes, win_n = [], 0
    for size in SIZES:
        pools, pok = {}, True
        for arm in ("F", "B", "C"):
            pools[arm], oka = pool(size, arm, "yield")
            pok = pok and oka
        se, spread, gp = spread_win(pools, pok)
        g2_sizes.append({"size": size, "pools": pools, "SE": se,
                         "spread": spread, "pass": bool(gp)})
        if gp:
            g2_n += 1
        cpools, cpok = {}, True
        for arm in ("F", "B", "C"):
            cpools[arm], oka = pool(size, arm, "attempts")
            cpok = cpok and oka
        cse, cspread, cgp = spread_win(cpools, cpok)
        g2c_sizes.append({"size": size, "pools": cpools, "SE": cse,
                          "spread": cspread, "pass": bool(cgp)})
        if cgp:
            g2c_n += 1
        joint = {}
        if pok and cpok and all(
                pools[a]["se"] is not None and
                pools[a]["mean"] is not None for a in ("F", "B", "C")):
            sse = math.sqrt(sum(pools[a]["se"] ** 2
                                for a in ("F", "B", "C")) / 3.0)
            for a in ("B", "C"):
                qwin = pools[a]["mean"] > pools["F"]["mean"] + 2.0 * sse
                cok = cpools[a]["mean"] <= cpools["F"]["mean"]
                joint[a] = bool(qwin and cok)
        else:
            joint = {"B": False, "C": False}
        winner = ("B" if joint["B"]
                  else ("C" if joint["C"] else None))
        wpass = winner is not None
        if pok and all(pools[a]["mean"] is not None
                       for a in ("F", "B", "C")):
            spass = (pools["B"]["mean"] > pools["F"]["mean"] or
                     pools["C"]["mean"] > pools["F"]["mean"])
        else:
            spass = False
        win_sizes.append({"size": size, "win": bool(wpass),
                          "strict_win": bool(spass), "pools_ok": bool(pok),
                          "joint": dict(joint), "winner": winner})
        if wpass:
            win_n += 1
    g2_ok = g2_n >= 2

    tiny_solved = (gate3tiny["total"] == 3 and gate3tiny["solved"] == 3)
    tiny_match = (gate3tiny["match"] == 3)
    target_cap = (len(gate3targets) == 1 and
                  gate3targets[0].get("status") == "cap-hit")
    g3pass = bool(tiny_solved and tiny_match and target_cap)

    complete = all(
        len(cell_list(size, loss, seed, arm, "yield")) == 1
        for size in SIZES for loss in LOSS_RATES for seed in SEEDS
        for arm in ("F", "B", "C", "R"))
    tiny_attempted = gate3tiny["total"] == 3
    targets_attempted = len(gate3targets) == 1
    wall = elapsed()
    clean = len(skipped) == 0
    g4_ok = bool(complete and tiny_attempted and targets_attempted and
                 wall < WALL_LIMIT_S and clean)

    selftest_ok = bool(selftest.get("ran")) and not selftest.get("failed")
    strict_n = sum(1 for w in win_sizes if w.get("strict_win"))
    pools_all = all(w.get("pools_ok") for w in win_sizes)
    pursue = (win_n >= 2 and g1_ok and g2_ok and g3pass and g4_ok and
              selftest_ok)
    reject = (complete and tiny_solved and tiny_match and g1_ok and
              pools_all and strict_n == 0)
    if pursue:
        reason = "PURSUE-condition holds (adaptive joint yield win + " \
            "cost no-regress at >=2 sizes + gates 1,2,3,4 + " \
            "self-tests ok); payload verdict stays " \
            "unresolved-with-reason, classification is coordinator-side."
    elif reject:
        reason = "REJECT-condition holds (complete cells, tiny solved " \
            "and matched, Gate-1 controls pass, no strict pooled " \
            "adaptive yield win at any size); payload verdict stays " \
            "unresolved-with-reason, classification is coordinator-side."
    else:
        reason = "UNRESOLVED + next experiment (joint wins=%d/3, strict " \
            "adaptive wins=%d/3, g1=%s g2=%s g2c(cost-spread)=%s g3=%s " \
            "(tiny %d/3 solved %d/3 matched, target cap-hit=%s) " \
            "selftest=%s g4=%s complete=%s skipped=%d; no-replenishment " \
            "pool lets concentration policies grind finite comps — " \
            "next: photon replenishment/multiplexing, then retest " \
            "adaptive)." % (
                win_n, strict_n, g1_ok, g2_ok, g2c_n >= 2, g3pass,
                gate3tiny["solved"], gate3tiny["match"], target_cap,
                selftest_ok, g4_ok, complete, len(skipped))
    verdict_bits = {
        "gate1": {"pass": bool(g1_ok), "cells": g1_cells},
        "gate2": {"pass": bool(g2_ok), "n_sizes_pass": g2_n,
                  "sizes": g2_sizes},
        "gate2_c": {"pass": bool(g2c_n >= 2), "n_sizes_pass": g2c_n,
                    "sizes": g2c_sizes},
        "gate3": {"pass": bool(g3pass), "tiny_solved": tiny_solved,
                  "tiny_match": tiny_match, "tiny": gate3tiny,
                  "targets": gate3targets, "target_cap": target_cap},
        "gate4": {"pass": bool(g4_ok), "complete": bool(complete),
                  "tiny_attempted": bool(tiny_attempted),
                  "targets_attempted": bool(targets_attempted),
                  "wall_sec": wall, "clean": bool(clean)},
        "acceptance": {"pursue_condition": bool(pursue),
                       "reject_condition": bool(reject),
                       "win_sizes": win_sizes, "n_win": win_n,
                       "n_strict_win": strict_n,
                       "selftest_ok": bool(selftest_ok)},
        "reason": reason,
    }

    results = {
        "screen": "20",
        "verdict": "unresolved-with-reason: payload reports numbers "
                   "and gate evidence; classification is coordinator-side.",
        "design": {
            "model": "screen-authored stochastic cluster-growth sim "
                     "(numpy + stdlib only; no external physics libs)",
            "sizes": list(SIZES),
            "loss_rates": list(LOSS_RATES),
            "p_fusion": P_FUSION,
            "microcluster_photons": M_PHOTONS,
            "seeds": list(SEEDS),
            "trials_per_cell_arm": N_MC,
            "decay": DECAY,
            "age_cutoff": AGE_CUT,
            "rounds_factor": ROUNDS_FACTOR,
            "arms": {"F": "static raster order",
                     "B": "largest-component-first",
                     "C": "B + age-cutoff discard",
                     "R": "random-pair control (%d rollouts/cell)" % N_MC},
            "metrics": "terminal largest-component photon count "
                       "(yield), fusion attempts (cost)",
            "pareto": "PURSUE needs adaptive yield win + cost "
                      "no-regress on the SAME arm; a yield-only win "
                      "with higher cost is NOT a Pareto win",
            "exact": "outcome enumeration on tiny (N=%d,M=%d,rounds=%d, "
                     "node cap %d) + MC-vs-exact agreement within 3SE; "
                     "target config (N=%d) must cap-hit" % (
                         TINY_N, TINY_M, TINY_ROUNDS, ENUM_CAP,
                         TARGET_ENUM_N),
        },
        "timing": {"wall_s": wall, "guards": {"wall_guard_s": WALL_GUARD_S,
                                              "limit_s": WALL_LIMIT_S}},
        "cells": {("%d/%.3f/%d/%s" % k): {"n": len(v["yield"]),
                                          **pooled_stats(v["yield"]),
                                          "attempts": pooled_stats(
                                              v["attempts"])}
                  for k, v in cells.items()},
        "gates": verdict_bits,
        "skipped": skipped,
    }
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)


if __name__ == "__main__":
    main()
