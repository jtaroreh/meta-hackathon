"""Screen 09 payload: defect-tolerant surface-code compilation around
fabrication dropouts.

Screen-authored deterministic defect-patch model (stdlib + numpy only;
no external physics, solver, or policy libraries): fixed 2D
superconducting grids with seeded random fabrication-dropout masks
(2%/4% rates); super-plaquette gauge-fixing frozen rule (each dead
data qubit merges adjacent stabilizers; each dead cell edge-adjacent
to a patch costs one extra syndrome round); logical patch = connected
set of live data qubits with effective distance >= 2 verified by
screen-authored exact shortest-path enumeration (BFS between opposite
extent edges, no external solver). Arms: B bounding-box defect
exclusion (naive shave-to-clean-rectangle baseline), R random
deformed-patch control (seeded boundary-notched full-live patch), G
greedy irregular patch routing (shrink-to-improve + single-cell
hill-climb from B under a distance floor), A simulated annealing over
boundary allocation from the G patch (best tracked, so A never exceeds
G). Metric: logical spacetime volume (patch area x rounds under frozen
rules) + effective code distance verification. A bounded-exact subset
search validates the tiny instance (solved, optimum by enumeration)
and cap-hits at target scale (limit-expiry). Writes ALL output under
cwd (the attempt work dir): results.json + witnesses/. Deterministic
given seeds. Verdict is always unresolved-with-reason; classification
is coordinator-side.
"""

import argparse
import json
import math
import os
import time

import numpy as np

GRID_SIZES = (7, 9, 11)
DROPOUT_RATES = (0.02, 0.04)
SEEDS = (1, 2, 3, 4, 5)
ARMS = ("B", "R", "G", "A")

ANNEAL_ITERS = 300
A_T0 = 1.0
A_ALPHA = 0.99
NOTCH_ATTEMPTS = 6
GREEDY_SHRINK_SWEEPS = 3
GREEDY_ANNEX_SWEEPS = 2

WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0
EXACT_CAP = 50000

TINY_SIZE = 3
TINY_DEAD = ((0, 0),)
TINY_EXP_OPT = 6
TINY_EXP = {"B": (18, 2), "G": (6, 2)}

TARGET = {"size": 9, "rate": 0.04, "seed": 1}


def seed_rng(si, ri, seed, salt):
    return np.random.default_rng(
        (int(si * 100003 + ri * 17011 + seed * 10007
             + salt * 1000003) % (2 ** 63 - 1)))


def dropout_count(size, rate):
    return max(1, int(round(rate * size * size)))


def gen_mask(si, ri, seed):
    """Seeded fabrication-dropout mask: k distinct dead data qubits."""
    size = GRID_SIZES[si]
    rate = DROPOUT_RATES[ri]
    k = dropout_count(size, rate)
    rng = seed_rng(si, ri, seed, 11)
    cells = rng.choice(size * size, size=k, replace=False)
    dead = frozenset((int(c // size), int(c % size)) for c in cells)
    return {"size": size, "rate": rate, "seed": seed, "dead": dead,
            "k": k}


def all_cells(size):
    return [(r, c) for r in range(size) for c in range(size)]


def nbrs(cell, size):
    r, c = cell
    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < size and 0 <= nc < size:
            yield (nr, nc)


def bfs_steps(size, cells, sources, targets):
    """Shortest 4-neighborhood path length (edges) within cells from any
    source to any target; None if unreachable or either set is empty."""
    if not sources or not targets:
        return None
    if sources & targets:
        return 0
    seen = set(sources)
    frontier = list(sources)
    dist = 0
    while frontier:
        dist += 1
        nxt = []
        for u in frontier:
            for v in nbrs(u, size):
                if v in cells and v not in seen:
                    if v in targets:
                        return dist
                    seen.add(v)
                    nxt.append(v)
        frontier = nxt
    return None


def patch_stats(cells, dead, size):
    """Validity + metric for a logical patch under frozen rules.

    Valid iff connected (4-neighborhood), contains no dead cell, and
    effective distance >= 2, where dX/dZ are the exact shortest live
    paths (BFS, steps + 1 = cells along the operator) between the
    patch's own north/south and west/east extent edges. Rounds =
    d_eff + n_adj_dead (frozen super-plaquette gauge-fixing rule: one
    extra round per neighboring dead data qubit). Volume = area x
    rounds. Single cells and single-row/col strips have d_eff < 2 and
    are invalid by construction.
    """
    cells = set(cells)
    if not cells or (cells & set(dead)):
        return {"valid": False, "area": len(cells), "dist": 0,
                "rounds": None, "volume": None}
    start = next(iter(cells))
    seen = {start}
    frontier = [start]
    while frontier:
        nxt = []
        for u in frontier:
            for v in nbrs(u, size):
                if v in cells and v not in seen:
                    seen.add(v)
                    nxt.append(v)
        frontier = nxt
    if len(seen) != len(cells):
        return {"valid": False, "area": len(cells), "dist": 0,
                "rounds": None, "volume": None}
    rs = [r for r, _ in cells]
    cs = [c for _, c in cells]
    r0, r1, c0, c1 = min(rs), max(rs), min(cs), max(cs)
    north = {cell for cell in cells if cell[0] == r0}
    south = {cell for cell in cells if cell[0] == r1}
    west = {cell for cell in cells if cell[1] == c0}
    east = {cell for cell in cells if cell[1] == c1}
    sx = bfs_steps(size, cells, north, south)
    sz = bfs_steps(size, cells, west, east)
    if sx is None or sz is None:
        return {"valid": False, "area": len(cells), "dist": 0,
                "rounds": None, "volume": None}
    dist = min(sx, sz) + 1
    if dist < 2:
        return {"valid": False, "area": len(cells), "dist": int(dist),
                "rounds": None, "volume": None}
    adj = 0
    for d in dead:
        for v in nbrs(d, size):
            if v in cells:
                adj += 1
                break
    rounds = int(dist) + int(adj)
    return {"valid": True, "area": len(cells), "dist": int(dist),
            "rounds": rounds, "volume": len(cells) * rounds,
            "n_adj_dead": int(adj)}


def empty_result(stopped):
    return {"volume": None, "area": None, "dist": None,
            "rounds": None, "valid": False, "stopped": bool(stopped)}


def run_b(mask, stop):
    """Bounding-box defect exclusion baseline: naive deterministic
    shave-to-clean-rectangle. While a dead cell lies inside the box,
    remove the row/column with the most dead cells (ties: rows before
    columns, then smaller index); an interior removal splits the box
    and the larger piece is kept (ties: smaller r0, then smaller c0).
    Terminates with a defect-free rectangle."""
    size = mask["size"]
    dead = set(mask["dead"])
    if stop is not None and stop():
        return empty_result(True)
    r0, r1, c0, c1 = 0, size - 1, 0, size - 1
    while True:
        inside = [(r, c) for (r, c) in dead
                  if r0 <= r <= r1 and c0 <= c <= c1]
        if not inside:
            break
        rows = {}
        cols = {}
        for (r, c) in inside:
            rows[r] = rows.get(r, 0) + 1
            cols[c] = cols.get(c, 0) + 1
        best_row = max(rows, key=lambda r: (rows[r], -r))
        best_col = max(cols, key=lambda c: (cols[c], -c))
        if rows[best_row] >= cols[best_col]:
            kill = ("row", best_row)
        else:
            kill = ("col", best_col)
        if kill[0] == "row":
            k = kill[1]
            if k == r0:
                r0 += 1
            elif k == r1:
                r1 -= 1
            else:
                top = (k - r0) * (c1 - c0 + 1)
                bot = (r1 - k) * (c1 - c0 + 1)
                if top > bot:
                    r1 = k - 1
                elif bot > top:
                    r0 = k + 1
                else:
                    r1 = k - 1
        else:
            k = kill[1]
            if k == c0:
                c0 += 1
            elif k == c1:
                c1 -= 1
            else:
                left = (k - c0) * (r1 - r0 + 1)
                right = (c1 - k) * (r1 - r0 + 1)
                if left > right:
                    c1 = k - 1
                elif right > left:
                    c0 = k + 1
                else:
                    c1 = k - 1
    cells = {(r, c) for r in range(r0, r1 + 1)
             for c in range(c0, c1 + 1)}
    st = patch_stats(cells, dead, size)
    return {"volume": st["volume"], "area": st["area"],
            "dist": st["dist"], "rounds": st["rounds"],
            "valid": bool(st["valid"]), "stopped": False,
            "box": [r0, r1, c0, c1]}


def largest_component(cells, size):
    """Largest 4-connected component (ties: smallest first cell in
    row-major order, so the repair is deterministic)."""
    remaining = set(cells)
    best = set()
    while remaining:
        start = min(remaining)
        seen = {start}
        frontier = [start]
        while frontier:
            nxt = []
            for u in frontier:
                for v in nbrs(u, size):
                    if v in remaining and v not in seen:
                        seen.add(v)
                        nxt.append(v)
            frontier = nxt
        if (len(seen) > len(best)
                or (len(seen) == len(best)
                    and min(seen) < (min(best) if best else None))):
            best = set(seen)
        remaining -= seen
    return best


def run_r(mask, rng, stop):
    """Random deformed-patch control: seeded random boundary notches
    carved from the full live grid. Each of NOTCH_ATTEMPTS proposals
    picks a seeded side/position/width/depth and removes those live
    cells; a proposal that breaks validity is undone. A trailing
    largest-component repair plus a B fallback keep R always valid."""
    size = mask["size"]
    dead = set(mask["dead"])
    if stop is not None and stop():
        return empty_result(True)
    cur = {(r, c) for r in range(size) for c in range(size)} - dead
    for t in range(NOTCH_ATTEMPTS):
        if stop is not None and stop():
            return empty_result(True)
        side = int(rng.integers(4))
        width = int(rng.integers(1, 4))
        depth = int(rng.integers(1, 3))
        if side == 0:
            base = int(rng.integers(size))
            cut = {(r, c) for r in range(0, depth)
                   for c in range(base, min(size, base + width))}
        elif side == 1:
            base = int(rng.integers(size))
            cut = {(r, c) for r in range(size - depth, size)
                   for c in range(base, min(size, base + width))}
        elif side == 2:
            base = int(rng.integers(size))
            cut = {(r, c) for r in range(base, min(size, base + width))
                   for c in range(0, depth)}
        else:
            base = int(rng.integers(size))
            cut = {(r, c) for r in range(base, min(size, base + width))
                   for c in range(size - depth, size)}
        trial = cur - cut
        if patch_stats(trial, dead, size)["valid"]:
            cur = trial
    if not patch_stats(cur, dead, size)["valid"]:
        cur = largest_component(cur, size)
    st = patch_stats(cur, dead, size)
    if not st["valid"]:
        return dict(run_b(mask, stop), arm_note="r-fallback-b")
    return {"volume": st["volume"], "area": st["area"],
            "dist": st["dist"], "rounds": st["rounds"],
            "valid": True, "stopped": False}


def extent_of(cells):
    rs = [r for r, _ in cells]
    cs = [c for _, c in cells]
    return min(rs), max(rs), min(cs), max(cs)


def _run_g_full(mask, d_floor, stop):
    """Greedy irregular patch routing from the B rectangle under a
    distance floor (d >= d_floor, so G never degrades B's distance).
    Phase 1: shrink-to-improve sweeps over the four extent sides
    (accept iff valid, floor kept, volume strictly decreases).
    Phase 2: irregular single-cell hill-climb in row-major order
    (annex an adjacent live cell, or remove any cell; same accept
    rule). First-improvement; strictly decreasing volume, so G never
    exceeds B's volume. Returns (result, patch_cells)."""
    size = mask["size"]
    dead = set(mask["dead"])
    if stop is not None and stop():
        return empty_result(True), set()
    b = run_b(mask, None)
    cur = {(r, c) for r in range(b["box"][0], b["box"][1] + 1)
           for c in range(b["box"][2], b["box"][3] + 1)}
    cur_st = patch_stats(cur, dead, size)
    evals = [0]

    def consider(trial):
        evals[0] += 1
        if evals[0] % 32 == 0 and stop is not None and stop():
            return "stop"
        st = patch_stats(trial, dead, size)
        if (st["valid"] and st["dist"] >= d_floor
                and st["volume"] < cur_st["volume"]):
            return st
        return None

    for _ in range(GREEDY_SHRINK_SWEEPS):
        if stop is not None and stop():
            return empty_result(True), set()
        r0, r1, c0, c1 = extent_of(cur)
        moved = False
        for side in ("top", "bottom", "left", "right"):
            if side == "top":
                cut = {(r0, c) for c in range(c0, c1 + 1)}
            elif side == "bottom":
                cut = {(r1, c) for c in range(c0, c1 + 1)}
            elif side == "left":
                cut = {(r, c0) for r in range(r0, r1 + 1)}
            else:
                cut = {(r, c1) for r in range(r0, r1 + 1)}
            trial = cur - cut
            if not trial:
                continue
            out = consider(trial)
            if out == "stop":
                return empty_result(True), set()
            if out is not None:
                cur = trial
                cur_st = out
                moved = True
                r0, r1, c0, c1 = extent_of(cur)
        if not moved:
            break
    for _ in range(GREEDY_ANNEX_SWEEPS):
        if stop is not None and stop():
            return empty_result(True), set()
        moved = False
        for cell in all_cells(size):
            if cell in dead:
                continue
            if cell in cur:
                trial = cur - {cell}
            else:
                if not any(v in cur for v in nbrs(cell, size)):
                    continue
                trial = cur | {cell}
            if not trial:
                continue
            out = consider(trial)
            if out == "stop":
                return empty_result(True), set()
            if out is not None:
                cur = trial
                cur_st = out
                moved = True
        if not moved:
            break
    return ({"volume": cur_st["volume"], "area": cur_st["area"],
             "dist": cur_st["dist"], "rounds": cur_st["rounds"],
             "valid": True, "stopped": False}, cur)


def run_g(mask, d_floor, stop):
    out, _cells = _run_g_full(mask, d_floor, stop)
    return out


def run_arm(si, ri, seed, arm, n_iters, stop):
    mask = gen_mask(si, ri, seed)
    if arm == "B":
        return run_b(mask, stop), mask
    if arm == "R":
        return run_r(mask, seed_rng(si, ri, seed, 999), stop), mask
    b = run_b(mask, None)
    gout, gcells = _run_g_full(mask, b["dist"], stop)
    if gout.get("stopped"):
        return gout, mask
    if arm == "G":
        return gout, mask
    if stop is not None and stop():
        return empty_result(True), mask
    return (run_a(mask, gcells, b["dist"],
                  seed_rng(si, ri, seed, 777), n_iters, stop),
            mask)


def run_a(mask, start_cells, d_floor, rng, n_iters, stop):
    """Simulated annealing over boundary allocation from the G patch:
    single-cell flips plus full-extent-side shave/annex moves, every
    proposal validity-checked with the distance floor enforced
    (violations are rejected, never annealed through), cost = spacetime
    volume. Best tracked, so A never exceeds G."""
    size = mask["size"]
    dead = set(mask["dead"])
    if stop is not None and stop():
        return empty_result(True)
    cur = set(start_cells)
    cur_st = patch_stats(cur, dead, size)
    best = set(cur)
    best_st = dict(cur_st)
    temp = A_T0
    for it in range(n_iters):
        if it % 32 == 0 and stop is not None and stop():
            return empty_result(True)
        if bool(rng.random() < 0.5):
            cell = (int(rng.integers(size)), int(rng.integers(size)))
            if cell in dead:
                temp *= A_ALPHA
                continue
            if cell in cur:
                trial = cur - {cell}
            else:
                if not any(v in cur for v in nbrs(cell, size)):
                    temp *= A_ALPHA
                    continue
                trial = cur | {cell}
        else:
            r0, r1, c0, c1 = extent_of(cur)
            side = int(rng.integers(4))
            grow = bool(rng.random() < 0.5)
            if side == 0:
                line = {(r0 - 1, c) for c in range(c0, c1 + 1)
                        if 0 <= r0 - 1 < size}
                edge = {(r0, c) for c in range(c0, c1 + 1)}
            elif side == 1:
                line = {(r1 + 1, c) for c in range(c0, c1 + 1)
                        if 0 <= r1 + 1 < size}
                edge = {(r1, c) for c in range(c0, c1 + 1)}
            elif side == 2:
                line = {(r, c0 - 1) for r in range(r0, r1 + 1)
                        if 0 <= c0 - 1 < size}
                edge = {(r, c0) for r in range(r0, r1 + 1)}
            else:
                line = {(r, c1 + 1) for r in range(r0, r1 + 1)
                        if 0 <= c1 + 1 < size}
                edge = {(r, c1) for r in range(r0, r1 + 1)}
            if grow:
                trial = cur | ({c for c in line if c not in dead}
                               or set())
                if trial == cur:
                    temp *= A_ALPHA
                    continue
            else:
                trial = cur - edge
                if not trial:
                    temp *= A_ALPHA
                    continue
        st = patch_stats(trial, dead, size)
        if not st["valid"] or st["dist"] < d_floor:
            temp *= A_ALPHA
            continue
        if (st["volume"] < cur_st["volume"] or bool(
                rng.random() < math.exp(
                    -(st["volume"] - cur_st["volume"]) / temp))):
            cur = trial
            cur_st = st
            if st["volume"] < best_st["volume"]:
                best = set(trial)
                best_st = dict(st)
        temp *= A_ALPHA
    return {"volume": best_st["volume"], "area": best_st["area"],
            "dist": best_st["dist"], "rounds": best_st["rounds"],
            "valid": True, "stopped": False}


def exact_opt(live_order, dead, size, cap, stop):
    """Bounded-exact subset search over patch configurations minimizing
    spacetime volume subject to validity (connected, defect-free,
    d_eff >= 2). Incumbent-tracked branch-and-bound: a partial
    assignment with area_so_far >= incumbent cannot improve (final
    volume >= final area >= area_so_far, since rounds >= 1), so it is
    pruned; the incumbent starts at +infinity, which provably disables
    pruning until the first leaf. Statuses: solved / cap-hit /
    stopped-guard. Cell order is fixed (row-major live cells)."""
    dead = set(dead)
    order = list(live_order)
    incumbent = [None]
    best = [None]
    nodes = [0]
    capped = [False]
    stopped = [False]
    chosen = []

    def rec(k, area):
        if capped[0] or stopped[0]:
            return
        nodes[0] += 1
        if nodes[0] > cap:
            capped[0] = True
            return
        if nodes[0] % 512 == 0 and stop is not None and stop():
            stopped[0] = True
            return
        if incumbent[0] is not None and area >= incumbent[0]:
            return
        if k == len(order):
            st = patch_stats(chosen, dead, size)
            if st["valid"] and (incumbent[0] is None
                                or st["volume"] < incumbent[0]):
                incumbent[0] = st["volume"]
                best[0] = {"volume": st["volume"], "area": st["area"],
                           "dist": st["dist"], "rounds": st["rounds"]}
            return
        chosen.append(order[k])
        rec(k + 1, area + 1)
        chosen.pop()
        if capped[0] or stopped[0]:
            return
        rec(k + 1, area)

    rec(0, 0)
    if stopped[0]:
        return {"status": "stopped-guard", "nodes": nodes[0],
                "opt_volume": incumbent[0], "best": best[0],
                "cap": cap, "started": True}
    if capped[0]:
        return {"status": "cap-hit", "nodes": nodes[0],
                "opt_volume": incumbent[0], "best": best[0],
                "cap": cap, "started": True}
    return {"status": "solved", "nodes": nodes[0],
            "opt_volume": incumbent[0], "best": best[0],
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


def tiny_mask():
    return {"size": TINY_SIZE, "rate": None, "seed": 0,
            "dead": frozenset(TINY_DEAD),
            "k": len(TINY_DEAD)}


def tiny_live_order():
    size = TINY_SIZE
    dead = set(TINY_DEAD)
    return [(r, c) for r in range(size) for c in range(size)
            if (r, c) not in dead]


def target_mask():
    si = GRID_SIZES.index(TARGET["size"])
    ri = list(DROPOUT_RATES).index(TARGET["rate"])
    return gen_mask(si, ri, TARGET["seed"])


def audit_mask(si, ri, seed):
    m = gen_mask(si, ri, seed)
    size = GRID_SIZES[si]
    k = dropout_count(size, DROPOUT_RATES[ri])
    return (len(m["dead"]) == k
            and all(0 <= r < size and 0 <= c < size
                    for r, c in m["dead"])), m


def self_tests():
    out = {"ran": True, "failed": []}
    try:
        for si in range(len(GRID_SIZES)):
            for ri in range(len(DROPOUT_RATES)):
                for seed in (1, 2):
                    ok, _m = audit_mask(si, ri, seed)
                    if not ok:
                        out["failed"].append(
                            "mask-%d-%d-%d" % (si, ri, seed))
        _ok, m1 = audit_mask(0, 0, 1)
        _ok2, m1b = audit_mask(0, 0, 1)
        if m1["dead"] != m1b["dead"]:
            out["failed"].append("mask-determinism")
        tm = tiny_mask()
        if set(tm["dead"]) != {(0, 0)}:
            out["failed"].append("tiny-mask")
        tb = run_b(tm, None)
        if ((tb["volume"], tb["dist"]) != TINY_EXP["B"]
                or not tb["valid"] or tb["stopped"]):
            out["failed"].append("tiny-B-hand: %r" % (tb,))
        tg = run_g(tm, tb["dist"], None)
        if ((tg["volume"], tg["dist"]) != TINY_EXP["G"]
                or not tg["valid"] or tg["stopped"]):
            out["failed"].append("tiny-G-hand: %r" % (tg,))
        ta = run_a(tm, {(r, c) for r in range(1, 3)
                        for c in range(1, 3)}, tb["dist"],
                   seed_rng(0, 0, 7, 777), 50, None)
        if (ta["stopped"] or not ta["valid"]
                or ta["dist"] < tb["dist"]
                or ta["volume"] > tg["volume"]):
            out["failed"].append("tiny-A-invariant: %r" % (ta,))
        tex = exact_opt(tiny_live_order(), tm["dead"], TINY_SIZE,
                        EXACT_CAP, None)
        if (tex["status"] != "solved"
                or tex["opt_volume"] != TINY_EXP_OPT):
            out["failed"].append("tiny-exact-opt: %r" % (tex,))
        full = {(r, c) for r in range(TINY_SIZE)
                for c in range(TINY_SIZE)} - set(tm["dead"])
        st_full = patch_stats(full, tm["dead"], TINY_SIZE)
        if not st_full["valid"] or st_full["dist"] != 3:
            out["failed"].append("dist-full-tiny: %r" % (st_full,))
        if patch_stats({(0, 1)}, tm["dead"], TINY_SIZE)["valid"]:
            out["failed"].append("single-cell-blind")
        if patch_stats({(0, 1), (0, 2)}, tm["dead"],
                       TINY_SIZE)["valid"]:
            out["failed"].append("strip-blind")
        if patch_stats({(0, 1), (2, 2)}, tm["dead"],
                       TINY_SIZE)["valid"]:
            out["failed"].append("disconnected-blind")
        if patch_stats({(0, 0), (0, 1), (1, 0)}, tm["dead"],
                       TINY_SIZE)["valid"]:
            out["failed"].append("dead-inside-blind")
        for si, ri, seed in ((0, 0, 1), (2, 1, 3)):
            _ok, dag = audit_mask(si, ri, seed)
            for arm, fn in (
                    ("B", lambda: run_b(dag, None)),
                    ("G", lambda: run_g(
                        dag, run_b(dag, None)["dist"], None)),
                    ("R", lambda: run_r(
                        dag, seed_rng(si, ri, seed, 999), None))):
                r = fn()
                if not r["valid"] or r["stopped"]:
                    out["failed"].append(
                        "arm-valid-%s-%d-%d-%d" % (arm, si, ri, seed))
            gb = run_b(dag, None)
            gg = run_g(dag, gb["dist"], None)
            if (not gg["valid"] or gg["dist"] < gb["dist"]
                    or gg["volume"] > gb["volume"]):
                out["failed"].append(
                    "g-beats-b-invariant-%d-%d-%d" % (si, ri, seed))
            ga = run_a(dag, {(r, c)
                             for r in range(gb["box"][0],
                                            gb["box"][1] + 1)
                             for c in range(gb["box"][2],
                                            gb["box"][3] + 1)},
                       gb["dist"], seed_rng(si, ri, seed, 777), 50,
                       None)
            if (not ga["valid"] or ga["volume"] > gb["volume"]
                    or ga["dist"] < gb["dist"]):
                out["failed"].append(
                    "a-beats-start-invariant-%d-%d-%d" % (si, ri, seed))
        _ok, dag = audit_mask(0, 0, 1)
        gb = run_b(dag, None)
        g1 = run_g(dag, gb["dist"], None)
        g2 = run_g(dag, gb["dist"], None)
        if (g1["volume"], g1["dist"]) != (g2["volume"], g2["dist"]):
            out["failed"].append("determinism-greedy")
        r1 = run_r(dag, seed_rng(0, 0, 1, 999), None)
        r2 = run_r(dag, seed_rng(0, 0, 1, 999), None)
        if (r1["volume"], r1["dist"]) != (r2["volume"], r2["dist"]):
            out["failed"].append("determinism-random")
        for arm in ("B", "R", "G", "A"):
            if arm == "B":
                s = run_b(dag, lambda: True)
            elif arm == "R":
                s = run_r(dag, seed_rng(0, 0, 1, 999),
                          lambda: True)
            elif arm == "G":
                s = run_g(dag, gb["dist"], lambda: True)
            else:
                s = run_a(dag, {(r, c) for r in range(3)
                                for c in range(3)
                                if (r, c) not in dag["dead"]},
                          gb["dist"], seed_rng(0, 0, 1, 777), 50,
                          lambda: True)
            if not s.get("stopped"):
                out["failed"].append("stop-propagation-%s" % arm)
        tmask = target_mask()
        tlive = [(r, c) for r in range(tmask["size"])
                 for c in range(tmask["size"])
                 if (r, c) not in tmask["dead"]]
        stx = exact_opt(tlive, tmask["dead"], tmask["size"],
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

    volumes = {}
    dists = {}
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
        ex = exact_opt(tiny_live_order(), tiny_mask()["dead"],
                       TINY_SIZE, EXACT_CAP, over)
        gate3tiny["arms"]["tiny"] = ex
        gate3tiny["total"] += 1
        if ex["status"] == "solved" and ex["opt_volume"] == \
                TINY_EXP_OPT:
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
        tmask = target_mask()
        tlive = [(r, c) for r in range(tmask["size"])
                 for c in range(tmask["size"])
                 if (r, c) not in tmask["dead"]]
        tex = exact_opt(tlive, tmask["dead"], tmask["size"],
                        EXACT_CAP, over)
        gate3targets.append(dict(tex, size=tmask["size"],
                                 rate=tmask["rate"], seed=tmask["seed"]))
        if tex["status"] == "stopped-guard":
            skipped.append({"what": "target-exact",
                            "reason": "stopped-guard",
                            "iters_done": tex.get("nodes", 0),
                            "n_evaluated": EXACT_CAP})
    with open(os.path.join(witdir, "gate3_targets.json"), "w") as f:
        json.dump(gate3targets, f, indent=1, default=str)
    checkpoint("targets")

    def run_cell(si, ri, seed):
        rec = {"size": GRID_SIZES[si], "rate": DROPOUT_RATES[ri],
               "seed": seed, "arms": {}}
        for arm in ARMS:
            if over():
                rec["blocked"] = "wall-guard"
                return rec
            out, _mask = run_arm(si, ri, seed, arm, n_iters, over)
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
                "volume": int(out["volume"]),
                "area": int(out["area"]),
                "dist": int(out["dist"]),
                "rounds": int(out["rounds"])}
        return rec

    def record_cell(rec):
        if rec.get("blocked") is None and all(
                a in rec["arms"] for a in ARMS):
            for a in ARMS:
                key = (rec["size"], a)
                volumes.setdefault(key, []).append(
                    rec["arms"][a]["volume"])
                dists.setdefault(key, []).append(
                    rec["arms"][a]["dist"])
            cellrecs.append(rec)
            return True
        cellrecs.append(rec)
        skipped.append({"what": "cell %d/%.2f/%d" % (
            rec["size"], rec["rate"], rec["seed"]),
            "reason": rec.get("blocked", "arm-incomplete"),
            "iters_done": rec.get("iters_done", len(rec["arms"])),
            "n_evaluated": len(ARMS)})
        return False

    for si, size in enumerate(GRID_SIZES):
        if over():
            for ri, rate in enumerate(DROPOUT_RATES):
                for seed in SEEDS:
                    skipped.append(
                        {"what": "cell %d/%.2f/%d" % (
                            size, rate, seed),
                         "reason": "wall-guard", "iters_done": 0,
                         "n_evaluated": len(ARMS)})
        else:
            for ri, rate in enumerate(DROPOUT_RATES):
                for seed in SEEDS:
                    if over():
                        skipped.append(
                            {"what": "cell %d/%.2f/%d" % (
                                size, rate, seed),
                             "reason": "wall-guard", "iters_done": 0,
                             "n_evaluated": len(ARMS)})
                        continue
                    rec = run_cell(si, ri, seed)
                    record_cell(rec)
        with open(os.path.join(witdir, "cells.json"), "w") as f:
            json.dump(cellrecs, f, indent=1, default=str)
        checkpoint("size%d" % size)
    with open(os.path.join(witdir, "cells.json"), "w") as f:
        json.dump(cellrecs, f, indent=1, default=str)
    checkpoint("corpus")

    def pool(size, arm, store):
        vals = store.get((size, arm), [])
        return pooled_stats(vals), len(vals) == 2 * len(SEEDS)

    _ok, det_mask = audit_mask(0, 0, 1)
    det_b = run_b(det_mask, None)
    det_g1, _m = run_arm(0, 0, 1, "G", n_iters, None)
    det_g2, _m = run_arm(0, 0, 1, "G", n_iters, None)
    det_r1, _m = run_arm(0, 0, 1, "R", n_iters, None)
    det_r2, _m = run_arm(0, 0, 1, "R", n_iters, None)
    determinism_ok = bool(
        (det_g1["volume"], det_g1["dist"]) == (
            det_g2["volume"], det_g2["dist"])
        and (det_r1["volume"], det_r1["dist"]) == (
            det_r2["volume"], det_r2["dist"]))

    g1_cells, g1_beats = [], True
    for si, size in enumerate(GRID_SIZES):
        for ri, rate in enumerate(DROPOUT_RATES):
            for seed in SEEDS:
                mg = next((r["arms"]["G"]["volume"] for r in cellrecs
                           if r.get("blocked") is None
                           and r["size"] == size
                           and r["rate"] == rate
                           and r["seed"] == seed), None)
                mr = next((r["arms"]["R"]["volume"] for r in cellrecs
                           if r.get("blocked") is None
                           and r["size"] == size
                           and r["rate"] == rate
                           and r["seed"] == seed), None)
                ok = (mg is not None and mr is not None and mg < mr)
                g1_cells.append({"cell": "%d/%.2f/%d" % (
                    size, rate, seed),
                    "mean_G": mg, "mean_R": mr,
                    "pass": bool(ok)})
                if not ok:
                    g1_beats = False
    g1_ok = bool(g1_beats and tiny_ok and determinism_ok)

    g2_fams, g2_n = [], 0
    g2s_fams, g2s_n = [], 0
    win_fams = []
    n_win = {"G": 0, "A": 0}
    n_strict = 0
    pools_all = True
    for size in GRID_SIZES:
        pools, pok = {}, True
        for arm in ("B", "G", "A"):
            pools[arm], oka = pool(size, arm, volumes)
            pok = pok and oka
        se, spread, gp = spread_win(pools, pok)
        g2_fams.append({"size": size, "pools": pools, "SE": se,
                        "spread": spread, "pass": bool(gp)})
        if gp:
            g2_n += 1
        dpools, dpok = {}, True
        for arm in ("B", "G", "A"):
            lv = [r["arms"][arm]["dist"] for r in cellrecs
                  if r.get("blocked") is None
                  and r["size"] == size and arm in r["arms"]]
            dpools[arm] = pooled_stats(lv)
            dpok = dpok and len(lv) == 2 * len(SEEDS)
        sse, sspread, sgp = spread_win(dpools, dpok)
        g2s_fams.append({"size": size, "pools": dpools,
                         "SE": sse, "spread": sspread,
                         "pass": bool(sgp)})
        if sgp:
            g2s_n += 1
        joint = {}
        if pok and all(
                pools[a]["se"] is not None and
                pools[a]["mean"] is not None for a in ("B", "G", "A")):
            sse2 = math.sqrt(sum(pools[a]["se"] ** 2
                                 for a in ("B", "G", "A")) / 3.0)
            for a in ("G", "A"):
                vwin = pools[a]["mean"] < pools["B"]["mean"] - \
                    2.0 * sse2
                dpo = pooled_stats(dists.get((size, a), []))
                dpo_b = pooled_stats(dists.get((size, "B"), []))
                dwin = (dpo["mean"] is not None
                        and dpo_b["mean"] is not None
                        and dpo["mean"] >= dpo_b["mean"])
                joint[a] = bool(vwin and dwin)
        else:
            joint = {"G": False, "A": False}
        for a in ("G", "A"):
            if joint[a]:
                n_win[a] += 1
        winner = ("G" if joint["G"]
                  else ("A" if joint["A"] else None))
        if pok and all(pools[a]["mean"] is not None
                       for a in ("B", "G", "A")):
            spass = (pools["G"]["mean"] < pools["B"]["mean"] or
                     pools["A"]["mean"] < pools["B"]["mean"])
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
    complete = (nrec == len(GRID_SIZES) * len(DROPOUT_RATES)
                * len(SEEDS) and all(
        len(volumes.get((size, a), [])) == 2 * len(SEEDS)
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
        reason = "PURSUE-condition holds (joint spacetime-volume " \
            "win + matched-or-better distance on the SAME arm at " \
            ">=2 grid sizes + gates 1,2,3,4 + self-tests ok); " \
            "payload verdict stays unresolved-with-reason, " \
            "classification is coordinator-side."
    elif reject:
        reason = "REJECT-condition holds (complete cells, tiny " \
            "solved, Gate-1 controls pass, no strict pooled volume " \
            "win at any size); payload verdict stays " \
            "unresolved-with-reason, classification is coordinator-side."
    else:
        reason = "UNRESOLVED + next experiment (joint wins G=%d/3, " \
            "A=%d/3, strict wins=%d/3, g1=%s g2=%s " \
            "g2s(dist-spread)=%s g3=%s (tiny solved=%s, target " \
            "cap-hit=%s) selftest=%s g4=%s complete=%s skipped=%d; " \
            "next: wider gauge-fixing move families + " \
            "correlated-defect masks retest)." % (
                n_win["G"], n_win["A"], n_strict, g1_ok, g2_ok,
                g2s_n >= 2, g3pass, tiny_solved, target_cap,
                selftest_ok, g4_ok, complete, len(skipped))
    verdict_bits = {
        "gate1": {"pass": bool(g1_ok), "beats_all_30": bool(g1_beats),
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
                       "n_win_G": n_win["G"], "n_win_A": n_win["A"],
                       "win_sizes": win_fams, "n_strict_win": n_strict,
                       "pools_all": bool(pools_all),
                       "selftest_ok": bool(selftest_ok)},
        "reason": reason,
    }

    results = {
        "screen": "09",
        "verdict": "unresolved-with-reason: payload reports numbers "
                   "and gate evidence; classification is coordinator-side.",
        "design": {
            "model": "screen-authored deterministic defect-tolerant "
                     "surface-code patch model (stdlib + numpy only; "
                     "no external libs)",
            "grids": ["7x7 (49 data qubits)",
                      "9x9 (81 data qubits)",
                      "11x11 (121 data qubits)"],
            "dropout_rates": list(DROPOUT_RATES),
            "dropout_counts": {
                "%dx%d@%.2f" % (s, s, r): dropout_count(s, r)
                for s in GRID_SIZES for r in DROPOUT_RATES},
            "seeds": list(SEEDS),
            "cells": "3 sizes x 2 rates x 5 seeds = 30 cells x 4 "
                     "arms (120 evaluations; seeds are replicates)",
            "gauge_rule": "rounds = d_eff + n_adj_dead (one extra "
                          "syndrome round per dead qubit 4-adjacent "
                          "to the patch; frozen super-plaquette "
                          "gauge-fixing rule)",
            "distance": "exact BFS shortest live path between the "
                        "patch's own north/south and west/east "
                        "extent edges (steps + 1); d_eff = min; "
                        "valid iff connected, defect-free, d_eff>=2",
            "anneal": {"iters": n_iters, "t0": A_T0,
                       "alpha": A_ALPHA},
            "notches": {"attempts": NOTCH_ATTEMPTS,
                        "width": "1..3", "depth": "1..2"},
            "greedy": {"shrink_sweeps": GREEDY_SHRINK_SWEEPS,
                       "annex_sweeps": GREEDY_ANNEX_SWEEPS},
            "arms": {"B": "bounding-box defect exclusion: naive "
                          "shave-to-clean-rectangle (rows-before-cols, "
                          "smaller-index ties; larger piece kept)",
                     "R": "random deformed-patch control: seeded "
                          "boundary-notched full-live patch "
                          "(undo-on-invalid + repair)",
                     "G": "greedy irregular patch routing from B "
                          "(shrink + single-cell hill-climb, "
                          "d >= d_B floor, volume strictly down)",
                     "A": "simulated annealing over boundary "
                          "allocation from G (best tracked)"},
            "metrics": "logical spacetime volume (patch area x "
                       "rounds under frozen rules) + effective code "
                       "distance verification (shortest logical "
                       "operator under super-plaquette gauge-fixing)",
            "pareto": "PURSUE needs a spacetime-volume win + "
                      "matched-or-better distance on the SAME arm; "
                      "joint wins counted PER ARM with bar "
                      "max(G,A)>=2, never any-winner",
            "exact": "bounded-exact subset search on tiny (3x3, "
                     "corner dropout, must solve, optimum %d volume) "
                     "+ target-scale instance (9x9, 4%% dropout, "
                     "seed 1, node cap %d, must cap-hit)" % (
                         TINY_EXP_OPT, EXACT_CAP),
        },
        "timing": {"wall_s": wall, "guards": {"wall_guard_s": WALL_GUARD_S,
                                              "limit_s": WALL_LIMIT_S}},
        "cells": {("%d/%.2f/%d/%s" % (r["size"], r["rate"], r["seed"],
                                      a)): {"volume": r["arms"][a][
                                          "volume"],
                                      "area": r["arms"][a]["area"],
                                      "dist": r["arms"][a]["dist"],
                                      "rounds": r["arms"][a][
                                          "rounds"]}
                  for r in cellrecs if r.get("blocked") is None
                  for a in ARMS},
        "pools": {("%d/%s" % (size, a)): {
            **pooled_stats(volumes.get((size, a), [])),
            "mean_dist": pooled_stats(
                dists.get((size, a), []))["mean"]}
            for size in GRID_SIZES for a in ARMS},
        "gates": verdict_bits,
        "skipped": skipped,
    }
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)


if __name__ == "__main__":
    main()
