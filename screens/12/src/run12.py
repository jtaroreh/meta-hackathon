"""Screen 12 payload: mid-circuit measurement & qubit-reuse topological scheduling.

Screen-authored deterministic reuse-scheduling simulator (stdlib + numpy
only; no MILP/SMT/OLSQA/Vandaele/Lau/PhasePoly/torch anywhere): logical CNOT
circuits on W in {24, 32, 40} wires from a birth/death active-pool generator
(bounded live width, causal cones = per-wire gate chains), mapped onto 16
physical qubits on a frozen 4x4 2D grid with mid-circuit reset-and-reuse.
Arms choose topological gate orderings + reuse targets: G greedy
earliest-reuse (width-minimizing baseline), B routing-aware beam search, A
routing-aware annealing, R random control. Metric: total routed CNOT count +
two-qubit depth at fixed physical width. A bounded-exact DFS validates the
tiny instance (solved, optimum by construction) and cap-hits at target scale
(limit-expiry). Writes ALL output under cwd (the attempt work dir):
results.json + witnesses/. Deterministic given seeds. Verdict is always
unresolved-with-reason; classification is coordinator-side.
"""

import argparse
import json
import math
import os
import time

import numpy as np

FAMILIES = (24, 32, 40)
PHYS_N = 16
GRID_W = 4
SEEDS = (1, 2, 3, 4, 5)
ARMS = ("G", "B", "A", "R")

N_INST = 36
GATES_PER_WIRE = 8
ACTIVE_INIT = 12
ACTIVE_LO = 10
P_RETIRE = 0.35

BEAM_W = 10
BEAM_BRANCH = 5
ANNEAL_ITERS = 500
ANNEAL_T0 = 2.0
ANNEAL_ALPHA = 0.99
DEPTH_W = 5.0

WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0
EXACT_CAP = 50000

TINY_GATES = ((0, 1), (1, 2))
TINY_EXP = {"cnots": 2, "depth": 2}
TARGET_FAM = 0
TARGET_SEED = 1
TARGET_REP = 0

DIST = [[0] * PHYS_N for _ in range(PHYS_N)]
for _i in range(PHYS_N):
    for _j in range(PHYS_N):
        DIST[_i][_j] = abs(_i // GRID_W - _j // GRID_W) + abs(
            _i % GRID_W - _j % GRID_W)


def seed_rng(fam_idx, seed, rep, salt):
    return np.random.default_rng(
        (int(fam_idx * 100003 + seed * 10007 + rep * 101 + salt * 1000003)
         % (2 ** 63 - 1)))


def gen_circuit(fam_idx, seed, rep):
    """Birth/death active-pool generator: exactly W distinct wires, live set
    bounded by the active pool (<= 14). Deterministic given inputs."""
    W = FAMILIES[fam_idx]
    n_gates = GATES_PER_WIRE * W
    rng = seed_rng(fam_idx, seed, rep, 11)
    active = list(range(ACTIVE_INIT))
    counts = {w: 0 for w in active}
    uncovered = set(active)
    next_id = ACTIVE_INIT
    gates = []
    for t in range(n_gates):
        if uncovered and (n_gates - t) <= len(uncovered) * 2 + 2:
            a = min(uncovered)
            rest = [w for w in active if w != a]
            b = rest[int(rng.integers(len(rest)))]
        else:
            pair = rng.choice(active, 2, replace=False)
            a, b = int(pair[0]), int(pair[1])
        gates.append((a, b))
        counts[a] += 1
        counts[b] += 1
        uncovered.discard(a)
        uncovered.discard(b)
        if next_id < W:
            must = (n_gates - t - 1) <= (W - next_id) * 2
            if bool(rng.random() < P_RETIRE) or must:
                cands = [w for w in active
                         if w != a and w != b and counts[w] >= 1
                         and len(active) > ACTIVE_LO]
                if cands:
                    out = cands[0]
                    active.remove(out)
                    active.append(next_id)
                    counts[next_id] = 0
                    uncovered.add(next_id)
                    next_id += 1
    return {"gates": gates, "W": W}


def build_dag(gates):
    n = len(gates)
    preds = [set() for _ in range(n)]
    succs = [set() for _ in range(n)]
    last = {}
    for i, (a, b) in enumerate(gates):
        for w in (a, b):
            if w in last:
                preds[i].add(last[w])
                succs[last[w]].add(i)
            last[w] = i
    return preds, succs


def wire_neighbors(gates, W):
    nbrs = [set() for _ in range(W)]
    for (a, b) in gates:
        nbrs[a].add(b)
        nbrs[b].add(a)
    return nbrs


def route_pick(w, free, phys, nbrs):
    """Free physical minimizing summed grid distance to already-placed
    neighboring wires; lowest index breaks ties (and wins when no neighbor
    is placed yet)."""
    placed = [u for u in nbrs[w] if u in phys]
    best_q = None
    best_s = None
    for q in sorted(free):
        s = 0
        for u in placed:
            s += DIST[q][phys[u]]
        if best_s is None or s < best_s:
            best_s = s
            best_q = q
    return best_q


def eval_schedule(gates, order, place_mode, rng, nbrs):
    """List-schedule an order with reset-and-reuse placement. Returns
    (routed_cnots, depth, evictions). Eviction (no free physical) takes the
    resident with furthest next use, +6 routed CNOTs, +2 time units."""
    n = len(order)
    occ = {}
    for p, g in enumerate(order):
        for w in gates[g]:
            occ.setdefault(w, []).append(p)
    rem = {w: len(ps) for w, ps in occ.items()}
    phys = {}
    free = set(range(PHYS_N))
    ft = [0] * PHYS_N
    cnots = 0
    evict = 0
    for p, g in enumerate(order):
        a, b = gates[g]
        for w in (a, b):
            if w not in phys:
                if free:
                    if place_mode == "earliest":
                        q = min(free)
                    elif place_mode == "route":
                        q = route_pick(w, free, phys, nbrs)
                    else:
                        q = int(rng.choice(sorted(free)))
                    free.discard(q)
                    phys[w] = q
                else:
                    best_w = None
                    best_nxt = -1
                    for w2 in phys:
                        if w2 == a or w2 == b:
                            continue
                        nxt = occ[w2][-1]
                        for _pp in occ[w2]:
                            if _pp > p:
                                nxt = _pp
                                break
                        if nxt > best_nxt or (
                                nxt == best_nxt and (
                                    best_w is None or w2 > best_w)):
                            best_nxt = nxt
                            best_w = w2
                    q = phys.pop(best_w)
                    ft[q] += 2
                    cnots += 6
                    evict += 1
                    free.add(q)
                    if place_mode == "earliest":
                        q2 = min(free)
                    elif place_mode == "route":
                        q2 = route_pick(w, free, phys, nbrs)
                    else:
                        q2 = int(rng.choice(sorted(free)))
                    free.discard(q2)
                    phys[w] = q2
        pa, pb = phys[a], phys[b]
        d = DIST[pa][pb]
        cnots += 3 * d - 2
        dur = 2 * d - 1
        start = ft[pa] if ft[pa] >= ft[pb] else ft[pb]
        end = start + dur
        ft[pa] = end
        ft[pb] = end
        for w in (a, b):
            rem[w] -= 1
            if rem[w] == 0:
                free.add(phys.pop(w))
    return int(cnots), int(max(ft)), int(evict)


def kahn_rng(preds, succs, rng):
    n = len(preds)
    rem = [len(preds[i]) for i in range(n)]
    ready = [i for i in range(n) if rem[i] == 0]
    order = []
    while ready:
        idx = int(rng.integers(len(ready)))
        g = ready.pop(idx)
        order.append(g)
        for s in succs[g]:
            rem[s] -= 1
            if rem[s] == 0:
                ready.append(s)
    return order


def kahn_keys(preds, succs, keys):
    n = len(preds)
    rem = [len(preds[i]) for i in range(n)]
    ready = [i for i in range(n) if rem[i] == 0]
    order = []
    while ready:
        ready.sort(key=lambda g: (keys[g], g))
        g = ready.pop(0)
        order.append(g)
        for s in succs[g]:
            rem[s] -= 1
            if rem[s] == 0:
                ready.append(s)
    return order


def run_greedy(gates, nbrs):
    order = list(range(len(gates)))
    c, d, e = eval_schedule(gates, order, "earliest", None, nbrs)
    return {"cnots": c, "depth": d, "evict": e, "stopped": False}


def run_random(gates, preds, succs, nbrs, rng):
    order = kahn_rng(preds, succs, rng)
    c, d, e = eval_schedule(gates, order, "random", rng, nbrs)
    return {"cnots": c, "depth": d, "evict": e, "stopped": False}


def beam_run(gates, preds, succs, nbrs, stop):
    """Routing-aware beam search over topological orders with greedy
    routing-aware placement. State score = routed CNOTs + DEPTH_W * makespan
    so far + 1 per unscheduled gate. Returns best re-evaluated solution."""
    n = len(gates)
    occ = {}
    for gi, (a, b) in enumerate(gates):
        occ.setdefault(a, []).append(gi)
        occ.setdefault(b, []).append(gi)

    def fresh_state():
        return {"sched": bytearray(n), "rem": [len(preds[i])
                                               for i in range(n)],
                "remw": {w: len(v) for w, v in occ.items()},
                "phys": {}, "free": set(range(PHYS_N)),
                "ft": [0] * PHYS_N, "acc": 0, "ms": 0, "order": []}

    def deaths(st, g):
        for w in gates[g]:
            st["remw"][w] -= 1
            if st["remw"][w] == 0 and w in st["phys"]:
                st["free"].add(st["phys"].pop(w))

    def place_cost(st, g):
        """Tentative (cost, dur, start, assignment, evictions) for
        scheduling g next. Evicts the resident with most remaining gates
        (never a current endpoint) when no physical is free."""
        a, b = gates[g]
        cur = dict(st["phys"])
        cfree = set(st["free"])
        asg = {}
        ev = []
        for w in (a, b):
            if w not in cur:
                if not cfree:
                    cands = [w2 for w2 in cur if w2 != a and w2 != b]
                    if not cands:
                        return None
                    victim = max(cands, key=lambda w2: (
                        st["remw"][w2], w2))
                    qv = cur.pop(victim)
                    ev.append((victim, qv))
                    cfree.add(qv)
                asg[w] = route_pick(w, cfree, cur, nbrs)
                cfree.discard(asg[w])
                cur[w] = asg[w]
        pa, pb = cur[a], cur[b]
        d = DIST[pa][pb]
        pen = 6 * len(ev)
        fta = st["ft"][pa] + (2 if any(q == pa for _, q in ev) else 0)
        ftb = st["ft"][pb] + (2 if any(q == pb for _, q in ev) else 0)
        start = fta if fta >= ftb else ftb
        return (3 * d - 2 + pen, 2 * d - 1, start, asg, pa, pb, ev)

    beam = [fresh_state()]
    for step in range(n):
        if step % 32 == 0 and stop is not None and stop():
            return {"cnots": None, "depth": None, "evict": None,
                    "stopped": True}
        pool = []
        for st in beam:
            if len(st["order"]) == n:
                pool.append((st["acc"] + DEPTH_W * st["ms"], tuple(
                    st["order"]), st))
                continue
            ready = [g for g in range(n)
                     if not st["sched"][g] and st["rem"][g] == 0]
            scored = []
            for g in ready:
                pc = place_cost(st, g)
                if pc is None:
                    continue
                scored.append((pc[0], g, pc))
            scored.sort(key=lambda t: (t[0], t[1]))
            for _, g, pc in scored[:BEAM_BRANCH]:
                cost, dur, start, asg, pa, pb, ev = pc
                ns = {"sched": bytearray(st["sched"]),
                      "rem": list(st["rem"]),
                      "remw": dict(st["remw"]),
                      "phys": dict(st["phys"]),
                      "free": set(st["free"]),
                      "ft": list(st["ft"]), "acc": st["acc"] + cost,
                      "ms": st["ms"], "order": list(st["order"])}
                for victim, qv in ev:
                    del ns["phys"][victim]
                    ns["free"].add(qv)
                    ns["ft"][qv] += 2
                for w, q in asg.items():
                    ns["free"].discard(q)
                    ns["phys"][w] = q
                end = start + dur
                ns["ft"][pa] = end
                ns["ft"][pb] = end
                if end > ns["ms"]:
                    ns["ms"] = end
                ns["sched"][g] = 1
                ns["order"].append(g)
                for s in succs[g]:
                    ns["rem"][s] -= 1
                deaths(ns, g)
                score = (ns["acc"] + DEPTH_W * ns["ms"]
                         + 1.0 * (n - len(ns["order"])))
                pool.append((score, tuple(ns["order"]), ns))
        pool.sort(key=lambda t: (t[0], t[1]))
        beam = [t[2] for t in pool[:BEAM_W]]
        if all(len(st["order"]) == n for st in beam):
            break
    done = [st for st in beam if len(st["order"]) == n]
    if not done:
        return {"cnots": None, "depth": None, "evict": None,
                "stopped": True}
    done.sort(key=lambda st: (st["acc"] + DEPTH_W * st["ms"],
                              tuple(st["order"])))
    order = done[0]["order"]
    c, d, e = eval_schedule(gates, order, "route", None, nbrs)
    return {"cnots": c, "depth": d, "evict": e, "stopped": False}


def anneal_run(gates, preds, succs, nbrs, rng, n_iters, stop):
    """Routing-aware annealing over priority-key topological orders with
    greedy routing-aware placement; cost = routed CNOTs + DEPTH_W * depth.
    Starts at the canonical order; tracks best."""
    n = len(gates)
    keys = [float(i) for i in range(n)]
    order = kahn_keys(preds, succs, keys)
    c, d, _e = eval_schedule(gates, order, "route", None, nbrs)
    best = (c + DEPTH_W * d, c, d, list(order))
    cur = (c + DEPTH_W * d, list(keys))
    temp = ANNEAL_T0
    for it in range(n_iters):
        if it % 32 == 0 and stop is not None and stop():
            break
        j = int(rng.integers(n))
        old = keys[j]
        keys[j] = float(rng.random() * n)
        order2 = kahn_keys(preds, succs, keys)
        c2, d2, _e2 = eval_schedule(gates, order2, "route", None, nbrs)
        cost2 = c2 + DEPTH_W * d2
        if cost2 < cur[0] or bool(
                rng.random() < math.exp(-(cost2 - cur[0]) / temp)):
            cur = (cost2, None)
            if cost2 < best[0]:
                best = (cost2, c2, d2, list(order2))
        else:
            keys[j] = old
        temp *= ANNEAL_ALPHA
    return {"cnots": int(best[1]), "depth": int(best[2]), "evict": 0,
            "stopped": False}


def exact_opt(gates, W, cap, stop):
    """Bounded-exact DFS over topological orders x reuse-target choices,
    minimizing routed CNOTs (eviction branches included). Statuses: solved /
    cap-hit / stopped-guard."""
    n = len(gates)
    preds, succs = build_dag(gates)
    rem = [len(preds[i]) for i in range(n)]
    sched = bytearray(n)
    occ = {}
    for gi, (a, b) in enumerate(gates):
        occ.setdefault(a, []).append(gi)
        occ.setdefault(b, []).append(gi)
    remw = {w: len(v) for w, v in occ.items()}
    phys = {}
    free = set(range(PHYS_N))
    ft = [0] * PHYS_N
    acc = [0]
    nodes = [0]
    capped = [False]
    stopped = [False]
    best = [None]
    order = []

    def rec():
        if capped[0] or stopped[0]:
            return
        nodes[0] += 1
        if nodes[0] > cap:
            capped[0] = True
            return
        if nodes[0] % 512 == 0 and stop is not None and stop():
            stopped[0] = True
            return
        if len(order) == n:
            if best[0] is None or acc[0] < best[0][0]:
                best[0] = (acc[0], max(ft), tuple(order))
            return
        if best[0] is not None and acc[0] + (n - len(order)) >= best[0][0]:
            return
        for g in range(n):
            if sched[g] or rem[g] != 0:
                continue
            a, b = gates[g]
            news = [w for w in (a, b) if w not in phys]
            if not news:
                opts = [()]
            elif len(news) == 1:
                opts = [(q,) for q in sorted(free)] if free else [None]
            else:
                if len(free) >= 2:
                    fl = sorted(free)
                    opts = [(q1, q2) for q1 in fl for q2 in fl
                            if q2 != q1]
                else:
                    opts = [None]
            for opt in opts:
                if opt is None:
                    victims = sorted(phys, key=lambda w2: (
                        -len(occ[w2]), w2))
                    victim = victims[0]
                    qv = phys.pop(victim)
                    ft[qv] += 2
                    acc[0] += 6
                    free.add(qv)
                    news2 = [w for w in (a, b) if w not in phys]
                    fl = sorted(free)
                    if len(news2) == 1:
                        oo = [(x,) for x in fl]
                    else:
                        oo = [(x1, x2) for x1 in fl for x2 in fl
                              if x2 != x1]
                    for cand in oo:
                        undo2 = []
                        for w, q in zip(news2, cand):
                            phys[w] = q
                            free.discard(q)
                            undo2.append((w, q))
                        pa, pb = phys[a], phys[b]
                        dd = DIST[pa][pb]
                        st0 = ft[pa] if ft[pa] >= ft[pb] else ft[pb]
                        en = st0 + 2 * dd - 1
                        olda, oldb = ft[pa], ft[pb]
                        ft[pa], ft[pb] = en, en
                        acc[0] += 3 * dd - 2
                        sched[g] = 1
                        order.append(g)
                        for s in succs[g]:
                            rem[s] -= 1
                        freed = []
                        for w in (a, b):
                            remw[w] -= 1
                            if remw[w] == 0 and w in phys:
                                freed.append((w, phys.pop(w)))
                                free.add(freed[-1][1])
                        rec()
                        for w, q in freed:
                            free.discard(q)
                            phys[w] = q
                        for w in (a, b):
                            remw[w] += 1
                        for s in succs[g]:
                            rem[s] += 1
                        order.pop()
                        sched[g] = 0
                        ft[pa], ft[pb] = olda, oldb
                        acc[0] -= 3 * dd - 2
                        for w, q in undo2:
                            free.add(q)
                            del phys[w]
                        if capped[0] or stopped[0]:
                            break
                    free.discard(qv)
                    phys[victim] = qv
                    ft[qv] -= 2
                    acc[0] -= 6
                    if capped[0] or stopped[0]:
                        return
                    continue
                undo_asg = []
                for w, q in zip(news, opt):
                    phys[w] = q
                    free.discard(q)
                    undo_asg.append((w, q))
                pa, pb = phys[a], phys[b]
                dd = DIST[pa][pb]
                st0 = ft[pa] if ft[pa] >= ft[pb] else ft[pb]
                en = st0 + 2 * dd - 1
                olda, oldb = ft[pa], ft[pb]
                ft[pa], ft[pb] = en, en
                acc[0] += 3 * dd - 2
                sched[g] = 1
                order.append(g)
                for s in succs[g]:
                    rem[s] -= 1
                freed = []
                for w in (a, b):
                    remw[w] -= 1
                    if remw[w] == 0 and w in phys:
                        freed.append((w, phys.pop(w)))
                        free.add(freed[-1][1])
                rec()
                for w, q in freed:
                    free.discard(q)
                    phys[w] = q
                for w in (a, b):
                    remw[w] += 1
                for s in succs[g]:
                    rem[s] += 1
                order.pop()
                sched[g] = 0
                ft[pa], ft[pb] = olda, oldb
                acc[0] -= 3 * dd - 2
                for w, q in undo_asg:
                    free.add(q)
                    del phys[w]
                if capped[0] or stopped[0]:
                    return

    rec()
    if stopped[0]:
        return {"status": "stopped-guard", "nodes": nodes[0],
                "opt_cnots": best[0][0] if best[0] else None,
                "opt_depth": best[0][1] if best[0] else None,
                "cap": cap, "started": True}
    if capped[0]:
        return {"status": "cap-hit", "nodes": nodes[0],
                "opt_cnots": best[0][0] if best[0] else None,
                "opt_depth": best[0][1] if best[0] else None,
                "cap": cap, "started": True}
    return {"status": "solved", "nodes": nodes[0],
            "opt_cnots": best[0][0] if best[0] else None,
            "opt_depth": best[0][1] if best[0] else None,
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


def audit_circuit(fam_idx, seed, rep):
    circ = gen_circuit(fam_idx, seed, rep)
    gates = circ["gates"]
    W = circ["W"]
    wires = set()
    for (a, b) in gates:
        wires.add(a)
        wires.add(b)
    first = {}
    last = {}
    for i, (a, b) in enumerate(gates):
        for w in (a, b):
            if w not in first:
                first[w] = i
            last[w] = i
    live_max = 0
    for t in range(len(gates)):
        live = sum(1 for w in wires if first[w] <= t <= last[w])
        if live > live_max:
            live_max = live
    return {"coverage_ok": len(wires) == W and min(wires) == 0
            and max(wires) == W - 1,
            "n_gates_ok": len(gates) == GATES_PER_WIRE * W,
            "live_max": live_max}


def self_tests():
    out = {"ran": True, "failed": []}
    try:
        for fi in range(len(FAMILIES)):
            for rep in (0, 1):
                au = audit_circuit(fi, 1, rep)
                if not au["coverage_ok"]:
                    out["failed"].append("gen-cover-%d-%d" % (fi, rep))
                if not au["n_gates_ok"]:
                    out["failed"].append("gen-count-%d-%d" % (fi, rep))
                if au["live_max"] > PHYS_N - 1:
                    out["failed"].append("gen-live-%d-%d" % (fi, rep))
        tiny_preds, tiny_succs = build_dag(list(TINY_GATES))
        tiny_nbrs = wire_neighbors(list(TINY_GATES), 3)
        tiny_expect = {"G": None, "B": None, "A": None}
        tg = run_greedy(list(TINY_GATES), tiny_nbrs)
        tiny_expect["G"] = (tg["cnots"], tg["depth"])
        tb = beam_run(list(TINY_GATES), tiny_preds, tiny_succs,
                      tiny_nbrs, None)
        tiny_expect["B"] = (tb["cnots"], tb["depth"])
        ta = anneal_run(list(TINY_GATES), tiny_preds, tiny_succs,
                        tiny_nbrs, seed_rng(0, 7, 7, 5), 50, None)
        tiny_expect["A"] = (ta["cnots"], ta["depth"])
        for arm, (cc, dd) in tiny_expect.items():
            if cc != TINY_EXP["cnots"] or dd != TINY_EXP["depth"]:
                out["failed"].append("tiny-%s-hand" % arm)
        tex = exact_opt(list(TINY_GATES), 3, EXACT_CAP, None)
        if tex["status"] != "solved" or tex["opt_cnots"] != TINY_EXP[
                "cnots"]:
            out["failed"].append("tiny-exact-opt")
        circ = gen_circuit(0, 1, 0)
        preds, succs = build_dag(circ["gates"])
        nbrs = wire_neighbors(circ["gates"], circ["W"])
        c1 = eval_schedule(circ["gates"], list(range(
            len(circ["gates"]))), "earliest", None, nbrs)
        c2 = eval_schedule(circ["gates"], list(range(
            len(circ["gates"]))), "earliest", None, nbrs)
        if c1 != c2:
            out["failed"].append("determinism")
        r1 = run_random(circ["gates"], preds, succs, nbrs,
                        seed_rng(0, 1, 0, 999))
        r2 = run_random(circ["gates"], preds, succs, nbrs,
                        seed_rng(0, 1, 0, 999))
        if (r1["cnots"], r1["depth"]) != (r2["cnots"], r2["depth"]):
            out["failed"].append("determinism-random")
    except Exception as ex:
        out["failed"].append("raise: %r" % ex)
    return out


def run_arm(fam_idx, seed, rep, arm, n_iters, stop):
    circ = gen_circuit(fam_idx, seed, rep)
    gates = circ["gates"]
    W = circ["W"]
    preds, succs = build_dag(gates)
    nbrs = wire_neighbors(gates, W)
    if arm == "G":
        return run_greedy(gates, nbrs)
    if arm == "R":
        return run_random(gates, preds, succs, nbrs,
                          seed_rng(fam_idx, seed, rep, 999))
    if arm == "B":
        return beam_run(gates, preds, succs, nbrs, stop)
    return anneal_run(gates, preds, succs, nbrs,
                      seed_rng(fam_idx, seed, rep, 555), n_iters, stop)


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
        ex = exact_opt(list(TINY_GATES), 3, EXACT_CAP, over)
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
        tcirc = gen_circuit(TARGET_FAM, TARGET_SEED, TARGET_REP)
        tex = exact_opt(tcirc["gates"], tcirc["W"], EXACT_CAP, over)
        gate3targets.append(tex)
    with open(os.path.join(witdir, "gate3_targets.json"), "w") as f:
        json.dump(gate3targets, f, indent=1, default=str)
    checkpoint("targets")

    def run_cell(fam_idx, seed):
        W = FAMILIES[fam_idx]
        rec = {"family": W, "seed": seed, "arms": {}}
        for arm in ARMS:
            if over():
                rec["blocked"] = "wall-guard"
                return rec
            cn, dp, ev = [], [], []
            nstop = 0
            for rep in range(n_inst):
                if rep % 32 == 0 and over():
                    nstop += 1
                    break
                out = run_arm(fam_idx, seed, rep, arm, n_iters, over)
                if out.get("stopped"):
                    nstop += 1
                    break
                cn.append(out["cnots"])
                dp.append(out["depth"])
                ev.append(out["evict"])
            if nstop:
                rec["blocked"] = "stopped-guard"
                rec["iters_done"] = len(cn)
                rec["n_evaluated"] = n_inst
                return rec
            rec["arms"][arm] = {
                "n": len(cn),
                "cnots": pooled_stats(cn),
                "depth": pooled_stats(dp),
                "evict": pooled_stats(ev)}
        return rec

    def record_cell(rec):
        if rec.get("blocked") is None and all(
                rec["arms"].get(a, {}).get("n") == n_inst
                for a in ARMS):
            for a in ARMS:
                key = (rec["family"], rec["seed"], a)
                cells.setdefault(key, {"cnots": [], "depth": []})
                cells[key]["cnots"].append(
                    rec["arms"][a]["cnots"]["mean"])
                cells[key]["depth"].append(
                    rec["arms"][a]["depth"]["mean"])
            return True
        skipped.append({"what": "cell %d/%d" % (
            rec["family"], rec["seed"]),
            "reason": rec.get("blocked", "arm-incomplete"),
            "iters_done": rec.get("iters_done", 0),
            "n_evaluated": n_inst})
        return False

    for fi, W in enumerate(FAMILIES):
        fam_cells = [(fi, seed) for seed in SEEDS]
        if over():
            for (f2, sd2) in fam_cells:
                skipped.append({"what": "cell %d/%d" % (
                    FAMILIES[f2], sd2), "reason": "wall-guard",
                    "iters_done": 0, "n_evaluated": n_inst})
        else:
            for (f2, sd2) in fam_cells:
                if over():
                    skipped.append({"what": "cell %d/%d" % (
                        FAMILIES[f2], sd2), "reason": "wall-guard",
                        "iters_done": 0, "n_evaluated": n_inst})
                    continue
                rec = run_cell(f2, sd2)
                cellrecs.append(rec)
                record_cell(rec)
        with open(os.path.join(witdir, "cells.json"), "w") as f:
            json.dump(cellrecs, f, indent=1, default=str)
        checkpoint("fam%d" % W)
    with open(os.path.join(witdir, "cells.json"), "w") as f:
        json.dump(cellrecs, f, indent=1, default=str)
    checkpoint("corpus")

    def cell_mean(W, seed, arm, field):
        return cells.get((W, seed, arm),
                         {"cnots": [], "depth": []})[field]

    def pool(W, arm, field):
        vals = []
        for seed in SEEDS:
            vals.extend(cell_mean(W, seed, arm, field))
        return pooled_stats(vals), len(vals) == len(SEEDS)

    gcirc = gen_circuit(0, 1, 0)
    gpreds, gsuccs = build_dag(gcirc["gates"])
    gnbrs = wire_neighbors(gcirc["gates"], gcirc["W"])
    det1 = run_arm(0, 1, 0, "G", n_iters, None)
    det2 = run_arm(0, 1, 0, "G", n_iters, None)
    det_r1 = run_arm(0, 1, 0, "R", n_iters, None)
    det_r2 = run_arm(0, 1, 0, "R", n_iters, None)
    _ = (gpreds, gsuccs, gnbrs)
    determinism_ok = bool(
        (det1["cnots"], det1["depth"]) == (det2["cnots"],
                                          det2["depth"])
        and (det_r1["cnots"], det_r1["depth"]) == (det_r2["cnots"],
                                                  det_r2["depth"]))

    g1_cells, g1_beats = [], True
    for W in FAMILIES:
        for seed in SEEDS:
            ms = cell_mean(W, seed, "G", "cnots")
            mr = cell_mean(W, seed, "R", "cnots")
            ok = (len(ms) == 1 and len(mr) == 1 and ms[0] < mr[0])
            g1_cells.append({"cell": "%d/%d" % (W, seed),
                             "mean_G": ms[0] if ms else None,
                             "mean_R": mr[0] if mr else None,
                             "pass": bool(ok)})
            if not ok:
                g1_beats = False
    g1_ok = bool(g1_beats and tiny_ok and determinism_ok)

    g2_fams, g2_n = [], 0
    g2s_fams, g2s_n = [], 0
    win_fams, win_n = [], 0
    for W in FAMILIES:
        pools, pok = {}, True
        for arm in ("G", "B", "A"):
            pools[arm], oka = pool(W, arm, "cnots")
            pok = pok and oka
        se, spread, gp = spread_win(pools, pok)
        g2_fams.append({"family": W, "pools": pools, "SE": se,
                        "spread": spread, "pass": bool(gp)})
        if gp:
            g2_n += 1
        spools, spok = {}, True
        for arm in ("G", "B", "A"):
            spools[arm], oka = pool(W, arm, "depth")
            spok = spok and oka
        sse, sspread, sgp = spread_win(spools, spok)
        g2s_fams.append({"family": W, "pools": spools,
                         "SE": sse, "spread": sspread,
                         "pass": bool(sgp)})
        if sgp:
            g2s_n += 1
        joint = {}
        if pok and spok and all(
                pools[a]["se"] is not None and
                pools[a]["mean"] is not None for a in ("G", "B", "A")):
            sse2 = math.sqrt(sum(pools[a]["se"] ** 2
                                 for a in ("G", "B", "A")) / 3.0)
            for a in ("B", "A"):
                cwin = pools[a]["mean"] < pools["G"]["mean"] - 2.0 * sse2
                cok = spools[a]["mean"] <= spools["G"]["mean"]
                joint[a] = bool(cwin and cok)
        else:
            joint = {"B": False, "A": False}
        winner = ("B" if joint["B"]
                  else ("A" if joint["A"] else None))
        wpass = winner is not None
        if pok and all(pools[a]["mean"] is not None
                       for a in ("G", "B", "A")):
            spass = (pools["B"]["mean"] < pools["G"]["mean"] or
                     pools["A"]["mean"] < pools["G"]["mean"])
        else:
            spass = False
        win_fams.append({"family": W, "win": bool(wpass),
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
        len(cell_mean(W, seed, arm, "cnots")) == 1
        for W in FAMILIES for seed in SEEDS for arm in ARMS)
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
        reason = "PURSUE-condition holds (routing-aware joint CNOT win " \
            "+ depth no-regress on the SAME arm at >=2 wire counts + " \
            "gates 1,2,3,4 + self-tests ok); payload verdict stays " \
            "unresolved-with-reason, classification is coordinator-side."
    elif reject:
        reason = "REJECT-condition holds (complete cells, tiny solved, " \
            "Gate-1 controls pass, no strict pooled routing-aware CNOT " \
            "win at any wire count); payload verdict stays " \
            "unresolved-with-reason, classification is coordinator-side."
    else:
        reason = "UNRESOLVED + next experiment (joint wins=%d/3, " \
            "strict routing-aware wins=%d/3, g1=%s g2=%s " \
            "g2s(depth-spread)=%s g3=%s (tiny solved=%s, target " \
            "cap-hit=%s) selftest=%s g4=%s complete=%s skipped=%d; " \
            "next: explicit live-range-split cone-block families with " \
            "wider beam + depth-regularized annealing retest)." % (
                win_n, strict_n, g1_ok, g2_ok, g2s_n >= 2, g3pass,
                tiny_solved, target_cap,
                selftest_ok, g4_ok, complete, len(skipped))
    verdict_bits = {
        "gate1": {"pass": bool(g1_ok), "beats_all_15": bool(g1_beats),
                  "tiny_ok": bool(tiny_ok),
                  "determinism_ok": bool(determinism_ok),
                  "cells": g1_cells},
        "gate2": {"pass": bool(g2_ok), "n_families_pass": g2_n,
                  "families": g2_fams},
        "gate2_s": {"pass": bool(g2s_n >= 2), "n_families_pass": g2s_n,
                    "families": g2s_fams},
        "gate3": {"pass": bool(g3pass), "tiny_solved": tiny_solved,
                  "tiny": gate3tiny,
                  "targets": gate3targets, "target_cap": target_cap},
        "gate4": {"pass": bool(g4_ok), "complete": bool(complete),
                  "tiny_attempted": bool(tiny_attempted),
                  "targets_attempted": bool(targets_attempted),
                  "wall_sec": wall, "clean": bool(clean)},
        "acceptance": {"pursue_condition": bool(pursue),
                       "reject_condition": bool(reject),
                       "win_families": win_fams, "n_win": win_n,
                       "n_strict_win": strict_n,
                       "selftest_ok": bool(selftest_ok)},
        "reason": reason,
    }

    results = {
        "screen": "12",
        "verdict": "unresolved-with-reason: payload reports numbers "
                   "and gate evidence; classification is coordinator-side.",
        "design": {
            "model": "screen-authored deterministic qubit-reuse "
                     "scheduling sim (stdlib + numpy only; no external "
                     "libs)",
            "families": list(FAMILIES),
            "physical": PHYS_N,
            "grid": "%dx%d" % (GRID_W, GRID_W),
            "seeds": list(SEEDS),
            "reps_per_cell_arm": n_inst,
            "gates_per_wire": GATES_PER_WIRE,
            "beam": {"width": BEAM_W, "branch": BEAM_BRANCH},
            "anneal": {"iters": n_iters, "t0": ANNEAL_T0,
                       "alpha": ANNEAL_ALPHA, "depth_w": DEPTH_W},
            "arms": {"G": "greedy earliest-reuse (canonical order, "
                          "lowest-index free physical)",
                     "B": "routing-aware beam search (order + "
                          "co-locating reuse targets)",
                     "A": "routing-aware annealing over priority-key "
                          "orders (co-locating reuse targets)",
                     "R": "random control (random topological order, "
                          "random free physical)"},
            "metrics": "total routed CNOTs (3d-2 per gate at Manhattan "
                       "distance d) + two-qubit depth (list-scheduled, "
                       "duration 2d-1) at fixed width 16",
            "pareto": "PURSUE needs a routed-CNOT win + depth "
                      "no-regress on the SAME arm; a CNOT-only win with "
                      "higher depth is NOT a joint win",
            "exact": "bounded-exact DFS scheduler on tiny "
                     "(must solve, optimum %d) + target-scale instance "
                     "(%d-wire family, node cap %d, must cap-hit)" % (
                         TINY_EXP["cnots"], FAMILIES[TARGET_FAM],
                         EXACT_CAP),
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
