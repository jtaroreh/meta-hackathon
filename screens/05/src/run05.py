"""Screen 05 payload: fault-tolerant magic-state cultivation /
post-selection schedules.

Screen-authored deterministic Clifford stabilizer-frame simulator
(stdlib + numpy only; no external physics, synthesis, or solver
libraries). Small cultivation stages (ring + chord cells, max degree 3,
bond-type check coloring X/Y/Z by edge index mod 3) measured over T
rounds per stage. A cultivation attempt runs the checks in canonical
order; an abort policy holds per-checkpoint syndrome-weight thresholds
(abort as soon as the cumulative detector weight exceeds the threshold)
plus a final acceptance threshold (post-select; the random
control keeps the final threshold strict at 0, randomizing only abort
timing). Faults are single-qubit X/Z faults at interior slots
(rounds 1..T-2, every check position); detectors compare consecutive
rounds of the same check.
Metric: wasted spacetime volume per accepted output at matched output
infidelity, by fault-enumeration approximation (exact weights 0..2 with
binomial weighting at physical depolarizing rate p; tail mass w>=3
counted as rejected at full volume and non-logical, disclosed). Arms: F
fixed post-selection (never abort early, strict final post-select --
the decomposed baseline), R random abort-control (seeded random
thresholds, mean over samples), G greedy adaptive abort (constrained
first-improvement from F: strictly lower wasted volume at matched
infidelity), A annealed adaptive policy (cost = W + LAMBDA *
infidelity). A bounded-exact joint search over check schedules x abort
policies validates the tiny cell (solved) and cap-hits at target scale
(limit-expiry). Writes ALL output under cwd (the attempt work dir):
results.json + witnesses/. Deterministic given seeds. Verdict is always
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

SIZES = (6, 9, 12)
T_OF = {6: 3, 9: 3, 12: 4}
P_ERRS = (0.001, 0.002, 0.005)
SEEDS = (1, 2, 3, 4, 5)
ARMS = ("F", "R", "G", "A")

ABORT_VALS = (0, 1, 2, 3, 99)
FINAL_VALS = (0, 1, 2)
R_SAMPLES = 3
GREEDY_SWEEPS = 2
A_ITERS = 40
A_T0 = 1.0
A_ALPHA = 0.97
LAMBDA = 5000.0
INF_REL = 0.10
INF_ABS = 1e-6
WIN_RED = 0.10
MEANF_FLOOR = 1e-9

WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0
EXACT_CAP = 50000

TINY_N = 6
TINY_T = 3
P_EXACT = 0.002
TARGET_STAGE_IDX = 2
TARGET_SEED = 1


def seed_rng(si, seed, salt):
    return np.random.default_rng(
        (int(si * 100003 + seed * 10007 + salt * 1000003)
         % (2 ** 63 - 1)))


def cell_edges(n, tiny=False):
    edges = [(i, (i + 1) % n) for i in range(n)]
    if not tiny:
        for i in range(0, n, 4):
            edges.append((i, (i + 3) % n))
    return edges


def build_cell(n, tiny=False, drop=()):
    edges_all = cell_edges(n, tiny)
    drop = set(drop)
    edges = [e for i, e in enumerate(edges_all) if i not in drop]
    types = [i % 3 for i in range(len(edges_all)) if i not in drop]
    C = len(edges)
    adj = [[] for _ in range(n)]
    for ei, (a, b) in enumerate(edges):
        adj[a].append(ei)
        adj[b].append(ei)
    return {"n": n, "C": C, "edges": edges, "adj": adj,
            "types": types, "tiny": tiny, "drop": sorted(drop)}


def drop_one(si, seed, Cfull):
    rng = seed_rng(si, seed, 31)
    return [int(rng.integers(Cfull))]


def round_layers(cell):
    free = [0] * cell["n"]
    for (a, b) in cell["edges"]:
        lv = (free[a] if free[a] >= free[b] else free[b]) + 1
        free[a] = lv
        free[b] = lv
    return int(max(free))


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


def precompute(cell, pi, T):
    """Enumerate weight-1 faults and weight-2 pairs under a schedule.

    Fault (q, r, pr, P): X/Z fault on qubit q just before interior
    round r (1..T-2) at intra-round check position pr. It flips the
    detector of each incident check (type != P-1) at detector-round r.
    A weight-2 pair has mask = XOR and residual = Pauli product.
    Returns numpy trajectories: final + cumulative detector weights
    per checkpoint, spent-volume tables, and volume constants.
    """
    pos = schedule_pos(pi)
    types = cell["types"]
    adj = cell["adj"]
    n = cell["n"]
    C = cell["C"]
    layers = round_layers(cell)
    Vf = float(n * T * layers)
    spent = np.asarray([float(n * (k + 1) * layers)
                        for k in range(T - 1)], dtype=float)
    cumsub = []
    for k in range(T - 1):
        s = 0
        for e in range(C):
            for d in range(1, T):
                if d <= k + 1:
                    s |= 1 << (e * (T - 1) + (d - 1))
        cumsub.append(s)
    f1 = []
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
                    f1.append(m)
    L1 = len(f1)
    fw1 = np.asarray([bin(m).count("1") for m in f1], dtype=int)
    cw1 = np.asarray(
        [[bin(m & s).count("1") for s in cumsub] for m in f1],
        dtype=int).reshape(L1, T - 1) if L1 else np.zeros(
            (0, T - 1), dtype=int)
    npairs = L1 * (L1 - 1) // 2
    fw2 = np.zeros(npairs, dtype=int)
    cw2 = np.zeros((npairs, T - 1), dtype=int)
    nt2 = np.zeros(npairs, dtype=bool)
    qs, ps = [], []
    for q in range(n):
        for r in range(1, T - 1):
            for pr in range(C):
                for P in (1, 3):
                    qs.append(q)
                    ps.append(P)
    k = 0
    for i in range(L1):
        mi = f1[i]
        for j in range(i + 1, L1):
            m = mi ^ f1[j]
            fw2[k] = bin(m).count("1")
            for c, s in enumerate(cumsub):
                cw2[k, c] = bin(m & s).count("1")
            d = {}
            for (q, P) in ((qs[i], ps[i]), (qs[j], ps[j])):
                v = pmul(d.get(q, 0), P)
                if v == 0:
                    d.pop(q, None)
                else:
                    d[q] = v
            nt2[k] = len(d) > 0
            k += 1
    return {"fw1": fw1, "cw1": cw1, "fw2": fw2, "cw2": cw2,
            "nt2": nt2, "L1": L1, "Vf": Vf, "spent": spent,
            "T": T, "layers": layers}


def abort_idx(cw, ath):
    idx = np.full(cw.shape[0], -1)
    alive = np.ones(cw.shape[0], dtype=bool)
    for k, th in enumerate(ath):
        hit = alive & (cw[:, k] > th)
        idx[hit] = k
        alive = alive & (~hit)
        if not alive.any():
            break
    return idx


def eval_policy(pre, ath, fth, p):
    """Wasted spacetime volume per accepted output at infidelity.

    Binomial weighting over weights 0..2 at physical rate p (per
    Pauli-resolved fault location); tail w>=3 counted as rejected at
    full volume and non-logical (disclosed approximation). Weight-1
    faults always carry nontrivial residual, so accepted w1 faults
    are logical. W = E[spent]/P(accept) - V_full.
    """
    Vf = pre["Vf"]
    L1 = pre["L1"]
    a1 = abort_idx(pre["cw1"], ath)
    acc1 = (a1 < 0) & (pre["fw1"] <= fth)
    sp1 = np.where(a1 >= 0, pre["spent"][np.maximum(a1, 0)], Vf)
    a2 = abort_idx(pre["cw2"], ath)
    acc2 = (a2 < 0) & (pre["fw2"] <= fth)
    sp2 = np.where(a2 >= 0, pre["spent"][np.maximum(a2, 0)], Vf)
    L = float(L1)
    P0 = (1.0 - p) ** L
    P1 = L * p * (1.0 - p) ** (L - 1) if L1 else 0.0
    P2 = (L * (L - 1.0) / 2.0) * p ** 2 * (1.0 - p) ** (L - 2.0) \
        if L1 >= 2 else 0.0
    Pt = max(0.0, 1.0 - P0 - P1 - P2)
    a1f = float(acc1.mean()) if L1 else 1.0
    v1 = float(sp1.mean()) if L1 else Vf
    a2f = float(acc2.mean()) if len(acc2) else 1.0
    v2 = float(sp2.mean()) if len(sp2) else Vf
    l2f = float((acc2 & pre["nt2"]).mean()) if len(acc2) else 0.0
    pacc = P0 + P1 * a1f + P2 * a2f
    E = P0 * Vf + P1 * v1 + P2 * v2 + Pt * Vf
    W = E / pacc - Vf if pacc > 0 else float("inf")
    inf = (P1 * a1f + P2 * l2f) / pacc if pacc > 0 else 1.0
    return {"W": float(W), "inf": float(inf), "pacc": float(pacc),
            "E": float(E)}


def run_F(pre, p):
    T = pre["T"]
    out = eval_policy(pre, [99] * (T - 1), 0, p)
    out["iters_done"] = 1
    out["n_evaluated"] = 1
    out["stopped"] = False
    return out


def run_R(pre, p, rng, n_samples, stop):
    """Random abort-timing control under strict final post-selection
    (final threshold fixed 0, so accepted set and infidelity match F
    by construction; only abort timing is randomized)."""
    T = pre["T"]
    Ws, Is, nc = [], [], 0
    for _ in range(n_samples):
        if stop is not None and stop():
            return {"stopped": True, "iters_done": nc,
                    "n_evaluated": n_samples}
        ath = [int(rng.integers(0, 4)) for _ in range(T - 1)]
        out = eval_policy(pre, ath, 0, p)
        if not math.isfinite(out["W"]):
            return {"stopped": True, "iters_done": nc,
                    "n_evaluated": n_samples}
        Ws.append(out["W"])
        Is.append(out["inf"])
        nc += 1
    return {"stopped": False, "W": sum(Ws) / len(Ws),
            "inf": sum(Is) / len(Is), "iters_done": nc,
            "n_evaluated": n_samples}


def run_G(pre, p, f_inf, stop):
    """Constrained greedy from F: first-improvement moves that strictly
    lower W while keeping inf <= f_inf * (1 + INF_REL) + INF_ABS."""
    T = pre["T"]
    bound = f_inf * (1.0 + INF_REL) + INF_ABS
    ath = [99] * (T - 1)
    fth = 0
    cur = eval_policy(pre, ath, fth, p)
    total = (T - 1) * len(ABORT_VALS) * GREEDY_SWEEPS + \
        len(FINAL_VALS) * GREEDY_SWEEPS
    done = 1
    ci = 0
    for _ in range(GREEDY_SWEEPS):
        for pos_idx in range(T):
            dom = ABORT_VALS if pos_idx < T - 1 else FINAL_VALS
            for v in dom:
                if ci % 32 == 0 and stop is not None and stop():
                    return {"stopped": True, "iters_done": done,
                            "n_evaluated": total}
                ci += 1
                old = ath[pos_idx] if pos_idx < T - 1 else fth
                if v == old:
                    continue
                if pos_idx < T - 1:
                    ath[pos_idx] = v
                else:
                    fth = v
                out = eval_policy(pre, ath, fth, p)
                done += 1
                if out["W"] < cur["W"] and out["inf"] <= bound:
                    cur = out
                else:
                    if pos_idx < T - 1:
                        ath[pos_idx] = old
                    else:
                        fth = old
    return {"stopped": False, "W": cur["W"], "inf": cur["inf"],
            "iters_done": done, "n_evaluated": total,
            "policy": list(ath) + [fth]}


def run_A(pre, p, rng, n_iters, stop):
    """Annealed adaptive policy; cost = W + LAMBDA * inf (frozen)."""
    T = pre["T"]
    ath = [99] * (T - 1)
    fth = 0
    cur = eval_policy(pre, ath, fth, p)
    cost = cur["W"] + LAMBDA * cur["inf"]
    best = (cost, cur["W"], cur["inf"], list(ath) + [fth])
    temp = A_T0
    done = 1
    for it in range(n_iters):
        if it % 32 == 0 and stop is not None and stop():
            return {"stopped": True, "iters_done": done,
                    "n_evaluated": n_iters + 1}
        pos_idx = int(rng.integers(T))
        dom = ABORT_VALS if pos_idx < T - 1 else FINAL_VALS
        v = int(dom[int(rng.integers(len(dom)))])
        old = ath[pos_idx] if pos_idx < T - 1 else fth
        if pos_idx < T - 1:
            ath[pos_idx] = v
        else:
            fth = v
        out = eval_policy(pre, ath, fth, p)
        done += 1
        if not math.isfinite(out["W"]):
            if pos_idx < T - 1:
                ath[pos_idx] = old
            else:
                fth = old
            temp *= A_ALPHA
            continue
        cost2 = out["W"] + LAMBDA * out["inf"]
        if cost2 < cost or bool(
                rng.random() < math.exp(-(cost2 - cost) / temp)):
            cost = cost2
            if cost2 < best[0]:
                best = (cost2, out["W"], out["inf"],
                        list(ath) + [fth])
        else:
            if pos_idx < T - 1:
                ath[pos_idx] = old
            else:
                fth = old
        temp *= A_ALPHA
    return {"stopped": False, "W": best[1], "inf": best[2],
            "iters_done": done, "n_evaluated": n_iters + 1,
            "policy": best[3]}


def all_threshold_policies(T):
    if T - 1 == 1:
        aborts = [[v] for v in ABORT_VALS]
    else:
        aborts = [[a, b] for a in ABORT_VALS for b in ABORT_VALS]
        if T - 1 > 2:
            base = [[]]
            for _ in range(T - 1):
                base = [p + [v] for p in base for v in ABORT_VALS]
            aborts = base
    return [(list(a), f) for a in aborts for f in FINAL_VALS]


def constrained_best(pre, p, bound):
    best = None
    for (ath, fth) in all_threshold_policies(pre["T"]):
        out = eval_policy(pre, ath, fth, p)
        if out["inf"] <= bound:
            if best is None or out["W"] < best[0]:
                best = (out["W"], out["inf"], list(ath) + [fth])
    return best


def bfs_joint(cell, T, cap, stop, p_exact):
    """Bounded-exact joint search over check schedules x abort policies.

    BFS over schedule prefixes (each extension = 1 node, cap-hit past
    cap); at full leaves, exhaustive threshold-policy enumeration
    constrained to matched infidelity vs canonical-order F. Statuses:
    solved / cap-hit / stopped-guard.
    """
    C = cell["C"]
    canon = list(range(C))
    pre_c = precompute(cell, canon, T)
    f0 = eval_policy(pre_c, [99] * (T - 1), 0, p_exact)
    bound = f0["inf"] * (1.0 + INF_REL) + INF_ABS
    q = deque([()])
    nodes = 0
    best = None
    while q:
        if nodes % 512 == 0 and stop is not None and stop():
            return {"status": "stopped-guard", "nodes": nodes,
                    "best": best, "cap": cap, "started": True}
        prefix = q.popleft()
        if len(prefix) == C:
            pre = precompute(cell, list(prefix), T)
            cb = constrained_best(pre, p_exact, bound)
            if cb is not None and (best is None or cb[0] < best["W"]):
                best = {"W": cb[0], "inf": cb[1],
                        "pi": list(prefix), "policy": cb[2]}
        else:
            used = set(prefix)
            for e in range(C):
                if e not in used:
                    nodes += 1
                    if nodes > cap:
                        return {"status": "cap-hit", "nodes": nodes,
                                "best": best, "cap": cap,
                                "started": True}
                    q.append(prefix + (e,))
    return {"status": "solved", "nodes": nodes, "best": best,
            "cap": cap, "started": True}


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
        if tc["C"] != TINY_N:
            out["failed"].append("tiny-C")
        T = TINY_T
        tpre = precompute(tc, list(range(tc["C"])), T)
        if tpre["L1"] != 72:
            out["failed"].append("tiny-L1-%d" % tpre["L1"])
        f0 = eval_policy(tpre, [99] * (T - 1), 0, P_EXACT)
        acc_w1 = int((((tpre["fw1"] <= 0))).sum())
        if acc_w1 != 0:
            out["failed"].append("tiny-hand-bound-%d" % acc_w1)
        if not (f0["W"] >= 0.0 and math.isfinite(f0["W"])):
            out["failed"].append("tiny-W-nan")
        tex = bfs_joint(tc, T, EXACT_CAP, None, P_EXACT)
        if tex["status"] != "solved" or not tex.get("best"):
            out["failed"].append("tiny-joint-solve")
        elif tex["best"]["W"] > f0["W"] + 1e-9:
            out["failed"].append("tiny-opt-above-F")
        elif tex["best"]["inf"] > f0["inf"] * (1.0 + INF_REL) + \
                INF_ABS + 1e-12:
            out["failed"].append("tiny-opt-inf-violation")
        c0 = build_cell(SIZES[0], drop=drop_one(0, SEEDS[0], SIZES[0]
                        + SIZES[0] // 4 + (1 if SIZES[0] % 4 else 0)))
        T0 = T_OF[SIZES[0]]
        pre0 = precompute(c0, list(range(c0["C"])), T0)
        g1 = run_G(pre0, P_ERRS[0], run_F(pre0, P_ERRS[0])["inf"],
                   None)
        g2 = run_G(pre0, P_ERRS[0], run_F(pre0, P_ERRS[0])["inf"],
                   None)
        if ((g1.get("W"), g1.get("inf")) !=
                (g2.get("W"), g2.get("inf"))):
            out["failed"].append("determinism-greedy")
        r1 = run_R(pre0, P_ERRS[0], seed_rng(0, 1, 999), R_SAMPLES,
                   None)
        r2 = run_R(pre0, P_ERRS[0], seed_rng(0, 1, 999), R_SAMPLES,
                   None)
        if ((r1.get("W"), r1.get("inf")) !=
                (r2.get("W"), r2.get("inf"))):
            out["failed"].append("determinism-random")
        d1 = drop_one(1, 2, 99)
        d2 = drop_one(1, 2, 99)
        if d1 != d2 or len(d1) != 1:
            out["failed"].append("determinism-disorder")
    except Exception as ex:
        out["failed"].append("raise: %r" % ex)
    return out


def run_arm(pre, p, arm, f_inf, n_iters, n_samples, stop, si, pi,
            seed):
    if arm == "F":
        return run_F(pre, p)
    if arm == "R":
        return run_R(pre, p, seed_rng(si * 10 + pi, seed, 999),
                     n_samples, stop)
    if arm == "G":
        return run_G(pre, p, f_inf, stop)
    return run_A(pre, p, seed_rng(si * 10 + pi, seed, 777),
                 n_iters, stop)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--attempt", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--anneal-iters", type=int, default=A_ITERS)
    ap.add_argument("--r-samples", type=int, default=R_SAMPLES)
    args = ap.parse_args()
    n_iters = int(args.anneal_iters)
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
        tex = bfs_joint(tiny_cell(), TINY_T, EXACT_CAP, over,
                        P_EXACT)
        gate3tiny["arms"]["tiny"] = tex
        gate3tiny["total"] += 1
        if tex["status"] == "solved" and tex.get("best"):
            gate3tiny["solved"] += 1
        if tex["status"] == "stopped-guard":
            skipped.append({"what": "tiny-exact",
                            "reason": "stopped-guard",
                            "iters_done": tex.get("nodes", 0),
                            "n_evaluated": EXACT_CAP})
    with open(os.path.join(witdir, "gate3_tiny.json"), "w") as f:
        json.dump(gate3tiny, f, indent=1, default=str)
    checkpoint("tiny")

    if over():
        gate3targets.append({"status": "skipped-guard"})
        skipped.append({"what": "target-exact", "reason": "wall-guard",
                        "iters_done": 0, "n_evaluated": 1})
    else:
        si, seed = TARGET_STAGE_IDX, TARGET_SEED
        n = SIZES[si]
        Cfull = n + (n // 4 + (1 if n % 4 else 0))
        tcell = build_cell(n, drop=drop_one(si, seed, Cfull))
        tex = bfs_joint(tcell, T_OF[n], EXACT_CAP, over, P_EXACT)
        gate3targets.append(dict(tex, stage=n, seed=seed))
        if tex["status"] == "stopped-guard":
            skipped.append({"what": "target-exact",
                            "reason": "stopped-guard",
                            "iters_done": tex.get("nodes", 0),
                            "n_evaluated": EXACT_CAP})
    with open(os.path.join(witdir, "gate3_targets.json"), "w") as f:
        json.dump(gate3targets, f, indent=1, default=str)
    checkpoint("targets")

    planned = {"F": 1, "R": n_samples, "G": None, "A": n_iters + 1}

    def run_cell(si, pi, seed):
        n = SIZES[si]
        T = T_OF[n]
        Cfull = n + (n // 4 + (1 if n % 4 else 0))
        cell = build_cell(n, drop=drop_one(si, seed, Cfull))
        C = cell["C"]
        planned["G"] = (T - 1) * len(ABORT_VALS) * GREEDY_SWEEPS + \
            len(FINAL_VALS) * GREEDY_SWEEPS
        if over():
            return {"blocked": "wall-guard", "size": n,
                    "p": P_ERRS[pi], "seed": seed,
                    "iters_done": 0, "n_evaluated": 0}
        pre = precompute(cell, list(range(C)), T)
        rec = {"size": n, "p": P_ERRS[pi], "seed": seed,
               "arms": {},
               "sig": sched_sig(cell, list(range(C)))}
        f_inf = run_F(pre, P_ERRS[pi])["inf"]
        for arm in ARMS:
            if over():
                rec["blocked"] = "wall-guard"
                rec["iters_done"] = 0
                rec["n_evaluated"] = planned[arm]
                return rec
            out = run_arm(pre, P_ERRS[pi], arm, f_inf, n_iters,
                          n_samples, over, si, pi, seed)
            if out.get("stopped"):
                rec["blocked"] = "stopped-guard"
                rec["iters_done"] = out.get("iters_done", 0)
                rec["n_evaluated"] = out.get(
                    "n_evaluated", planned[arm])
                return rec
            rec["arms"][arm] = {
                "n": 1, "W": out["W"], "inf": out["inf"],
                "iters_done": out.get("iters_done", 0),
                "n_evaluated": out.get("n_evaluated", 0)}
        return rec

    def record_cell(rec):
        if rec.get("blocked") is None and all(
                rec["arms"].get(a, {}).get("n") == 1 for a in ARMS):
            for a in ARMS:
                key = (rec["size"], rec["p"], rec["seed"], a)
                cells.setdefault(key, {"W": [], "inf": []})
                cells[key]["W"].append(rec["arms"][a]["W"])
                cells[key]["inf"].append(rec["arms"][a]["inf"])
            return True
        skipped.append({"what": "cell %s/p%s/%s" % (
            rec.get("size"), rec.get("p"), rec.get("seed")),
            "reason": rec.get("blocked", "arm-incomplete"),
            "iters_done": rec.get("iters_done", 0),
            "n_evaluated": rec.get("n_evaluated", 0)})
        return False

    for si, n in enumerate(SIZES):
        siz_cells = [(si, pi, seed) for pi in range(len(P_ERRS))
                     for seed in SEEDS]
        if over():
            for (s2, p2, sd2) in siz_cells:
                skipped.append({"what": "cell %s/p%s/%s" % (
                    SIZES[s2], P_ERRS[p2], sd2),
                    "reason": "wall-guard", "iters_done": 0,
                    "n_evaluated": 0})
        else:
            for (s2, p2, sd2) in siz_cells:
                if over():
                    skipped.append({"what": "cell %s/p%s/%s" % (
                        SIZES[s2], P_ERRS[p2], sd2),
                        "reason": "wall-guard", "iters_done": 0,
                        "n_evaluated": 0})
                    continue
                rec = run_cell(s2, p2, sd2)
                cellrecs.append(rec)
                record_cell(rec)
        with open(os.path.join(witdir, "cells.json"), "w") as f:
            json.dump(cellrecs, f, indent=1, default=str)
        checkpoint("size%d" % n)
    with open(os.path.join(witdir, "cells.json"), "w") as f:
        json.dump(cellrecs, f, indent=1, default=str)
    checkpoint("corpus")

    def cell_vals(n, p, seed, arm, field):
        return cells.get((n, p, seed, arm),
                         {"W": [], "inf": []})[field]

    def pool(vals):
        return pooled_stats(vals), len(vals) == len(SEEDS)

    n0 = SIZES[0]
    Cfull0 = n0 + (n0 // 4 + (1 if n0 % 4 else 0))
    pre_d = precompute(build_cell(
        n0, drop=drop_one(0, 1, Cfull0)), list(range(
            n0 + (n0 // 4 + (1 if n0 % 4 else 0)) - 1)), T_OF[n0])
    f_d = run_F(pre_d, P_ERRS[0])["inf"]
    det1 = run_G(pre_d, P_ERRS[0], f_d, None)
    det2 = run_G(pre_d, P_ERRS[0], f_d, None)
    det_r1 = run_R(pre_d, P_ERRS[0], seed_rng(1, 1, 999),
                   n_samples, None)
    det_r2 = run_R(pre_d, P_ERRS[0], seed_rng(1, 1, 999),
                   n_samples, None)
    determinism_ok = bool(
        (det1.get("W"), det1.get("inf")) == (det2.get("W"),
                                            det2.get("inf"))
        and (det_r1.get("W"), det_r1.get("inf")) == (
            det_r2.get("W"), det_r2.get("inf")))

    g1_cells, g1_beats = [], True
    for n in SIZES:
        for p in P_ERRS:
            ms = [cell_vals(n, p, s, "G", "W") for s in SEEDS]
            mr = [cell_vals(n, p, s, "R", "W") for s in SEEDS]
            ok = (all(len(v) == 1 for v in ms + mr)
                  and sum(v[0] for v in ms) / 5.0 <
                  sum(v[0] for v in mr) / 5.0)
            g1_cells.append({"cell": "%d/p%s" % (n, p),
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
        for p in P_ERRS:
            pools, pok = {}, True
            for arm in ("F", "G", "A"):
                vals = []
                for s in SEEDS:
                    vals.extend(cell_vals(n, p, s, arm, "W"))
                pools[arm], oka = pool(vals)
                pok = pok and oka
            se, spread, gp = spread_win(pools, pok)
            g2_fams.append({"cell": "%d/p%s" % (n, p),
                            "pools": pools, "SE": se,
                            "spread": spread, "pass": bool(gp)})
            if gp:
                g2_sizes.add(n)
    g2_n = sum(1 for g in g2_fams if g["pass"])
    g2_ok = bool(g2_n >= 4 and len(g2_sizes) >= 2)

    win_rates = []
    win_n = 0
    win_count = {"G": 0, "A": 0}
    for p in P_ERRS:
        pools, pok, ipools, iok = {}, True, {}, True
        for arm in ("F", "G", "A"):
            vals, ivals = [], []
            for si2, n in enumerate(SIZES):
                for s in SEEDS:
                    vals.extend(cell_vals(n, p, s, arm, "W"))
                    ivals.extend(cell_vals(n, p, s, arm, "inf"))
            pools[arm], oka = pooled_stats(vals), len(vals) == 15
            ipools[arm], oki = pooled_stats(ivals), \
                len(ivals) == 15
            pok = pok and oka
            iok = iok and oki
        joint = {"G": False, "A": False}
        if pok and iok and all(
                pools[a]["se"] is not None and
                pools[a]["mean"] is not None for a in ("F", "G",
                                                      "A")):
            sse = math.sqrt(sum(ipools[a]["se"] ** 2
                                for a in ("F", "G", "A")) / 3.0) \
                if all(ipools[a]["se"] is not None
                       for a in ("F", "G", "A")) else None
            fmean = pools["F"]["mean"]
            for a in ("G", "A"):
                wpass = (fmean is not None and fmean > MEANF_FLOOR
                         and pools[a]["mean"] is not None
                         and (fmean - pools[a]["mean"]) / fmean
                         >= WIN_RED)
                if sse is None:
                    hpass = (ipools[a]["mean"] is not None
                             and ipools["F"]["mean"] is not None
                             and ipools[a]["mean"]
                             <= ipools["F"]["mean"])
                else:
                    hpass = (ipools[a]["mean"] is not None
                             and ipools["F"]["mean"] is not None
                             and ipools[a]["mean"]
                             <= ipools["F"]["mean"] + 2.0 * sse)
                joint[a] = bool(wpass and hpass)
        winner = ("G" if joint["G"]
                  else ("A" if joint["A"] else None))
        wpass = winner is not None
        if pok and all(pools[a]["mean"] is not None
                       for a in ("F", "G", "A")):
            spass = (pools["G"]["mean"] < pools["F"]["mean"] or
                     pools["A"]["mean"] < pools["F"]["mean"])
        else:
            spass = False
        win_rates.append({"rate": p, "win": bool(wpass),
                          "strict_win": bool(spass),
                          "pools_ok": bool(pok and iok),
                          "pools_W": pools, "pools_inf": ipools,
                          "joint": dict(joint), "winner": winner})
        if wpass:
            win_n += 1
        for a in ("G", "A"):
            if joint[a]:
                win_count[a] += 1

    tiny_solved = (gate3tiny["total"] == 1 and gate3tiny["solved"]
                   == 1)
    target_cap = (len(gate3targets) == 1 and
                  gate3targets[0].get("status") == "cap-hit")
    g3pass = bool(tiny_solved and target_cap)

    complete = all(
        len(cell_vals(n, p, s, a, "W")) == 1
        for n in SIZES for p in P_ERRS for s in SEEDS
        for a in ARMS)
    tiny_attempted = gate3tiny["total"] == 1
    targets_attempted = len(gate3targets) == 1
    wall = elapsed()
    clean = len(skipped) == 0
    g4_ok = bool(complete and tiny_attempted and targets_attempted
                 and wall < WALL_LIMIT_S and clean)

    selftest_ok = bool(tiny_ok)
    strict_n = sum(1 for wrec in win_rates if wrec.get("strict_win"))
    pools_all = all(wrec.get("pools_ok") for wrec in win_rates)
    same_arm_wins = max(win_count["G"], win_count["A"])
    pursue = (same_arm_wins >= 2 and g1_ok and g2_ok and g3pass
              and g4_ok and selftest_ok)
    reject = (complete and tiny_solved and g1_ok and pools_all
              and strict_n == 0)
    if pursue:
        reason = "PURSUE-condition holds (adaptive abort W win >=" \
            "10% at matched infidelity on the SAME arm at >=2 " \
            "noise regimes + gates 1,2,3,4 + self-tests ok); " \
            "payload verdict stays unresolved-with-reason, " \
            "classification is coordinator-side."
    elif reject:
        reason = "REJECT-condition holds (complete cells, tiny " \
            "solved, Gate-1 controls pass, no strict pooled " \
            "cultivation W win at any rate); payload verdict " \
            "stays unresolved-with-reason, classification is " \
            "coordinator-side."
    else:
        reason = "UNRESOLVED + next experiment (joint wins=%d/3 " \
            "(per-arm G=%d A=%d), " \
            "strict abort wins=%d/3, g1=%s g2=%s " \
            "(%d/9 cells) g3=%s (tiny solved=%s, target " \
            "cap-hit=%s) selftest=%s g4=%s complete=%s skipped=%d; " \
            "next: check-order co-optimization + per-round " \
            "threshold variation retest)." % (
                win_n, win_count["G"], win_count["A"],
                strict_n, g1_ok, g2_ok, g2_n, g3pass,
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
                       "win_rates": win_rates, "n_win": win_n,
                       "win_count": dict(win_count),
                       "same_arm_wins": int(same_arm_wins),
                       "n_strict_win": strict_n,
                       "selftest_ok": bool(selftest_ok)},
        "reason": reason,
    }

    results = {
        "screen": "05",
        "verdict": "unresolved-with-reason: payload reports numbers "
                   "and gate evidence; classification is coordinator-side.",
        "design": {
            "model": "screen-authored deterministic Clifford "
                     "stabilizer-frame sim (stdlib + numpy only; no "
                     "external libs)",
            "stages": list(SIZES),
            "t_rounds": {str(k): T_OF[k] for k in SIZES},
            "p_errs": list(P_ERRS),
            "seeds": list(SEEDS),
            "anneal": {"iters": n_iters, "t0": A_T0,
                       "alpha": A_ALPHA, "lambda": LAMBDA},
            "greedy": {"sweeps": GREEDY_SWEEPS},
            "r_samples": n_samples,
            "arms": {"F": "fixed post-selection (never abort early, "
                          "strict final post-select)",
                     "R": "random abort-timing control (seeded "
                          "random abort thresholds, strict final "
                          "post-select, mean over samples)",
                     "G": "greedy adaptive abort (constrained "
                          "first-improvement from F: lower wasted "
                          "volume at matched infidelity)",
                     "A": "annealed adaptive policy "
                          "(cost = W + LAMBDA*infidelity)"},
            "metrics": "wasted spacetime volume per accepted output "
                       "(E[spent]/P(accept) - V_full, exact weights "
                       "0..2 binomial-weighted at p, tail w>=3 "
                       "rejected at full volume, non-logical) at "
                       "matched output infidelity (accepted-logical "
                       "rate; w1 accepted always logical)",
            "pareto": "PURSUE needs a wasted-volume win >=10% + "
                      "infidelity no-regress (<= F + 2*SE) on the SAME "
                      "arm; a volume-only win with higher infidelity "
                      "is NOT a joint win",
            "exact": "bounded-exact joint search over check schedules "
                     "x abort policies on tiny (must solve) + "
                     "target-scale instance (stage %d, node cap %d, "
                     "must cap-hit)" % (SIZES[TARGET_STAGE_IDX],
                                       EXACT_CAP),
        },
        "timing": {"wall_s": wall, "guards": {"wall_guard_s": WALL_GUARD_S,
                                              "limit_s": WALL_LIMIT_S}},
        "cells": {("%d/p%s/%s/%s" % k): {"n": len(v["W"]),
                                        **pooled_stats(v["W"]),
                                        "inf": pooled_stats(
                                            v["inf"])}
                  for k, v in cells.items()},
        "gates": verdict_bits,
        "skipped": skipped,
    }
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)


if __name__ == "__main__":
    main()
