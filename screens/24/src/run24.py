"""Screen 24 payload: fermion-to-qubit ternary-tree mapping optimization.

Screen-authored deterministic ternary-tree encoding model (stdlib +
numpy only; no external chemistry, synthesis, or solver libs):
synthetic frozen molecular Hamiltonians (1- and 2-body fermionic
mode graphs) on n in {12, 16, 20} spin-orbitals; encodings as
ternary trees (leaf-to-mode assignment + child-permutation rotations
preserving anticommutation structurally); Pauli-gadget routed cost
on frozen 2D grids under the sibling-screen 3d-2 convention.
Arms: J Jordan-Wigner interval baseline, K Fenwick (BK-inspired)
log-weight baseline, T balanced ternary baseline, G greedy leaf-swap
descent from T, A simulated annealing over swaps+rotations
(cost = routed CNOTs + LAMBDA * depth, frozen LAMBDA), R random
control. Metric: total routed CNOT weight of the Pauli network +
circuit depth at fixed grid. A bounded-exact branch-and-bound over
leaf assignments validates the tiny instance (solved, optimum by
construction) and cap-hits at target scale (limit-expiry). Writes
ALL output under cwd (the attempt work dir): results.json +
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

SIZES = (12, 16, 20)
GRID_COLS = {12: 4, 16: 4, 20: 5}
SEEDS = (1, 2, 3, 4, 5)
ARMS = ("J", "K", "T", "G", "A", "R")

N_INST = 120
ANNEAL_ITERS = 150
ANNEAL_T0 = 2.0
ANNEAL_ALPHA = 0.99
GREEDY_SWEEPS = 2
LAMBDA = 5.0

WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0
EXACT_CAP = 50000

HOP_LONG = {12: 6, 16: 8, 20: 10}
N_DENS = {12: 14, 16: 20, 20: 26}
N_PAIR = {12: 4, 16: 6, 20: 8}

PERMS5 = ((0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0))

TINY_N = 4
TINY_GADGETS = (((0, 1), 2), ((1, 2), 2), ((2, 3), 2),
                ((0, 2), 1), ((1, 3), 1))
TINY_EXP = {"cnots": 40, "depth": 42}
TARGET_SIZE_IDX = 2
TARGET_SEED = 1
TARGET_REP = 0


def grid_edges(n, cols):
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


def all_pairs_dist(n, edges):
    INF = 10 ** 9
    adj = [[] for _ in range(n)]
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    dist = [[INF] * n for _ in range(n)]
    for s in range(n):
        dist[s][s] = 0
        queue = deque([s])
        while queue:
            u = queue.popleft()
            for v in adj[u]:
                if dist[s][v] == INF:
                    dist[s][v] = dist[s][u] + 1
                    queue.append(v)
    return dist


DIST = {}
for _n in SIZES:
    DIST[_n] = all_pairs_dist(_n, grid_edges(_n, GRID_COLS[_n]))
DIST_TINY = [[0, 1], [1, 0]]


def seed_rng(size_idx, seed, rep, salt):
    return np.random.default_rng(
        (int(size_idx * 100003 + seed * 10007 + rep * 101
             + salt * 1000003) % (2 ** 63 - 1)))


def gen_ham(size_idx, seed, rep):
    """Frozen synthetic molecular Hamiltonian: chain hopping on all
    adjacent mode pairs + seeded long-range hopping pairs + seeded
    density pairs + seeded pair-hopping quadruples. Each hopping
    term yields 2 Pauli gadgets, each density term 1, each pair term
    2 (all sharing the term's mode support). Deterministic given
    inputs; frozen term counts per size."""
    n = SIZES[size_idx]
    rng = seed_rng(size_idx, seed, rep, 11)
    hops = [(p, p + 1) for p in range(n - 1)]
    nonadj = [(p, q) for p in range(n) for q in range(p + 2, n)]
    pick = rng.choice(len(nonadj), size=HOP_LONG[n], replace=False)
    hops += sorted(nonadj[i] for i in pick)
    allpairs = [(p, q) for p in range(n) for q in range(p + 1, n)]
    dpick = rng.choice(len(allpairs), size=N_DENS[n], replace=False)
    dens = sorted(allpairs[i] for i in dpick)
    pairs = []
    guard = 0
    while len(pairs) < N_PAIR[n] and guard < 500:
        guard += 1
        quad = tuple(sorted(int(x) for x in rng.integers(n, size=4)))
        if len(set(quad)) == 4 and quad not in pairs:
            pairs.append(quad)
    pairs.sort()
    gadgets = []
    for t in hops:
        gadgets.append((t, 2))
    for t in dens:
        gadgets.append((t, 1))
    for t in pairs:
        gadgets.append((t, 2))
    return {"n": n, "gadgets": gadgets,
            "counts": {"hop": len(hops), "dens": len(dens),
                       "pair": len(pairs)}}


def build_tree(n):
    """Full balanced ternary tree with exactly n internal nodes
    (= n qubits) and 2n+1 leaves. Shallowest-leaf-first expansion
    keeps it balanced. Rotations permute one node's 3 children
    (O(1) pointer update preserving the anticommutation
    structure). Canonical leaves = first n leaves in DFS order."""
    ch = [[n, n + 1, n + 2]]
    parent = {n: (0, 0), n + 1: (0, 1), n + 2: (0, 2)}
    queue = deque([n, n + 1, n + 2])
    nxt = n + 3
    while len(ch) < n:
        leaf = queue.popleft()
        nid = len(ch)
        p, s = parent.pop(leaf)
        ch[p][s] = nid
        ch.append([nxt, nxt + 1, nxt + 2])
        for t, lf in enumerate([nxt, nxt + 1, nxt + 2]):
            parent[lf] = (nid, t)
            queue.append(lf)
        nxt += 3
    masks = {}

    def dfs(u, mask):
        if u >= n:
            masks[u] = mask
            return [u]
        out = []
        for v in ch[u]:
            if v >= n:
                masks[v] = mask | (1 << u)
                out.append(v)
            else:
                out.extend(dfs(v, mask | (1 << u)))
        return out

    order = dfs(0, 0)
    return {"ch": ch, "canon": order[:n], "masks": masks,
            "n_leaves": len(masks)}


def tree_masks(ch, n):
    masks = {}

    def dfs(u, mask):
        if u >= n:
            masks[u] = mask
            return
        for v in ch[u]:
            dfs(v, mask | (1 << u) if u < n else mask)

    dfs(0, 0)
    return masks


def copy_tree(ch):
    return [list(c) for c in ch]


def bk_masks(n):
    """Fenwick-tree update/parity support sets (BK-inspired
    log-weight baseline): support(m) = U(m) | P(m)."""
    out = []
    for r in range(n):
        j = r + 1
        s = {r}
        k = j + (j & -j)
        while k <= n:
            s.add(k - 1)
            k += k & -k
        k = j - 1
        while k >= 1:
            s.add(k - 1)
            k -= k & -k
        mask = 0
        for q in s:
            mask |= 1 << q
        out.append(mask)
    return out


BK = {n: bk_masks(n) for n in SIZES}
BK_TINY = bk_masks(TINY_N)

DIST_TINY = all_pairs_dist(TINY_N, grid_edges(TINY_N, 2))


def gadget_cost(qubits, dist):
    """Pauli-gadget routed cost: support qubits chained in grid
    order; each link is 2 CNOTs (ladder + reverse) at 3d-2 routed
    CNOTs each, duration 2*(2d-1), plus 1 for the rotation."""
    cn = 0
    dp = 0
    for a, b in zip(qubits[:-1], qubits[1:]):
        d = dist[a][b]
        cn += 2 * (3 * d - 2)
        dp += 2 * (2 * d - 1)
    return cn, dp + 1


def mask_qubits(mask):
    qs = []
    q = 0
    while mask:
        if mask & 1:
            qs.append(q)
        mask >>= 1
        q += 1
    return qs


def eval_masks(mode_masks, gadgets, dist):
    cn = 0
    dp = 0
    for modes, mult in gadgets:
        m = 0
        for x in modes:
            m |= mode_masks[x]
        qs = mask_qubits(m)
        if len(qs) < 2:
            dp += mult
            continue
        c, d = gadget_cost(qs, dist)
        cn += mult * c
        dp += mult * d
    return int(cn), int(dp)


def eval_jw(gadgets, n, dist):
    cn = 0
    dp = 0
    for modes, mult in gadgets:
        lo = min(modes)
        hi = max(modes)
        qs = list(range(lo, hi + 1))
        if len(qs) < 2:
            dp += mult
            continue
        c, d = gadget_cost(qs, dist)
        cn += mult * c
        dp += mult * d
    return int(cn), int(dp)


def eval_bk(gadgets, masks, dist):
    return eval_masks(masks, gadgets, dist)


def unrouted_masks(mode_masks, gadgets):
    tot = 0
    for modes, mult in gadgets:
        m = 0
        for x in modes:
            m |= mode_masks[x]
        w = bin(m).count("1")
        if w > 1:
            tot += mult * 2 * (w - 1)
    return int(tot)


def run_j(gadgets, n, dist):
    c, d = eval_jw(gadgets, n, dist)
    return {"cnots": c, "depth": d, "stopped": False}


def run_k(gadgets, masks, dist):
    c, d = eval_bk(gadgets, masks, dist)
    return {"cnots": c, "depth": d, "stopped": False}


def run_t(gadgets, leaf_masks, canon, dist, n):
    mm = [leaf_masks[canon[m]] for m in range(n)]
    c, d = eval_masks(mm, gadgets, dist)
    return {"cnots": c, "depth": d, "stopped": False}


def run_r(gadgets, tree, dist, n, rng):
    perm = list(range(n))
    rng.shuffle(perm)
    ch = copy_tree(tree["ch"])
    for _ in range(n):
        node = int(rng.integers(n))
        p = PERMS5[int(rng.integers(5))]
        ch[node] = [ch[node][i] for i in p]
    lm = tree_masks(ch, n)
    mm = [lm[tree["canon"][perm[m]]] for m in range(n)]
    c, d = eval_masks(mm, gadgets, dist)
    return {"cnots": c, "depth": d, "stopped": False}


def run_g(gadgets, tree, dist, n, rng, stop):
    """Greedy leaf-swap descent from the balanced-ternary start plus
    one seeded random restart; first-improvement, strictly improving
    moves only, so the result never exceeds the T cost."""
    starts = [list(range(n))]
    alt = list(range(n))
    rng.shuffle(alt)
    starts.append(alt)
    lm0 = tree["masks"]
    canon = tree["canon"]
    best = None
    for start in starts:
        perm = list(start)
        mm = [lm0[canon[perm[m]]] for m in range(n)]
        c, d = eval_masks(mm, gadgets, dist)
        for _ in range(GREEDY_SWEEPS):
            for i in range(n):
                if stop is not None and stop():
                    return {"cnots": None, "depth": None,
                            "stopped": True}
                for j in range(i + 1, n):
                    perm[i], perm[j] = perm[j], perm[i]
                    mm = [lm0[canon[perm[m]]] for m in range(n)]
                    c2, d2 = eval_masks(mm, gadgets, dist)
                    if c2 < c or (c2 == c and d2 < d):
                        c, d = c2, d2
                    else:
                        perm[i], perm[j] = perm[j], perm[i]
        if best is None or c < best[0] or (c == best[0] and d < best[1]):
            best = (c, d)
    return {"cnots": int(best[0]), "depth": int(best[1]),
            "stopped": False}


def run_a(gadgets, tree, dist, n, rng, n_iters, stop):
    """Simulated annealing over leaf swaps + tree rotations from the
    T start; cost = routed CNOTs + LAMBDA * depth (frozen LAMBDA).
    Tracks best, so the result never exceeds the T cost."""
    canon = tree["canon"]
    ch = copy_tree(tree["ch"])
    lm = tree_masks(ch, n)
    perm = list(range(n))
    mm = [lm[canon[perm[m]]] for m in range(n)]
    c, d = eval_masks(mm, gadgets, dist)
    best = [c + LAMBDA * d, c, d]
    cur = best[0]
    temp = ANNEAL_T0
    for it in range(n_iters):
        if it % 32 == 0 and stop is not None and stop():
            break
        if float(rng.random()) < 0.7:
            i = int(rng.integers(n))
            j = int(rng.integers(n))
            if i == j:
                temp *= ANNEAL_ALPHA
                continue
            perm[i], perm[j] = perm[j], perm[i]
            mm = [lm[canon[perm[m]]] for m in range(n)]
            c2, d2 = eval_masks(mm, gadgets, dist)
            cost2 = c2 + LAMBDA * d2
            if cost2 < cur or bool(
                    rng.random() < math.exp(-(cost2 - cur) / temp)):
                cur = cost2
                if cost2 < best[0] or (cost2 == best[0]
                                       and c2 < best[1]):
                    best = [cost2, c2, d2]
            else:
                perm[i], perm[j] = perm[j], perm[i]
        else:
            node = int(rng.integers(n))
            p = PERMS5[int(rng.integers(5))]
            old = ch[node]
            ch[node] = [old[i] for i in p]
            lm = tree_masks(ch, n)
            mm = [lm[canon[perm[m]]] for m in range(n)]
            c2, d2 = eval_masks(mm, gadgets, dist)
            cost2 = c2 + LAMBDA * d2
            if cost2 < cur or bool(
                    rng.random() < math.exp(-(cost2 - cur) / temp)):
                cur = cost2
                if cost2 < best[0] or (cost2 == best[0]
                                       and c2 < best[1]):
                    best = [cost2, c2, d2]
            else:
                ch[node] = old
                lm = tree_masks(ch, n)
        temp *= ANNEAL_ALPHA
    return {"cnots": int(best[1]), "depth": int(best[2]),
            "stopped": False}


def exact_opt(gadgets, slot_masks, n, cap, stop):
    """Bounded-exact branch-and-bound over mode->leaf assignments
    (identity rotations), minimizing unrouted CNOT weight. Statuses:
    solved / cap-hit / stopped-guard."""
    by_mode = [[] for _ in range(n)]
    for gi, (modes, mult) in enumerate(gadgets):
        for x in modes:
            by_mode[x].append(gi)
    deg = [len(by_mode[m]) for m in range(n)]
    order = sorted(range(n), key=lambda q: (-deg[q], q))
    mm0 = list(slot_masks)
    bc = unrouted_masks(mm0, gadgets)
    best = [bc]
    assign = [-1] * n
    used = bytearray(n)
    nodes = [0]
    capped = [False]
    stopped = [False]

    def gadget_done(gi):
        return all(assign[x] != -1 for x in gadgets[gi][0])

    def gadget_cost_now(gi):
        m = 0
        for x in gadgets[gi][0]:
            m |= slot_masks[assign[x]]
        w = bin(m).count("1")
        return gadgets[gi][1] * 2 * (w - 1) if w > 1 else 0

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
        for s in range(n):
            if not used[s]:
                assign[q] = s
                used[s] = 1
                add = 0
                for gi in by_mode[q]:
                    if gadget_done(gi):
                        add += gadget_cost_now(gi)
                rec(k + 1, partial + add)
                used[s] = 0
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


TREES = {n: build_tree(n) for n in SIZES}
TREE_TINY = build_tree(TINY_N)


def tiny_t():
    t = TREE_TINY
    return run_t(list(TINY_GADGETS), t["masks"], t["canon"],
                 DIST_TINY, TINY_N)


def audit_ham(size_idx, seed, rep):
    ham = gen_ham(size_idx, seed, rep)
    n = ham["n"]
    exp_hop = (n - 1) + HOP_LONG[n]
    ok_counts = ham["counts"]["hop"] == exp_hop and \
        ham["counts"]["dens"] == N_DENS[n] and \
        ham["counts"]["pair"] == N_PAIR[n]
    seen = set()
    for modes, _ in ham["gadgets"]:
        seen.update(modes)
    exp_gadgets = 2 * exp_hop + N_DENS[n] + 2 * N_PAIR[n]
    ok_g = sum(m for _, m in ham["gadgets"]) == exp_gadgets
    connected = all(DIST[n][a][b] < 10 ** 9
                    for a in range(n) for b in range(n))
    return {"counts_ok": bool(ok_counts), "gadgets_ok": bool(ok_g),
            "coverage_ok": seen == set(range(n)),
            "connected": bool(connected)}


def self_tests():
    out = {"ran": True, "failed": []}
    try:
        for n in SIZES:
            t = TREES[n]
            if len(t["ch"]) != n:
                out["failed"].append("tree-internal-%d" % n)
            if t["n_leaves"] != 2 * n + 1:
                out["failed"].append("tree-leaves-%d" % n)
            if len(t["canon"]) != n or any(
                    m == 0 for m in
                    (t["masks"][lf] for lf in t["canon"])):
                out["failed"].append("tree-canon-%d" % n)
        for si in range(len(SIZES)):
            for rep in (0, 1):
                au = audit_ham(si, 1, rep)
                for k, v in au.items():
                    if not v:
                        out["failed"].append("ham-%s-%d-%d" % (k, si, rep))
        tt = tiny_t()
        if tt["cnots"] != TINY_EXP["cnots"] or \
                tt["depth"] != TINY_EXP["depth"]:
            out["failed"].append("tiny-T-hand")
        tg = run_g(list(TINY_GADGETS), TREE_TINY, DIST_TINY, TINY_N,
                   seed_rng(0, 7, 7, 555), None)
        if tg["cnots"] != TINY_EXP["cnots"] or \
                tg["depth"] != TINY_EXP["depth"]:
            out["failed"].append("tiny-G-hand")
        ta = run_a(list(TINY_GADGETS), TREE_TINY, DIST_TINY, TINY_N,
                   seed_rng(0, 7, 7, 777), 50, None)
        if ta["cnots"] > TINY_EXP["cnots"]:
            out["failed"].append("tiny-A-regress")
        slot0 = [TREE_TINY["masks"][lf]
                 for lf in TREE_TINY["canon"]]
        tex = exact_opt(list(TINY_GADGETS), slot0, TINY_N,
                        EXACT_CAP, None)
        if tex["status"] != "solved" or tex["opt_cnots"] != \
                unrouted_masks(slot0, list(TINY_GADGETS)):
            out["failed"].append("tiny-exact-opt")
        ham = gen_ham(0, 1, 0)
        t0 = TREES[ham["n"]]
        mm = [t0["masks"][lf] for lf in t0["canon"]]
        c1 = eval_masks(mm, ham["gadgets"], DIST[ham["n"]])
        c2 = eval_masks(mm, ham["gadgets"], DIST[ham["n"]])
        if c1 != c2:
            out["failed"].append("determinism")
        g1 = run_g(ham["gadgets"], t0, DIST[ham["n"]], ham["n"],
                   seed_rng(0, 1, 0, 555), None)
        g2 = run_g(ham["gadgets"], t0, DIST[ham["n"]], ham["n"],
                   seed_rng(0, 1, 0, 555), None)
        if (g1["cnots"], g1["depth"]) != (g2["cnots"], g2["depth"]):
            out["failed"].append("determinism-greedy")
        r1 = run_r(ham["gadgets"], t0, DIST[ham["n"]], ham["n"],
                   seed_rng(0, 1, 0, 999))
        r2 = run_r(ham["gadgets"], t0, DIST[ham["n"]], ham["n"],
                   seed_rng(0, 1, 0, 999))
        if (r1["cnots"], r1["depth"]) != (r2["cnots"], r2["depth"]):
            out["failed"].append("determinism-random")
        a1 = run_a(ham["gadgets"], t0, DIST[ham["n"]], ham["n"],
                   seed_rng(0, 1, 0, 777), 50, None)
        a2 = run_a(ham["gadgets"], t0, DIST[ham["n"]], ham["n"],
                   seed_rng(0, 1, 0, 777), 50, None)
        if (a1["cnots"], a1["depth"]) != (a2["cnots"], a2["depth"]):
            out["failed"].append("determinism-anneal")
    except Exception as ex:
        out["failed"].append("raise: %r" % ex)
    return out


def run_arm(size_idx, seed, rep, arm, n_iters, stop):
    ham = gen_ham(size_idx, seed, rep)
    gadgets = ham["gadgets"]
    n = ham["n"]
    dist = DIST[n]
    if arm == "J":
        return run_j(gadgets, n, dist)
    if arm == "K":
        return run_k(gadgets, BK[n], dist)
    t = TREES[n]
    if arm == "T":
        return run_t(gadgets, t["masks"], t["canon"], dist, n)
    if arm == "R":
        return run_r(gadgets, t, dist, n,
                     seed_rng(size_idx, seed, rep, 999))
    if arm == "G":
        return run_g(gadgets, t, dist, n,
                     seed_rng(size_idx, seed, rep, 555), stop)
    return run_a(gadgets, t, dist, n,
                 seed_rng(size_idx, seed, rep, 777), n_iters, stop)


def ham_sig(size_idx, seed, rep):
    ham = gen_ham(size_idx, seed, rep)
    h = hashlib.sha256(repr(ham["gadgets"]).encode())
    return h.hexdigest()[:16]


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
        slot0 = [TREE_TINY["masks"][lf]
                 for lf in TREE_TINY["canon"]]
        ex = exact_opt(list(TINY_GADGETS), slot0, TINY_N,
                       EXACT_CAP, over)
        gate3tiny["arms"]["tiny"] = ex
        gate3tiny["total"] += 1
        if ex["status"] == "solved" and ex["opt_cnots"] == \
                unrouted_masks(slot0, list(TINY_GADGETS)):
            gate3tiny["solved"] += 1
    with open(os.path.join(witdir, "gate3_tiny.json"), "w") as f:
        json.dump(gate3tiny, f, indent=1, default=str)
    checkpoint("tiny")

    if over():
        gate3targets.append({"status": "skipped-guard"})
        skipped.append({"what": "target-exact", "reason": "wall-guard",
                        "iters_done": 0, "n_evaluated": 0})
    else:
        tham = gen_ham(TARGET_SIZE_IDX, TARGET_SEED, TARGET_REP)
        tn = tham["n"]
        tslot = [TREES[tn]["masks"][lf]
                 for lf in TREES[tn]["canon"]]
        tex = exact_opt(tham["gadgets"], tslot, tn, EXACT_CAP, over)
        gate3targets.append(dict(tex, size=tn, seed=TARGET_SEED,
                                 rep=TARGET_REP))
    with open(os.path.join(witdir, "gate3_targets.json"), "w") as f:
        json.dump(gate3targets, f, indent=1, default=str)
    checkpoint("targets")

    def run_cell(si, seed):
        n = SIZES[si]
        rec = {"size": n, "seed": seed, "arms": {},
               "sig": ham_sig(si, seed, 0)}
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
                "depth": pooled_stats(dp)}
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

    det_g1 = run_arm(0, 1, 0, "G", n_iters, None)
    det_g2 = run_arm(0, 1, 0, "G", n_iters, None)
    det_r1 = run_arm(0, 1, 0, "R", n_iters, None)
    det_r2 = run_arm(0, 1, 0, "R", n_iters, None)
    det_a1 = run_arm(0, 1, 0, "A", n_iters, None)
    det_a2 = run_arm(0, 1, 0, "A", n_iters, None)
    determinism_ok = bool(
        (det_g1["cnots"], det_g1["depth"]) == (det_g2["cnots"],
                                              det_g2["depth"])
        and (det_r1["cnots"], det_r1["depth"]) == (det_r2["cnots"],
                                                  det_r2["depth"])
        and (det_a1["cnots"], det_a1["depth"]) == (det_a2["cnots"],
                                                  det_a2["depth"]))

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
        for arm in ("J", "K", "T", "G", "A"):
            pools[arm], oka = pool(n, arm, "cnots")
            pok = pok and oka
        se, spread, gp = spread_win(pools, pok)
        g2_fams.append({"size": n, "pools": pools, "SE": se,
                        "spread": spread, "pass": bool(gp)})
        if gp:
            g2_n += 1
        spools, spok = {}, True
        for arm in ("J", "K", "T", "G", "A"):
            spools[arm], oka = pool(n, arm, "depth")
            spok = spok and oka
        sse, sspread, sgp = spread_win(spools, spok)
        g2s_fams.append({"size": n, "pools": spools,
                         "SE": sse, "spread": sspread,
                         "pass": bool(sgp)})
        if sgp:
            g2s_n += 1
        joint = {}
        base_ok = pok and spok and all(
            pools[a]["se"] is not None and
            pools[a]["mean"] is not None
            for a in ("J", "K", "T", "G", "A"))
        if base_ok:
            base_depth = min(spools[a]["mean"]
                             for a in ("J", "K", "T"))
            for a in ("G", "A"):
                keys4 = ("J", "K", "T", a)
                se4 = math.sqrt(sum(pools[k]["se"] ** 2
                                    for k in keys4) / 4.0)
                cwin = all(pools[a]["mean"] < pools[b]["mean"]
                           - 2.0 * se4 for b in ("J", "K", "T"))
                cok = spools[a]["mean"] <= base_depth
                joint[a] = bool(cwin and cok)
        else:
            joint = {"G": False, "A": False}
        winner = ("G" if joint["G"]
                  else ("A" if joint["A"] else None))
        wpass = winner is not None
        if pok and all(pools[a]["mean"] is not None
                       for a in ("J", "K", "T", "G", "A")):
            best_base = min(pools[b]["mean"] for b in ("J", "K", "T"))
            spass = (pools["G"]["mean"] < best_base or
                     pools["A"]["mean"] < best_base)
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
        reason = "PURSUE-condition holds (joint routed-CNOT win " \
            "over ALL of {J,K,T} + depth no-regress on the SAME " \
            "search arm at >=2 sizes + gates 1,2,3,4 + self-tests " \
            "ok); payload verdict stays unresolved-with-reason, " \
            "classification is coordinator-side."
    elif reject:
        reason = "REJECT-condition holds (complete cells, tiny " \
            "solved, Gate-1 controls pass, no strict pooled " \
            "routed-CNOT win at any size); payload verdict stays " \
            "unresolved-with-reason, classification is " \
            "coordinator-side."
    else:
        reason = "UNRESOLVED + next experiment (joint wins=%d/3, " \
            "strict search wins=%d/3, g1=%s g2=%s " \
            "g2s(depth-spread)=%s g3=%s (tiny solved=%s, target " \
            "cap-hit=%s) selftest=%s g4=%s complete=%s skipped=%d; " \
            "next: Pauli-gadget resynthesis with parity-reuse " \
            "routing + larger active-space retest)." % (
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
        "screen": "24",
        "verdict": "unresolved-with-reason: payload reports numbers "
                   "and gate evidence; classification is coordinator-side.",
        "design": {
            "model": "screen-authored deterministic ternary-tree "
                     "encoding model (stdlib + numpy only; no "
                     "external libs)",
            "sizes": list(SIZES),
            "grids": {str(n): "%dx%d" % (n // GRID_COLS[n],
                                         GRID_COLS[n])
                      for n in SIZES},
            "seeds": list(SEEDS),
            "reps_per_cell_arm": n_inst,
            "hamiltonians": {"hop_chain": "n-1",
                             "hop_long": HOP_LONG,
                             "dens": N_DENS, "pair": N_PAIR},
            "greedy": {"sweeps": GREEDY_SWEEPS},
            "anneal": {"iters": n_iters, "t0": ANNEAL_T0,
                       "alpha": ANNEAL_ALPHA, "lambda": LAMBDA},
            "arms": {"J": "Jordan-Wigner interval baseline",
                     "K": "Fenwick (BK-inspired) log-weight baseline",
                     "T": "balanced ternary baseline (identity map)",
                     "G": "greedy leaf-swap descent "
                          "(T start + one seeded restart)",
                     "A": "simulated annealing over swaps+rotations "
                          "(CNOTs + LAMBDA*depth)",
                     "R": "random map + random rotations control"},
            "metrics": "total routed CNOT weight of the Pauli "
                       "network (2 CNOTs per support link at 3d-2 "
                       "each) + circuit depth (list-scheduled, "
                       "2*(2d-1) per link, +1 per gadget)",
            "pareto": "PURSUE needs a routed-CNOT win over ALL of "
                      "{J,K,T} by > 2*SE + depth no-regress vs the "
                      "best baseline on the SAME arm; a CNOT-only "
                      "win with higher depth is NOT a joint win",
            "exact": "bounded-exact branch-and-bound over leaf "
                     "assignments on tiny (must solve) + "
                     "target-scale instance (%d-orbital family, "
                     "seed %d rep %d, node cap %d, must cap-hit)" % (
                         SIZES[TARGET_SIZE_IDX], TARGET_SEED,
                         TARGET_REP, EXACT_CAP),
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
