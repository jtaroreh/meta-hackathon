"""Screen 13 payload: crosstalk-aware parallel two-qubit gate coloring
on tunable couplers.

Screen-authored deterministic two-qubit layering model (stdlib +
numpy only; no external physics or policy libraries): qubits on
frozen square grids with tunable couplers on grid edges; each cell
schedules a frozen list of CZ/iSWAP gates on seeded random
couplers. The hardware conflict hypergraph has hard edges (two
gates sharing a qubit never share a layer) and soft spectator
edges (concurrent gates on edge-adjacent couplers pay a
frequency-collision penalty). Metric is expected circuit survival
probability (frozen product of per-gate fidelities times
spectator-crosstalk penalties times idle T1/T2 decay per layer)
plus layer-validity verification. Arms: D naive minimum-depth
packing baseline (fixed order, first-fit, crosstalk-blind), R
random layering control (seeded shuffled order, seeded uniform
legal layer, deeper than D on average), G greedy
crosstalk-penalized list scheduling (minimum incremental -log
survival per gate), A crosstalk-penalized annealing over
single-gate relocations with validity repair from the G coloring,
best tracked so A never regresses G. A bounded-exact coloring
search validates the tiny instance (solved, optimum by
enumeration) and cap-hits at target scale (limit-expiry). Writes
ALL output under cwd (the attempt work dir): results.json plus
witnesses/. Deterministic given seeds. Verdict is always
unresolved-with-reason; classification is coordinator-side.
"""

import argparse
import json
import math
import os
import time

import numpy as np

GRID_SIZES = (3, 4, 5)
N_QUBITS_PER_SIZE = (9, 16, 25)
N_GATES = 12
SEEDS = (1, 2, 3, 4, 5)
ARMS = ("D", "R", "G", "A")
F_CZ = 0.995
F_ISWAP = 0.996
X_TALK = 0.997
IDLE_DECAY = 0.9999
ANNEAL_ITERS = 300
A_T0 = 1.0
A_ALPHA = 0.99
N_INST = 400
EXACT_CAP = 50000
WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0
TINY_SIZE = 2
TINY_GATES = (("CZ", 0, 1), ("ISWAP", 0, 2))
TINY_EXP_SURVIVAL = 0.9906236514572361
TINY_EXP_LAYERS = 2
TARGET = {"size": 5, "seed": 1, "rep": 0}
NEXT_EXPERIMENT = ("frequency-aware qubit placement co-optimization "
                   "+ correlated crosstalk-noise retest")


def seed_rng(si, seed, rep, salt):
    return np.random.default_rng(
        (int(si * 100003 + seed * 10007 + rep * 101
             + salt * 1000003) % (2 ** 63 - 1)))


def grid_edges(size):
    edges = []
    for r in range(size):
        for c in range(size):
            q = r * size + c
            if c + 1 < size:
                edges.append((q, q + 1))
            if r + 1 < size:
                edges.append((q, q + size))
    return edges


EDGES = {s: grid_edges(s) for s in GRID_SIZES}


def qdist(size, a, b):
    return abs(a // size - b // size) + abs(a % size - b % size)


def spectator(e1, e2, size):
    """True when two couplers are spectator-adjacent: no shared qubit
    (that is a hard conflict, never a spectator pair) but some
    endpoint pair at grid distance 1 (frequency-collision proxy)."""
    if len({e1[0], e1[1], e2[0], e2[1]}) < 4:
        return False
    return min(qdist(size, a, b) for a in e1 for b in e2) == 1


def gate_fid(kind):
    return F_CZ if kind == "CZ" else F_ISWAP


def gen_gates(si, seed, rep):
    """Frozen gate lists: N_GATES CZ/iSWAP gates on seeded random grid
    edges, kind alternating CZ/iSWAP by seeded index parity. Seeds are
    replicates. Deterministic given inputs."""
    size = GRID_SIZES[si]
    edges = EDGES[size]
    rng = seed_rng(si, seed, rep, 11)
    idx = rng.integers(len(edges), size=N_GATES)
    gates = []
    for k, ei in enumerate(idx):
        kind = "CZ" if (int(k) + seed) % 2 == 0 else "ISWAP"
        a, b = edges[int(ei)]
        gates.append((kind, a, b))
    return tuple(gates)


def layer_conflict(layers, li, gate, gates):
    """True when gate shares a qubit with a gate already in layer li."""
    for gi in layers[li]:
        g = gates[gi]
        if gate[1] == g[1] or gate[1] == g[2] or gate[2] == g[1] \
                or gate[2] == g[2]:
            return True
    return False


def assign_gate(layers, gates, gi, goal_layer):
    """Place gate gi at goal_layer; on a hard conflict, scan forward to
    the first legal layer (repair), appending a fresh layer when none
    is legal. Existing gates are never moved: goal_layer names only
    the desired layer while scan_layer is a separate cursor that walks
    the newcomer forward, so a full target never reroutes gates that
    are already placed. Returns the layer index now holding gi."""
    gate = gates[gi]
    if goal_layer < len(layers) and not layer_conflict(
            layers, goal_layer, gate, gates):
        layers[goal_layer].append(gi)
        return goal_layer
    scan_layer = goal_layer
    while scan_layer < len(layers):
        if not layer_conflict(layers, scan_layer, gate, gates):
            layers[scan_layer].append(gi)
            return scan_layer
        scan_layer += 1
    layers.append([gi])
    return len(layers) - 1


def verify_layers(layers, gates):
    """Layer-validity check: every gate placed exactly once, no qubit
    in two gates of one layer."""
    seen = set()
    for layer in layers:
        used = set()
        for gi in layer:
            if gi in seen:
                return False
            seen.add(gi)
            g = gates[gi]
            if g[1] in used or g[2] in used:
                return False
            used.add(g[1])
            used.add(g[2])
    return len(seen) == len(gates)


def layer_factor(layer, gates, size, n):
    """Survival factor of one layer: per-gate fidelities times
    spectator penalties times idle decay. Returns (factor, pairs,
    idle_qubits)."""
    f = 1.0
    for gi in layer:
        f *= gate_fid(gates[gi][0])
    pairs = 0
    for i in range(len(layer)):
        for j in range(i + 1, len(layer)):
            e1 = (gates[layer[i]][1], gates[layer[i]][2])
            e2 = (gates[layer[j]][1], gates[layer[j]][2])
            if spectator(e1, e2, size):
                pairs += 1
    f *= X_TALK ** pairs
    used = set()
    for gi in layer:
        used.add(gates[gi][1])
        used.add(gates[gi][2])
    idle = n - len(used)
    f *= IDLE_DECAY ** idle
    return f, pairs, idle


def coloring_survival(layers, gates, size, n):
    s = 1.0
    tp = 0
    ti = 0
    for layer in layers:
        f, p, idle = layer_factor(layer, gates, size, n)
        s *= f
        tp += p
        ti += idle
    return {"survival": s, "pairs": tp, "idle": ti,
            "layers": len(layers)}


def empty_stats(stopped):
    return {"survival": None, "layers": None, "pairs": None,
            "idle": None, "valid": False, "stopped": bool(stopped)}


def finish(layers, gates, size, n):
    ev = coloring_survival(layers, gates, size, n)
    return {"survival": float(ev["survival"]),
            "layers": int(ev["layers"]), "pairs": int(ev["pairs"]),
            "idle": int(ev["idle"]),
            "valid": bool(verify_layers(layers, gates)),
            "stopped": False}


def run_d(gates, size, n, stop):
    """Naive minimum-depth packing baseline: fixed gate order,
    first-fit into the earliest layer with no shared qubit
    (depth-minimal, crosstalk-blind)."""
    layers = []
    for gi in range(len(gates)):
        if stop is not None and stop():
            return empty_stats(True)
        assign_gate(layers, gates, gi, 0)
    return finish(layers, gates, size, n)


def run_r(gates, size, n, rng, stop):
    """Random layering control: seeded shuffled gate order, each gate
    to a seeded uniform legal layer (existing or new; the new layer
    is always legal, so validity holds). Deeper than D on average."""
    order = list(range(len(gates)))
    for i in range(len(order) - 1, 0, -1):
        j = int(rng.integers(i + 1))
        order[i], order[j] = order[j], order[i]
    layers = []
    for gi in order:
        if stop is not None and stop():
            return empty_stats(True)
        assign_gate(layers, gates, gi,
                    int(rng.integers(len(layers) + 1)))
    return finish(layers, gates, size, n)


def _run_g_full(gates, size, n, stop):
    """Greedy crosstalk-penalized list scheduling: fixed order, each
    gate into the layer minimizing incremental -log survival over
    all existing layers plus one fresh layer (ties go to the lowest
    layer). Returns (result, coloring) with coloring[gi] the layer
    holding gate gi."""
    layers = []
    for gi in range(len(gates)):
        if stop is not None and stop():
            return empty_stats(True), []
        best_goal = 0
        best_cost = None
        for goal_layer in range(len(layers) + 1):
            trial = [list(layer) for layer in layers]
            assign_gate(trial, gates, gi, goal_layer)
            ev = coloring_survival(trial, gates, size, n)
            cost = -math.log(ev["survival"])
            if best_cost is None or cost < best_cost - 1e-15:
                best_cost = cost
                best_goal = goal_layer
        assign_gate(layers, gates, gi, best_goal)
    coloring = [None] * len(gates)
    for li, layer in enumerate(layers):
        for gj in layer:
            coloring[gj] = li
    return finish(layers, gates, size, n), coloring


def run_g(gates, size, n, stop):
    out, _c = _run_g_full(gates, size, n, stop)
    return out


def rebuild(coloring, gates):
    """Rebuild layers from a per-gate coloring vector in gate order
    with validity repair (assign_gate), so any vector yields a valid
    layering. Returns the layer list."""
    layers = []
    for gi in range(len(gates)):
        assign_gate(layers, gates, gi, coloring[gi])
    return layers


def actual_coloring(layers, gates):
    actual = [None] * len(gates)
    for li, layer in enumerate(layers):
        for gj in layer:
            actual[gj] = li
    return actual


def run_a(gates, size, n, rng, n_iters, stop):
    """Crosstalk-penalized annealing over single-gate relocations
    from the G coloring. Each proposal moves one random gate to a
    random layer (existing or fresh) with validity repair; cost is
    -log survival, best tracked, so A never regresses G."""
    if stop is not None and stop():
        return empty_stats(True)
    gout, gcolor = _run_g_full(gates, size, n, None)
    if gout.get("stopped") or not gout.get("valid"):
        return empty_stats(True)
    best = list(gcolor)
    best_out = gout
    cur = list(gcolor)
    cur_cost = -math.log(gout["survival"])
    best_cost = cur_cost
    temp = A_T0
    for it in range(n_iters):
        if it % 32 == 0 and stop is not None and stop():
            return empty_stats(True)
        gi = int(rng.integers(len(gates)))
        span = max(cur) + 2 if cur else 1
        trial = list(cur)
        trial[gi] = int(rng.integers(span))
        layers = rebuild(trial, gates)
        ev = coloring_survival(layers, gates, size, n)
        new_cost = -math.log(ev["survival"])
        temp *= A_ALPHA
        if new_cost <= cur_cost or bool(
                rng.random() < math.exp(-(new_cost - cur_cost)
                                        / temp)):
            cur = actual_coloring(layers, gates)
            cur_cost = new_cost
            if new_cost < best_cost:
                best = list(cur)
                best_cost = new_cost
                best_out = finish(layers, gates, size, n)
    return dict(best_out, stopped=False)


def run_arm(si, seed, rep, arm, n_iters, stop):
    gates = gen_gates(si, seed, rep)
    size = GRID_SIZES[si]
    n = N_QUBITS_PER_SIZE[si]
    if arm == "D":
        return run_d(gates, size, n, stop)
    if arm == "R":
        return run_r(gates, size, n,
                     seed_rng(si, seed, rep, 999), stop)
    if arm == "G":
        return run_g(gates, size, n, stop)
    return run_a(gates, size, n, seed_rng(si, seed, rep, 777),
                 n_iters, stop)


def exact_opt(gates, size, n, cap, stop):
    """Bounded-exact coloring search: DFS over gates in fixed order,
    branching each gate over every existing layer plus one fresh
    layer, with validity repair on conflict. Partial accumulated
    gate-fidelity plus spectator cost is an admissible lower bound
    (remaining gate, spectator, and idle terms are all nonnegative),
    so a partial schedule at or above the incumbent cannot improve
    and is pruned; the incumbent starts at +infinity, which provably
    disables pruning until the first leaf. Statuses: solved /
    cap-hit / stopped-guard. Branch order is fixed (deterministic)."""
    incumbent = [None]
    best = [None]
    nodes = [0]
    capped = [False]
    stopped = [False]
    cur_layers = []

    def placed_cost():
        c = 0.0
        for layer in cur_layers:
            for gi in layer:
                c += -math.log(gate_fid(gates[gi][0]))
            for i in range(len(layer)):
                for j in range(i + 1, len(layer)):
                    e1 = (gates[layer[i]][1], gates[layer[i]][2])
                    e2 = (gates[layer[j]][1], gates[layer[j]][2])
                    if spectator(e1, e2, size):
                        c += -math.log(X_TALK)
        return c

    def rec(depth):
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
            ev = coloring_survival(cur_layers, gates, size, n)
            if incumbent[0] is None or ev["survival"] > incumbent[0]:
                incumbent[0] = ev["survival"]
                best[0] = {"survival": float(ev["survival"]),
                           "layers": int(ev["layers"]),
                           "pairs": int(ev["pairs"]),
                           "idle": int(ev["idle"])}
            return
        lb = placed_cost()
        if incumbent[0] is not None and lb >= -math.log(incumbent[0]):
            return
        for goal_layer in range(len(cur_layers) + 1):
            saved = [list(layer) for layer in cur_layers]
            assign_gate(cur_layers, gates, depth, goal_layer)
            rec(depth + 1)
            cur_layers[:] = saved
            if capped[0] or stopped[0]:
                return

    rec(0)
    if stopped[0]:
        return {"status": "stopped-guard", "nodes": nodes[0],
                "opt_survival": incumbent[0], "best": best[0],
                "cap": cap, "started": True}
    if capped[0]:
        return {"status": "cap-hit", "nodes": nodes[0],
                "opt_survival": incumbent[0], "best": best[0],
                "cap": cap, "started": True}
    return {"status": "solved", "nodes": nodes[0],
            "opt_survival": incumbent[0], "best": best[0],
            "cap": cap, "started": True}


def audit_gen(si, seed, rep):
    size = GRID_SIZES[si]
    n = N_QUBITS_PER_SIZE[si]
    gates = gen_gates(si, seed, rep)
    edgeset = set(EDGES[size]) | {(b, a) for a, b in EDGES[size]}
    ok = (len(gates) == N_GATES
          and all(g[0] in ("CZ", "ISWAP") for g in gates)
          and all((g[1], g[2]) in edgeset for g in gates)
          and all(0 <= g[1] < n and 0 <= g[2] < n
                  and g[1] != g[2] for g in gates))
    return ok, gates


def target_gates():
    si = GRID_SIZES.index(TARGET["size"])
    return (GRID_SIZES[si], N_QUBITS_PER_SIZE[si],
            gen_gates(si, TARGET["seed"], TARGET["rep"]))


def self_tests():
    out = {"ran": True, "failed": []}
    try:
        for si in range(len(GRID_SIZES)):
            for rep in (0, 1):
                ok, _g = audit_gen(si, 1, rep)
                if not ok:
                    out["failed"].append("gen-%d-%d" % (si, rep))
        _ok, g1 = audit_gen(0, 1, 0)
        _ok, g1b = audit_gen(0, 1, 0)
        if g1 != g1b:
            out["failed"].append("gen-determinism")
        if list(TINY_GATES) != [("CZ", 0, 1), ("ISWAP", 0, 2)]:
            out["failed"].append("tiny-fixture")
        tiny = list(TINY_GATES)
        td = run_d(tiny, TINY_SIZE, 4, None)
        if (not td["valid"] or td["stopped"]
                or td["layers"] != TINY_EXP_LAYERS
                or abs(td["survival"] - TINY_EXP_SURVIVAL) > 1e-9):
            out["failed"].append("tiny-D-hand: %r" % (td,))
        tg = run_g(tiny, TINY_SIZE, 4, None)
        if (not tg["valid"] or tg["stopped"]
                or tg["layers"] != TINY_EXP_LAYERS
                or abs(tg["survival"] - TINY_EXP_SURVIVAL) > 1e-9):
            out["failed"].append("tiny-G-hand: %r" % (tg,))
        ta = run_a(tiny, TINY_SIZE, 4,
                   seed_rng(0, 7, 7, 777), 50, None)
        if (ta["stopped"] or not ta["valid"]
                or ta["survival"] < tg["survival"] - 1e-12):
            out["failed"].append("tiny-A-invariant: %r" % (ta,))
        tr = run_r(tiny, TINY_SIZE, 4,
                   seed_rng(0, 7, 7, 999), None)
        if tr["stopped"] or not tr["valid"]:
            out["failed"].append("tiny-R-valid: %r" % (tr,))
        dplace = [[[0]], [("CZ", 0, 1), ("ISWAP", 0, 2)]]
        dlyr = [list(dplace[0][0])]
        dgates = list(dplace[1])
        landing = assign_gate(dlyr, dgates, 1, 0)
        if (landing != 1 or dlyr != [[0], [1]]
                or not verify_layers(dlyr, dgates)):
            out["failed"].append(
                "displacement-repair: %r %r" % (landing, dlyr))
        bad = [[0, 1]]
        if verify_layers(bad, dgates):
            out["failed"].append("verify-missed-conflict")
        tex = exact_opt(tiny, TINY_SIZE, 4, EXACT_CAP, None)
        if (tex["status"] != "solved" or tex["best"] is None
                or abs(tex["opt_survival"] - TINY_EXP_SURVIVAL)
                > 1e-9):
            out["failed"].append("tiny-exact-opt: %r" % (tex,))
        for si, seed in ((0, 1), (2, 3)):
            _ok, dg = audit_gen(si, seed, 0)
            size = GRID_SIZES[si]
            n = N_QUBITS_PER_SIZE[si]
            for arm, fn in (
                    ("D", lambda: run_d(dg, size, n, None)),
                    ("G", lambda: run_g(dg, size, n, None)),
                    ("R", lambda: run_r(
                        dg, size, n,
                        seed_rng(si, seed, 0, 999), None))):
                r = fn()
                if not r["valid"] or r["stopped"]:
                    out["failed"].append(
                        "arm-valid-%s-%d-%d" % (arm, si, seed))
            ga = run_a(dg, size, n,
                       seed_rng(si, seed, 0, 777), 50, None)
            gg = run_g(dg, size, n, None)
            if (not ga["valid"] or ga["stopped"]
                    or ga["survival"] < gg["survival"] - 1e-12):
                out["failed"].append(
                    "a-beats-start-invariant-%d-%d" % (si, seed))
            _ok, dg2 = audit_gen(si, seed, 0)
            g1a = run_g(dg, size, n, None)
            g1b = run_g(dg2, size, n, None)
            if g1a["survival"] != g1b["survival"]:
                out["failed"].append("determinism-greedy")
            r1 = run_r(dg, size, n,
                       seed_rng(si, seed, 0, 999), None)
            r2 = run_r(dg2, size, n,
                       seed_rng(si, seed, 0, 999), None)
            if r1["survival"] != r2["survival"]:
                out["failed"].append("determinism-random")
        _ok, dag = audit_gen(0, 1, 0)
        dag_size = GRID_SIZES[0]
        dag_n = N_QUBITS_PER_SIZE[0]
        stoppers = {
            "D": lambda: run_d(dag, dag_size, dag_n,
                               lambda: True),
            "G": lambda: run_g(dag, dag_size, dag_n,
                               lambda: True),
            "R": lambda: run_r(dag, dag_size, dag_n,
                               seed_rng(0, 1, 0, 999),
                               lambda: True),
            "A": lambda: run_a(dag, dag_size, dag_n,
                               seed_rng(0, 1, 0, 777), 50,
                               lambda: True),
        }
        for arm, fn in stoppers.items():
            if not fn().get("stopped"):
                out["failed"].append("stop-propagation-%s" % arm)
        for si in range(len(GRID_SIZES)):
            for seed in SEEDS:
                size = GRID_SIZES[si]
                n = N_QUBITS_PER_SIZE[si]
                _ok, sw_g = audit_gen(si, seed, 0)
                for arm, fn in (
                        ("D", lambda: run_d(sw_g, size, n, None)),
                        ("G", lambda: run_g(sw_g, size, n, None)),
                        ("R", lambda: run_r(
                            sw_g, size, n,
                            seed_rng(si, seed, 0, 999), None)),
                        ("A", lambda: run_a(
                            sw_g, size, n,
                            seed_rng(si, seed, 0, 777), 30,
                            None))):
                    r = fn()
                    if not r["valid"] or r["stopped"]:
                        out["failed"].append(
                            "sweep-valid-%s-%d-%d" % (arm, si, seed))
        tsize, tn, tgates = target_gates()
        stx = exact_opt(list(tgates), tsize, tn,
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
                        "iters_done": 0, "n_evaluated": EXACT_CAP})
    else:
        ex = exact_opt(list(TINY_GATES), TINY_SIZE, 4,
                       EXACT_CAP, over)
        gate3tiny["arms"]["tiny"] = ex
        gate3tiny["total"] += 1
        if ex["status"] == "solved" and ex["best"] is not None \
                and abs(ex["opt_survival"] - TINY_EXP_SURVIVAL) < 1e-9:
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
        tsize, tn, tgates = target_gates()
        tex = exact_opt(list(tgates), tsize, tn,
                        EXACT_CAP, over)
        gate3targets.append(dict(tex, size=tn, seed=TARGET["seed"],
                                 rep=TARGET["rep"]))
        if tex["status"] == "stopped-guard":
            skipped.append({"what": "target-exact",
                            "reason": "stopped-guard",
                            "iters_done": tex.get("nodes", 0),
                            "n_evaluated": EXACT_CAP})
    with open(os.path.join(witdir, "gate3_targets.json"), "w") as f:
        json.dump(gate3targets, f, indent=1, default=str)
    checkpoint("targets")

    def run_cell(si, seed):
        n = N_QUBITS_PER_SIZE[si]
        rec = {"size": GRID_SIZES[si], "seed": seed, "arms": {}}
        for arm in ARMS:
            if over():
                rec["blocked"] = "wall-guard"
                return rec
            sv, ly, nv = [], [], 0
            nstop = 0
            for rep in range(n_inst):
                if rep % 32 == 0 and over():
                    nstop += 1
                    break
                out = run_arm(si, seed, rep, arm, n_iters, over)
                if out.get("stopped"):
                    nstop += 1
                    break
                sv.append(out["survival"])
                ly.append(out["layers"])
                nv += 1 if out.get("valid") else 0
            if nstop:
                rec["blocked"] = "stopped-guard"
                rec["iters_done"] = len(sv)
                rec["n_evaluated"] = n_inst
                return rec
            rec["arms"][arm] = {
                "n": len(sv),
                "surv": pooled_stats(sv),
                "layers": pooled_stats(ly),
                "n_valid": int(nv)}
        return rec

    def record_cell(rec):
        if rec.get("blocked") is None and all(
                rec["arms"].get(a, {}).get("n") == n_inst
                for a in ARMS):
            for a in ARMS:
                key = (rec["size"], rec["seed"], a)
                cells.setdefault(key, {"surv": [], "layers": [],
                                       "valid": []})
                cells[key]["surv"].append(
                    rec["arms"][a]["surv"]["mean"])
                cells[key]["layers"].append(
                    rec["arms"][a]["layers"]["mean"])
                cells[key]["valid"].append(
                    rec["arms"][a]["n_valid"] / n_inst)
            cellrecs.append(rec)
            return True
        cellrecs.append(rec)
        skipped.append({"what": "cell %d/%d" % (
            rec["size"], rec["seed"]),
            "reason": rec.get("blocked", "arm-incomplete"),
            "iters_done": rec.get("iters_done", 0),
            "n_evaluated": n_inst})
        return False

    for si, size in enumerate(GRID_SIZES):
        siz_cells = [(si, seed) for seed in SEEDS]
        if over():
            for (s2, sd2) in siz_cells:
                skipped.append({"what": "cell %d/%d" % (
                    GRID_SIZES[s2], sd2), "reason": "wall-guard",
                    "iters_done": 0, "n_evaluated": n_inst})
        else:
            for (s2, sd2) in siz_cells:
                if over():
                    skipped.append({"what": "cell %d/%d" % (
                        GRID_SIZES[s2], sd2), "reason": "wall-guard",
                        "iters_done": 0, "n_evaluated": n_inst})
                    continue
                rec = run_cell(s2, sd2)
                record_cell(rec)
        with open(os.path.join(witdir, "cells.json"), "w") as f:
            json.dump(cellrecs, f, indent=1, default=str)
        checkpoint("size%d" % size)
    with open(os.path.join(witdir, "cells.json"), "w") as f:
        json.dump(cellrecs, f, indent=1, default=str)
    checkpoint("corpus")

    def cell_mean(size, seed, arm, field):
        return cells.get((size, seed, arm),
                         {"surv": [], "layers": [],
                          "valid": []})[field]

    def pool(size, arm, field):
        vals = []
        for seed in SEEDS:
            vals.extend(cell_mean(size, seed, arm, field))
        return pooled_stats(vals), len(vals) == len(SEEDS)

    def valid_pool(size, arm):
        vals = []
        for seed in SEEDS:
            vals.extend(cell_mean(size, seed, arm, "valid"))
        return vals

    det1 = run_arm(0, 1, 0, "G", n_iters, None)
    det2 = run_arm(0, 1, 0, "G", n_iters, None)
    det_r1 = run_arm(0, 1, 0, "R", n_iters, None)
    det_r2 = run_arm(0, 1, 0, "R", n_iters, None)
    determinism_ok = bool(
        det1["survival"] == det2["survival"]
        and det_r1["survival"] == det_r2["survival"])

    g1_cells, g1_beats = [], True
    for size in GRID_SIZES:
        for seed in SEEDS:
            ms = cell_mean(size, seed, "G", "surv")
            mr = cell_mean(size, seed, "R", "surv")
            ok = (len(ms) == 1 and len(mr) == 1 and ms[0] > mr[0])
            g1_cells.append({"cell": "%d/%d" % (size, seed),
                             "mean_G": ms[0] if ms else None,
                             "mean_R": mr[0] if mr else None,
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
        for arm in ("D", "G", "A"):
            pools[arm], oka = pool(size, arm, "surv")
            pok = pok and oka
        se, spread, gp = spread_win(pools, pok)
        g2_fams.append({"size": size, "pools": pools, "SE": se,
                        "spread": spread, "pass": bool(gp)})
        if gp:
            g2_n += 1
        joint = {}
        if pok and all(
                pools[a]["se"] is not None and
                pools[a]["mean"] is not None for a in ("D", "G",
                                                      "A")):
            sse2 = math.sqrt(sum(pools[a]["se"] ** 2
                                 for a in ("D", "G", "A")) / 3.0)
            for a in ("G", "A"):
                swin = pools[a]["mean"] > pools["D"]["mean"] + \
                    2.0 * sse2
                vpools = pooled_stats(valid_pool(size, a))
                vpool_d = pooled_stats(valid_pool(size, "D"))
                vwin = (vpools["mean"] is not None
                        and vpool_d["mean"] is not None
                        and vpools["mean"] >= vpool_d["mean"])
                joint[a] = bool(swin and vwin)
        else:
            joint = {"G": False, "A": False}
        for a in ("G", "A"):
            if joint[a]:
                n_win[a] += 1
        winner = ("G" if joint["G"]
                  else ("A" if joint["A"] else None))
        wpass = winner is not None
        if pok and all(pools[a]["mean"] is not None
                       for a in ("D", "G", "A")):
            spass = (pools["G"]["mean"] > pools["D"]["mean"] or
                     pools["A"]["mean"] > pools["D"]["mean"])
        else:
            spass = False
            pools_all = False
        if not pok:
            pools_all = False
        if spass:
            n_strict += 1
        win_fams.append({"size": size, "win": bool(wpass),
                         "strict_win": bool(spass),
                         "pools_ok": bool(pok),
                         "joint": dict(joint), "winner": winner})
    g2_ok = g2_n >= 2

    tiny_solved = (gate3tiny["total"] == 1 and gate3tiny["solved"] == 1)
    target_cap = (len(gate3targets) == 1 and
                  gate3targets[0].get("status") == "cap-hit")
    g3pass = bool(tiny_solved and target_cap)

    complete = all(
        len(cell_mean(size, seed, arm, "surv")) == 1
        for size in GRID_SIZES for seed in SEEDS for arm in ARMS)
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
        reason = "PURSUE-condition holds (joint survival win + " \
            "matched-or-better validity on the SAME arm at >=2 " \
            "grid sizes + gates 1,2,3,4 + self-tests ok); payload " \
            "verdict stays unresolved-with-reason, classification " \
            "is coordinator-side."
    elif reject:
        reason = "REJECT-condition holds (complete cells, tiny " \
            "solved, Gate-1 controls pass, no strict pooled " \
            "survival win at any size); payload verdict stays " \
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
        "gate1": {"pass": bool(g1_ok), "beats_all_15": bool(g1_beats),
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
        "screen": "13",
        "verdict": "unresolved-with-reason: payload reports numbers "
                   "and gate evidence; classification is coordinator-side.",
        "design": {
            "model": "screen-authored deterministic crosstalk-aware "
                     "two-qubit layering model (stdlib + numpy only; "
                     "no external libs)",
            "grids": ["3x3 (9 qubits)", "4x4 (16 qubits)",
                      "5x5 (25 qubits)"],
            "gates_per_cell": N_GATES,
            "seeds": list(SEEDS),
            "cells": "3 sizes x 5 seeds = 15 cells x 4 arms "
                     "(seeds are replicates)",
            "reps_per_cell_arm": n_inst,
            "conflicts": "hard qubit-sharing edges (never co-layered) "
                         "+ soft spectator edges (concurrent gates on "
                         "edge-adjacent couplers pay X_TALK)",
            "survival": "frozen product: F_CZ/F_ISWAP per gate x "
                        "X_TALK per spectator pair x IDLE_DECAY per "
                        "idle qubit per layer",
            "fidelities": {"F_CZ": F_CZ, "F_ISWAP": F_ISWAP,
                           "X_TALK": X_TALK,
                           "IDLE_DECAY": IDLE_DECAY},
            "anneal": {"iters": n_iters, "t0": A_T0,
                       "alpha": A_ALPHA},
            "arms": {"D": "naive minimum-depth packing baseline: "
                          "fixed order, first-fit, crosstalk-blind",
                     "R": "random layering control: seeded shuffled "
                          "order, seeded uniform legal layer",
                     "G": "greedy crosstalk-penalized list scheduling: "
                          "minimum incremental -log survival per gate",
                     "A": "crosstalk-penalized annealing over "
                          "single-gate relocations from G, best tracked"},
            "metrics": "expected circuit survival probability (frozen "
                       "product) + layer validity (no shared qubit in "
                       "one layer)",
            "pareto": "PURSUE needs a survival win + matched-or-better "
                      "validity on the SAME arm; joint wins counted "
                      "PER ARM with bar max(G,A)>=2, never any-winner",
            "exact": "bounded-exact coloring search on tiny (2x2, 2 "
                     "gates, must solve, optimum survival %r) "
                     "+ target-scale instance (5x5, seed %d rep %d, "
                     "node cap %d, must cap-hit)" % (
                         TINY_EXP_SURVIVAL, TARGET["seed"],
                         TARGET["rep"], EXACT_CAP),
        },
        "timing": {"wall_s": wall, "guards": {"wall_guard_s": WALL_GUARD_S,
                                              "limit_s": WALL_LIMIT_S}},
        "cells": {("%d/%d/%s" % k): {"n": len(v["surv"]),
                                     **pooled_stats(v["surv"]),
                                     "layers": pooled_stats(
                                         v["layers"]),
                                     "mean_valid": pooled_stats(
                                         v["valid"])["mean"]}
                  for k, v in cells.items()},
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
