"""Screen 07 payload: AutoCCZ + buffer scheduling (deterministic 2D tile/buffer model).

Screen-authored deterministic tile-and-buffer scheduling simulator
(stdlib + numpy only; no MILP/SMT/OLSQA/Vandaele/Lau/PhasePoly/torch
anywhere): factories emit T / AutoCCZ states with seeded Bernoulli
stochasticity at frozen factory:compute ratios; a shared-or-partitioned
buffer stages states; a width-limited corridor delivers them to a compute
front of T/CCZ demands with a 2-wide ready window. Metric: provisioned
active tiles x code cycles (footprint volume) + stall counts. Arms: S static
FIFO (fixed buffer partition, FIFO serve), B dynamic buffer-aware (shared
pool, abundant-first serve), C joint buffer+corridor (B rules + one-step
corridor rollout, deeper lookahead), R random control. A bounded-exact
DFS scheduler validates the tiny instance (solved) and cap-hits at target
scale (limit-expiry). Writes ALL output under cwd (the attempt work dir):
results.json + witnesses/. Deterministic given seeds. Verdict is always
unresolved-with-reason; classification is coordinator-side.
"""

import argparse
import json
import math
import os
import time

import numpy as np

REGIMES = ("small", "base", "stressed")
SEEDS = (1, 2, 3, 4, 5)
ARMS = ("S", "B", "C", "R")

REGIME_PARAMS = {
    "small": {"p_t": 1.0 / 3.0, "p_ccz": 1.0 / 6.0, "buf_total": 10,
              "static_t": 5, "static_ccz": 5, "corridor_w": 2,
              "fact_tiles": 20, "front_len": 240},
    "base": {"p_t": 1.0 / 5.0, "p_ccz": 1.0 / 10.0, "buf_total": 8,
             "static_t": 4, "static_ccz": 4, "corridor_w": 1,
             "fact_tiles": 14, "front_len": 240},
    "stressed": {"p_t": 1.0 / 8.0, "p_ccz": 1.0 / 16.0, "buf_total": 6,
                 "static_t": 3, "static_ccz": 3, "corridor_w": 1,
                 "fact_tiles": 10, "front_len": 240},
}
TILE_COMPUTE = 64
CORR_TILE_PER_W = 8
TILE_PER_STATE = 2
READY_WINDOW = 2
LOOKAHEAD_K_B = 8
LOOKAHEAD_K_C = 16
ROLLOUT_H = 3
R_IDLE_P = 0.35
N_REP = 400
HORIZON = 12000
CYCLE_CAP = 12000
WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0
EXACT_CAP = 50000

TINY_BASE = 50
TINY_BUF = 2
TINY_W = 2
TINY1_FRONT = ("T", "T")
TINY1_ARRIVALS = {0: ("T",), 1: ("T",)}
TINY1_EXP = {"cycles": 2, "stalls": 0, "volume": 108}
TINY2_FRONT = ("CCZ",)
TINY2_ARRIVALS = {2: ("CCZ",)}
TINY2_EXP = {"cycles": 3, "stalls": 2, "volume": 156}
TARGET_FRONT_LEN = 20
TARGET_HORIZON = 120


def base_tiles_of(regime):
    p = REGIME_PARAMS[regime]
    return TILE_COMPUTE + p["fact_tiles"] + p["corridor_w"] * CORR_TILE_PER_W


def build_front(length):
    motif = ("T", "T", "CCZ", "T", "T", "T", "CCZ", "T", "T", "T")
    front = [motif[i % len(motif)] for i in range(length)]
    for b in range(50, length, 50):
        for k in range(8):
            if b + k < length:
                front[b + k] = "CCZ"
    return tuple(front)


def trace_rng(regime_idx, seed, rep):
    return np.random.default_rng(
        (int(regime_idx * 100003 + seed * 10007 + rep * 101 + 11)
         % (2 ** 63 - 1)))


def make_traces(regime, seed, rep, horizon=HORIZON):
    ri = REGIMES.index(regime)
    rng = trace_rng(ri, seed, rep)
    p = REGIME_PARAMS[regime]
    t = (rng.random(horizon) < p["p_t"]).astype(np.int8)
    c = (rng.random(horizon) < p["p_ccz"]).astype(np.int8)
    return t, c


def choice_rng(regime, seed, rep):
    ri = REGIMES.index(regime)
    return np.random.default_rng(
        (int(ri * 20011 + seed * 30011 + rep * 103 + 999)
         % (2 ** 63 - 1)))


def upcoming_need(served, front, k):
    need_t = 0
    need_c = 0
    seen = 0
    for i in range(len(front)):
        if not served[i]:
            if front[i] == "T":
                need_t += 1
            else:
                need_c += 1
            seen += 1
            if seen >= k:
                break
    return need_t, need_c


def abund_first_order(cands, front, buf_t, buf_c, served, k):
    scored = []
    need_t, need_c = upcoming_need(served, front, k)
    for i in cands:
        typ = front[i]
        buf = buf_t if typ == "T" else buf_c
        need = need_t if typ == "T" else need_c
        scored.append((float(buf) / float(need + 1), i))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [i for _, i in scored]


def rollout_cost(pick, ready_idx, front, buf_t, buf_c, served, params, k):
    bt = buf_t - (1 if front[pick] == "T" else 0)
    bc = buf_c - (1 if front[pick] == "CCZ" else 0)
    sv = list(served)
    sv[pick] = True
    stalls = 0
    for _ in range(ROLLOUT_H):
        win = [i for i in range(len(front)) if not sv[i]][:READY_WINDOW]
        if not win:
            break
        sub = [i for i in win
               if (front[i] == "T" and bt > 0)
               or (front[i] == "CCZ" and bc > 0)]
        if not sub:
            stalls += 1
            continue
        nxt = abund_first_order(sub, front, bt, bc, tuple(sv), k)[0]
        if front[nxt] == "T":
            bt -= 1
        else:
            bc -= 1
        sv[nxt] = True
    return stalls


def pick_serves(policy, ready, front, buf_t, buf_c, served, w, rng,
                look_k):
    servable = [i for i in ready
                if (front[i] == "T" and buf_t > 0)
                or (front[i] == "CCZ" and buf_c > 0)]
    if not servable:
        return []
    if policy == "S":
        order = sorted(servable)
    elif policy == "R":
        if len(servable) >= 2 and float(rng.random()) < R_IDLE_P:
            return []
        order = list(servable)
        rng.shuffle(order)
        order = order[:1]
    elif policy == "B":
        order = abund_first_order(servable, front, buf_t, buf_c, served,
                                  look_k)
    else:
        scored = []
        for c in servable:
            cost = rollout_cost(c, ready, front, buf_t, buf_c, served,
                                None, look_k)
            scored.append((cost, c))
        scored.sort(key=lambda s: (s[0], s[1]))
        order = [c for _, c in scored]
    picks = []
    take_t = 0
    take_c = 0
    for i in order:
        if len(picks) >= w:
            break
        if front[i] == "T":
            if buf_t - take_t <= 0:
                continue
            take_t += 1
        else:
            if buf_c - take_c <= 0:
                continue
            take_c += 1
        picks.append(i)
    return picks


def store_arrival(policy, typ, buf_t, buf_c, params, rng, front=None,
                 served=None, k=8):
    if policy in ("S", "R"):
        cap = params["static_t"] if typ == "T" else params["static_ccz"]
        cur = buf_t if typ == "T" else buf_c
        if cur < cap:
            return (buf_t + 1, buf_c) if typ == "T" else (buf_t, buf_c + 1), \
                False
        return (buf_t, buf_c), True
    if buf_t + buf_c < params["buf_total"]:
        return (buf_t + 1, buf_c) if typ == "T" else (buf_t, buf_c + 1), \
            False
    if front is not None and served is not None:
        need_t, need_c = upcoming_need(served, front, k)
        score_t = float(buf_t) / float(need_t + 1)
        score_c = float(buf_c) / float(need_c + 1)
        if typ == "T":
            if score_t < score_c and buf_c > 0:
                return (buf_t + 1, buf_c - 1), True
        else:
            if score_c < score_t and buf_t > 0:
                return (buf_t - 1, buf_c + 1), True
    return (buf_t, buf_c), True


def simulate(policy, trace_t, trace_c, front, params, base, rng,
             stop=None):
    buf_t = 0
    buf_c = 0
    served = [False] * len(front)
    done = 0
    t = 0
    stalls = 0
    waste = 0
    vol = 0
    peak = 0
    n = len(front)
    horizon = len(trace_t)
    look_k = LOOKAHEAD_K_C if policy == "C" else LOOKAHEAD_K_B
    stopped = False
    w = params["corridor_w"]
    while done < n and t < CYCLE_CAP:
        if stop is not None and t % 32 == 0 and stop():
            stopped = True
            break
        if t < horizon:
            if trace_t[t]:
                (buf_t, buf_c), dw = store_arrival(
                    policy, "T", buf_t, buf_c, params, rng, front,
                    served, look_k)
                waste += 1 if dw else 0
            if trace_c[t]:
                (buf_t, buf_c), dw = store_arrival(
                    policy, "CCZ", buf_t, buf_c, params, rng, front,
                    served, look_k)
                waste += 1 if dw else 0
        if buf_t + buf_c > peak:
            peak = buf_t + buf_c
        win = [i for i in range(n) if not served[i]][:READY_WINDOW]
        if not win:
            break
        picks = pick_serves(policy, win, front, buf_t, buf_c,
                            tuple(served), w, rng, look_k)
        if not picks:
            stalls += 1
        for i in picks:
            if front[i] == "T":
                buf_t -= 1
            else:
                buf_c -= 1
            served[i] = True
            done += 1
        vol += base + params["buf_total"] * TILE_PER_STATE
        t += 1
    return {"cycles": int(t), "stalls": int(stalls), "volume": int(vol),
            "waste": int(waste), "peak": int(peak),
            "done": int(done), "stopped": bool(stopped)}


def simulate_fixed(policy, arrivals, front, buf_total, w, base):
    params = {"buf_total": buf_total, "static_t": buf_total,
              "static_ccz": buf_total, "corridor_w": w}
    buf_t = 0
    buf_c = 0
    served = [False] * len(front)
    done = 0
    t = 0
    stalls = 0
    vol = 0
    n = len(front)
    rng = np.random.default_rng(0)
    while done < n and t < 50:
        for typ in arrivals.get(t, ()):
            (buf_t, buf_c), _ = store_arrival(
                policy, typ, buf_t, buf_c, params, rng)
        win = [i for i in range(n) if not served[i]][:READY_WINDOW]
        picks = pick_serves(policy, win, front, buf_t, buf_c,
                            tuple(served), w, rng, LOOKAHEAD_K_B)
        if not picks:
            stalls += 1
        for i in picks:
            if front[i] == "T":
                buf_t -= 1
            else:
                buf_c -= 1
            served[i] = True
            done += 1
        vol += base + params["buf_total"] * TILE_PER_STATE
        t += 1
    return {"cycles": int(t), "stalls": int(stalls), "volume": int(vol),
            "done": int(done)}


def exact_opt(front, sched_t, sched_c, buf_total, w, base, horizon, cap,
              stop=None):
    n = len(front)
    nodes = [0]
    capped = [False]
    stopped = [False]
    best = [None]
    init_served = tuple([False] * n)

    def rec(t, buf_t, buf_c, served, vol):
        if capped[0] or stopped[0]:
            return
        nodes[0] += 1
        if nodes[0] > cap:
            capped[0] = True
            return
        if stop is not None and nodes[0] % 512 == 0 and stop():
            stopped[0] = True
            return
        done = sum(1 for s in served if s)
        if done == n:
            if best[0] is None or vol < best[0]:
                best[0] = vol
            return
        if t >= horizon:
            return
        bt = buf_t + (1 if t < len(sched_t) and sched_t[t] else 0)
        bc = buf_c + (1 if t < len(sched_c) and sched_c[t] else 0)
        if bt + bc > buf_total:
            over = (bt + bc) - buf_total
            bt = max(0, bt - over)
        win = [i for i in range(n) if not served[i]][:READY_WINDOW]
        servable = [i for i in win
                    if (front[i] == "T" and bt > 0)
                    or (front[i] == "CCZ" and bc > 0)]
        options = []
        if servable:
            for i in servable:
                options.append((i,))
            if w >= 2 and len(servable) >= 2:
                i, j = servable[0], servable[1]
                need_t = (1 if front[i] == "T" else 0) + (
                    1 if front[j] == "T" else 0)
                need_c = (1 if front[i] == "CCZ" else 0) + (
                    1 if front[j] == "CCZ" else 0)
                if bt >= need_t and bc >= need_c:
                    options.append((i, j))
        options.append(())
        for opt in options:
            nbt, nbc = bt, bc
            sv = list(served)
            for i in opt:
                if front[i] == "T":
                    nbt -= 1
                else:
                    nbc -= 1
                sv[i] = True
            rec(t + 1, nbt, nbc, tuple(sv),
                vol + base + buf_total * TILE_PER_STATE)

    rec(0, 0, 0, init_served, 0)
    if stopped[0]:
        return {"status": "stopped-guard", "nodes": nodes[0],
                "opt_volume": best[0], "cap": cap, "started": True}
    if capped[0]:
        return {"status": "cap-hit", "nodes": nodes[0],
                "opt_volume": best[0], "cap": cap, "started": True}
    return {"status": "solved", "nodes": nodes[0],
            "opt_volume": best[0], "cap": cap, "started": True}


def target_schedule():
    rng = np.random.default_rng(7007)
    p = REGIME_PARAMS["stressed"]
    st = [bool(x) for x in (rng.random(TARGET_HORIZON) < p["p_t"])]
    sc = [bool(x) for x in (rng.random(TARGET_HORIZON) < p["p_ccz"])]
    return st, sc


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
        for pol in ARMS:
            r1 = simulate_fixed(pol, TINY1_ARRIVALS, TINY1_FRONT, TINY_BUF,
                                TINY_W, TINY_BASE)
            for k, v in TINY1_EXP.items():
                if r1[k] != v:
                    out["failed"].append("tiny1-%s-%s" % (pol, k))
            r2 = simulate_fixed(pol, TINY2_ARRIVALS, TINY2_FRONT, 1, 1,
                                TINY_BASE)
            for k, v in TINY2_EXP.items():
                if r2[k] != v:
                    out["failed"].append("tiny2-%s-%s" % (pol, k))
        a = simulate("B", *make_traces("base", 1, 0), build_front(240),
                     REGIME_PARAMS["base"], base_tiles_of("base"),
                     choice_rng("base", 1, 0), None)
        b = simulate("B", *make_traces("base", 1, 0), build_front(240),
                     REGIME_PARAMS["base"], base_tiles_of("base"),
                     choice_rng("base", 1, 0), None)
        if a != b:
            out["failed"].append("determinism")
        st2 = [False] * 6
        sc2 = [False] * 6
        sc2[2] = True
        ex = exact_opt(TINY2_FRONT, st2, sc2, 1, 1, TINY_BASE, 6,
                       EXACT_CAP, None)
        if ex["status"] != "solved" or ex["opt_volume"] != TINY2_EXP[
                "volume"]:
            out["failed"].append("tiny-exact-opt")
    except Exception as ex:
        out["failed"].append("raise: %r" % ex)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--attempt", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--n-rep", type=int, default=N_REP)
    ap.add_argument("--front-len", type=int, default=None)
    args = ap.parse_args()
    n_rep = int(args.n_rep)
    outdir = os.getcwd()
    witdir = os.path.join(outdir, "witnesses")
    os.makedirs(witdir, exist_ok=True)
    t0 = time.perf_counter()

    def elapsed():
        return time.perf_counter() - t0

    def over():
        return elapsed() > WALL_GUARD_S

    fronts = {}
    for regime in REGIMES:
        fl = REGIME_PARAMS[regime]["front_len"] if args.front_len is None \
            else int(args.front_len)
        fronts[regime] = build_front(fl)
    cells = {}
    cellrecs = []
    skipped = []
    gate3tiny = {"arms": {}, "solved": 0, "total": 0}
    gate3targets = []
    selftest = self_tests()
    with open(os.path.join(witdir, "selftest.json"), "w") as f:
        json.dump(selftest, f, indent=1, default=str)

    def checkpoint(tag):
        try:
            with open(os.path.join(witdir, "checkpoint-%s.json" % tag),
                      "w") as f:
                json.dump({"tag": tag, "wall_s": elapsed(),
                           "n_cells": len(cells),
                           "gate3tiny": gate3tiny,
                           "gate3targets": gate3targets,
                           "n_skipped": len(skipped),
                           "verdict": "unresolved-with-reason: partial "
                                      "checkpoint"}, f, indent=1,
                          default=str)
        except Exception:
            pass

    tiny_ok = bool(selftest.get("ran")) and not selftest.get("failed")

    st2 = [False] * 6
    sc2 = [False] * 6
    sc2[2] = True
    if over():
        gate3tiny["arms"]["tiny"] = {"status": "skipped-guard"}
        skipped.append({"what": "tiny-exact", "reason": "wall-guard",
                        "iters_done": 0, "n_evaluated": 0})
    else:
        ex = exact_opt(TINY2_FRONT, st2, sc2, 1, 1, TINY_BASE, 6,
                       EXACT_CAP, over)
        gate3tiny["arms"]["tiny"] = ex
        gate3tiny["total"] += 1
        if ex["status"] == "solved" and ex["opt_volume"] == TINY2_EXP[
                "volume"]:
            gate3tiny["solved"] += 1
    with open(os.path.join(witdir, "gate3_tiny.json"), "w") as f:
        json.dump(gate3tiny, f, indent=1, default=str)
    checkpoint("tiny")

    if over():
        gate3targets.append({"status": "skipped-guard"})
        skipped.append({"what": "target-exact", "reason": "wall-guard",
                        "iters_done": 0, "n_evaluated": 0})
    else:
        st, sc = target_schedule()
        tex = exact_opt(build_front(TARGET_FRONT_LEN), st, sc,
                        REGIME_PARAMS["stressed"]["buf_total"], 1,
                        base_tiles_of("stressed"), TARGET_HORIZON,
                        EXACT_CAP, over)
        gate3targets.append(tex)
    with open(os.path.join(witdir, "gate3_targets.json"), "w") as f:
        json.dump(gate3targets, f, indent=1, default=str)
    checkpoint("targets")

    def run_cell(regime, seed):
        rec = {"regime": regime, "seed": seed, "arms": {}}
        params = REGIME_PARAMS[regime]
        front = fronts[regime]
        base = base_tiles_of(regime)
        for ai, arm in enumerate(ARMS):
            if over():
                rec["blocked"] = "wall-guard"
                return rec
            vols, sts, cyc = [], [], []
            nstop = 0
            for rep in range(n_rep):
                if rep % 32 == 0 and over():
                    nstop += 1
                    break
                tr_t, tr_c = make_traces(regime, seed, rep)
                rng = choice_rng(regime, seed, rep)
                out = simulate(arm, tr_t, tr_c, front, params, base,
                               rng, over)
                if out["stopped"]:
                    nstop += 1
                    break
                if out["done"] != len(front):
                    nstop += 1
                    break
                vols.append(out["volume"])
                sts.append(out["stalls"])
                cyc.append(out["cycles"])
            if nstop:
                rec["blocked"] = "stopped-guard"
                rec["iters_done"] = len(vols)
                rec["n_evaluated"] = n_rep
                return rec
            rec["arms"][arm] = {
                "n": len(vols),
                "volume": pooled_stats(vols),
                "stalls": pooled_stats(sts),
                "cycles": pooled_stats(cyc)}
        return rec

    def record_cell(rec):
        if rec.get("blocked") is None and all(
                rec["arms"].get(a, {}).get("n") == n_rep
                for a in ARMS):
            for a in ARMS:
                key = (rec["regime"], rec["seed"], a)
                cells.setdefault(key, {"volume": [], "stalls": []})
                cells[key]["volume"].append(
                    rec["arms"][a]["volume"]["mean"])
                cells[key]["stalls"].append(
                    rec["arms"][a]["stalls"]["mean"])
            return True
        skipped.append({"what": "cell %s/%d" % (
            rec["regime"], rec["seed"]),
            "reason": rec.get("blocked", "arm-incomplete"),
            "iters_done": rec.get("iters_done", 0),
            "n_evaluated": n_rep})
        return False

    for regime in REGIMES:
        regime_cells = [(regime, seed) for seed in SEEDS]
        if over():
            for (r2, sd2) in regime_cells:
                skipped.append({"what": "cell %s/%d" % (r2, sd2),
                                "reason": "wall-guard",
                                "iters_done": 0, "n_evaluated": n_rep})
        else:
            for (r2, sd2) in regime_cells:
                if over():
                    skipped.append({"what": "cell %s/%d" % (r2, sd2),
                                    "reason": "wall-guard",
                                    "iters_done": 0, "n_evaluated": n_rep})
                    continue
                rec = run_cell(r2, sd2)
                cellrecs.append(rec)
                record_cell(rec)
        with open(os.path.join(witdir, "cells.json"), "w") as f:
            json.dump(cellrecs, f, indent=1, default=str)
        checkpoint(regime)
    with open(os.path.join(witdir, "cells.json"), "w") as f:
        json.dump(cellrecs, f, indent=1, default=str)
    checkpoint("corpus")

    def cell_mean(regime, seed, arm, field):
        return cells.get((regime, seed, arm),
                         {"volume": [], "stalls": []})[field]

    def pool(regime, arm, field):
        vals = []
        for seed in SEEDS:
            vals.extend(cell_mean(regime, seed, arm, field))
        return pooled_stats(vals), len(vals) == len(SEEDS)

    det_probe = simulate(
        "S", *make_traces("small", 1, 0), fronts["small"],
        REGIME_PARAMS["small"], base_tiles_of("small"),
        choice_rng("small", 1, 0), None)
    det_probe2 = simulate(
        "S", *make_traces("small", 1, 0), fronts["small"],
        REGIME_PARAMS["small"], base_tiles_of("small"),
        choice_rng("small", 1, 0), None)
    determinism_ok = bool(det_probe == det_probe2)

    g1_cells, g1_beats = [], True
    for regime in REGIMES:
        for seed in SEEDS:
            ms = cell_mean(regime, seed, "S", "volume")
            mr = cell_mean(regime, seed, "R", "volume")
            ok = (len(ms) == 1 and len(mr) == 1 and ms[0] < mr[0])
            g1_cells.append({"cell": "%s/%d" % (regime, seed),
                             "mean_S": ms[0] if ms else None,
                             "mean_R": mr[0] if mr else None,
                             "pass": bool(ok)})
            if not ok:
                g1_beats = False
    g1_ok = bool(g1_beats and tiny_ok and determinism_ok)

    g2_regimes, g2_n = [], 0
    g2s_regimes, g2s_n = [], 0
    win_regimes, win_n = [], 0
    for regime in REGIMES:
        pools, pok = {}, True
        for arm in ("S", "B", "C"):
            pools[arm], oka = pool(regime, arm, "volume")
            pok = pok and oka
        se, spread, gp = spread_win(pools, pok)
        g2_regimes.append({"regime": regime, "pools": pools, "SE": se,
                           "spread": spread, "pass": bool(gp)})
        if gp:
            g2_n += 1
        spools, spok = {}, True
        for arm in ("S", "B", "C"):
            spools[arm], oka = pool(regime, arm, "stalls")
            spok = spok and oka
        sse, sspread, sgp = spread_win(spools, spok)
        g2s_regimes.append({"regime": regime, "pools": spools,
                            "SE": sse, "spread": sspread,
                            "pass": bool(sgp)})
        if sgp:
            g2s_n += 1
        joint = {}
        if pok and spok and all(
                pools[a]["se"] is not None and
                pools[a]["mean"] is not None for a in ("S", "B", "C")):
            sse2 = math.sqrt(sum(pools[a]["se"] ** 2
                                 for a in ("S", "B", "C")) / 3.0)
            for a in ("B", "C"):
                vwin = pools[a]["mean"] < pools["S"]["mean"] - 2.0 * sse2
                cok = spools[a]["mean"] <= spools["S"]["mean"]
                joint[a] = bool(vwin and cok)
        else:
            joint = {"B": False, "C": False}
        winner = ("B" if joint["B"]
                  else ("C" if joint["C"] else None))
        wpass = winner is not None
        if pok and all(pools[a]["mean"] is not None
                       for a in ("S", "B", "C")):
            spass = (pools["B"]["mean"] < pools["S"]["mean"] or
                     pools["C"]["mean"] < pools["S"]["mean"])
        else:
            spass = False
        win_regimes.append({"regime": regime, "win": bool(wpass),
                            "strict_win": bool(spass),
                            "pools_ok": bool(pok),
                            "joint": dict(joint), "winner": winner})
        if wpass:
            win_n += 1
    g2_ok = g2_n >= 2

    tiny_solved = (gate3tiny["total"] == 1 and gate3tiny["solved"] == 1)
    target_cap = (len(gate3targets) == 1 and
                  gate3targets[0].get("status") == "cap-hit")
    g3pass = bool(tiny_solved and target_cap)

    complete = all(
        len(cell_mean(regime, seed, arm, "volume")) == 1
        for regime in REGIMES for seed in SEEDS for arm in ARMS)
    tiny_attempted = gate3tiny["total"] == 1
    targets_attempted = len(gate3targets) == 1
    wall = elapsed()
    clean = len(skipped) == 0
    g4_ok = bool(complete and tiny_attempted and targets_attempted and
                 wall < WALL_LIMIT_S and clean)

    selftest_ok = bool(tiny_ok)
    strict_n = sum(1 for wrec in win_regimes if wrec.get("strict_win"))
    pools_all = all(wrec.get("pools_ok") for wrec in win_regimes)
    pursue = (win_n >= 2 and g1_ok and g2_ok and g3pass and g4_ok and
              selftest_ok)
    reject = (complete and tiny_solved and g1_ok and
              pools_all and strict_n == 0)
    if pursue:
        reason = "PURSUE-condition holds (dynamic joint volume win + " \
            "stall no-regress on the SAME arm at >=2 regimes + gates " \
            "1,2,3,4 + self-tests ok); payload verdict stays " \
            "unresolved-with-reason, classification is coordinator-side."
    elif reject:
        reason = "REJECT-condition holds (complete cells, tiny solved, " \
            "Gate-1 controls pass, no strict pooled dynamic volume " \
            "win at any regime); payload verdict stays " \
            "unresolved-with-reason, classification is coordinator-side."
    else:
        reason = "UNRESOLVED + next experiment (joint wins=%d/3, " \
            "strict dynamic wins=%d/3, g1=%s g2=%s g2s(stall-spread)=" \
            "%s g3=%s (tiny solved=%s, target cap-hit=%s) " \
            "selftest=%s g4=%s complete=%s skipped=%d; next: " \
            "burst-heavier fronts with larger shared buffers to " \
            "separate joint corridor scheduling from buffer-only " \
            "gains)." % (
                win_n, strict_n, g1_ok, g2_ok, g2s_n >= 2, g3pass,
                tiny_solved, target_cap,
                selftest_ok, g4_ok, complete, len(skipped))
    verdict_bits = {
        "gate1": {"pass": bool(g1_ok), "beats_all_15": bool(g1_beats),
                  "tiny_ok": bool(tiny_ok),
                  "determinism_ok": bool(determinism_ok),
                  "cells": g1_cells},
        "gate2": {"pass": bool(g2_ok), "n_regimes_pass": g2_n,
                  "regimes": g2_regimes},
        "gate2_s": {"pass": bool(g2s_n >= 2), "n_regimes_pass": g2s_n,
                    "regimes": g2s_regimes},
        "gate3": {"pass": bool(g3pass), "tiny_solved": tiny_solved,
                  "tiny": gate3tiny,
                  "targets": gate3targets, "target_cap": target_cap},
        "gate4": {"pass": bool(g4_ok), "complete": bool(complete),
                  "tiny_attempted": bool(tiny_attempted),
                  "targets_attempted": bool(targets_attempted),
                  "wall_sec": wall, "clean": bool(clean)},
        "acceptance": {"pursue_condition": bool(pursue),
                       "reject_condition": bool(reject),
                       "win_regimes": win_regimes, "n_win": win_n,
                       "n_strict_win": strict_n,
                       "selftest_ok": bool(selftest_ok)},
        "reason": reason,
    }

    results = {
        "screen": "07",
        "verdict": "unresolved-with-reason: payload reports numbers "
                   "and gate evidence; classification is coordinator-side.",
        "design": {
            "model": "screen-authored deterministic 2D tile/buffer "
                     "scheduling sim (stdlib + numpy only; no external "
                     "libs)",
            "regimes": {r: dict(REGIME_PARAMS[r]) for r in REGIMES},
            "base_tiles": {r: base_tiles_of(r) for r in REGIMES},
            "tile_compute": TILE_COMPUTE,
            "corr_tile_per_w": CORR_TILE_PER_W,
            "tile_per_state": TILE_PER_STATE,
            "seeds": list(SEEDS),
            "reps_per_cell_arm": n_rep,
            "front_len": {r: len(fronts[r]) for r in REGIMES},
            "ready_window": READY_WINDOW,
            "lookahead": {"B": LOOKAHEAD_K_B, "C": LOOKAHEAD_K_C},
            "arms": {"S": "static FIFO (fixed buffer partition, "
                          "FIFO serve)",
                     "B": "dynamic buffer-aware (shared pool, "
                          "abundant-first serve)",
                     "C": "joint buffer+corridor (B rules + one-step "
                          "corridor rollout, deeper lookahead)",
                     "R": "random control (static partition, "
                          "single random transfer, contention idle "
                          "p=%.2f)" % R_IDLE_P},
            "metrics": "provisioned active tiles x code cycles "
                       "(footprint volume), stall counts",
            "pareto": "PURSUE needs a dynamic volume win + stall "
                      "no-regress on the SAME arm; a volume-only win "
                      "with higher stalls is NOT a joint win",
            "exact": "bounded-exact DFS scheduler on tiny "
                     "(1 instance, must solve, optimum %d) + "
                     "target-scale instance (front %d, horizon %d, "
                     "node cap %d, must cap-hit)" % (
                         TINY2_EXP["volume"], TARGET_FRONT_LEN,
                         TARGET_HORIZON, EXACT_CAP),
        },
        "timing": {"wall_s": wall, "guards": {"wall_guard_s": WALL_GUARD_S,
                                              "limit_s": WALL_LIMIT_S}},
        "cells": {("%s/%d/%s" % k): {"n": len(v["volume"]),
                                     **pooled_stats(v["volume"]),
                                     "stalls": pooled_stats(
                                         v["stalls"])}
                  for k, v in cells.items()},
        "gates": verdict_bits,
        "skipped": skipped,
    }
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)


if __name__ == "__main__":
    main()
