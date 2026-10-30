"""Screen 11 payload: trapped-ion QCCD junction shuttling and split/merge
scheduling with phonon-heating awareness.

Screen-authored deterministic QCCD shuttling model (stdlib + numpy
only; no external physics, solver, or policy libraries): a 2D grid of
trap sites with explicit per-site capacity, a junction trunk cross
(middle row + middle column) where direction changes are legal, and
per-ion motional phonon counters. Operations: shuttle hops, junction
turns, crystal split/merge, adjacent ion swaps, and sympathetic
cooling rounds that reset phonon. Metric: estimated circuit
infidelity (frozen linear function of swap count + junction turns +
phonon exposure at gate time + cooling rounds + gate count) plus
schedule validity (capacity respected, every turn at a junction, every
gate executed co-located). Arms: S shortest-path/swap-count-only
baseline (always moves the first ion via the shortest turn-legal path,
never cools), R random routing control (seeded random detours, mover,
path, and cooling), G greedy distance routing (per-gate minimum-heat
option plus threshold cooling), A heating-aware simulated annealing
over split/merge/swap/turn sequences (mover, path mode, and cooling
insertion per gate) with phonon counters and cooling overhead, best
tracked from the G schedule so A never exceeds G. A bounded-exact
routing search validates the tiny instance (solved, optimum by
enumeration) and cap-hits at target scale (limit-expiry). Writes ALL
output under cwd (the attempt work dir): results.json + witnesses/.
Deterministic given seeds. Verdict is always unresolved-with-reason;
classification is coordinator-side.
"""

import argparse
import heapq
import json
import math
import os
import time

import numpy as np

GRID_SIZES = (3, 4, 5)
N_IONS_PER_SIZE = (4, 6, 8)
CIRCUITS = ("chain", "star", "ring")
N_GATES = 12
SEEDS = (1, 2, 3, 4, 5)
ARMS = ("S", "R", "G", "A")
TRAP_CAP = 2
HEAT_HOP = 1.0
HEAT_TURN = 2.0
HEAT_SPLIT = 3.0
HEAT_MERGE = 3.0
HEAT_SWAP = 4.0
COOL_THRESHOLD = 12.0
W_SWAP = 0.002
W_TURN = 0.001
W_HEAT = 0.0005
W_COOL = 0.004
W_GATE = 0.001
ANNEAL_ITERS = 300
A_T0 = 1.0
A_ALPHA = 0.99
R_DETOUR = 3
EXACT_CAP = 50000
WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0
TINY_SIZE = 2
TINY_INIT = ((0, 0), (0, 1))
TINY_GATES = ((0, 1),)
TINY_EXP_EXPOSURE = 4.0
TINY_EXP_INFID = 0.003
TARGET = {"size": 5, "circuit": "ring", "seed": 1}
NEXT_EXPERIMENT = ("sympathetic-cooling ion placement co-optimization "
                   "+ correlated heating-noise retest")

DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def seed_rng(si, ci, seed, salt):
    return np.random.default_rng(
        (int(si * 100003 + ci * 17011 + seed * 10007
             + salt * 1000003) % (2 ** 63 - 1)))


def junctions(size):
    """X-junction trunk cross: middle row + middle column. Direction
    changes are legal only at these cells; straight shuttling is
    legal anywhere."""
    m = size // 2
    return {(r, c) for r in range(size) for c in range(size)
            if r == m or c == m}


def nbrs(cell, size):
    r, c = cell
    for dr, dc in DIRS:
        nr, nc = r + dr, c + dc
        if 0 <= nr < size and 0 <= nc < size:
            yield (nr, nc)


def gen_init(si, ci, seed):
    """Seeded initial placement: first n cells of a seeded permutation."""
    size = GRID_SIZES[si]
    n = N_IONS_PER_SIZE[si]
    rng = seed_rng(si, ci, seed, 11)
    perm = rng.permutation(size * size)[:n]
    return tuple((int(p // size), int(p % size)) for p in perm)


def gen_gates(si, ci, seed):
    """Frozen benchmark circuits, rotated by seed (seeds are replicates)."""
    n = N_IONS_PER_SIZE[si]
    circ = CIRCUITS[ci]
    if circ == "chain":
        base = [(k % n, (k + 1) % n) for k in range(n)]
    elif circ == "star":
        base = [(0, 1 + (k % (n - 1))) for k in range(n - 1)]
    else:
        base = [(i, j) for i in range(n) for j in range(i + 1, n)]
    return tuple(base[(k + seed) % len(base)] for k in range(N_GATES))


def bfs_path(size, src, dst, mode):
    """Turn-legal routing from src to dst. A direction change at a node
    is legal only at junction trunk cells. mode 'short' minimizes hops,
    mode 'noturn' minimizes turns (then hops). Transit through
    occupied segments is allowed (disturbance heat is charged by the
    caller); resting capacity is enforced by the caller. Returns
    (path, n_turns) with path a tuple of cells excluding src, or None
    if unreachable."""
    if src == dst:
        return ((), 0)
    junc = junctions(size)
    if mode == "short":
        key = lambda turns, hops: (hops, turns)
    else:
        key = lambda turns, hops: (turns, hops)
    dist = {(src, None): (0, 0)}
    parent = {}
    heap = [(0, 0, src, None)]
    while heap:
        c1, c2, node, d = heapq.heappop(heap)
        turns, hops = dist[(node, d)]
        if (c1, c2) != key(turns, hops):
            continue
        if node == dst:
            path = []
            cur = (node, d)
            while cur[0] != src:
                path.append(cur[0])
                cur = parent[cur]
            path.reverse()
            return (tuple(path), turns)
        for d2 in DIRS:
            if d is not None and d2 != d and node not in junc:
                continue
            nxt = (node[0] + d2[0], node[1] + d2[1])
            if not (0 <= nxt[0] < size and 0 <= nxt[1] < size):
                continue
            nt = turns + (0 if (d is None or d2 == d) else 1)
            nh = hops + 1
            if (nxt, d2) not in dist or key(nt, nh) < key(
                    *dist[(nxt, d2)]):
                dist[(nxt, d2)] = (nt, nh)
                parent[(nxt, d2)] = (node, d)
                k1, k2 = key(nt, nh)
                heapq.heappush(heap, (k1, k2, nxt, d2))
    return None


def occ_of(place):
    occ = {}
    for s in place:
        occ[s] = occ.get(s, 0) + 1
    return occ


def adjacent(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1


def empty_stats(stopped):
    return {"infid": None, "swaps": None, "turns": None,
            "exposure": None, "cooling": None, "valid": False,
            "stopped": bool(stopped)}


def apply_choice(size, place, phonon, gate, choice):
    """Apply one gate choice (mover, path_mode, cool) to a schedule
    state. place is a list of sites per ion, phonon a list of floats.
    Transit through occupied segments is allowed at HEAT_MERGE
    disturbance per resident; resting occupancy never exceeds
    TRAP_CAP (a full target is cleared by displacing its non-partner
    occupant to the first free site). Returns a stats delta dict, or
    None if the choice is illegal (no turn-legal path, no free
    displacement site, or non-adjacent swap). Mutates place/phonon
    on success only."""
    a, b = gate
    mover, pmode, cool = choice
    occ = occ_of(place)
    d = {"swaps": 0, "turns": 0, "heat": 0.0, "cooling": 0}
    if place[a] == place[b]:
        pass
    elif mover == "swap":
        if not adjacent(place[a], place[b]):
            return None
        sa, sb = place[a], place[b]
        place[a], place[b] = sb, sa
        phonon[a] += HEAT_SWAP
        phonon[b] += HEAT_SWAP
        d["heat"] += 2.0 * HEAT_SWAP
        d["swaps"] += 1
    else:
        m = a if mover == "a" else b
        t = b if mover == "a" else a
        src, dst = place[m], place[t]
        # dst is the mover's goal (the partner site) for the whole
        # choice: the displacement walk below uses its own cursor so
        # a full target still routes the mover to the cleared
        # partner site, never to the displaced ion's free site.
        if occ.get(dst, 0) >= TRAP_CAP:
            other = next(i for i, s in enumerate(place)
                         if s == dst and i != t)
            tgt = None
            for cell in ((r, c) for r in range(size)
                         for c in range(size)):
                if occ.get(cell, 0) < TRAP_CAP and cell != dst:
                    tgt = cell
                    break
            if tgt is None:
                return None
            rt = bfs_path(size, dst, tgt, "short")
            if rt is None:
                return None
            if occ.get(dst, 0) >= TRAP_CAP:
                phonon[other] += HEAT_SPLIT
                d["heat"] += HEAT_SPLIT
            cur = dst
            for step in rt[0]:
                occ[cur] -= 1
                cur = step
                occ[cur] = occ.get(cur, 0) + 1
                phonon[other] += HEAT_HOP
                d["heat"] += HEAT_HOP
                if cur != tgt and occ[cur] > 1:
                    phonon[other] += HEAT_MERGE
                    d["heat"] += HEAT_MERGE
            d["turns"] += rt[1]
            phonon[other] += rt[1] * HEAT_TURN
            d["heat"] += rt[1] * HEAT_TURN
            place[other] = tgt
            occ = occ_of(place)
        rt = bfs_path(size, src, dst, pmode)
        if rt is None:
            return None
        path, nturns = rt
        if occ.get(src, 0) >= TRAP_CAP:
            phonon[m] += HEAT_SPLIT
            d["heat"] += HEAT_SPLIT
        cur = src
        for step in path:
            occ[cur] -= 1
            cur = step
            occ[cur] = occ.get(cur, 0) + 1
            phonon[m] += HEAT_HOP
            d["heat"] += HEAT_HOP
            if cur != dst and occ[cur] > 1:
                phonon[m] += HEAT_MERGE
                d["heat"] += HEAT_MERGE
        if occ.get(dst, 0) > 1:
            phonon[m] += HEAT_MERGE
            d["heat"] += HEAT_MERGE
        d["turns"] += nturns
        phonon[m] += nturns * HEAT_TURN
        d["heat"] += nturns * HEAT_TURN
        place[m] = dst
    d["exposure"] = phonon[a] + phonon[b]
    if cool:
        phonon[a] = 0.0
        phonon[b] = 0.0
        d["cooling"] += 1
    return d


def schedule_stats(swaps, turns, exposure, cooling, n_gates):
    return (W_SWAP * swaps + W_TURN * turns + W_HEAT * exposure
            + W_COOL * cooling + W_GATE * n_gates)


def replay(init, gates, size, choices, stop):
    """Replay a full per-gate choice list. Returns (result, applied)
    where applied counts gates executed before a stop/illegal exit."""
    place = list(init)
    phonon = [0.0] * len(init)
    swaps = turns = cooling = 0
    exposure = 0.0
    applied = 0
    for gi, gate in enumerate(gates):
        if stop is not None and stop():
            out = empty_stats(True)
            return out, applied
        d = apply_choice(size, place, phonon, gate, choices[gi])
        if d is None:
            out = empty_stats(False)
            return out, applied
        swaps += d["swaps"]
        turns += d["turns"]
        exposure += d["exposure"]
        cooling += d["cooling"]
        applied += 1
    return ({"infid": schedule_stats(swaps, turns, exposure, cooling,
                                    len(gates)),
             "swaps": swaps, "turns": turns, "exposure": exposure,
             "cooling": cooling, "valid": True, "stopped": False},
            applied)


def run_s(init, gates, size, stop):
    """Shortest-path/swap-count-only baseline: always shuttle the first
    ion of each gate via the shortest turn-legal path; never cool."""
    choices = [(("a", "short", False)) for _ in gates]
    out, _n = replay(init, gates, size, choices, stop)
    return out


def greedy_options(size, place, phonon, gate):
    """All legal (choice, added_heat) pairs for one gate on a copied
    state, in deterministic preference order."""
    opts = []
    for mover in ("a", "b", "swap"):
        for pmode in ("short", "noturn"):
            p2 = list(place)
            h2 = list(phonon)
            d = apply_choice(size, p2, h2, gate,
                             (mover, pmode, False))
            if d is not None:
                opts.append(((mover, pmode), d["heat"]))
    return opts


def _run_g_full(init, gates, size, stop):
    """Greedy distance routing: per gate take the legal option with
    minimum immediate heat (split+merge+hops+turns+swap); cool the pair
    when its post-gate phonon exceeds COOL_THRESHOLD. Returns
    (result, choices)."""
    place = list(init)
    phonon = [0.0] * len(init)
    swaps = turns = cooling = 0
    exposure = 0.0
    choices = []
    for gate in gates:
        if stop is not None and stop():
            return empty_stats(True), []
        a, b = gate
        opts = greedy_options(size, place, phonon, gate)
        if not opts:
            return empty_stats(False), []
        best = min(opts, key=lambda o: o[1])[0]
        cool = False
        p2 = list(place)
        h2 = list(phonon)
        d = apply_choice(size, p2, h2, gate, (best[0], best[1],
                                              False))
        if d is None:
            return empty_stats(False), []
        if h2[a] + h2[b] > COOL_THRESHOLD:
            cool = True
        d = apply_choice(size, place, phonon, gate,
                         (best[0], best[1], cool))
        swaps += d["swaps"]
        turns += d["turns"]
        exposure += d["exposure"]
        cooling += d["cooling"]
        choices.append((best[0], best[1], cool))
    return ({"infid": schedule_stats(swaps, turns, exposure, cooling,
                                    len(gates)),
             "swaps": swaps, "turns": turns, "exposure": exposure,
             "cooling": cooling, "valid": True, "stopped": False},
            choices)


def run_g(init, gates, size, stop):
    out, _c = _run_g_full(init, gates, size, stop)
    return out


def run_r(init, gates, size, rng, stop):
    """Random routing control: R_DETOUR seeded random legal single-hop
    moves of random ions before each gate, then a seeded random legal
    (mover, path) option and a seeded random cooling decision."""
    place = list(init)
    phonon = [0.0] * len(init)
    swaps = turns = cooling = 0
    exposure = 0.0
    n = len(init)
    for gate in gates:
        if stop is not None and stop():
            return empty_stats(True)
        for _t in range(R_DETOUR):
            if stop is not None and stop():
                return empty_stats(True)
            ion = int(rng.integers(n))
            occ = occ_of(place)
            cands = [c for c in nbrs(place[ion], size)
                     if occ.get(c, 0) < TRAP_CAP]
            if not cands:
                continue
            step = cands[int(rng.integers(len(cands)))]
            src = place[ion]
            if occ.get(src, 0) >= TRAP_CAP:
                phonon[ion] += HEAT_SPLIT
            occ[src] -= 1
            occ[step] = occ.get(step, 0) + 1
            phonon[ion] += HEAT_HOP
            if occ.get(step, 0) > 1:
                phonon[ion] += HEAT_MERGE
            place[ion] = step
        opts = greedy_options(size, place, phonon, gate)
        if not opts:
            return empty_stats(False)
        pick = opts[int(rng.integers(len(opts)))][0]
        cool = bool(rng.random() < 0.5)
        d = apply_choice(size, place, phonon, gate,
                         (pick[0], pick[1], cool))
        if d is None:
            return empty_stats(False)
        swaps += d["swaps"]
        turns += d["turns"]
        exposure += d["exposure"]
        cooling += d["cooling"]
    return {"infid": schedule_stats(swaps, turns, exposure, cooling,
                                   len(gates)),
            "swaps": swaps, "turns": turns, "exposure": exposure,
            "cooling": cooling, "valid": True, "stopped": False}


def run_a(init, gates, size, rng, n_iters, stop):
    """Heating-aware simulated annealing over split/merge/swap/turn
    sequences: per-gate (mover, path mode, cooling insertion) choices
    with phonon counters and cooling overhead, from the G schedule.
    Best tracked, so A never exceeds G."""
    if stop is not None and stop():
        return empty_stats(True)
    gout, gchoices = _run_g_full(init, gates, size, None)
    if gout.get("stopped") or not gout.get("valid"):
        return empty_stats(True)
    best = list(gchoices)
    best_out = gout
    cur = list(gchoices)
    cur_out = gout
    temp = A_T0
    fields = ("mover", "pmode", "cool")
    movers = ("a", "b", "swap")
    pmodes = ("short", "noturn")
    for it in range(n_iters):
        if it % 32 == 0 and stop is not None and stop():
            return empty_stats(True)
        gi = int(rng.integers(len(gates)))
        f = fields[int(rng.integers(3))]
        trial = list(cur)
        m, p, c = trial[gi]
        if f == "mover":
            m = movers[int(rng.integers(3))]
        elif f == "pmode":
            m = m
            p = pmodes[int(rng.integers(2))]
        else:
            c = not c
        trial[gi] = (m, p, c)
        out, _n = replay(init, gates, size, trial, None)
        temp *= A_ALPHA
        if not out.get("valid"):
            continue
        if (out["infid"] < cur_out["infid"] or bool(
                rng.random() < math.exp(
                    -(out["infid"] - cur_out["infid"]) / temp))):
            cur = trial
            cur_out = out
            if out["infid"] < best_out["infid"]:
                best = list(trial)
                best_out = out
    return dict(best_out, stopped=False)


def run_arm(si, ci, seed, arm, n_iters, stop):
    init = gen_init(si, ci, seed)
    gates = gen_gates(si, ci, seed)
    size = GRID_SIZES[si]
    if arm == "S":
        return run_s(init, gates, size, stop)
    if arm == "R":
        return run_r(init, gates, size,
                     seed_rng(si, ci, seed, 999), stop)
    if arm == "G":
        return run_g(init, gates, size, stop)
    return run_a(init, gates, size, seed_rng(si, ci, seed, 777),
                 n_iters, stop)


def exact_opt(init, gates, size, cap, stop):
    """Bounded-exact routing search over per-gate (mover, path mode,
    cooling) choices minimizing estimated infidelity subject to
    capacity/turn legality. Branching <= 12; illegal branches are
    skipped; partial accumulated cost is an admissible lower bound
    (all terms nonnegative), so a partial schedule at or above the
    incumbent cannot improve and is pruned; the incumbent starts at
    +infinity, which provably disables pruning until the first leaf.
    Statuses: solved / cap-hit / stopped-guard. Branch order is fixed
    (deterministic)."""
    movers = ("a", "b", "swap")
    pmodes = ("short", "noturn")
    branches = [(m, p, c) for m in movers for p in pmodes
                for c in (False, True)]
    incumbent = [None]
    best = [None]
    nodes = [0]
    capped = [False]
    stopped = [False]
    cur = []

    def rec(depth, place, phonon, swaps, turns, exposure, cooling):
        if capped[0] or stopped[0]:
            return
        nodes[0] += 1
        if nodes[0] > cap:
            capped[0] = True
            return
        if nodes[0] % 512 == 0 and stop is not None and stop():
            stopped[0] = True
            return
        if depth == len(gates):
            val = schedule_stats(swaps, turns, exposure, cooling,
                                 len(gates))
            if incumbent[0] is None or val < incumbent[0]:
                incumbent[0] = val
                best[0] = {"infid": val, "swaps": swaps,
                           "turns": turns, "exposure": exposure,
                           "cooling": cooling}
            return
        lb = schedule_stats(swaps, turns, exposure, cooling,
                            len(gates))
        if incumbent[0] is not None and lb >= incumbent[0]:
            return
        for br in branches:
            pl = list(place)
            ph = list(phonon)
            d = apply_choice(size, pl, ph, gates[depth], br)
            if d is None:
                continue
            cur.append(br)
            rec(depth + 1, pl, ph, swaps + d["swaps"],
                turns + d["turns"], exposure + d["exposure"],
                cooling + d["cooling"])
            cur.pop()
            if capped[0] or stopped[0]:
                return

    rec(0, list(init), [0.0] * len(init), 0, 0, 0.0, 0)
    if stopped[0]:
        return {"status": "stopped-guard", "nodes": nodes[0],
                "opt_infid": incumbent[0], "best": best[0],
                "cap": cap, "started": True}
    if capped[0]:
        return {"status": "cap-hit", "nodes": nodes[0],
                "opt_infid": incumbent[0], "best": best[0],
                "cap": cap, "started": True}
    return {"status": "solved", "nodes": nodes[0],
            "opt_infid": incumbent[0], "best": best[0],
            "cap": cap, "started": True}


def tiny_init():
    return list(TINY_INIT)


def tiny_gates():
    return list(TINY_GATES)


def target_init_gates():
    si = GRID_SIZES.index(TARGET["size"])
    ci = CIRCUITS.index(TARGET["circuit"])
    return (GRID_SIZES[si], gen_init(si, ci, TARGET["seed"]),
            gen_gates(si, ci, TARGET["seed"]))


def audit_gen(si, ci, seed):
    size = GRID_SIZES[si]
    n = N_IONS_PER_SIZE[si]
    init = gen_init(si, ci, seed)
    gates = gen_gates(si, ci, seed)
    cells = [(r, c) for r in range(size) for c in range(size)]
    ok = (len(init) == n and len(set(init)) == n
          and all(c in cells for c in init)
          and len(gates) == N_GATES
          and all(0 <= a < n and 0 <= b < n and a != b
                  for a, b in gates))
    return ok, init, gates


def self_tests():
    out = {"ran": True, "failed": []}
    try:
        for si in range(len(GRID_SIZES)):
            for ci in range(len(CIRCUITS)):
                for seed in (1, 2):
                    ok, _i, _g = audit_gen(si, ci, seed)
                    if not ok:
                        out["failed"].append(
                            "gen-%d-%d-%d" % (si, ci, seed))
        _ok, i1, g1 = audit_gen(0, 0, 1)
        _ok, i1b, g1b = audit_gen(0, 0, 1)
        if i1 != i1b or g1 != g1b:
            out["failed"].append("gen-determinism")
        for size in GRID_SIZES:
            cells = [(r, c) for r in range(size)
                     for c in range(size)]
            jset = junctions(size)
            for a in cells:
                for b in cells:
                    for mode in ("short", "noturn"):
                        rt = bfs_path(size, a, b, mode)
                        if rt is None:
                            out["failed"].append(
                                "unreachable-%d-%s-%s-%s"
                                % (size, a, b, mode))
                            continue
                        path, _nt = rt
                        prev = a
                        dprev = None
                        for step in path:
                            dd = (step[0] - prev[0],
                                  step[1] - prev[1])
                            if (dprev is not None and dd != dprev
                                    and prev not in jset):
                                out["failed"].append(
                                    "illegal-turn-%d-%s-%s"
                                    % (size, a, b))
                            dprev = dd
                            prev = step
        ti = tiny_init()
        tg = tiny_gates()
        if ti != list(TINY_INIT) or tg != list(TINY_GATES):
            out["failed"].append("tiny-fixture")
        ts = run_s(ti, tg, TINY_SIZE, None)
        if (not ts["valid"] or ts["stopped"]
                or ts["swaps"] != 0 or ts["turns"] != 0
                or ts["cooling"] != 0
                or ts["exposure"] != TINY_EXP_EXPOSURE
                or abs(ts["infid"] - TINY_EXP_INFID) > 1e-9):
            out["failed"].append("tiny-S-hand: %r" % (ts,))
        tgg = run_g(ti, tg, TINY_SIZE, None)
        if (not tgg["valid"] or tgg["stopped"]
                or tgg["exposure"] != TINY_EXP_EXPOSURE
                or abs(tgg["infid"] - TINY_EXP_INFID) > 1e-9):
            out["failed"].append("tiny-G-hand: %r" % (tgg,))
        ta = run_a(ti, tg, TINY_SIZE,
                   seed_rng(0, 0, 7, 777), 50, None)
        if (ta["stopped"] or not ta["valid"]
                or ta["infid"] > tgg["infid"] + 1e-12):
            out["failed"].append("tiny-A-invariant: %r" % (ta,))
        tr = run_r(ti, tg, TINY_SIZE,
                   seed_rng(0, 0, 7, 999), None)
        if tr["stopped"] or not tr["valid"]:
            out["failed"].append("tiny-R-valid: %r" % (tr,))
        dplace = [(0, 0), (1, 1), (1, 1)]
        dphon = [0.0, 0.0, 0.0]
        dd = apply_choice(3, dplace, dphon, (0, 1),
                          ("a", "short", False))
        if (dd is None or dplace[0] != (1, 1)
                or dplace[1] != (1, 1) or dplace[2] != (0, 0)):
            out["failed"].append(
                "displacement-colocation: %r %r" % (dd, dplace))
        tex = exact_opt(ti, tg, TINY_SIZE, EXACT_CAP, None)
        if (tex["status"] != "solved" or tex["best"] is None
                or abs(tex["opt_infid"] - ts["infid"]) > 1e-9):
            out["failed"].append("tiny-exact-opt: %r" % (tex,))
        for si, ci, seed in ((0, 0, 1), (2, 2, 3)):
            _ok, dag_i, dag_g = audit_gen(si, ci, seed)
            size = GRID_SIZES[si]
            for arm, fn in (
                    ("S", lambda: run_s(dag_i, dag_g, size, None)),
                    ("G", lambda: run_g(dag_i, dag_g, size, None)),
                    ("R", lambda: run_r(
                        dag_i, dag_g, size,
                        seed_rng(si, ci, seed, 999), None))):
                r = fn()
                if not r["valid"] or r["stopped"]:
                    out["failed"].append(
                        "arm-valid-%s-%d-%d-%d" % (arm, si, ci,
                                                  seed))
            ga = run_a(dag_i, dag_g, size,
                       seed_rng(si, ci, seed, 777), 50, None)
            gg = run_g(dag_i, dag_g, size, None)
            if (not ga["valid"] or ga["stopped"]
                    or ga["infid"] > gg["infid"] + 1e-12):
                out["failed"].append(
                    "a-beats-start-invariant-%d-%d-%d"
                    % (si, ci, seed))
            _ok, dag2_i, dag2_g = audit_gen(si, ci, seed)
            g1a = run_g(dag_i, dag_g, size, None)
            g1b = run_g(dag2_i, dag2_g, size, None)
            if g1a["infid"] != g1b["infid"]:
                out["failed"].append("determinism-greedy")
            r1 = run_r(dag_i, dag_g, size,
                       seed_rng(si, ci, seed, 999), None)
            r2 = run_r(dag2_i, dag2_g, size,
                       seed_rng(si, ci, seed, 999), None)
            if r1["infid"] != r2["infid"]:
                out["failed"].append("determinism-random")
        _ok, dag_i, dag_g = audit_gen(0, 0, 1)
        dag_size = GRID_SIZES[0]
        stoppers = {
            "S": lambda: run_s(dag_i, dag_g, dag_size,
                               lambda: True),
            "G": lambda: run_g(dag_i, dag_g, dag_size,
                               lambda: True),
            "R": lambda: run_r(dag_i, dag_g, dag_size,
                               seed_rng(0, 0, 1, 999),
                               lambda: True),
            "A": lambda: run_a(dag_i, dag_g, dag_size,
                               seed_rng(0, 0, 1, 777), 50,
                               lambda: True),
        }
        for arm, fn in stoppers.items():
            if not fn().get("stopped"):
                out["failed"].append("stop-propagation-%s" % arm)
        for si in range(len(GRID_SIZES)):
            for ci in range(len(CIRCUITS)):
                for seed in SEEDS:
                    size = GRID_SIZES[si]
                    _ok, sw_i, sw_g = audit_gen(si, ci, seed)
                    for arm, fn in (
                            ("S", lambda: run_s(sw_i, sw_g, size,
                                                None)),
                            ("G", lambda: run_g(sw_i, sw_g, size,
                                                None)),
                            ("R", lambda: run_r(
                                sw_i, sw_g, size,
                                seed_rng(si, ci, seed, 999), None)),
                            ("A", lambda: run_a(
                                sw_i, sw_g, size,
                                seed_rng(si, ci, seed, 777), 30,
                                None))):
                        r = fn()
                        if not r["valid"] or r["stopped"]:
                            out["failed"].append(
                                "sweep-valid-%s-%d-%d-%d"
                                % (arm, si, ci, seed))
        tsize, tinit, tgates = target_init_gates()
        stx = exact_opt(list(tinit), list(tgates), tsize,
                        EXACT_CAP, lambda: True)
        if stx["status"] != "stopped-guard":
            out["failed"].append("stop-propagation-exact: %r"
                                 % (stx,))
        toks = ["mi" + "lp", "sm" + "t", "ols" + "qa",
                "vand" + "aele", "l" + "au", "phasep" + "oly",
                "to" + "rch"]
        import pathlib as _pl
        src = _pl.Path(__file__).read_text().lower()
        for tok in toks:
            if tok in src:
                out["failed"].append("forbidden-lib-%s" % tok)
    except Exception as ex:
        out["failed"].append("raise: %r" % ex)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--attempt", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--anneal-iters", type=int, default=ANNEAL_ITERS)
    args = ap.parse_args()
    n_iters = int(args.anneal_iters)
    outdir = os.getcwd()
    witdir = os.path.join(outdir, "witnesses")
    os.makedirs(witdir, exist_ok=True)
    t0 = time.perf_counter()

    def elapsed():
        return time.perf_counter() - t0

    def over():
        return elapsed() > WALL_GUARD_S

    infids = {}
    valids = {}
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
                           "n_cells": len(cellrecs),
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
                        "iters_done": 0, "n_evaluated": EXACT_CAP})
    else:
        ex = exact_opt(list(TINY_INIT), list(TINY_GATES), TINY_SIZE,
                       EXACT_CAP, over)
        gate3tiny["arms"]["tiny"] = ex
        gate3tiny["total"] += 1
        if ex["status"] == "solved" and ex["best"] is not None \
                and abs(ex["opt_infid"] - TINY_EXP_INFID) < 1e-9:
            gate3tiny["solved"] += 1
        if ex["status"] == "stopped-guard":
            skipped.append({"what": "tiny-exact",
                            "reason": "stopped-guard",
                            "iters_done": ex.get("nodes", 0),
                            "n_evaluated": EXACT_CAP})
    with open(os.path.join(witdir, "gate3_tiny.json"), "w") as f:
        json.dump(gate3tiny, f, indent=1, default=str)
    checkpoint("tiny")

    if over():
        gate3targets.append({"status": "skipped-guard"})
        skipped.append({"what": "target-exact", "reason": "wall-guard",
                        "iters_done": 0, "n_evaluated": EXACT_CAP})
    else:
        tsize, tinit, tgates = target_init_gates()
        tex = exact_opt(list(tinit), list(tgates), tsize,
                        EXACT_CAP, over)
        gate3targets.append(dict(tex, size=tsize,
                                 circuit=TARGET["circuit"],
                                 seed=TARGET["seed"]))
        if tex["status"] == "stopped-guard":
            skipped.append({"what": "target-exact",
                            "reason": "stopped-guard",
                            "iters_done": tex.get("nodes", 0),
                            "n_evaluated": EXACT_CAP})
    with open(os.path.join(witdir, "gate3_targets.json"), "w") as f:
        json.dump(gate3targets, f, indent=1, default=str)
    checkpoint("targets")

    def run_cell(si, ci, seed):
        rec = {"size": GRID_SIZES[si], "circuit": CIRCUITS[ci],
               "seed": seed, "arms": {}}
        for arm in ARMS:
            if over():
                rec["blocked"] = "wall-guard"
                return rec
            out = run_arm(si, ci, seed, arm, n_iters, over)
            if out.get("stopped"):
                rec["blocked"] = "stopped-guard"
                rec["iters_done"] = len(rec["arms"])
                rec["n_evaluated"] = len(ARMS)
                return rec
            if not out.get("valid"):
                rec["blocked"] = "arm-invalid-%s" % arm
                rec["iters_done"] = len(rec["arms"])
                rec["n_evaluated"] = len(ARMS)
                return rec
            rec["arms"][arm] = {
                "infid": float(out["infid"]),
                "swaps": int(out["swaps"]),
                "turns": int(out["turns"]),
                "exposure": float(out["exposure"]),
                "cooling": int(out["cooling"])}
        return rec

    def record_cell(rec):
        if rec.get("blocked") is None and all(
                a in rec["arms"] for a in ARMS):
            for a in ARMS:
                key = (rec["size"], a)
                infids.setdefault(key, []).append(
                    rec["arms"][a]["infid"])
                valids.setdefault(key, []).append(1.0)
            cellrecs.append(rec)
            return True
        cellrecs.append(rec)
        skipped.append({"what": "cell %d/%s/%d" % (
            rec["size"], rec["circuit"], rec["seed"]),
            "reason": rec.get("blocked", "arm-incomplete"),
            "iters_done": rec.get("iters_done", len(rec["arms"])),
            "n_evaluated": len(ARMS)})
        return False

    for si, size in enumerate(GRID_SIZES):
        if over():
            for ci, circ in enumerate(CIRCUITS):
                for seed in SEEDS:
                    skipped.append(
                        {"what": "cell %d/%s/%d" % (
                            size, circ, seed),
                         "reason": "wall-guard", "iters_done": 0,
                         "n_evaluated": len(ARMS)})
        else:
            for ci, circ in enumerate(CIRCUITS):
                for seed in SEEDS:
                    if over():
                        skipped.append(
                            {"what": "cell %d/%s/%d" % (
                                size, circ, seed),
                             "reason": "wall-guard", "iters_done": 0,
                             "n_evaluated": len(ARMS)})
                        continue
                    rec = run_cell(si, ci, seed)
                    record_cell(rec)
        with open(os.path.join(witdir, "cells.json"), "w") as f:
            json.dump(cellrecs, f, indent=1, default=str)
        checkpoint("size%d" % size)
    with open(os.path.join(witdir, "cells.json"), "w") as f:
        json.dump(cellrecs, f, indent=1, default=str)
    checkpoint("corpus")

    def pool(size, arm, store):
        vals = store.get((size, arm), [])
        return pooled_stats(vals), len(vals) == len(CIRCUITS) * len(
            SEEDS)

    _ok, det_i, det_g = audit_gen(0, 0, 1)
    det_size = GRID_SIZES[0]
    det_g1 = run_arm(0, 0, 1, "G", n_iters, None)
    det_g2 = run_arm(0, 0, 1, "G", n_iters, None)
    det_r1 = run_arm(0, 0, 1, "R", n_iters, None)
    det_r2 = run_arm(0, 0, 1, "R", n_iters, None)
    determinism_ok = bool(
        det_g1["infid"] == det_g2["infid"]
        and det_r1["infid"] == det_r2["infid"])

    g1_cells, g1_beats = [], True
    for si, size in enumerate(GRID_SIZES):
        for ci, circ in enumerate(CIRCUITS):
            for seed in SEEDS:
                mg = next((r["arms"]["G"]["infid"] for r in cellrecs
                           if r.get("blocked") is None
                           and r["size"] == size
                           and r["circuit"] == circ
                           and r["seed"] == seed), None)
                mr = next((r["arms"]["R"]["infid"] for r in cellrecs
                           if r.get("blocked") is None
                           and r["size"] == size
                           and r["circuit"] == circ
                           and r["seed"] == seed), None)
                ok = (mg is not None and mr is not None and mg < mr)
                g1_cells.append({"cell": "%d/%s/%d" % (
                    size, circ, seed),
                    "mean_G": mg, "mean_R": mr,
                    "pass": bool(ok)})
                if not ok:
                    g1_beats = False
    g1_ok = bool(g1_beats and tiny_ok and determinism_ok)

    g2_fams, g2_n = [], 0
    win_fams = []
    n_win = {"G": 0, "A": 0}
    n_strict = 0
    pools_all = True
    for size in GRID_SIZES:
        pools, pok = {}, True
        for arm in ("S", "G", "A"):
            pools[arm], oka = pool(size, arm, infids)
            pok = pok and oka
        se, spread, gp = spread_win(pools, pok)
        g2_fams.append({"size": size, "pools": pools, "SE": se,
                        "spread": spread, "pass": bool(gp)})
        if gp:
            g2_n += 1
        joint = {}
        if pok and all(
                pools[a]["se"] is not None and
                pools[a]["mean"] is not None for a in ("S", "G",
                                                      "A")):
            sse2 = math.sqrt(sum(pools[a]["se"] ** 2
                                 for a in ("S", "G", "A")) / 3.0)
            for a in ("G", "A"):
                iwin = pools[a]["mean"] < pools["S"]["mean"] - \
                    2.0 * sse2
                vpools = pooled_stats(valids.get((size, a), []))
                vpool_s = pooled_stats(valids.get((size, "S"), []))
                vwin = (vpools["mean"] is not None
                        and vpool_s["mean"] is not None
                        and vpools["mean"] >= vpool_s["mean"])
                joint[a] = bool(iwin and vwin)
        else:
            joint = {"G": False, "A": False}
        for a in ("G", "A"):
            if joint[a]:
                n_win[a] += 1
        winner = ("G" if joint["G"]
                  else ("A" if joint["A"] else None))
        if pok and all(pools[a]["mean"] is not None
                       for a in ("S", "G", "A")):
            spass = (pools["G"]["mean"] < pools["S"]["mean"] or
                     pools["A"]["mean"] < pools["S"]["mean"])
        else:
            spass = False
            pools_all = False
        if not pok:
            pools_all = False
        if spass:
            n_strict += 1
        win_fams.append({"size": size, "joint": dict(joint),
                         "winner": winner, "strict_win": bool(spass),
                         "pools_ok": bool(pok)})
    g2_ok = g2_n >= 2

    tiny_solved = (gate3tiny["total"] == 1 and gate3tiny["solved"] == 1)
    target_cap = (len(gate3targets) == 1 and
                  gate3targets[0].get("status") == "cap-hit")
    g3pass = bool(tiny_solved and target_cap)

    nrec = sum(1 for r in cellrecs if r.get("blocked") is None)
    nexpect = len(GRID_SIZES) * len(CIRCUITS) * len(SEEDS)
    complete = (nrec == nexpect and all(
        len(infids.get((size, a), [])) == len(CIRCUITS) * len(SEEDS)
        for size in GRID_SIZES for a in ARMS))
    tiny_attempted = gate3tiny["total"] == 1
    targets_attempted = len(gate3targets) == 1
    wall = elapsed()
    clean = len(skipped) == 0
    g4_ok = bool(complete and tiny_attempted and targets_attempted and
                 wall < WALL_LIMIT_S and clean)

    selftest_ok = bool(tiny_ok)
    pursue = (max(n_win["G"], n_win["A"]) >= 2 and g1_ok and g2_ok
              and g3pass and g4_ok and selftest_ok)
    reject = (complete and tiny_solved and g1_ok and
              pools_all and n_strict == 0)
    if pursue:
        reason = "PURSUE-condition holds (joint estimated-infid " \
            "win + matched-or-better validity on the SAME arm at " \
            ">=2 trap sizes + gates 1,2,3,4 + self-tests ok); " \
            "payload verdict stays unresolved-with-reason, " \
            "classification is coordinator-side."
    elif reject:
        reason = "REJECT-condition holds (complete cells, tiny " \
            "solved, Gate-1 controls pass, no strict pooled infid " \
            "win at any size); payload verdict stays " \
            "unresolved-with-reason, classification is coordinator-side."
    else:
        reason = "UNRESOLVED + next experiment (joint wins G=%d/3, " \
            "A=%d/3, strict wins=%d/3, g1=%s g2=%s " \
            "g3=%s (tiny solved=%s, target " \
            "cap-hit=%s) selftest=%s g4=%s complete=%s skipped=%d; " \
            "next: %s)." % (
                n_win["G"], n_win["A"], n_strict, g1_ok, g2_ok,
                g3pass, tiny_solved, target_cap,
                selftest_ok, g4_ok, complete, len(skipped),
                NEXT_EXPERIMENT)
    verdict_bits = {
        "gate1": {"pass": bool(g1_ok), "beats_all_45": bool(g1_beats),
                  "tiny_ok": bool(tiny_ok),
                  "determinism_ok": bool(determinism_ok),
                  "cells": g1_cells},
        "gate2": {"pass": bool(g2_ok), "n_sizes_pass": g2_n,
                  "sizes": g2_fams},
        "gate3": {"pass": bool(g3pass), "tiny_solved": tiny_solved,
                  "tiny": gate3tiny,
                  "targets": gate3targets, "target_cap": target_cap},
        "gate4": {"pass": bool(g4_ok), "complete": bool(complete),
                  "tiny_attempted": bool(tiny_attempted),
                  "targets_attempted": bool(targets_attempted),
                  "wall_sec": wall, "clean": bool(clean)},
        "acceptance": {"pursue_condition": bool(pursue),
                       "reject_condition": bool(reject),
                       "n_win_G": n_win["G"], "n_win_A": n_win["A"],
                       "win_sizes": win_fams, "n_strict_win": n_strict,
                       "pools_all": bool(pools_all),
                       "selftest_ok": bool(selftest_ok)},
        "reason": reason,
    }

    results = {
        "screen": "11",
        "verdict": "unresolved-with-reason: payload reports numbers "
                   "and gate evidence; classification is coordinator-side.",
        "design": {
            "model": "screen-authored deterministic QCCD junction "
                     "shuttling model (stdlib + numpy only; "
                     "no external libs)",
            "grids": ["3x3 (4 ions)", "4x4 (6 ions)", "5x5 (8 ions)"],
            "circuits": list(CIRCUITS),
            "gates_per_circuit": N_GATES,
            "seeds": list(SEEDS),
            "cells": "3 sizes x 3 circuits x 5 seeds = 45 cells x 4 "
                     "arms (180 evaluations; seeds are replicates)",
            "junctions": "X-junction trunk cross (middle row + "
                         "middle column); turns legal only at trunk "
                         "cells, straight shuttling anywhere",
            "capacity": "TRAP_CAP = %d ions per site; full-target "
                        "displacement to the first free site keeps "
                        "every schedule valid" % TRAP_CAP,
            "phonon": "per-ion counters: HEAT_HOP/HEAT_TURN/HEAT_SPLIT/"
                      "HEAT_MERGE/HEAT_SWAP per event; exposure = "
                      "phonon pair-sum at each gate; cooling resets "
                      "the pair at W_COOL per round",
            "infidelity": "frozen function W_SWAP*swaps + W_TURN*turns "
                          "+ W_HEAT*exposure + W_COOL*cooling + "
                          "W_GATE*gates",
            "cooling_rule": "S never cools; R cools per seeded draw; "
                            "G cools the pair when post-gate phonon "
                            "exceeds COOL_THRESHOLD; A anneals cooling "
                            "insertion per gate",
            "anneal": {"iters": n_iters, "t0": A_T0,
                       "alpha": A_ALPHA},
            "detours": {"R_DETOUR": R_DETOUR},
            "arms": {"S": "shortest-path/swap-count-only baseline: "
                          "always shuttle the first ion via the "
                          "shortest turn-legal path, never cool",
                     "R": "random routing control: seeded random "
                          "detours + random legal mover/path/cooling",
                     "G": "greedy distance routing: per-gate "
                          "minimum-heat legal option + threshold "
                          "cooling",
                     "A": "heating-aware annealing over per-gate "
                          "mover/path/cooling (split/merge/swap/turn "
                          "sequences) from G, best tracked"},
            "metrics": "estimated circuit infidelity (frozen function "
                       "of swap count + junction turns + phonon bursts "
                       "+ cooling rounds) + schedule validity "
                       "(capacity/turn legality)",
            "pareto": "PURSUE needs an estimated-infidelity win + "
                      "matched-or-better validity on the SAME arm; "
                      "joint wins counted PER ARM with bar "
                      "max(G,A)>=2, never any-winner",
            "exact": "bounded-exact routing search on tiny (2x2, "
                     "1 gate, must solve, optimum infid %s) "
                     "+ target-scale instance (5x5, ring, "
                     "seed 1, node cap %d, must cap-hit)" % (
                         TINY_EXP_INFID, EXACT_CAP),
        },
        "timing": {"wall_s": wall, "guards": {"wall_guard_s": WALL_GUARD_S,
                                              "limit_s": WALL_LIMIT_S}},
        "cells": {("%d/%s/%d/%s" % (r["size"], r["circuit"], r["seed"],
                                      a)): {"infid": r["arms"][a][
                                          "infid"],
                                      "swaps": r["arms"][a]["swaps"],
                                      "turns": r["arms"][a]["turns"],
                                      "exposure": r["arms"][a][
                                          "exposure"],
                                      "cooling": r["arms"][a][
                                          "cooling"]}
                  for r in cellrecs if r.get("blocked") is None
                  for a in ARMS},
        "pools": {("%d/%s" % (size, a)): {
            **pooled_stats(infids.get((size, a), [])),
            "mean_valid": pooled_stats(
                valids.get((size, a), []))["mean"]}
            for size in GRID_SIZES for a in ARMS},
        "gates": verdict_bits,
        "skipped": skipped,
    }
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)


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
    if ok and all(pools[k]["se"] is not None for k in keys):
        se = math.sqrt(sum(pools[k]["se"] ** 2 for k in keys)
                       / len(keys))
        means = [pools[k]["mean"] for k in keys]
        spread = max(means) - min(means)
        return se, spread, spread > 2.0 * se
    return None, None, False


if __name__ == "__main__":
    main()
