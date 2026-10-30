"""Screen 19 payload: Clifford tableau synthesis on restricted topologies.

Screen-authored deterministic bitwise stabilizer-tableau simulator
(stdlib + numpy only; no external synthesis/physics/solver libs):
random Clifford circuits (H/S/CNOT) on n in {8, 12, 16} qubits,
tableau-canonicalized, synthesized under different
logical-to-physical placements on frozen grid / heavy-hex layouts.
Arms: D canonical Gaussian elimination + SWAP routing (identity
placement baseline), G greedy pairwise-swap placement descent, A
simulated annealing over placements
(cost = routed CNOTs + LAMBDA * depth, frozen LAMBDA), R random
placement control. Metric: routed CNOT count + circuit depth at
fixed layout. A bounded-exact branch-and-bound over placements
validates the tiny instance (solved, optimum by construction) and
cap-hits at target scale (limit-expiry). Writes ALL output under
cwd (the attempt work dir): results.json + witnesses/.
Deterministic given seeds. Verdict is always unresolved-with-reason;
classification is coordinator-side.
"""

import argparse
import hashlib
import json
import math
import os
import time

import numpy as np

SIZES = (8, 12, 16)
GATES_PER_QUBIT = 6
DEPTH_BUDGET = {8: 40, 12: 60, 16: 80}
SEEDS = (1, 2, 3, 4, 5)
ARMS = ("D", "G", "A", "R")

N_INST = 1300
ANNEAL_ITERS = 400
ANNEAL_T0 = 2.0
ANNEAL_ALPHA = 0.99
GREEDY_SWEEPS = 3
LAMBDA = 5.0

WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0
EXACT_CAP = 50000

TINY_GATES = (("H", 0, -1), ("CX", 0, 1))
TINY_EXP = {"cnots": 1, "depth": 2}
TARGET_SIZE = 2
TARGET_SEED = 1
TARGET_REP = 0
TARGET_LAYOUT = "grid"


def grid_edges(n, cols=4):
    rows = n // cols
    edges = []
    for r in range(rows):
        for c in range(cols):
            i = r * cols + c
            if c + 1 < cols:
                edges.append((i, i + 1))
            if r + 1 < rows:
                edges.append((i, i + cols))
    return edges


def hex_edges(n):
    edges = [(i, i + 1) for i in range(n - 1)]
    for i in range(0, n - 3, 4):
        edges.append((i, i + 3))
    return edges


def all_pairs_dist(n, edges):
    INF = 10 ** 9
    adj = [[] for _ in range(n)]
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    dist = [[INF] * n for _ in range(n)]
    for s in range(n):
        dist[s][s] = 0
        queue = [s]
        for u in queue:
            for v in adj[u]:
                if dist[s][v] == INF:
                    dist[s][v] = dist[s][u] + 1
                    queue.append(v)
    return dist


LAYOUT_EDGES = {}
LAYOUT_DIST = {}
for _n in SIZES:
    LAYOUT_EDGES[(_n, "grid")] = grid_edges(_n)
    LAYOUT_EDGES[(_n, "hex")] = hex_edges(_n)
    for _lay in ("grid", "hex"):
        LAYOUT_DIST[(_n, _lay)] = all_pairs_dist(
            _n, LAYOUT_EDGES[(_n, _lay)])


def seed_rng(size_idx, seed, rep, salt):
    return np.random.default_rng(
        (int(size_idx * 100003 + seed * 10007 + rep * 101
             + salt * 1000003) % (2 ** 63 - 1)))


def layout_of(rep):
    return "grid" if rep % 2 == 0 else "hex"


def gen_circuit(size_idx, seed, rep):
    """Random Clifford circuit: H/S/CNOT on frozen grid edges, forced
    coverage so every wire appears. Deterministic given inputs."""
    n = SIZES[size_idx]
    n_gates = GATES_PER_QUBIT * n
    rng = seed_rng(size_idx, seed, rep, 11)
    edges = LAYOUT_EDGES[(n, "grid")]
    uncovered = set(range(n))
    gates = []
    for t in range(n_gates):
        if uncovered and (n_gates - t) <= len(uncovered) + 1:
            q = min(uncovered)
            if bool(rng.random() < 0.6):
                cand = [e for e in edges if q in e]
                e = cand[int(rng.integers(len(cand)))]
                gates.append(("CX", e[0], e[1]))
                uncovered.discard(e[0])
                uncovered.discard(e[1])
            else:
                gates.append(("H", q, -1))
                uncovered.discard(q)
        else:
            u = float(rng.random())
            if u < 0.25:
                q = int(rng.integers(n))
                gates.append(("H", q, -1))
                uncovered.discard(q)
            elif u < 0.40:
                q = int(rng.integers(n))
                gates.append(("S", q, -1))
                uncovered.discard(q)
            else:
                e = edges[int(rng.integers(len(edges)))]
                gates.append(("CX", e[0], e[1]))
                uncovered.discard(e[0])
                uncovered.discard(e[1])
    return {"gates": gates, "n": n, "layout": layout_of(rep)}


def tableau_sig(gates, n):
    """Bitwise stabilizer-tableau simulation (CHP rules) over 2n rows;
    returns a deterministic canonical digest of the sorted rows."""
    xs = [0] * (2 * n)
    zs = [0] * (2 * n)
    rs = [0] * (2 * n)
    for i in range(n):
        zs[i] = 1 << i
        xs[n + i] = 1 << i
    for g in gates:
        if g[0] == "H":
            a = g[1]
            bit = 1 << a
            for i in range(2 * n):
                if xs[i] & bit and zs[i] & bit:
                    rs[i] ^= 1
                xb = bool(xs[i] & bit)
                zb = bool(zs[i] & bit)
                if xb and not zb:
                    zs[i] |= bit
                    xs[i] &= ~bit
                elif zb and not xb:
                    xs[i] |= bit
                    zs[i] &= ~bit
        elif g[0] == "S":
            a = g[1]
            bit = 1 << a
            for i in range(2 * n):
                if xs[i] & bit:
                    if zs[i] & bit:
                        rs[i] ^= 1
                    zs[i] ^= bit
        else:
            c, t = g[1], g[2]
            cb, tb = 1 << c, 1 << t
            for i in range(2 * n):
                xc = bool(xs[i] & cb)
                zt = bool(zs[i] & tb)
                if xc and zt:
                    rs[i] ^= 1 ^ bool(xs[i] & tb) ^ bool(zs[i] & cb)
                if xc:
                    xs[i] ^= tb
                if zt:
                    zs[i] ^= cb
    rows = sorted((xs[i], zs[i], rs[i]) for i in range(2 * n))
    h = hashlib.sha256(repr(rows).encode())
    return h.hexdigest()[: 16]


def eval_place(gates, place, dist, n):
    """Route a fixed gate list under a placement. CNOT at distance d
    costs 3d-2 routed CNOTs (one SWAP chain each way), duration 2d-1;
    single-qubit gates cost 0 CNOTs, duration 1."""
    ft = [0] * n
    cnots = 0
    for g in gates:
        if g[0] == "CX":
            pa, pb = place[g[1]], place[g[2]]
            d = dist[pa][pb]
            cnots += 3 * d - 2
            dur = 2 * d - 1
            start = ft[pa] if ft[pa] >= ft[pb] else ft[pb]
            end = start + dur
            ft[pa] = end
            ft[pb] = end
        else:
            q = place[g[1]]
            ft[q] += 1
    return int(cnots), int(max(ft))


def run_d(gates, n, dist):
    place = list(range(n))
    c, d = eval_place(gates, place, dist, n)
    return {"cnots": c, "depth": d, "stopped": False}


def run_r(gates, n, dist, rng):
    place = list(range(n))
    rng.shuffle(place)
    c, d = eval_place(gates, place, dist, n)
    return {"cnots": c, "depth": d, "stopped": False}


def run_g(gates, n, dist, rng, stop):
    """Greedy pairwise-swap placement descent from identity plus one
    seeded random restart; first-improvement, strictly improving moves
    only, so the result never exceeds the identity cost."""
    starts = [list(range(n))]
    alt = list(range(n))
    rng.shuffle(alt)
    starts.append(alt)
    best = None
    for place in starts:
        c, d = eval_place(gates, place, dist, n)
        for _ in range(GREEDY_SWEEPS):
            for i in range(n):
                if stop is not None and stop():
                    return {"cnots": None, "depth": None,
                            "stopped": True}
                for j in range(i + 1, n):
                    place[i], place[j] = place[j], place[i]
                    c2, d2 = eval_place(gates, place, dist, n)
                    if c2 < c or (c2 == c and d2 < d):
                        c, d = c2, d2
                    else:
                        place[i], place[j] = place[j], place[i]
        if best is None or c < best[0] or (c == best[0] and d < best[1]):
            best = (c, d)
    return {"cnots": int(best[0]), "depth": int(best[1]),
            "stopped": False}


def run_a(gates, n, dist, rng, n_iters, stop):
    """Simulated annealing over placements; cost = routed CNOTs +
    LAMBDA * depth (frozen LAMBDA). Starts at identity; tracks best."""
    place = list(range(n))
    c, d = eval_place(gates, place, dist, n)
    best = [c + LAMBDA * d, c, d, list(place)]
    cur = c + LAMBDA * d
    temp = ANNEAL_T0
    for it in range(n_iters):
        if it % 32 == 0 and stop is not None and stop():
            break
        i = int(rng.integers(n))
        j = int(rng.integers(n))
        if i == j:
            temp *= ANNEAL_ALPHA
            continue
        place[i], place[j] = place[j], place[i]
        c2, d2 = eval_place(gates, place, dist, n)
        cost2 = c2 + LAMBDA * d2
        if cost2 < cur or bool(
                rng.random() < math.exp(-(cost2 - cur) / temp)):
            cur = cost2
            if cost2 < best[0] or (cost2 == best[0]
                                   and c2 < best[1]):
                best = [cost2, c2, d2, list(place)]
        else:
            place[i], place[j] = place[j], place[i]
        temp *= ANNEAL_ALPHA
    return {"cnots": int(best[1]), "depth": int(best[2]),
            "stopped": False}


def exact_opt(gates, n, dist, cap, stop):
    """Bounded-exact branch-and-bound over logical->physical
    placements, minimizing routed CNOTs. Statuses: solved /
    cap-hit / stopped-guard."""
    pairs = [(g[1], g[2]) for g in gates if g[0] == "CX"]
    deg = [0] * n
    for a, b in pairs:
        deg[a] += 1
        deg[b] += 1
    order = sorted(range(n), key=lambda q: (-deg[q], q))
    w = [[3 * dist[p][q] - 2 if p != q else 0 for q in range(n)]
         for p in range(n)]
    ident = list(range(n))
    bc, _bd = eval_place(gates, ident, dist, n)
    best = [bc]
    assign = [-1] * n
    used = bytearray(n)
    nodes = [0]
    capped = [False]
    stopped = [False]
    pos_of = [0] * n
    for pos, q in enumerate(order):
        pos_of[q] = pos

    def rec(k, partial):
        if capped[0] or stopped[0]:
            return
        nodes[0] += 1
        if nodes[0] > cap:
            capped[0] = True
            return
        if nodes[0] % 512 == 0 and stop is not None and stop():
            stopped[0] = True
            return
        if k == n:
            if partial < best[0]:
                best[0] = partial
            return
        if partial >= best[0]:
            return
        q = order[k]
        for p in range(n):
            if not used[p]:
                assign[q] = p
                used[p] = 1
                add = 0
                for a, b in pairs:
                    if a == q and assign[b] != -1:
                        add += w[p][assign[b]]
                    elif b == q and assign[a] != -1:
                        add += w[assign[a]][p]
                rec(k + 1, partial + add)
                used[p] = 0
                assign[q] = -1
                if capped[0] or stopped[0]:
                    return

    rec(0, 0)
    if stopped[0]:
        return {"status": "stopped-guard", "nodes": nodes[0],
                "opt_cnots": best[0], "cap": cap, "started": True}
    if capped[0]:
        return {"status": "cap-hit", "nodes": nodes[0],
                "opt_cnots": best[0], "cap": cap, "started": True}
    return {"status": "solved", "nodes": nodes[0],
            "opt_cnots": best[0], "cap": cap, "started": True}


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


def audit_circuit(size_idx, seed, rep):
    circ = gen_circuit(size_idx, seed, rep)
    gates = circ["gates"]
    n = circ["n"]
    wires = set()
    for g in gates:
        if g[0] == "CX":
            wires.add(g[1])
            wires.add(g[2])
        else:
            wires.add(g[1])
    dist = LAYOUT_DIST[(n, circ["layout"])]
    connected = all(dist[a][b] < 10 ** 9
                    for a in range(n) for b in range(n))
    return {"coverage_ok": wires == set(range(n)),
            "n_gates_ok": len(gates) == GATES_PER_QUBIT * n,
            "connected": bool(connected)}


def self_tests():
    out = {"ran": True, "failed": []}
    try:
        for si in range(len(SIZES)):
            for rep in (0, 1):
                au = audit_circuit(si, 1, rep)
                if not au["coverage_ok"]:
                    out["failed"].append("gen-cover-%d-%d" % (si, rep))
                if not au["n_gates_ok"]:
                    out["failed"].append("gen-count-%d-%d" % (si, rep))
                if not au["connected"]:
                    out["failed"].append("gen-conn-%d-%d" % (si, rep))
        if LAYOUT_DIST[(8, "grid")] == LAYOUT_DIST[(8, "hex")]:
            out["failed"].append("layouts-identical")
        tn = 2
        tdist = LAYOUT_DIST[(2, "grid")] if (2, "grid") in LAYOUT_DIST \
            else [[0, 1], [1, 0]]
        tiny = list(TINY_GATES)
        sigs = {}
        for arm, fn in (("D", lambda: run_d(tiny, tn, tdist)),
                        ("G", lambda: run_g(
                            tiny, tn, tdist,
                            seed_rng(0, 7, 7, 5), None)),
                        ("A", lambda: run_a(
                            tiny, tn, tdist,
                            seed_rng(0, 7, 7, 5), 50, None)),
                        ("R", lambda: run_r(
                            tiny, tn, tdist,
                            seed_rng(0, 7, 7, 999)))):
            r = fn()
            sigs[arm] = (tableau_sig(tiny, tn), r["cnots"], r["depth"])
        for arm in ("D", "G", "A"):
            if sigs[arm][1] != TINY_EXP["cnots"] or \
                    sigs[arm][2] != TINY_EXP["depth"]:
                out["failed"].append("tiny-%s-hand" % arm)
        if not (sigs["D"][0] == sigs["G"][0] == sigs["A"][0]
                == sigs["R"][0]):
            out["failed"].append("tiny-sig-equiv")
        tex = exact_opt(tiny, tn, tdist, EXACT_CAP, None)
        if tex["status"] != "solved" or tex["opt_cnots"] != TINY_EXP[
                "cnots"]:
            out["failed"].append("tiny-exact-opt")
        circ = gen_circuit(0, 1, 0)
        dist = LAYOUT_DIST[(circ["n"], circ["layout"])]
        c1 = eval_place(circ["gates"], list(range(circ["n"])),
                        dist, circ["n"])
        c2 = eval_place(circ["gates"], list(range(circ["n"])),
                        dist, circ["n"])
        if c1 != c2:
            out["failed"].append("determinism")
        g1 = run_g(circ["gates"], circ["n"], dist,
                   seed_rng(0, 1, 0, 555), None)
        g2 = run_g(circ["gates"], circ["n"], dist,
                   seed_rng(0, 1, 0, 555), None)
        if (g1["cnots"], g1["depth"]) != (g2["cnots"], g2["depth"]):
            out["failed"].append("determinism-greedy")
        r1 = run_r(circ["gates"], circ["n"], dist,
                   seed_rng(0, 1, 0, 999))
        r2 = run_r(circ["gates"], circ["n"], dist,
                   seed_rng(0, 1, 0, 999))
        if (r1["cnots"], r1["depth"]) != (r2["cnots"], r2["depth"]):
            out["failed"].append("determinism-random")
    except Exception as ex:
        out["failed"].append("raise: %r" % ex)
    return out


def run_arm(size_idx, seed, rep, arm, n_iters, stop):
    circ = gen_circuit(size_idx, seed, rep)
    gates = circ["gates"]
    n = circ["n"]
    dist = LAYOUT_DIST[(n, circ["layout"])]
    if arm == "D":
        return run_d(gates, n, dist)
    if arm == "R":
        return run_r(gates, n, dist,
                     seed_rng(size_idx, seed, rep, 999))
    if arm == "G":
        return run_g(gates, n, dist,
                     seed_rng(size_idx, seed, rep, 555), stop)
    return run_a(gates, n, dist,
                 seed_rng(size_idx, seed, rep, 777), n_iters, stop)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--attempt", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--n-inst", type=int, default=N_INST)
    ap.add_argument("--anneal-iters", type=int, default=ANNEAL_ITERS)
    args = ap.parse_args()
    n_inst = int(args.n_inst)
    n_iters = int(args.anneal_iters)
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

    if over():
        gate3tiny["arms"]["tiny"] = {"status": "skipped-guard"}
        skipped.append({"what": "tiny-exact", "reason": "wall-guard",
                        "iters_done": 0, "n_evaluated": 0})
    else:
        tdist = [[0, 1], [1, 0]]
        ex = exact_opt(list(TINY_GATES), 2, tdist, EXACT_CAP, over)
        gate3tiny["arms"]["tiny"] = ex
        gate3tiny["total"] += 1
        if ex["status"] == "solved" and ex["opt_cnots"] == TINY_EXP[
                "cnots"]:
            gate3tiny["solved"] += 1
    with open(os.path.join(witdir, "gate3_tiny.json"), "w") as f:
        json.dump(gate3tiny, f, indent=1, default=str)
    checkpoint("tiny")

    if over():
        gate3targets.append({"status": "skipped-guard"})
        skipped.append({"what": "target-exact", "reason": "wall-guard",
                        "iters_done": 0, "n_evaluated": 0})
    else:
        tcirc = gen_circuit(TARGET_SIZE, TARGET_SEED, TARGET_REP)
        tdist = LAYOUT_DIST[(tcirc["n"], TARGET_LAYOUT)]
        tex = exact_opt(tcirc["gates"], tcirc["n"], tdist,
                        EXACT_CAP, over)
        gate3targets.append(dict(tex, layout=TARGET_LAYOUT,
                                 size=tcirc["n"]))
    with open(os.path.join(witdir, "gate3_targets.json"), "w") as f:
        json.dump(gate3targets, f, indent=1, default=str)
    checkpoint("targets")

    def run_cell(si, seed):
        n = SIZES[si]
        rec = {"size": n, "seed": seed, "arms": {},
               "sig": tableau_sig(gen_circuit(si, seed, 0)["gates"],
                                   n)}
        for arm in ARMS:
            if over():
                rec["blocked"] = "wall-guard"
                return rec
            cn, dp = [], []
            nstop = 0
            for rep in range(n_inst):
                if rep % 32 == 0 and over():
                    nstop += 1
                    break
                out = run_arm(si, seed, rep, arm, n_iters, over)
                if out.get("stopped"):
                    nstop += 1
                    break
                cn.append(out["cnots"])
                dp.append(out["depth"])
            if nstop:
                rec["blocked"] = "stopped-guard"
                rec["iters_done"] = len(cn)
                rec["n_evaluated"] = n_inst
                return rec
            rec["arms"][arm] = {
                "n": len(cn),
                "cnots": pooled_stats(cn),
                "depth": pooled_stats(dp),
                "over_budget": int(sum(
                    1 for v in dp if v > DEPTH_BUDGET[n]))}
        return rec

    def record_cell(rec):
        if rec.get("blocked") is None and all(
                rec["arms"].get(a, {}).get("n") == n_inst
                for a in ARMS):
            for a in ARMS:
                key = (rec["size"], rec["seed"], a)
                cells.setdefault(key, {"cnots": [], "depth": []})
                cells[key]["cnots"].append(
                    rec["arms"][a]["cnots"]["mean"])
                cells[key]["depth"].append(
                    rec["arms"][a]["depth"]["mean"])
            return True
        skipped.append({"what": "cell %d/%d" % (
            rec["size"], rec["seed"]),
            "reason": rec.get("blocked", "arm-incomplete"),
            "iters_done": rec.get("iters_done", 0),
            "n_evaluated": n_inst})
        return False

    for si, n in enumerate(SIZES):
        siz_cells = [(si, seed) for seed in SEEDS]
        if over():
            for (s2, sd2) in siz_cells:
                skipped.append({"what": "cell %d/%d" % (
                    SIZES[s2], sd2), "reason": "wall-guard",
                    "iters_done": 0, "n_evaluated": n_inst})
        else:
            for (s2, sd2) in siz_cells:
                if over():
                    skipped.append({"what": "cell %d/%d" % (
                        SIZES[s2], sd2), "reason": "wall-guard",
                        "iters_done": 0, "n_evaluated": n_inst})
                    continue
                rec = run_cell(s2, sd2)
                cellrecs.append(rec)
                record_cell(rec)
        with open(os.path.join(witdir, "cells.json"), "w") as f:
            json.dump(cellrecs, f, indent=1, default=str)
        checkpoint("size%d" % n)
    with open(os.path.join(witdir, "cells.json"), "w") as f:
        json.dump(cellrecs, f, indent=1, default=str)
    checkpoint("corpus")

    def cell_mean(n, seed, arm, field):
        return cells.get((n, seed, arm),
                         {"cnots": [], "depth": []})[field]

    def pool(n, arm, field):
        vals = []
        for seed in SEEDS:
            vals.extend(cell_mean(n, seed, arm, field))
        return pooled_stats(vals), len(vals) == len(SEEDS)

    det1 = run_arm(0, 1, 0, "G", n_iters, None)
    det2 = run_arm(0, 1, 0, "G", n_iters, None)
    det_r1 = run_arm(0, 1, 0, "R", n_iters, None)
    det_r2 = run_arm(0, 1, 0, "R", n_iters, None)
    determinism_ok = bool(
        (det1["cnots"], det1["depth"]) == (det2["cnots"],
                                          det2["depth"])
        and (det_r1["cnots"], det_r1["depth"]) == (det_r2["cnots"],
                                                  det_r2["depth"]))

    g1_cells, g1_beats = [], True
    for n in SIZES:
        for seed in SEEDS:
            ms = cell_mean(n, seed, "G", "cnots")
            mr = cell_mean(n, seed, "R", "cnots")
            ok = (len(ms) == 1 and len(mr) == 1 and ms[0] < mr[0])
            g1_cells.append({"cell": "%d/%d" % (n, seed),
                             "mean_G": ms[0] if ms else None,
                             "mean_R": mr[0] if mr else None,
                             "pass": bool(ok)})
            if not ok:
                g1_beats = False
    g1_ok = bool(g1_beats and tiny_ok and determinism_ok)

    g2_fams, g2_n = [], 0
    g2s_fams, g2s_n = [], 0
    win_fams, win_n = [], 0
    for n in SIZES:
        pools, pok = {}, True
        for arm in ("D", "G", "A"):
            pools[arm], oka = pool(n, arm, "cnots")
            pok = pok and oka
        se, spread, gp = spread_win(pools, pok)
        g2_fams.append({"size": n, "pools": pools, "SE": se,
                        "spread": spread, "pass": bool(gp)})
        if gp:
            g2_n += 1
        spools, spok = {}, True
        for arm in ("D", "G", "A"):
            spools[arm], oka = pool(n, arm, "depth")
            spok = spok and oka
        sse, sspread, sgp = spread_win(spools, spok)
        g2s_fams.append({"size": n, "pools": spools,
                         "SE": sse, "spread": sspread,
                         "pass": bool(sgp)})
        if sgp:
            g2s_n += 1
        joint = {}
        if pok and spok and all(
                pools[a]["se"] is not None and
                pools[a]["mean"] is not None for a in ("D", "G", "A")):
            sse2 = math.sqrt(sum(pools[a]["se"] ** 2
                                 for a in ("D", "G", "A")) / 3.0)
            for a in ("G", "A"):
                cwin = pools[a]["mean"] < pools["D"]["mean"] - 2.0 * sse2
                cok = spools[a]["mean"] <= spools["D"]["mean"]
                joint[a] = bool(cwin and cok)
        else:
            joint = {"G": False, "A": False}
        winner = ("G" if joint["G"]
                  else ("A" if joint["A"] else None))
        wpass = winner is not None
        if pok and all(pools[a]["mean"] is not None
                       for a in ("D", "G", "A")):
            spass = (pools["G"]["mean"] < pools["D"]["mean"] or
                     pools["A"]["mean"] < pools["D"]["mean"])
        else:
            spass = False
        win_fams.append({"size": n, "win": bool(wpass),
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
        len(cell_mean(n, seed, arm, "cnots")) == 1
        for n in SIZES for seed in SEEDS for arm in ARMS)
    tiny_attempted = gate3tiny["total"] == 1
    targets_attempted = len(gate3targets) == 1
    wall = elapsed()
    clean = len(skipped) == 0
    g4_ok = bool(complete and tiny_attempted and targets_attempted and
                 wall < WALL_LIMIT_S and clean)

    selftest_ok = bool(tiny_ok)
    strict_n = sum(1 for wrec in win_fams if wrec.get("strict_win"))
    pools_all = all(wrec.get("pools_ok") for wrec in win_fams)
    pursue = (win_n >= 2 and g1_ok and g2_ok and g3pass and g4_ok and
              selftest_ok)
    reject = (complete and tiny_solved and g1_ok and
              pools_all and strict_n == 0)
    if pursue:
        reason = "PURSUE-condition holds (joint synthesis CNOT win " \
            "+ depth no-regress on the SAME arm at >=2 sizes + " \
            "gates 1,2,3,4 + self-tests ok); payload verdict stays " \
            "unresolved-with-reason, classification is coordinator-side."
    elif reject:
        reason = "REJECT-condition holds (complete cells, tiny solved, " \
            "Gate-1 controls pass, no strict pooled synthesis CNOT " \
            "win at any size); payload verdict stays " \
            "unresolved-with-reason, classification is coordinator-side."
    else:
        reason = "UNRESOLVED + next experiment (joint wins=%d/3, " \
            "strict synthesis wins=%d/3, g1=%s g2=%s " \
            "g2s(depth-spread)=%s g3=%s (tiny solved=%s, target " \
            "cap-hit=%s) selftest=%s g4=%s complete=%s skipped=%d; " \
            "next: gate-reordering synthesis families with look-ahead " \
            "+ depth-regularized annealing retest)." % (
                win_n, strict_n, g1_ok, g2_ok, g2s_n >= 2, g3pass,
                tiny_solved, target_cap,
                selftest_ok, g4_ok, complete, len(skipped))
    verdict_bits = {
        "gate1": {"pass": bool(g1_ok), "beats_all_15": bool(g1_beats),
                  "tiny_ok": bool(tiny_ok),
                  "determinism_ok": bool(determinism_ok),
                  "cells": g1_cells},
        "gate2": {"pass": bool(g2_ok), "n_sizes_pass": g2_n,
                  "sizes": g2_fams},
        "gate2_s": {"pass": bool(g2s_n >= 2), "n_sizes_pass": g2s_n,
                    "sizes": g2s_fams},
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
        "screen": "19",
        "verdict": "unresolved-with-reason: payload reports numbers "
                   "and gate evidence; classification is coordinator-side.",
        "design": {
            "model": "screen-authored deterministic bitwise "
                     "stabilizer-tableau sim (stdlib + numpy only; no "
                     "external libs)",
            "sizes": list(SIZES),
            "layouts": ["grid", "hex"],
            "depth_budgets": DEPTH_BUDGET,
            "seeds": list(SEEDS),
            "reps_per_cell_arm": n_inst,
            "gates_per_qubit": GATES_PER_QUBIT,
            "greedy": {"sweeps": GREEDY_SWEEPS},
            "anneal": {"iters": n_iters, "t0": ANNEAL_T0,
                       "alpha": ANNEAL_ALPHA, "lambda": LAMBDA},
            "arms": {"D": "canonical Gaussian elimination + SWAP "
                          "routing (identity placement)",
                     "G": "greedy pairwise-swap placement descent "
                          "(identity + one seeded restart)",
                     "A": "simulated annealing over placements "
                          "(CNOTs + LAMBDA*depth)",
                     "R": "random placement control"},
            "metrics": "total routed CNOTs (3d-2 per CNOT at graph "
                       "distance d) + circuit depth (list-scheduled, "
                       "2d-1 per CNOT, 1 per single-qubit gate)",
            "pareto": "PURSUE needs a routed-CNOT win + depth "
                      "no-regress on the SAME arm; a CNOT-only win with "
                      "higher depth is NOT a joint win",
            "exact": "bounded-exact branch-and-bound over placements "
                     "on tiny (must solve, optimum %d) + target-scale "
                     "instance (%d-qubit family, %s layout, node cap "
                     "%d, must cap-hit)" % (
                         TINY_EXP["cnots"], SIZES[TARGET_SIZE],
                         TARGET_LAYOUT, EXACT_CAP),
        },
        "timing": {"wall_s": wall, "guards": {"wall_guard_s": WALL_GUARD_S,
                                              "limit_s": WALL_LIMIT_S}},
        "cells": {("%d/%d/%s" % k): {"n": len(v["cnots"]),
                                     **pooled_stats(v["cnots"]),
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
