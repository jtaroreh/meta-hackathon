"""Screen 08 payload: transversal entangling-gate scheduling in
reconfigurable qLDPC blocks.

Screen-authored deterministic transversal-layer scheduler (stdlib +
numpy only; no external solver/decoder/policy libs): two small block
codes (C8/C12, two patches each) with frozen cyclic automorphism
generators and frozen valid transversal shift subsets; three
benchmark DAGs (S/M/L gate counts) built as seeded parallel rounds at
one transversal shift per round plus per-qubit chains and extra
forward edges. Arms: Q sequential single-gate addressing (baseline),
R random layer-packing control, G greedy layer packing
(canonical + one seeded restart, best tracked), A simulated annealing
over automorphism-shift + layer assignments from the G solution
(best tracked, so A never exceeds G). Metric: total syndrome-round
latency (layers x ROUNDS_PER_LAYER) + verification of every gate's
automorphism alignment. A bounded-exact layer-packing search
validates the tiny instance (solved) and cap-hits at target scale
(limit-expiry). Writes ALL output under cwd (the attempt work dir):
results.json + witnesses/. Deterministic given seeds. Verdict is
always unresolved-with-reason; classification is coordinator-side.
"""

import argparse
import json
import math
import os
import time

import numpy as np

CODES = (8, 12)
CODE_NAME = {8: "C8", 12: "C12"}
SHIFTS = {8: (1, 2, 3), 12: (1, 3, 4)}
DAGS = ("S", "M", "L")
DAG_IDX = {"S": 0, "M": 1, "L": 2}
GATE_COUNTS = {"S": 12, "M": 20, "L": 28}
SEEDS = (1, 2, 3, 4, 5)
ARMS = ("Q", "R", "G", "A")

ROUNDS_PER_LAYER = 2
EXTRA_EDGES = 2

A_ITERS = 200
A_T0 = 1.0
A_ALPHA = 0.99

WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0
EXACT_CAP = 50000

TINY_N = 4
TINY_SHIFTS = (1,)
TINY_GATES = [
    {"kind": "I", "a": 0, "b": 1, "blk": 0, "preds": []},
    {"kind": "I", "a": 2, "b": 3, "blk": 0, "preds": []},
    {"kind": "I", "a": 3, "b": 0, "blk": 0, "preds": [0, 1]},
]
TINY_EXP_LAYERS = 2
TINY_EXP = {"Q": 3 * ROUNDS_PER_LAYER, "G": 2 * ROUNDS_PER_LAYER,
            "A": 2 * ROUNDS_PER_LAYER}

TARGET = {"code": 12, "dag": "L", "seed": 1}


def seed_rng(code_idx, dag_idx, seed, salt):
    return np.random.default_rng(
        (int(code_idx * 100003 + dag_idx * 17011 + seed * 10007
             + salt * 1000003) % (2 ** 63 - 1)))


def req_shift(n, a, b):
    return int((b - a) % n)


def gate_keys(g):
    if g["kind"] == "I":
        b = int(g["blk"])
        return frozenset(((b, int(g["a"])), (b, int(g["b"]))))
    return frozenset(((0, int(g["a"])), (1, int(g["b"]))))


def gen_dag(code_idx, dag_idx, seed):
    """Seeded benchmark DAG: parallel rounds of disjoint pairs sharing
    one transversal shift, plus per-qubit chains and EXTRA_EDGES
    forward edges. Index order is topological by construction."""
    n = CODES[code_idx]
    shifts = SHIFTS[n]
    total = GATE_COUNTS[DAGS[dag_idx]]
    rng = seed_rng(code_idx, dag_idx, seed, 11)
    gates = []
    last = {}
    while len(gates) < total:
        s = int(shifts[int(rng.integers(len(shifts)))])
        order = list(range(n))
        rng.shuffle(order)
        used = set()
        made = 0
        for a in order:
            if len(gates) >= total:
                break
            b = (a + s) % n
            intra = bool(rng.random() < 0.5)
            blk = int(rng.integers(2)) if intra else -1
            g = {"kind": "I" if intra else "X", "a": int(a),
                 "b": int(b), "blk": blk, "preds": set()}
            if intra:
                assert req_shift(n, a, b) in shifts
            keys = gate_keys(g)
            if keys & used:
                continue
            for k in keys:
                if k in last:
                    g["preds"].add(int(last[k]))
            idx = len(gates)
            for k in keys:
                last[k] = idx
            g["req"] = req_shift(n, int(a), int(b))
            g["preds"] = sorted(g["preds"])
            gates.append(g)
            used |= keys
            made += 1
        if made == 0:
            break
    for _ in range(EXTRA_EDGES):
        i = int(rng.integers(len(gates) - 1))
        j = int(rng.integers(i + 1, len(gates)))
        if i not in gates[j]["preds"]:
            gates[j]["preds"] = sorted(gates[j]["preds"] + [i])
    return {"n": n, "shifts": list(shifts), "gates": gates,
            "code": CODE_NAME[n], "dag": DAGS[dag_idx], "seed": seed}


def verify_schedule(dag, layers):
    """Check a schedule: layers = [{"shift": s, "gates": [idx]}].
    Every gate exactly once, layer shift in the valid subset and equal
    to each member's required shift, disjoint qubits, DAG order."""
    shifts = set(dag["shifts"])
    gates = dag["gates"]
    seen = []
    layer_of = {}
    for li, lay in enumerate(layers):
        s = lay["shift"]
        if s not in shifts:
            return {"ok": False,
                    "fail": "bad-shift L%d" % li}
        for gi in lay["gates"]:
            if gi in layer_of:
                return {"ok": False, "fail": "dup-gate %d" % gi}
            layer_of[gi] = li
            seen.append(gi)
            if gates[gi]["req"] != s:
                return {"ok": False,
                        "fail": "misaligned gate %d" % gi}
    if sorted(seen) != list(range(len(gates))):
        return {"ok": False, "fail": "coverage"}
    for li, lay in enumerate(layers):
        used = set()
        for gi in lay["gates"]:
            keys = gate_keys(gates[gi])
            if keys & used:
                return {"ok": False,
                        "fail": "conflict L%d" % li}
            used |= keys
            for p in gates[gi]["preds"]:
                if layer_of[p] >= li:
                    return {"ok": False,
                            "fail": "order gate %d" % gi}
    return {"ok": True, "fail": None}


def latency_of(layers):
    return int(len(layers) * ROUNDS_PER_LAYER)


def random_linear_extension(dag, rng):
    gates = dag["gates"]
    succs = [[] for _ in gates]
    indeg = [0] * len(gates)
    for gi, g in enumerate(gates):
        for p in g["preds"]:
            succs[p].append(gi)
            indeg[gi] += 1
    ready = [gi for gi in range(len(gates)) if indeg[gi] == 0]
    order = []
    while ready:
        k = int(rng.integers(len(ready)))
        gi = ready.pop(k)
        order.append(gi)
        for sj in succs[gi]:
            indeg[sj] -= 1
            if indeg[sj] == 0:
                ready.append(sj)
    return order


def earliest_fit(order, dag):
    """First-fit layer packing in a topological order: each gate joins
    the earliest layer whose shift matches, qubits are free, and all
    preds sit in strictly earlier layers; else opens a new layer."""
    gates = dag["gates"]
    layers = []
    layer_of = [-1] * len(gates)
    for gi in order:
        req = int(gates[gi]["req"])
        keys = gate_keys(gates[gi])
        placed = False
        for li, lay in enumerate(layers):
            if lay["shift"] != req:
                continue
            if any(layer_of[p] >= li for p in gates[gi]["preds"]):
                continue
            if keys & lay["used"]:
                continue
            lay["gates"].append(gi)
            lay["used"] |= keys
            layer_of[gi] = li
            placed = True
            break
        if not placed:
            layers.append({"shift": req, "gates": [gi],
                           "used": set(keys)})
            layer_of[gi] = len(layers) - 1
    sched = [{"shift": int(lay["shift"]),
              "gates": [int(x) for x in lay["gates"]]}
             for lay in layers]
    return sched


def sched_from_assignment(dag, layer_of, shifts):
    layers = [{"shift": int(shifts[li]), "gates": []}
              for li in range(len(shifts))]
    for gi, li in enumerate(layer_of):
        layers[int(li)]["gates"].append(int(gi))
    return [lay for lay in layers if lay["gates"]]


def run_q(dag):
    sched = [{"shift": int(dag["gates"][gi]["req"]), "gates": [gi]}
             for gi in range(len(dag["gates"]))]
    ok = verify_schedule(dag, sched)["ok"]
    return {"layers": len(sched), "latency": latency_of(sched),
            "valid": bool(ok), "stopped": False}


def run_r(dag, rng, stop):
    """Random control: random linear extension, each gate to a uniform
    random feasible layer (existing match or new). Valid by checking."""
    gates = dag["gates"]
    order = random_linear_extension(dag, rng)
    layers = []
    layer_of = [-1] * len(gates)
    for step, gi in enumerate(order):
        if step % 32 == 0 and stop is not None and stop():
            return {"layers": None, "latency": None, "valid": False,
                    "stopped": True}
        req = int(gates[gi]["req"])
        keys = gate_keys(gates[gi])
        feas = []
        for li, lay in enumerate(layers):
            if lay["shift"] != req:
                continue
            if any(layer_of[p] >= li for p in gates[gi]["preds"]):
                continue
            if keys & lay["used"]:
                continue
            feas.append(li)
        feas.append(-1)
        pick = feas[int(rng.integers(len(feas)))]
        if pick == -1:
            layers.append({"shift": req, "gates": [gi],
                           "used": set(keys)})
            layer_of[gi] = len(layers) - 1
        else:
            layers[pick]["gates"].append(gi)
            layers[pick]["used"] |= keys
            layer_of[gi] = pick
    sched = sched_from_assignment(
        dag, layer_of, [lay["shift"] for lay in layers])
    ok = verify_schedule(dag, sched)["ok"]
    return {"layers": len(sched), "latency": latency_of(sched),
            "valid": bool(ok), "stopped": False}


def run_g(dag, rng, stop):
    """Greedy: earliest-fit in canonical topo order and in one seeded
    random linear extension; best (fewest layers) tracked."""
    best = None
    orders = [list(range(len(dag["gates"]))),
              random_linear_extension(dag, rng)]
    for order in orders:
        if stop is not None and stop():
            return {"layers": None, "latency": None, "valid": False,
                    "stopped": True}
        sched = earliest_fit(order, dag)
        if best is None or len(sched) < len(best):
            best = sched
    ok = verify_schedule(dag, best)["ok"]
    return {"layers": len(best), "latency": latency_of(best),
            "valid": bool(ok), "stopped": False}


def run_a(dag, start, rng, n_iters, stop):
    """Simulated annealing over automorphism-shift + layer assignments:
    relocate moves and layer-shift-change moves (with eject-reinsert
    repair), every proposal validity-checked, cost = layers. Starts at
    the greedy solution and tracks the best, so A never exceeds G."""
    gates = dag["gates"]
    shifts = list(dag["shifts"])
    cur = [{"shift": int(lay["shift"]),
            "gates": [int(x) for x in lay["gates"]]} for lay in start]
    best = [dict(lay, gates=list(lay["gates"])) for lay in cur]
    cur_cost = len(cur)
    best_cost = len(best)
    temp = A_T0

    def insert_earliest(layers, gi):
        req = int(gates[gi]["req"])
        keys = gate_keys(gates[gi])
        lo = [-1] * len(gates)
        for li, lay in enumerate(layers):
            for h in lay["gates"]:
                lo[h] = li
        for li, lay in enumerate(layers):
            if lay["shift"] != req:
                continue
            if any(lo[p] >= li for p in gates[gi]["preds"]
                   if lo[p] >= 0):
                continue
            if keys & set().union(
                    *(gate_keys(gates[h]) for h in lay["gates"]),
                    set()):
                continue
            ok = True
            for h in lay["gates"]:
                if gi in gates[h]["preds"] and li >= lo[h]:
                    ok = False
            if not ok:
                continue
            lay["gates"].append(gi)
            return True
        return False

    for it in range(n_iters):
        if it % 32 == 0 and stop is not None and stop():
            return {"layers": None, "latency": None, "valid": False,
                    "stopped": True}
        trial = [{"shift": lay["shift"], "gates": list(lay["gates"])}
                 for lay in cur]
        if bool(rng.random() < 0.5) or len(trial) < 2:
            gi = int(rng.integers(len(gates)))
            for lay in trial:
                if gi in lay["gates"]:
                    lay["gates"].remove(gi)
            trial = [lay for lay in trial if lay["gates"]]
            pos = int(rng.integers(len(trial) + 1))
            if pos >= len(trial):
                trial.append({"shift": int(gates[gi]["req"]),
                              "gates": [gi]})
            else:
                trial[pos]["gates"].append(gi)
        else:
            li = int(rng.integers(len(trial)))
            trial[li]["shift"] = int(
                shifts[int(rng.integers(len(shifts)))])
            ejected = [h for h in trial[li]["gates"]
                       if int(gates[h]["req"]) != trial[li]["shift"]]
            trial[li]["gates"] = [
                h for h in trial[li]["gates"]
                if int(gates[h]["req"]) == trial[li]["shift"]]
            trial = [lay for lay in trial if lay["gates"]]
            bad = False
            for h in ejected:
                if not insert_earliest(trial, h):
                    nb = {"shift": int(gates[h]["req"]), "gates": []}
                    trial.append(nb)
                    if not insert_earliest(trial, h):
                        bad = True
                        break
            if bad:
                temp *= A_ALPHA
                continue
        trial = [lay for lay in trial if lay["gates"]]
        if not verify_schedule(dag, trial)["ok"]:
            temp *= A_ALPHA
            continue
        cost = len(trial)
        if cost < cur_cost or bool(
                rng.random() < math.exp(-(cost - cur_cost) / temp)):
            cur = trial
            cur_cost = cost
            if cost < best_cost:
                best = [dict(lay, gates=list(lay["gates"]))
                        for lay in trial]
                best_cost = cost
        temp *= A_ALPHA
    ok = verify_schedule(dag, best)["ok"]
    return {"layers": len(best), "latency": latency_of(best),
            "valid": bool(ok), "stopped": False}


def exact_opt(dag, cap, stop):
    """Bounded-exact branch-and-bound over layer assignments (layer
    shifts = gate required shifts), minimizing layer count. Statuses:
    solved / cap-hit / stopped-guard. Index order is topological."""
    gates = dag["gates"]
    gkeys = [gate_keys(g) for g in gates]
    req = [int(g["req"]) for g in gates]
    incumbent = earliest_fit(list(range(len(gates))), dag)
    best = [len(incumbent)]
    layer_of = [-1] * len(gates)
    members = []
    mshifts = []
    nodes = [0]
    capped = [False]
    stopped = [False]

    def rec(k, used):
        if capped[0] or stopped[0]:
            return
        nodes[0] += 1
        if nodes[0] > cap:
            capped[0] = True
            return
        if nodes[0] % 512 == 0 and stop is not None and stop():
            stopped[0] = True
            return
        if k == len(gates):
            if used < best[0]:
                best[0] = used
            return
        if used >= best[0]:
            return
        keys = gkeys[k]
        for li in range(used):
            if mshifts[li] != req[k]:
                continue
            if any(layer_of[p] >= li for p in gates[k]["preds"]):
                continue
            bad = False
            for h in members[li]:
                if keys & gkeys[h]:
                    bad = True
                    break
            if bad:
                continue
            layer_of[k] = li
            members[li].append(k)
            rec(k + 1, used)
            members[li].pop()
            layer_of[k] = -1
            if capped[0] or stopped[0]:
                return
        layer_of[k] = used
        members.append([k])
        mshifts.append(req[k])
        rec(k + 1, used + 1)
        members.pop()
        mshifts.pop()
        layer_of[k] = -1

    rec(0, 0)
    if stopped[0]:
        return {"status": "stopped-guard", "nodes": nodes[0],
                "opt_layers": best[0], "cap": cap, "started": True}
    if capped[0]:
        return {"status": "cap-hit", "nodes": nodes[0],
                "opt_layers": best[0], "cap": cap, "started": True}
    return {"status": "solved", "nodes": nodes[0],
            "opt_layers": best[0], "cap": cap, "started": True}


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


def tiny_dag():
    gates = []
    for g in TINY_GATES:
        gates.append({"kind": g["kind"], "a": g["a"], "b": g["b"],
                      "blk": g["blk"], "preds": list(g["preds"]),
                      "req": req_shift(TINY_N, g["a"], g["b"])})
    return {"n": TINY_N, "shifts": list(TINY_SHIFTS), "gates": gates,
            "code": "tiny", "dag": "tiny", "seed": 0}


def audit_dag(code_idx, dag_idx, seed):
    dag = gen_dag(code_idx, dag_idx, seed)
    gates = dag["gates"]
    shifts = set(dag["shifts"])
    ok = (len(gates) == GATE_COUNTS[DAGS[dag_idx]]
          and all(g["req"] in shifts for g in gates)
          and all(p < gi for gi, g in enumerate(gates)
                  for p in g["preds"]))
    return ok, dag


def self_tests():
    out = {"ran": True, "failed": []}
    try:
        for ci in range(len(CODES)):
            for di in range(len(DAGS)):
                for seed in (1, 2):
                    ok, _dag = audit_dag(ci, di, seed)
                    if not ok:
                        out["failed"].append(
                            "gen-%d-%d-%d" % (ci, di, seed))
        for ci, di in ((0, 0), (1, 2)):
            _ok, dag = audit_dag(ci, di, 1)
            pack = earliest_fit(list(range(len(dag["gates"]))), dag)
            if not len(pack) < len(dag["gates"]):
                out["failed"].append("packing-%d-%d" % (ci, di))
        td = tiny_dag()
        if not verify_schedule(td, [
                {"shift": 1, "gates": [0, 1]},
                {"shift": 1, "gates": [2]}])["ok"]:
            out["failed"].append("tiny-hand-valid")
        if verify_schedule(td, [
                {"shift": 1, "gates": [0, 2]},
                {"shift": 1, "gates": [1]}])["ok"]:
            out["failed"].append("tiny-order-blind")
        if verify_schedule(td, [
                {"shift": 1, "gates": [0]},
                {"shift": 2, "gates": [1, 2]}])["ok"]:
            out["failed"].append("tiny-shift-blind")
        tq = run_q(td)
        if tq["latency"] != TINY_EXP["Q"] or not tq["valid"]:
            out["failed"].append("tiny-Q-hand")
        tg = run_g(td, seed_rng(0, 0, 7, 555), None)
        if tg["latency"] != TINY_EXP["G"] or not tg["valid"]:
            out["failed"].append("tiny-G-hand")
        gstart = earliest_fit(list(range(len(td["gates"]))), td)
        ta = run_a(td, gstart, seed_rng(0, 0, 7, 777), 50, None)
        if ta["latency"] != TINY_EXP["A"] or not ta["valid"]:
            out["failed"].append("tiny-A-hand")
        tex = exact_opt(td, EXACT_CAP, None)
        if tex["status"] != "solved" or tex["opt_layers"] != \
                TINY_EXP_LAYERS:
            out["failed"].append("tiny-exact-opt")
        for ci, di, seed in ((0, 0, 1), (1, 1, 2)):
            _ok, dag = audit_dag(ci, di, seed)
            for arm, fn in (
                    ("Q", lambda: run_q(dag)),
                    ("G", lambda: run_g(
                        dag, seed_rng(ci, di, seed, 555), None)),
                    ("R", lambda: run_r(
                        dag, seed_rng(ci, di, seed, 999), None))):
                r = fn()
                if not r["valid"] or r["stopped"]:
                    out["failed"].append("arm-valid-%s" % arm)
        _ok, dag = audit_dag(0, 0, 1)
        g1 = run_g(dag, seed_rng(0, 0, 1, 555), None)
        g2 = run_g(dag, seed_rng(0, 0, 1, 555), None)
        if (g1["layers"], g1["latency"]) != (
                g2["layers"], g2["latency"]):
            out["failed"].append("determinism-greedy")
        r1 = run_r(dag, seed_rng(0, 0, 1, 999), None)
        r2 = run_r(dag, seed_rng(0, 0, 1, 999), None)
        if (r1["layers"], r1["latency"]) != (
                r2["layers"], r2["latency"]):
            out["failed"].append("determinism-random")
        st = run_g(dag, seed_rng(0, 0, 1, 555),
                   lambda: True)
        if not st.get("stopped"):
            out["failed"].append("stop-propagation")
    except Exception as ex:
        out["failed"].append("raise: %r" % ex)
    return out


def run_arm(code_idx, dag_idx, seed, arm, n_iters, stop):
    dag = gen_dag(code_idx, dag_idx, seed)
    if arm == "Q":
        return run_q(dag)
    if arm == "R":
        return run_r(dag, seed_rng(code_idx, dag_idx, seed, 999),
                     stop)
    if arm == "G":
        return run_g(dag, seed_rng(code_idx, dag_idx, seed, 555),
                     stop)
    gstart = earliest_fit(list(range(len(dag["gates"]))), dag)
    g2 = earliest_fit(random_linear_extension(
        dag, seed_rng(code_idx, dag_idx, seed, 555)), dag)
    if len(g2) < len(gstart):
        gstart = g2
    if stop is not None and stop():
        return {"layers": None, "latency": None, "valid": False,
                "stopped": True}
    return run_a(dag, gstart,
                 seed_rng(code_idx, dag_idx, seed, 777), n_iters,
                 stop)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--attempt", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--anneal-iters", type=int, default=A_ITERS)
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

    cells = {}
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
        ex = exact_opt(tiny_dag(), EXACT_CAP, over)
        gate3tiny["arms"]["tiny"] = ex
        gate3tiny["total"] += 1
        if ex["status"] == "solved" and ex["opt_layers"] == \
                TINY_EXP_LAYERS:
            gate3tiny["solved"] += 1
    with open(os.path.join(witdir, "gate3_tiny.json"), "w") as f:
        json.dump(gate3tiny, f, indent=1, default=str)
    checkpoint("tiny")

    if over():
        gate3targets.append({"status": "skipped-guard"})
        skipped.append({"what": "target-exact", "reason": "wall-guard",
                        "iters_done": 0, "n_evaluated": EXACT_CAP})
    else:
        tdg = gen_dag(CODES.index(TARGET["code"]),
                      DAG_IDX[TARGET["dag"]], TARGET["seed"])
        tex = exact_opt(tdg, EXACT_CAP, over)
        gate3targets.append(dict(tex, code=CODE_NAME[tdg["n"]],
                                 dag=tdg["dag"], seed=TARGET["seed"]))
    with open(os.path.join(witdir, "gate3_targets.json"), "w") as f:
        json.dump(gate3targets, f, indent=1, default=str)
    checkpoint("targets")

    def run_cell(ci, di, seed):
        rec = {"code": CODE_NAME[CODES[ci]], "dag": DAGS[di],
               "seed": seed, "arms": {}}
        for arm in ARMS:
            if over():
                rec["blocked"] = "wall-guard"
                return rec
            out = run_arm(ci, di, seed, arm, n_iters, over)
            if out.get("stopped"):
                rec["blocked"] = "stopped-guard"
                rec["iters_done"] = len(rec["arms"])
                rec["n_evaluated"] = len(ARMS)
                return rec
            rec["arms"][arm] = {
                "latency": int(out["latency"]),
                "layers": int(out["layers"]),
                "valid": bool(out["valid"])}
        return rec

    def record_cell(rec):
        if rec.get("blocked") is None and all(
                a in rec["arms"] for a in ARMS):
            for a in ARMS:
                key = (rec["dag"], a)
                cells.setdefault(key, []).append(
                    rec["arms"][a]["latency"])
                valids.setdefault(key, []).append(
                    1 if rec["arms"][a]["valid"] else 0)
            cellrecs.append(rec)
            return True
        cellrecs.append(rec)
        skipped.append({"what": "cell %s/%s/%d" % (
            rec["code"], rec["dag"], rec["seed"]),
            "reason": rec.get("blocked", "arm-incomplete"),
            "iters_done": rec.get("iters_done", len(rec["arms"])),
            "n_evaluated": len(ARMS)})
        return False

    for ci, n in enumerate(CODES):
        if over():
            for di, dag in enumerate(DAGS):
                for seed in SEEDS:
                    skipped.append(
                        {"what": "cell %s/%s/%d" % (
                            CODE_NAME[n], dag, seed),
                         "reason": "wall-guard", "iters_done": 0,
                         "n_evaluated": len(ARMS)})
        else:
            for di, dag in enumerate(DAGS):
                for seed in SEEDS:
                    if over():
                        skipped.append(
                            {"what": "cell %s/%s/%d" % (
                                CODE_NAME[n], dag, seed),
                             "reason": "wall-guard", "iters_done": 0,
                             "n_evaluated": len(ARMS)})
                        continue
                    rec = run_cell(ci, di, seed)
                    record_cell(rec)
        with open(os.path.join(witdir, "cells.json"), "w") as f:
            json.dump(cellrecs, f, indent=1, default=str)
        checkpoint("code%d" % n)
    with open(os.path.join(witdir, "cells.json"), "w") as f:
        json.dump(cellrecs, f, indent=1, default=str)
    checkpoint("corpus")

    def pool(dag, arm, store):
        vals = store.get((dag, arm), [])
        return pooled_stats(vals), len(vals) == 2 * len(SEEDS)

    det1 = run_arm(0, 0, 1, "G", n_iters, None)
    det2 = run_arm(0, 0, 1, "G", n_iters, None)
    det_r1 = run_arm(0, 0, 1, "R", n_iters, None)
    det_r2 = run_arm(0, 0, 1, "R", n_iters, None)
    determinism_ok = bool(
        (det1["latency"], det1["layers"]) == (
            det2["latency"], det2["layers"])
        and (det_r1["latency"], det_r1["layers"]) == (
            det_r2["latency"], det_r2["layers"]))

    g1_cells, g1_beats = [], True
    for ci, n in enumerate(CODES):
        for dag in DAGS:
            for seed in SEEDS:
                mg = next((r["arms"]["G"]["latency"] for r in cellrecs
                           if r.get("blocked") is None
                           and r["code"] == CODE_NAME[n]
                           and r["dag"] == dag
                           and r["seed"] == seed), None)
                mr = next((r["arms"]["R"]["latency"] for r in cellrecs
                           if r.get("blocked") is None
                           and r["code"] == CODE_NAME[n]
                           and r["dag"] == dag
                           and r["seed"] == seed), None)
                ok = (mg is not None and mr is not None and mg < mr)
                g1_cells.append({"cell": "%s/%s/%d" % (
                    CODE_NAME[n], dag, seed),
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
    for dag in DAGS:
        pools, pok = {}, True
        for arm in ("Q", "G", "A"):
            pools[arm], oka = pool(dag, arm, cells)
            pok = pok and oka
        se, spread, gp = spread_win(pools, pok)
        g2_fams.append({"dag": dag, "pools": pools, "SE": se,
                        "spread": spread, "pass": bool(gp)})
        if gp:
            g2_n += 1
        lpools, lpok = {}, True
        for arm in ("Q", "G", "A"):
            lv = [r["arms"][arm]["layers"] for r in cellrecs
                  if r.get("blocked") is None
                  and r["dag"] == dag and arm in r["arms"]]
            lpools[arm] = pooled_stats(lv)
            lpok = lpok and len(lv) == 2 * len(SEEDS)
        sse, sspread, sgp = spread_win(lpools, lpok)
        g2s_fams.append({"dag": dag, "pools": lpools,
                         "SE": sse, "spread": sspread,
                         "pass": bool(sgp)})
        if sgp:
            g2s_n += 1
        joint = {}
        if pok and all(
                pools[a]["se"] is not None and
                pools[a]["mean"] is not None for a in ("Q", "G", "A")):
            sse2 = math.sqrt(sum(pools[a]["se"] ** 2
                                 for a in ("Q", "G", "A")) / 3.0)
            for a in ("G", "A"):
                cwin = pools[a]["mean"] < pools["Q"]["mean"] - \
                    2.0 * sse2
                vv = valids.get((dag, a), [])
                vwin = len(vv) == 2 * len(SEEDS) and all(
                    v == 1 for v in vv)
                joint[a] = bool(cwin and vwin)
        else:
            joint = {"G": False, "A": False}
        for a in ("G", "A"):
            if joint[a]:
                n_win[a] += 1
        winner = ("G" if joint["G"]
                  else ("A" if joint["A"] else None))
        if pok and all(pools[a]["mean"] is not None
                       for a in ("Q", "G", "A")):
            spass = (pools["G"]["mean"] < pools["Q"]["mean"] or
                     pools["A"]["mean"] < pools["Q"]["mean"])
        else:
            spass = False
            pools_all = False
        if not pok:
            pools_all = False
        if spass:
            n_strict += 1
        win_fams.append({"dag": dag, "joint": dict(joint),
                         "winner": winner, "strict_win": bool(spass),
                         "pools_ok": bool(pok)})
    g2_ok = g2_n >= 2

    tiny_solved = (gate3tiny["total"] == 1 and gate3tiny["solved"] == 1)
    target_cap = (len(gate3targets) == 1 and
                  gate3targets[0].get("status") == "cap-hit")
    g3pass = bool(tiny_solved and target_cap)

    nrec = sum(1 for r in cellrecs if r.get("blocked") is None)
    complete = (nrec == 2 * len(DAGS) * len(SEEDS) and all(
        len(cells.get((dag, a), [])) == 2 * len(SEEDS)
        for dag in DAGS for a in ARMS))
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
        reason = "PURSUE-condition holds (parallel schedule latency " \
            "win + 100%% validity on the SAME arm at >=2 DAG sizes " \
            "+ gates 1,2,3,4 + self-tests ok); payload verdict stays " \
            "unresolved-with-reason, classification is coordinator-side."
    elif reject:
        reason = "REJECT-condition holds (complete cells, tiny " \
            "solved, Gate-1 controls pass, no strict pooled latency " \
            "win at any DAG); payload verdict stays " \
            "unresolved-with-reason, classification is coordinator-side."
    else:
        reason = "UNRESOLVED + next experiment (joint wins G=%d/3, " \
            "A=%d/3, strict wins=%d/3, g1=%s g2=%s " \
            "g2s(layers-spread)=%s g3=%s (tiny solved=%s, target " \
            "cap-hit=%s) selftest=%s g4=%s complete=%s skipped=%d; " \
            "next: logical-remapping co-optimization + multi-shift " \
            "gate retest)." % (
                n_win["G"], n_win["A"], n_strict, g1_ok, g2_ok,
                g2s_n >= 2, g3pass, tiny_solved, target_cap,
                selftest_ok, g4_ok, complete, len(skipped))
    verdict_bits = {
        "gate1": {"pass": bool(g1_ok), "beats_all_30": bool(g1_beats),
                  "tiny_ok": bool(tiny_ok),
                  "determinism_ok": bool(determinism_ok),
                  "cells": g1_cells},
        "gate2": {"pass": bool(g2_ok), "n_dags_pass": g2_n,
                  "dags": g2_fams},
        "gate2_s": {"pass": bool(g2s_n >= 2), "n_dags_pass": g2s_n,
                    "dags": g2s_fams},
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
                       "win_dags": win_fams, "n_strict_win": n_strict,
                       "pools_all": bool(pools_all),
                       "selftest_ok": bool(selftest_ok)},
        "reason": reason,
    }

    results = {
        "screen": "08",
        "verdict": "unresolved-with-reason: payload reports numbers "
                   "and gate evidence; classification is coordinator-side.",
        "design": {
            "model": "screen-authored deterministic transversal-layer "
                     "scheduler (stdlib + numpy only; no external libs)",
            "codes": ["C8 (n=8, shifts [1,2,3])",
                      "C12 (n=12, shifts [1,3,4])"],
            "dags": ["S=12 gates", "M=20 gates", "L=28 gates"],
            "seeds": list(SEEDS),
            "rounds_per_layer": ROUNDS_PER_LAYER,
            "anneal": {"iters": n_iters, "t0": A_T0,
                       "alpha": A_ALPHA},
            "arms": {"Q": "sequential single-gate addressing "
                          "(one gate per layer)",
                     "R": "random layer-packing control (random order, "
                          "random feasible layer)",
                     "G": "greedy earliest-fit (canonical + one seeded "
                          "restart, best tracked)",
                     "A": "simulated annealing over shift + layer "
                          "assignments from G (best tracked)"},
            "metrics": "total syndrome-round latency (layers x 2) + "
                       "schedule-validity verification (alignment, "
                       "disjointness, DAG order)",
            "pareto": "PURSUE needs a latency win + 100% validity on "
                      "the SAME arm; joint wins counted PER ARM with "
                      "bar max(G,A)>=2, never any-winner",
            "exact": "bounded-exact layer-packing search on tiny "
                     "(must solve, optimum %d layers) + target-scale "
                     "instance (C12 code, L DAG, seed 1, 28 gates, "
                     "node cap %d, must cap-hit)" % (
                         TINY_EXP_LAYERS, EXACT_CAP),
        },
        "timing": {"wall_s": wall, "guards": {"wall_guard_s": WALL_GUARD_S,
                                              "limit_s": WALL_LIMIT_S}},
        "cells": {("%s/%s" % k): {"n": len(v),
                                  **pooled_stats(v),
                                  "valid_rate": (
                                      sum(valids.get(k, []))
                                      / len(valids[k])
                                      if valids.get(k) else None)}
                  for k, v in cells.items()},
        "gates": verdict_bits,
        "skipped": skipped,
    }
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)


if __name__ == "__main__":
    main()
