"""Screen 03 payload: Floquet / dynamical-code schedule optimization.

Screen-authored deterministic detector simulator (stdlib + numpy only;
no external physics/solver libs): 2-body Pauli checks on small
heavy-hex cells (ring + chords, max degree 3) with bond-type coloring
(X/Y/Z by edge index mod 3), measured over T = 4 rounds. A schedule is
one permutation of the check set used every round. Faults are
single-qubit X/Z faults at interior slots (rounds 1..T-2); detectors
compare consecutive rounds of the same check. Metric: exact
detecting-region distance (minimum fault weight with empty syndrome
and nontrivial residual, exact weights 1..3 by exhaustive
fault enumeration, censored ">3" above) + cycle depth (T x
list-scheduled layers). Arms: H static Hastings-Haah cyclic
(canonical order baseline), R random control, G greedy
first-improvement on distance, S local-swap annealing
(cost = -distance + LAMBDA * depth). Defects: 0/1/2 edges removed
(seeded, nested). A bounded-exact BFS over schedules validates the
tiny cell (solved) and cap-hits at target scale (limit-expiry).
Writes ALL output under cwd (the attempt work dir): results.json +
witnesses/. Deterministic given seeds. Verdict is always
unresolved-with-reason; classification is coordinator-side.
"""

import argparse
import hashlib
import json
import math
import os
import time
from collections import deque

import numpy as np

SIZES = (8, 14, 20)
T_ROUNDS = 4
SEEDS = (1, 2, 3, 4, 5)
DEFECTS = (0, 1, 2)
ARMS = ("H", "R", "G", "S")

R_SAMPLES = 3
GREEDY_SWEEPS = 1
S_ITERS = 30
S_T0 = 0.5
S_ALPHA = 0.95
LAMBDA = 0.05
MAXW = 3
DCENS = 4

WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0
EXACT_CAP = 50000

TINY_N = 6
TARGET_SIZE_IDX = 2
TARGET_SEED = 1
TARGET_DEFECT = 0


def seed_rng(si, di, seed, salt):
    return np.random.default_rng(
        (int(si * 100003 + di * 7919 + seed * 10007
             + salt * 1000003) % (2 ** 63 - 1)))


def cell_edges(n, tiny=False):
    edges = [(i, (i + 1) % n) for i in range(n)]
    if not tiny:
        for i in range(0, n, 4):
            edges.append((i, (i + 3) % n))
    return edges


def build_cell(n, tiny=False, drop=()):
    edges_all = cell_edges(n, tiny)
    keep = [e for i, e in enumerate(edges_all) if i not in set(drop)]
    types = {}
    for i, e in enumerate(edges_all):
        if i not in set(drop):
            types[len(types)] = i % 3
    edges = keep
    C = len(edges)
    tlist = [types[k] for k in range(C)]
    adj = [[] for _ in range(n)]
    for ei, (a, b) in enumerate(edges):
        adj[a].append(ei)
        adj[b].append(ei)
    return {"n": n, "C": C, "edges": edges, "adj": adj,
            "types": tlist, "tiny": tiny, "drop": list(drop)}


def def_edges(si, seed, k, Cfull, n):
    if k == 0:
        return []
    rng = seed_rng(si, 7, seed, 31)
    picks = sorted(int(x) for x in rng.choice(Cfull, size=2,
                                                 replace=False))
    return picks[:k]


def sched_sig(cell, pi):
    h = hashlib.sha256(repr((cell["edges"], pi)).encode())
    return h.hexdigest()[:16]


def schedule_pos(pi):
    pos = [0] * len(pi)
    for p, e in enumerate(pi):
        pos[e] = p
    return pos


def pmul(a, b):
    if a == 0:
        return b
    if b == 0:
        return a
    if a == b:
        return 0
    return 6 - a - b


def residual_nontrivial(fps):
    d = {}
    for q, P in fps:
        v = pmul(d.get(q, 0), P)
        if v == 0:
            d.pop(q, None)
        else:
            d[q] = v
    return len(d) > 0


def fault_list(cell, pos, T):
    C = cell["C"]
    types = cell["types"]
    adj = cell["adj"]
    n = cell["n"]
    out = []
    for q in range(n):
        inc = [(e, types[e]) for e in adj[q]]
        for r in range(1, T - 1):
            base = r * C
            for pr in range(C):
                for P in (1, 3):
                    m = 0
                    for (e, t) in inc:
                        if t == P - 1:
                            continue
                        k = r - 1 if pr <= pos[e] else r
                        m |= 1 << (e * (T - 1) + k)
                    out.append((q, base + pr, P, m))
    return out


def exact_distance(cell, pi, T, stop=None):
    pos = schedule_pos(pi)
    faults = fault_list(cell, pos, T)
    L = len(faults)
    masks = [f[3] for f in faults]
    for i, m in enumerate(masks):
        if m == 0:
            q, s, P = faults[i][0], faults[i][1], faults[i][2]
            return {"d": 1, "w": [[q, s, P]], "stopped": False,
                    "n_faults": L}
    groups = {}
    for i, (q, s, P, m) in enumerate(faults):
        groups.setdefault(m, []).append((i, q, P))
    for m, lst in groups.items():
        seen = {}
        for (i, q, P) in lst:
            for (q2, P2) in seen:
                if (q, P) != (q2, P2):
                    i2 = seen[(q2, P2)]
                    return {"d": 2, "w": [
                        [faults[i2][0], faults[i2][1],
                         faults[i2][2]],
                        [q, faults[i][1], P]], "stopped": False,
                            "n_faults": L}
            seen.setdefault((q, P), i)
    qp = [(faults[i][0], faults[i][2]) for i in range(L)]
    for i in range(L):
        if i % 512 == 0 and stop is not None and stop():
            return {"d": None, "w": [], "stopped": True,
                    "n_faults": L}
        mi = masks[i]
        q1, P1 = qp[i]
        for j in range(i + 1, L):
            hit = groups.get(mi ^ masks[j])
            if not hit:
                continue
            q2, P2 = qp[j]
            for (k, q3, P3) in hit:
                if residual_nontrivial([(q1, P1), (q2, P2),
                                        (q3, P3)]):
                    return {"d": 3, "w": [
                        [q1, faults[i][1], P1],
                        [q2, faults[j][1], P2],
                        [q3, faults[k][1], P3]],
                            "stopped": False, "n_faults": L}
    return {"d": None, "w": [], "stopped": False, "n_faults": L}


def cycle_depth(cell, pi, T):
    n = cell["n"]
    edges = cell["edges"]
    free = [0] * n
    for e in pi:
        a, b = edges[e]
        lv = (free[a] if free[a] >= free[b] else free[b]) + 1
        free[a] = lv
        free[b] = lv
    return int(T * max(free))


def eval_schedule(cell, pi, T, stop=None):
    rec = exact_distance(cell, pi, T, stop)
    if rec.get("stopped"):
        return {"stopped": True}
    depth = cycle_depth(cell, pi, T)
    d = rec["d"]
    return {"stopped": False, "d": d, "dn": (d if d else DCENS),
            "censored": bool(not d), "depth": depth, "w": rec["w"],
            "n_faults": rec["n_faults"]}


def run_H(cell, T, stop):
    C = cell["C"]
    out = eval_schedule(cell, list(range(C)), T, stop)
    if out.get("stopped"):
        return {"stopped": True, "iters_done": 0, "n_evaluated": 1}
    return {"stopped": False, "d": out["dn"], "depth": out["depth"],
            "censored": out["censored"], "iters_done": 1,
            "n_evaluated": 1}


def run_R(cell, T, rng, stop, n_samples):
    C = cell["C"]
    ds, dp, nc = [], [], 0
    for _ in range(n_samples):
        if stop is not None and stop():
            return {"stopped": True, "iters_done": nc,
                    "n_evaluated": n_samples}
        pi = [int(x) for x in rng.permutation(C)]
        out = eval_schedule(cell, pi, T, stop)
        if out.get("stopped"):
            return {"stopped": True, "iters_done": nc,
                    "n_evaluated": n_samples}
        ds.append(out["dn"])
        dp.append(out["depth"])
        nc += 1
    return {"stopped": False, "d": sum(ds) / len(ds),
            "depth": sum(dp) / len(dp), "iters_done": nc,
            "n_evaluated": n_samples}


def run_G(cell, T, stop):
    C = cell["C"]
    pi = list(range(C))
    cur = eval_schedule(cell, pi, T, stop)
    if cur.get("stopped"):
        return {"stopped": True, "iters_done": 0,
                "n_evaluated": C * (C - 1) // 2 * GREEDY_SWEEPS}
    total = C * (C - 1) // 2 * GREEDY_SWEEPS
    done = 1
    ci = 0
    for _ in range(GREEDY_SWEEPS):
        for i in range(C):
            for j in range(i + 1, C):
                if ci % 32 == 0 and stop is not None and stop():
                    return {"stopped": True, "iters_done": done,
                            "n_evaluated": total}
                ci += 1
                pi[i], pi[j] = pi[j], pi[i]
                out = eval_schedule(cell, pi, T, stop)
                if out.get("stopped"):
                    pi[i], pi[j] = pi[j], pi[i]
                    return {"stopped": True, "iters_done": done,
                            "n_evaluated": total}
                done += 1
                if (out["dn"] > cur["dn"] or
                        (out["dn"] == cur["dn"] and
                         out["depth"] < cur["depth"])):
                    cur = out
                else:
                    pi[i], pi[j] = pi[j], pi[i]
    return {"stopped": False, "d": cur["dn"], "depth": cur["depth"],
            "censored": cur["censored"], "iters_done": done,
            "n_evaluated": total + 1}


def run_S(cell, T, rng, stop, n_iters):
    C = cell["C"]
    pi = list(range(C))
    cur = eval_schedule(cell, pi, T, stop)
    if cur.get("stopped"):
        return {"stopped": True, "iters_done": 0,
                "n_evaluated": n_iters}
    best = (cur["dn"], -cur["depth"])
    bd, bp = cur["dn"], cur["depth"]
    cost = -cur["dn"] + LAMBDA * cur["depth"]
    temp = S_T0
    done = 1
    for it in range(n_iters):
        if it % 32 == 0 and stop is not None and stop():
            break
        pair = rng.integers(0, C, 2)
        i, j = int(pair[0]), int(pair[1])
        if i == j:
            temp *= S_ALPHA
            continue
        pi[i], pi[j] = pi[j], pi[i]
        out = eval_schedule(cell, pi, T, stop)
        if out.get("stopped"):
            pi[i], pi[j] = pi[j], pi[i]
            break
        done += 1
        cost2 = -out["dn"] + LAMBDA * out["depth"]
        if cost2 < cost or bool(
                rng.random() < math.exp(-(cost2 - cost) / temp)):
            cost = cost2
            if (out["dn"], -out["depth"]) > best:
                best = (out["dn"], -out["depth"])
                bd, bp = out["dn"], out["depth"]
        else:
            pi[i], pi[j] = pi[j], pi[i]
        temp *= S_ALPHA
    return {"stopped": False, "d": bd, "depth": bp,
            "iters_done": done, "n_evaluated": n_iters + 1}


def bfs_schedules(cell, T, cap, stop):
    C = cell["C"]
    q = deque([()])
    nodes = 0
    best = None
    while q:
        if nodes % 512 == 0 and stop is not None and stop():
            return {"status": "stopped-guard", "nodes": nodes,
                    "best": best, "cap": cap, "started": True}
        p = q.popleft()
        if len(p) == C:
            out = eval_schedule(cell, list(p), T, stop)
            if out.get("stopped"):
                return {"status": "stopped-guard", "nodes": nodes,
                        "best": best, "cap": cap, "started": True}
            key = (out["dn"], -out["depth"])
            if best is None or key > (best["dn"], -best["depth"]):
                best = {"dn": out["dn"], "depth": out["depth"],
                        "pi": list(p), "w": out["w"],
                        "censored": out["censored"]}
        else:
            used = set(p)
            for e in range(C):
                if e not in used:
                    nodes += 1
                    if nodes > cap:
                        return {"status": "cap-hit", "nodes": nodes,
                                "best": best, "cap": cap,
                                "started": True}
                    q.append(p + (e,))
    return {"status": "solved", "nodes": nodes, "best": best,
            "cap": cap, "started": True}


def direct_check(cell, pi, T, w):
    C = cell["C"]
    types = cell["types"]
    adj = cell["adj"]
    pos = schedule_pos(pi)
    flipped = set()
    res = {}
    for (q, s, P) in w:
        v = pmul(res.get(q, 0), P)
        if v == 0:
            res.pop(q, None)
        else:
            res[q] = v
        for (e, t) in ((e2, types[e2]) for e2 in adj[q]):
            if t == P - 1:
                continue
            for k in range(T - 1):
                if k * C + pos[e] < s <= (k + 1) * C + pos[e]:
                    if (e, k) in flipped:
                        flipped.discard((e, k))
                    else:
                        flipped.add((e, k))
    return len(flipped) == 0 and len(res) > 0


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


def tiny_cell():
    return build_cell(TINY_N, tiny=True, drop=())


def self_tests():
    out = {"ran": True, "failed": []}
    try:
        for si, n in enumerate(SIZES):
            e0 = cell_edges(n)
            if len(e0) != n + (n // 4 + (1 if n % 4 else 0)):
                out["failed"].append("cell-count-%d" % n)
            deg = [0] * n
            for a, b in e0:
                deg[a] += 1
                deg[b] += 1
            if max(deg) > 3:
                out["failed"].append("cell-deg-%d" % n)
        tc = tiny_cell()
        tH = list(range(tc["C"]))
        hev = eval_schedule(tc, tH, T_ROUNDS, None)
        if hev.get("stopped") or hev["dn"] < 2:
            out["failed"].append("tiny-hand-bound")
        else:
            if hev["d"] is not None:
                if not direct_check(tc, tH, T_ROUNDS, hev["w"]):
                    out["failed"].append("tiny-witness")
                fl = fault_list(tc, schedule_pos(tH), T_ROUNDS)
                if any(m == 0 for (_, _, _, m) in fl):
                    out["failed"].append("tiny-w1-exists")
            else:
                out["failed"].append("tiny-censored")
        tbfs = bfs_schedules(tc, T_ROUNDS, EXACT_CAP, None)
        if tbfs["status"] != "solved" or not tbfs["best"]:
            out["failed"].append("tiny-bfs-solve")
        elif tbfs["best"]["dn"] < hev["dn"]:
            out["failed"].append("tiny-opt-below-H")
        elif not tbfs["best"]["censored"] and not direct_check(
                tc, tbfs["best"]["pi"], T_ROUNDS,
                tbfs["best"]["w"]):
            out["failed"].append("tiny-opt-witness")
        c0 = build_cell(SIZES[0], drop=def_edges(
            0, SEEDS[0], 1, SIZES[0] + SIZES[0] // 4 +
            (1 if SIZES[0] % 4 else 0), SIZES[0]))
        g1 = run_G(c0, T_ROUNDS, None)
        g2 = run_G(c0, T_ROUNDS, None)
        if ((g1.get("d"), g1.get("depth")) !=
                (g2.get("d"), g2.get("depth"))):
            out["failed"].append("determinism-greedy")
        r1 = run_R(c0, T_ROUNDS, seed_rng(0, 0, 1, 999), None,
                   R_SAMPLES)
        r2 = run_R(c0, T_ROUNDS, seed_rng(0, 0, 1, 999), None,
                   R_SAMPLES)
        if ((r1.get("d"), r1.get("depth")) !=
                (r2.get("d"), r2.get("depth"))):
            out["failed"].append("determinism-random")
        d1 = def_edges(1, 2, 2, 99, 99)
        d2 = def_edges(1, 2, 2, 99, 99)
        if d1 != d2 or len(d1) != 2:
            out["failed"].append("determinism-defect")
    except Exception as ex:
        out["failed"].append("raise: %r" % ex)
    return out


def run_arm(si, di, seed, arm, n_iters, n_samples, stop):
    n = SIZES[si]
    Cfull = n + (n // 4 + (1 if n % 4 else 0))
    drop = def_edges(si, seed, DEFECTS[di], Cfull, n)
    cell = build_cell(n, drop=drop)
    if arm == "H":
        return run_H(cell, T_ROUNDS, stop)
    if arm == "R":
        return run_R(cell, T_ROUNDS,
                     seed_rng(si, di, seed, 999), stop, n_samples)
    if arm == "G":
        return run_G(cell, T_ROUNDS, stop)
    return run_S(cell, T_ROUNDS, seed_rng(si, di, seed, 777),
                 stop, n_iters)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--attempt", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--s-iters", type=int, default=S_ITERS)
    ap.add_argument("--r-samples", type=int, default=R_SAMPLES)
    args = ap.parse_args()
    n_iters = int(args.s_iters)
    n_samples = int(args.r_samples)
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
    gate3tiny = {"arms": {}, "solved": 0, "total": 0}
    gate3targets = []
    selftest = self_tests()
    with open(os.path.join(witdir, "selftest.json"), "w") as f:
        json.dump(selftest, f, indent=1, default=str)

    def checkpoint(tag):
        try:
            with open(os.path.join(
                    witdir, "checkpoint-%s.json" % tag), "w") as f:
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

    if over():
        gate3tiny["arms"]["tiny"] = {"status": "skipped-guard"}
        skipped.append({"what": "tiny-exact", "reason": "wall-guard",
                        "iters_done": 0, "n_evaluated": 1})
    else:
        tex = bfs_schedules(tiny_cell(), T_ROUNDS, EXACT_CAP, over)
        gate3tiny["arms"]["tiny"] = tex
        gate3tiny["total"] += 1
        if tex["status"] == "solved" and tex.get("best"):
            gate3tiny["solved"] += 1
    with open(os.path.join(witdir, "gate3_tiny.json"), "w") as f:
        json.dump(gate3tiny, f, indent=1, default=str)
    checkpoint("tiny")

    if over():
        gate3targets.append({"status": "skipped-guard"})
        skipped.append({"what": "target-exact", "reason": "wall-guard",
                        "iters_done": 0, "n_evaluated": 1})
    else:
        si, di, seed = TARGET_SIZE_IDX, 0, TARGET_SEED
        n = SIZES[si]
        Cfull = n + (n // 4 + (1 if n % 4 else 0))
        tcell = build_cell(
            n, drop=def_edges(si, seed, DEFECTS[di], Cfull, n))
        tex = bfs_schedules(tcell, T_ROUNDS, EXACT_CAP, over)
        gate3targets.append(dict(tex, size=n, defect=DEFECTS[di],
                                seed=seed))
    with open(os.path.join(witdir, "gate3_targets.json"), "w") as f:
        json.dump(gate3targets, f, indent=1, default=str)
    checkpoint("targets")

    planned = {"H": 1, "R": n_samples, "G": None, "S": n_iters + 1}

    def run_cell(si, di, seed):
        n = SIZES[si]
        Cfull = n + (n // 4 + (1 if n % 4 else 0))
        drop = def_edges(si, seed, DEFECTS[di], Cfull, n)
        C = Cfull - len(drop)
        planned["G"] = C * (C - 1) // 2 * GREEDY_SWEEPS + 1
        rec = {"size": n, "defect": DEFECTS[di], "seed": seed,
               "arms": {},
               "sig": sched_sig(build_cell(n, drop=drop),
                                list(range(C)))}
        for arm in ARMS:
            if over():
                rec["blocked"] = "wall-guard"
                return rec
            out = run_arm(si, di, seed, arm, n_iters, n_samples,
                          over)
            if out.get("stopped"):
                rec["blocked"] = "stopped-guard"
                rec["iters_done"] = out.get("iters_done", 0)
                rec["n_evaluated"] = out.get(
                    "n_evaluated", planned[arm])
                return rec
            rec["arms"][arm] = {
                "n": 1, "d": out["d"], "depth": out["depth"],
                "iters_done": out.get("iters_done", 0),
                "n_evaluated": out.get("n_evaluated", 0)}
        return rec

    def record_cell(rec):
        if rec.get("blocked") is None and all(
                rec["arms"].get(a, {}).get("n") == 1 for a in ARMS):
            for a in ARMS:
                key = (rec["size"], rec["defect"], rec["seed"], a)
                cells.setdefault(key, {"d": [], "depth": []})
                cells[key]["d"].append(rec["arms"][a]["d"])
                cells[key]["depth"].append(rec["arms"][a]["depth"])
            return True
        skipped.append({"what": "cell %d/d%d/%d" % (
            rec["size"], rec["defect"], rec["seed"]),
            "reason": rec.get("blocked", "arm-incomplete"),
            "iters_done": rec.get("iters_done", 0),
            "n_evaluated": rec.get("n_evaluated", 0)})
        return False

    for si, n in enumerate(SIZES):
        siz_cells = [(si, di, seed) for di in range(len(DEFECTS))
                     for seed in SEEDS]
        if over():
            for (s2, d2, sd2) in siz_cells:
                skipped.append({"what": "cell %d/d%d/%d" % (
                    SIZES[s2], DEFECTS[d2], sd2),
                    "reason": "wall-guard", "iters_done": 0,
                    "n_evaluated": 0})
        else:
            for (s2, d2, sd2) in siz_cells:
                if over():
                    skipped.append({"what": "cell %d/d%d/%d" % (
                        SIZES[s2], DEFECTS[d2], sd2),
                        "reason": "wall-guard", "iters_done": 0,
                        "n_evaluated": 0})
                    continue
                rec = run_cell(s2, d2, sd2)
                cellrecs.append(rec)
                record_cell(rec)
        with open(os.path.join(witdir, "cells.json"), "w") as f:
            json.dump(cellrecs, f, indent=1, default=str)
        checkpoint("size%d" % n)
    with open(os.path.join(witdir, "cells.json"), "w") as f:
        json.dump(cellrecs, f, indent=1, default=str)
    checkpoint("corpus")

    def cell_vals(n, dk, seed, arm, field):
        return cells.get((n, dk, seed, arm),
                         {"d": [], "depth": []})[field]

    def pool(vals):
        return pooled_stats(vals), len(vals) == len(SEEDS)

    det1 = run_arm(0, 0, 1, "G", n_iters, n_samples, None)
    det2 = run_arm(0, 0, 1, "G", n_iters, n_samples, None)
    det_r1 = run_arm(0, 0, 1, "R", n_iters, n_samples, None)
    det_r2 = run_arm(0, 0, 1, "R", n_iters, n_samples, None)
    determinism_ok = bool(
        (det1.get("d"), det1.get("depth")) == (det2.get("d"),
                                              det2.get("depth"))
        and (det_r1.get("d"), det_r1.get("depth")) == (
            det_r2.get("d"), det_r2.get("depth")))

    g1_cells, g1_beats = [], True
    for n in SIZES:
        for dk in DEFECTS:
            ms = [cell_vals(n, dk, s, "G", "d") for s in SEEDS]
            mr = [cell_vals(n, dk, s, "R", "d") for s in SEEDS]
            ok = (all(len(v) == 1 for v in ms + mr)
                  and sum(v[0] for v in ms) / 5.0 >
                  sum(v[0] for v in mr) / 5.0)
            g1_cells.append({"cell": "%d/d%d" % (n, dk),
                             "mean_G": (sum(v[0] for v in ms) / 5.0
                                        if all(ms) else None),
                             "mean_R": (sum(v[0] for v in mr) / 5.0
                                        if all(mr) else None),
                             "pass": bool(ok)})
            if not ok:
                g1_beats = False
    g1_ok = bool(g1_beats and tiny_ok and determinism_ok)

    g2_fams = []
    g2_sizes = set()
    for n in SIZES:
        for dk in DEFECTS:
            pools, pok = {}, True
            for arm in ("H", "G", "S"):
                vals = []
                for s in SEEDS:
                    vals.extend(cell_vals(n, dk, s, arm, "d"))
                pools[arm], oka = pool(vals)
                pok = pok and oka
            se, spread, gp = spread_win(pools, pok)
            g2_fams.append({"cell": "%d/d%d" % (n, dk),
                            "pools": pools, "SE": se,
                            "spread": spread, "pass": bool(gp)})
            if gp:
                g2_sizes.add(n)
    g2_n = sum(1 for g in g2_fams if g["pass"])
    g2_ok = bool(g2_n >= 4 and len(g2_sizes) >= 2)

    win_fams = []
    win_n = 0
    for n in SIZES:
        pools, pok, dpools, dok = {}, True, {}, True
        for arm in ("H", "G", "S"):
            vals, dvals = [], []
            for s in SEEDS:
                for dk in (1, 2):
                    vals.extend(cell_vals(n, dk, s, arm, "d"))
                    dvals.extend(cell_vals(n, dk, s, arm,
                                           "depth"))
            pools[arm], oka = pooled_stats(vals), len(vals) == 10
            dpools[arm], okd = pooled_stats(dvals), \
                len(dvals) == 10
            pok = pok and oka
            dok = dok and okd
        joint = {"G": False, "S": False}
        if pok and dok and all(
                pools[a]["se"] is not None and
                pools[a]["mean"] is not None for a in ("H", "G",
                                                      "S")):
            sse2 = math.sqrt(sum(pools[a]["se"] ** 2
                                 for a in ("H", "G", "S")) / 3.0)
            for a in ("G", "S"):
                dwin = pools[a]["mean"] > pools["H"]["mean"] + \
                    2.0 * sse2
                hdepth = (dpools[a]["mean"] is not None
                          and dpools["H"]["mean"] is not None
                          and dpools[a]["mean"] <=
                          dpools["H"]["mean"])
                joint[a] = bool(dwin and hdepth)
        winner = ("G" if joint["G"]
                  else ("S" if joint["S"] else None))
        wpass = winner is not None
        if pok and all(pools[a]["mean"] is not None
                       for a in ("H", "G", "S")):
            spass = (pools["G"]["mean"] > pools["H"]["mean"] or
                     pools["S"]["mean"] > pools["H"]["mean"])
        else:
            spass = False
        win_fams.append({"size": n, "win": bool(wpass),
                         "strict_win": bool(spass),
                         "pools_ok": bool(pok and dok),
                         "joint": dict(joint), "winner": winner})
        if wpass:
            win_n += 1

    tiny_solved = (gate3tiny["total"] == 1 and gate3tiny["solved"]
                   == 1)
    target_cap = (len(gate3targets) == 1 and
                  gate3targets[0].get("status") == "cap-hit")
    g3pass = bool(tiny_solved and target_cap)

    complete = all(
        len(cell_vals(n, dk, s, a, "d")) == 1
        for n in SIZES for dk in DEFECTS for s in SEEDS
        for a in ARMS)
    tiny_attempted = gate3tiny["total"] == 1
    targets_attempted = len(gate3targets) == 1
    wall = elapsed()
    clean = len(skipped) == 0
    g4_ok = bool(complete and tiny_attempted and targets_attempted
                 and wall < WALL_LIMIT_S and clean)

    selftest_ok = bool(tiny_ok)
    strict_n = sum(1 for wrec in win_fams if wrec.get("strict_win"))
    pools_all = all(wrec.get("pools_ok") for wrec in win_fams)
    pursue = (win_n >= 2 and g1_ok and g2_ok and g3pass and g4_ok
              and selftest_ok)
    reject = (complete and tiny_solved and g1_ok and pools_all
              and strict_n == 0)
    if pursue:
        reason = "PURSUE-condition holds (joint schedule distance " \
            "win + depth no-regress on the SAME arm at >=2 sizes " \
            "under defect conditions + gates 1,2,3,4 + self-tests " \
            "ok); payload verdict stays unresolved-with-reason, " \
            "classification is coordinator-side."
    elif reject:
        reason = "REJECT-condition holds (complete cells, tiny " \
            "solved, Gate-1 controls pass, no strict pooled " \
            "schedule distance win at any size); payload verdict " \
            "stays unresolved-with-reason, classification is " \
            "coordinator-side."
    else:
        reason = "UNRESOLVED + next experiment (joint wins=%d/3, " \
            "strict schedule wins=%d/3, g1=%s g2=%s " \
            "(%d/9 cells) g3=%s (tiny solved=%s, target " \
            "cap-hit=%s) selftest=%s g4=%s complete=%s skipped=%d; " \
            "next: defect-aware check-type recoloring + per-round " \
            "schedule variation retest)." % (
                win_n, strict_n, g1_ok, g2_ok, g2_n, g3pass,
                tiny_solved, target_cap,
                selftest_ok, g4_ok, complete, len(skipped))
    verdict_bits = {
        "gate1": {"pass": bool(g1_ok), "beats_all_9": bool(g1_beats),
                  "tiny_ok": bool(tiny_ok),
                  "determinism_ok": bool(determinism_ok),
                  "cells": g1_cells},
        "gate2": {"pass": bool(g2_ok), "n_cells_pass": g2_n,
                  "sizes_pass": sorted(g2_sizes), "cells": g2_fams},
        "gate3": {"pass": bool(g3pass), "tiny_solved": tiny_solved,
                  "tiny": gate3tiny,
                  "targets": gate3targets, "target_cap": target_cap},
        "gate4": {"pass": bool(g4_ok), "complete": bool(complete),
                  "tiny_attempted": bool(tiny_attempted),
                  "targets_attempted": bool(targets_attempted),
                  "wall_sec": wall, "clean": bool(clean)},
        "acceptance": {"pursue_condition": bool(pursue),
                       "reject_condition": bool(reject),
                       "win_sizes": win_fams, "n_win": win_n,
                       "n_strict_win": strict_n,
                       "selftest_ok": bool(selftest_ok)},
        "reason": reason,
    }

    results = {
        "screen": "03",
        "verdict": "unresolved-with-reason: payload reports numbers "
                   "and gate evidence; classification is coordinator-side.",
        "design": {
            "model": "screen-authored deterministic detector sim "
                     "(stdlib + numpy only; no external libs)",
            "sizes": list(SIZES),
            "t_rounds": T_ROUNDS,
            "defects": list(DEFECTS),
            "seeds": list(SEEDS),
            "anneal": {"iters": n_iters, "t0": S_T0,
                       "alpha": S_ALPHA, "lambda": LAMBDA},
            "greedy": {"sweeps": GREEDY_SWEEPS},
            "r_samples": n_samples,
            "arms": {"H": "static Hastings-Haah cyclic (canonical "
                          "check order)",
                     "R": "random schedule control",
                     "G": "greedy first-improvement on detecting-"
                          "region distance (depth tiebreak)",
                     "S": "local-swap annealing over check order "
                          "(cost = -distance + LAMBDA*depth)"},
            "metrics": "exact detecting-region distance (min fault "
                       "weight, empty syndrome + nontrivial "
                       "residual; exact 1..3, censored >3 -> 4) + "
                       "cycle depth (T x list-scheduled layers)",
            "pareto": "PURSUE needs a distance win + depth "
                      "no-regress on the SAME arm; a distance-only "
                      "win with higher depth is NOT a joint win",
            "exact": "bounded-exact BFS over schedules on tiny "
                     "(must solve) + target-scale instance "
                     "(size %d, defect %d, node cap %d, must "
                     "cap-hit)" % (SIZES[TARGET_SIZE_IDX],
                                   DEFECTS[TARGET_DEFECT],
                                   EXACT_CAP),
        },
        "timing": {"wall_s": wall, "guards": {"wall_guard_s": WALL_GUARD_S,
                                              "limit_s": WALL_LIMIT_S}},
        "cells": {("%d/d%d/%d/%s" % k): {"n": len(v["d"]),
                                        **pooled_stats(v["d"]),
                                        "depth": pooled_stats(
                                            v["depth"])}
                  for k, v in cells.items()},
        "gates": verdict_bits,
        "skipped": skipped,
    }
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)


if __name__ == "__main__":
    main()
