"""Screen 14 payload: distributed multi-QPU optical interconnect and
teleportation scheduling (teledata vs telegate partition).

Screen-authored deterministic multi-QPU model (stdlib + numpy only;
no external physics, solver, or policy libraries): N_QPU modular QPUs
share all-to-all optical links with finite per-slot EPR generation
rates, finite link buffers, and a link buffer coherence cutoff. Each
cell replays a frozen list of remote two-qubit ops under a fixed
seeded channel realization (precomputed per-rep success table, shared
by every arm, so arm equivalence holds by construction). Metric is
circuit stall + EPR link decoherence cost (frozen weighted sum of
link waits, buffer expiries past the coherence cutoff, and
teledata/telegate counts) plus schedule-validity verification. Arms:
M static min-cut-style placement + all-telegate FIFO baseline, R
random partition/order control, G greedy lookahead scheduler over the
teledata/telegate partition, A annealing over partition +
link-consumption order from the G start (best tracked, never
regresses G). A bounded-exact scheduling search validates the tiny
instance (solved, optimum by enumeration) and cap-hits at target
scale (limit-expiry). Writes ALL output under cwd (the attempt work
dir): results.json plus witnesses/. Deterministic given seeds.
Verdict is always unresolved-with-reason; classification is
coordinator-side.
"""

import argparse
import json
import math
import os
import time

import numpy as np

N_QPU = 3
BENCHMARKS = ("ghz14", "qft12", "vqe12")
BENCH_QUBITS = (14, 12, 12)
N_REMOTE_OPS = (10, 12, 10)
EPR_RATES = (0.2, 0.5, 0.8)
SEEDS = (1, 2, 3, 4, 5)
ARMS = ("M", "R", "G", "A")
W_STALL = 1.0
W_EXP = 3.0
W_TD = 1.0
W_TG = 2.0
LINK_BUF = 2
COH_CUTOFF = 6
GATE_OVERHEAD = 1
MAX_SLOTS = 400
LOOKAHEAD = 3
ANNEAL_ITERS = 150
A_T0 = 1.0
A_ALPHA = 0.99
N_INST = 40
EXACT_CAP = 50000
WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0
TINY_N_QPU = 2
TINY_PLACE = (0, 1)
TINY_OPS = ((0, 1), (0, 1))
TINY_P = 1.0
TINY_EXP_COST_M = 4.0
TINY_EXP_COST_G = 1.0
TARGET = {"bi": 2, "ri": 1, "seed": 1, "rep": 0}
NEXT_EXPERIMENT = ("adaptive EPR buffering with entanglement-distillation "
                   "retries + cross-benchmark transfer retest")


def seed_rng(bi, ri, seed, rep, salt):
    return np.random.default_rng(
        (int(bi * 100003 + ri * 10009 + seed * 10007 + rep * 101
             + salt * 1000003) % (2 ** 63 - 1)))


def place_of(q, nqpu):
    return int(q % nqpu)


def all_pairs(nqpu):
    return tuple((a, b) for a in range(nqpu) for b in range(a + 1, nqpu))


PAIRS = all_pairs(N_QPU)
TINY_PAIRS = all_pairs(TINY_N_QPU)


def pair_key(pa, pb):
    return (pa, pb) if pa < pb else (pb, pa)


def gen_remote_ops(bi, seed, rep):
    """Frozen remote-op lists: N_REMOTE_OPS two-qubit ops, every op
    remote under round-robin placement. ghz14 is a seeded star around
    qubit 0, qft12 a seeded-offset chain, vqe12 seeded random remote
    pairs. Seeds are replicates. Deterministic given inputs."""
    nq = BENCH_QUBITS[bi]
    nok = N_REMOTE_OPS[bi]
    rng = seed_rng(bi, 0, seed, rep, 21)
    if BENCHMARKS[bi] == "ghz14":
        pool = [q for q in range(nq)
                if place_of(q, N_QPU) != place_of(0, N_QPU)]
        idx = rng.integers(len(pool), size=nok)
        return tuple((0, int(pool[int(i)])) for i in idx)
    if BENCHMARKS[bi] == "qft12":
        start = int(rng.integers(nq))
        return tuple(((start + t) % nq, (start + t + 1) % nq)
                     for t in range(nok))
    cand = [(a, b) for a in range(nq) for b in range(a + 1, nq)
            if place_of(a, N_QPU) != place_of(b, N_QPU)]
    idx = rng.integers(len(cand), size=nok)
    return tuple((int(cand[int(i)][0]), int(cand[int(i)][1]))
                 for i in idx)


def deps_from_ops(ops):
    """Program-order dependencies: op k depends on the latest earlier
    op sharing either qubit (immediate predecessor per qubit; chains
    cover transitivity)."""
    last = {}
    deps = []
    for k, (a, b) in enumerate(ops):
        dd = set()
        if a in last:
            dd.add(last[a])
        if b in last:
            dd.add(last[b])
        deps.append(sorted(dd))
        last[a] = k
        last[b] = k
    return deps


def gen_channel(bi, ri, seed, rep, nqpu=N_QPU, prob=None,
                nslots=MAX_SLOTS):
    """Seeded EPR channel realization: per-pair per-slot success
    table. Probabilistic links are modeled ONLY via these seeded
    draws (one rng stream, fixed table shared by every arm and every
    lookahead trial, so arm equivalence holds by construction)."""
    pr = EPR_RATES[ri] if prob is None else prob
    rng = seed_rng(bi, ri, seed, rep, 33)
    table = {}
    for prkey in all_pairs(nqpu):
        table[prkey] = [bool(x) for x in (rng.random(nslots) < pr)]
    return table


def new_link_state(pairs):
    return {"bufs": {pr: [] for pr in pairs}, "applied": 0,
            "expired": 0}


def clone_link_state(st):
    return {"bufs": {pr: list(v) for pr, v in st["bufs"].items()},
            "applied": st["applied"], "expired": st["expired"]}


def apply_slot(link_state, channel, pairs, slot):
    """Age every buffered pair, expire past COH_CUTOFF, then attempt
    one generation (dropped when the buffer is full)."""
    for pr in pairs:
        kept = []
        for age in link_state["bufs"][pr]:
            aged = age + 1
            if aged > COH_CUTOFF:
                link_state["expired"] += 1
            else:
                kept.append(aged)
        link_state["bufs"][pr] = kept
        if slot < len(channel[pr]) and channel[pr][slot]:
            if len(link_state["bufs"][pr]) < LINK_BUF:
                link_state["bufs"][pr].append(0)
    link_state["applied"] = slot + 1


def consume_epr(link_state, channel, pairs, want_pair, want_slot,
                nslots, stop):
    """Transition: take one EPR on the desired pair for the desired
    slot. Logical roles use separate names throughout: want_pair /
    want_slot name the desired consumption, while stall_slot is the
    distinct repair cursor that walks forward (expire + generate per
    slot) until the pair holds stock, and taken_age records the age
    of the consumed pair. Returns exec slot or a stopped/failed
    record."""
    stall_slot = want_slot
    while True:
        if stop is not None and stop():
            return {"ok": False, "stopped": True}
        if stall_slot >= nslots or stall_slot >= MAX_SLOTS:
            return {"ok": False, "stopped": False}
        while link_state["applied"] <= stall_slot:
            apply_slot(link_state, channel, pairs,
                       link_state["applied"])
        stock = link_state["bufs"][want_pair]
        if stock:
            taken_age = stock.pop(0)
            return {"ok": True, "stopped": False,
                    "exec_slot": stall_slot, "taken_age": taken_age}
        stall_slot += 1


def linearize(priority, deps, nok):
    """Repair any priority permutation into a linear extension:
    stable Kahn pass preferring the priority rank, so dependency
    order always holds while the priority still steers consumption
    order among ready ops."""
    rank = {op: i for i, op in enumerate(priority)}
    remaining = set(range(nok))
    finished = set()
    lin = []
    while remaining:
        avail = [op for op in remaining
                 if all(j in finished for j in deps[op])]
        if not avail:
            return None
        avail.sort(key=lambda op: rank.get(op, nok))
        nxt = avail[0]
        lin.append(nxt)
        finished.add(nxt)
        remaining.discard(nxt)
    return lin


def empty_stats(stopped):
    return {"cost": None, "wait": None, "expired": None, "n_td": None,
            "n_tg": None, "valid": False, "stopped": bool(stopped)}


def simulate(ops, nqpu, place0, channel, pairs, modes, priority,
             stop, nslots=MAX_SLOTS):
    """Execute remote ops in linearized priority order. A remote op
    consumes one EPR on its QPU pair (stalling until stock arrives);
    teledata relocates the moving qubit to the anchor qubit's QPU
    (moving_qubit vs anchor_qubit are distinct roles: only the mover
    changes placement), telegate pays GATE_OVERHEAD before dependents
    release. Local ops (after relocation) cost nothing. Cost is the
    frozen function W_STALL * total link wait + W_EXP * expiries +
    W_TD/W_TG per remote teledata/telegate."""
    nok = len(ops)
    deps = deps_from_ops(ops)
    lin = linearize(priority, deps, nok)
    if lin is None:
        return empty_stats(False)
    link_state = new_link_state(pairs)
    place = list(place0)
    compl = [None] * nok
    exec_slot = [None] * nok
    emode = [None] * nok
    total_wait = 0
    n_td = 0
    n_tg = 0
    mode_cost = 0.0
    time_cursor = 0
    for op in lin:
        if stop is not None and stop():
            return empty_stats(True)
        ready_t = 0
        for j in deps[op]:
            if compl[j] is None:
                return empty_stats(False)
            if compl[j] > ready_t:
                ready_t = compl[j]
        moving_qubit, anchor_qubit = ops[op]
        if place[moving_qubit] == place[anchor_qubit]:
            exec_s = ready_t if ready_t > time_cursor else time_cursor
            exec_slot[op] = exec_s
            emode[op] = None
            compl[op] = exec_s
            time_cursor = exec_s
            continue
        want_pair = pair_key(place[moving_qubit],
                             place[anchor_qubit])
        want_slot = ready_t if ready_t > time_cursor else time_cursor
        take = consume_epr(link_state, channel, pairs, want_pair,
                           want_slot, nslots, stop)
        if not take["ok"]:
            return empty_stats(bool(take.get("stopped")))
        exec_s = take["exec_slot"]
        total_wait += exec_s - ready_t
        exec_slot[op] = exec_s
        if modes[op] == "teledata":
            place[moving_qubit] = place[anchor_qubit]
            emode[op] = "teledata"
            n_td += 1
            mode_cost += W_TD
            compl[op] = exec_s
        else:
            emode[op] = "telegate"
            n_tg += 1
            mode_cost += W_TG
            compl[op] = exec_s + GATE_OVERHEAD
        time_cursor = exec_s
    cost = (W_STALL * total_wait + W_EXP * link_state["expired"]
            + mode_cost)
    return {"cost": float(cost), "wait": int(total_wait),
            "expired": int(link_state["expired"]), "n_td": int(n_td),
            "n_tg": int(n_tg), "valid": True, "stopped": False,
            "exec_slot": list(exec_slot), "emode": list(emode)}


def verify_schedule(ops, nqpu, place0, channel, pairs, rec):
    """Independent record-driven replay: re-applies the recorded
    exec slots and remote modes slot by slot (no priority logic),
    checking dep order, EPR availability at each consumption, and
    relocation consistency, then recomputes the frozen cost."""
    try:
        nok = len(ops)
        deps = deps_from_ops(ops)
        link_state = new_link_state(pairs)
        place = list(place0)
        compl = [None] * nok
        total_wait = 0
        n_td = 0
        n_tg = 0
        mode_cost = 0.0
        order = sorted(range(nok),
                       key=lambda op: (rec["exec_slot"][op], op))
        for op in order:
            exec_s = rec["exec_slot"][op]
            ready_t = 0
            for j in deps[op]:
                if compl[j] is None or compl[j] > exec_s:
                    return False
                if compl[j] > ready_t:
                    ready_t = compl[j]
            moving_qubit, anchor_qubit = ops[op]
            if place[moving_qubit] == place[anchor_qubit]:
                if rec["emode"][op] is not None:
                    return False
                compl[op] = exec_s
                continue
            if rec["emode"][op] not in ("teledata", "telegate"):
                return False
            while link_state["applied"] <= exec_s:
                apply_slot(link_state, channel, pairs,
                           link_state["applied"])
            stock = link_state["bufs"][pair_key(
                place[moving_qubit], place[anchor_qubit])]
            if not stock:
                return False
            stock.pop(0)
            total_wait += exec_s - ready_t
            if rec["emode"][op] == "teledata":
                place[moving_qubit] = place[anchor_qubit]
                n_td += 1
                mode_cost += W_TD
                compl[op] = exec_s
            else:
                n_tg += 1
                mode_cost += W_TG
                compl[op] = exec_s + GATE_OVERHEAD
        cost = (W_STALL * total_wait + W_EXP * link_state["expired"]
                + mode_cost)
        return (abs(cost - rec["cost"]) < 1e-9
                and n_td == rec["n_td"] and n_tg == rec["n_tg"]
                and total_wait == rec["wait"]
                and link_state["expired"] == rec["expired"])
    except Exception:
        return False


def run_m(ops, nqpu, place0, channel, pairs, stop):
    """Static baseline: frozen round-robin placement is never moved
    (all telegate), program-order FIFO link consumption."""
    modes = ["telegate"] * len(ops)
    return simulate(ops, nqpu, place0, channel, pairs, modes,
                    list(range(len(ops))), stop)


def run_r(ops, nqpu, place0, channel, pairs, rng, stop):
    """Random control: seeded random teledata/telegate partition and
    seeded random consumption priority (repaired to a linear
    extension at decode)."""
    nok = len(ops)
    modes = ["teledata" if bool(rng.random() < 0.5) else "telegate"
             for _ in range(nok)]
    priority = list(range(nok))
    for i in range(nok - 1, 0, -1):
        j = int(rng.integers(i + 1))
        priority[i], priority[j] = priority[j], priority[i]
    return simulate(ops, nqpu, place0, channel, pairs, modes,
                    priority, stop)


def plan_greedy(ops, nqpu, place0, channel, pairs, stop):
    """Greedy lookahead over the teledata/telegate partition under
    program-order consumption: fix ops left to right, scoring each
    candidate mode by a window rollout of that op plus the next
    LOOKAHEAD ops (prefix-closed, telegate default beyond fixed
    modes) on the shared seeded channel. Ties go telegate."""
    nok = len(ops)
    fixed = {}
    for k in range(nok):
        if stop is not None and stop():
            return None
        scored = []
        for cand in ("telegate", "teledata"):
            trial = dict(fixed)
            trial[k] = cand
            for w in range(k + 1, min(nok, k + 1 + LOOKAHEAD)):
                trial.setdefault(w, "telegate")
            wend = min(nok - 1, k + LOOKAHEAD)
            sub_modes = [trial[i] for i in range(wend + 1)]
            res = simulate(list(ops[:wend + 1]), nqpu, place0,
                           channel, pairs, sub_modes,
                           list(range(wend + 1)), None)
            cost = res["cost"] if res["valid"] else float("inf")
            scored.append((cost, cand))
        scored.sort(key=lambda t: (t[0],
                                   0 if t[1] == "telegate" else 1))
        fixed[k] = scored[0][1]
    return [fixed[i] for i in range(nok)]


def run_g(ops, nqpu, place0, channel, pairs, stop):
    """Greedy lookahead scheduler: partition from plan_greedy,
    program-order consumption."""
    modes = plan_greedy(ops, nqpu, place0, channel, pairs, stop)
    if modes is None:
        return empty_stats(True)
    return simulate(ops, nqpu, place0, channel, pairs, modes,
                    list(range(len(ops))), stop)


def run_a(ops, nqpu, place0, channel, pairs, rng, n_iters, stop):
    """Annealing over teledata/telegate partition + consumption
    order from the G start. Proposals flip one op mode or swap two
    priority positions; cost is frozen stall + decoherence, best
    tracked, so A never regresses G."""
    if stop is not None and stop():
        return empty_stats(True)
    gmodes = plan_greedy(ops, nqpu, place0, channel, pairs, None)
    if gmodes is None:
        return empty_stats(True)
    nok = len(ops)
    best_modes = list(gmodes)
    best_prio = list(range(nok))
    best_out = simulate(ops, nqpu, place0, channel, pairs,
                        best_modes, best_prio, None)
    if best_out.get("stopped") or not best_out.get("valid"):
        return empty_stats(True)
    cur_modes = list(best_modes)
    cur_prio = list(best_prio)
    cur_cost = best_out["cost"]
    best_cost = cur_cost
    temp = A_T0
    for it in range(n_iters):
        if it % 32 == 0 and stop is not None and stop():
            return empty_stats(True)
        prop_modes = list(cur_modes)
        prop_prio = list(cur_prio)
        if bool(rng.random() < 0.5):
            gi = int(rng.integers(nok))
            prop_modes[gi] = ("telegate"
                              if prop_modes[gi] == "teledata"
                              else "teledata")
        else:
            i = int(rng.integers(nok))
            j = int(rng.integers(nok))
            prop_prio[i], prop_prio[j] = prop_prio[j], prop_prio[i]
        out = simulate(ops, nqpu, place0, channel, pairs,
                       prop_modes, prop_prio, None)
        new_cost = out["cost"] if out["valid"] else float("inf")
        temp *= A_ALPHA
        if new_cost <= cur_cost or bool(
                rng.random() < math.exp(-(new_cost - cur_cost)
                                        / temp)):
            cur_modes = prop_modes
            cur_prio = prop_prio
            cur_cost = new_cost
            if new_cost < best_cost and out["valid"]:
                best_modes = prop_modes
                best_prio = prop_prio
                best_cost = new_cost
                best_out = out
    return dict(best_out, stopped=False)


def run_arm(bi, ri, seed, rep, arm, n_iters, stop):
    ops = gen_remote_ops(bi, seed, rep)
    nqpu = N_QPU
    nq = BENCH_QUBITS[bi]
    place0 = tuple(place_of(q, nqpu) for q in range(nq))
    channel = gen_channel(bi, ri, seed, rep)
    if arm == "M":
        return run_m(ops, nqpu, place0, channel, PAIRS, stop)
    if arm == "R":
        return run_r(ops, nqpu, place0, channel, PAIRS,
                     seed_rng(bi, ri, seed, rep, 999), stop)
    if arm == "G":
        return run_g(ops, nqpu, place0, channel, PAIRS, stop)
    return run_a(ops, nqpu, place0, channel, PAIRS,
                 seed_rng(bi, ri, seed, rep, 777), n_iters, stop)


def exact_opt(ops, nqpu, place0, channel, pairs, cap, stop):
    """Bounded-exact scheduling search: exhaustive DFS over ready-op
    x teledata/telegate branches with deterministic stall advance
    (idle only when nothing is executable, which is dominance-safe:
    idling while executable only grows waits and expiries). Serves
    each unconsumed slot's expire/generate identically to the
    engine. No pruning: every node is visited until the cap.
    Statuses solved / cap-hit / stopped-guard."""
    nok = len(ops)
    deps = deps_from_ops(ops)
    incumbent = [None]
    best = [None]
    nodes = [0]
    capped = [False]
    stopped = [False]

    def rec(done, place, bufs, applied, expired, waits, mode_cost,
            n_td, n_tg, compl, cur):
        if capped[0] or stopped[0]:
            return
        nodes[0] += 1
        if nodes[0] > cap:
            capped[0] = True
            return
        if nodes[0] % 512 == 0 and stop is not None and stop():
            stopped[0] = True
            return
        if all(done):
            cost = W_STALL * waits + W_EXP * expired + mode_cost
            if incumbent[0] is None or cost < incumbent[0]:
                incumbent[0] = float(cost)
                best[0] = {"cost": float(cost), "wait": waits,
                           "expired": expired, "n_td": n_td,
                           "n_tg": n_tg}
            return
        if cur >= MAX_SLOTS:
            return
        while applied <= cur:
            for pr in pairs:
                kept = []
                for age in bufs[pr]:
                    aged = age + 1
                    if aged > COH_CUTOFF:
                        expired += 1
                    else:
                        kept.append(aged)
                bufs[pr] = kept
                if applied < len(channel[pr]) and channel[pr][applied]:
                    if len(bufs[pr]) < LINK_BUF:
                        bufs[pr].append(0)
            applied += 1
        ready = [op for op in range(nok)
                 if not done[op]
                 and all(done[j] for j in deps[op])
                 and all(compl[j] is not None and compl[j] <= cur
                         for j in deps[op])]
        execable = []
        for op in ready:
            moving_qubit, anchor_qubit = ops[op]
            if place[moving_qubit] == place[anchor_qubit]:
                execable.append((op, None))
            else:
                want_pair = pair_key(place[moving_qubit],
                                     place[anchor_qubit])
                if bufs[want_pair]:
                    execable.append((op, want_pair))
        if not execable:
            rec(list(done), tuple(place), bufs, applied, expired,
                waits, mode_cost, n_td, n_tg, list(compl), cur + 1)
            return
        for op, want_pair in execable:
            ready_t = 0
            for j in deps[op]:
                if compl[j] > ready_t:
                    ready_t = compl[j]
            for cand in ("telegate", "teledata"):
                nplace = list(place)
                nbufs = {pr: list(v) for pr, v in bufs.items()}
                nmode_cost = mode_cost
                nn_td = n_td
                nn_tg = n_tg
                ncompl = list(compl)
                moving_qubit, anchor_qubit = ops[op]
                if want_pair is None:
                    ncompl[op] = cur
                else:
                    nbufs[want_pair] = list(nbufs[want_pair][1:])
                    if cand == "teledata":
                        nplace[moving_qubit] = nplace[anchor_qubit]
                        nn_td += 1
                        nmode_cost += W_TD
                        ncompl[op] = cur
                    else:
                        nn_tg += 1
                        nmode_cost += W_TG
                        ncompl[op] = cur + GATE_OVERHEAD
                ndone = list(done)
                ndone[op] = True
                rec(ndone, tuple(nplace), nbufs, applied, expired,
                    waits + (cur - ready_t), nmode_cost, nn_td,
                    nn_tg, ncompl, cur)
                if capped[0] or stopped[0]:
                    return

    rec([False] * nok, tuple(place0),
        {pr: [] for pr in pairs}, 0, 0, 0, 0.0, 0, 0,
        [None] * nok, 0)
    if stopped[0]:
        return {"status": "stopped-guard", "nodes": nodes[0],
                "opt_cost": incumbent[0], "best": best[0],
                "cap": cap, "started": True}
    if capped[0]:
        return {"status": "cap-hit", "nodes": nodes[0],
                "opt_cost": incumbent[0], "best": best[0],
                "cap": cap, "started": True}
    return {"status": "solved", "nodes": nodes[0],
            "opt_cost": incumbent[0], "best": best[0],
            "cap": cap, "started": True}


def audit_gen(bi, seed, rep):
    nq = BENCH_QUBITS[bi]
    ops = gen_remote_ops(bi, seed, rep)
    ok = (len(ops) == N_REMOTE_OPS[bi]
          and all(a != b and 0 <= a < nq and 0 <= b < nq
                  for a, b in ops)
          and all(place_of(a, N_QPU) != place_of(b, N_QPU)
                  for a, b in ops))
    return ok, ops


def tiny_setup():
    ops = list(TINY_OPS)
    place0 = tuple(TINY_PLACE)
    channel = gen_channel(0, 0, 7, 7, nqpu=TINY_N_QPU,
                          prob=TINY_P, nslots=MAX_SLOTS)
    return ops, TINY_N_QPU, place0, channel, TINY_PAIRS


def target_setup():
    bi = TARGET["bi"]
    ops = gen_remote_ops(bi, TARGET["seed"], TARGET["rep"])
    nq = BENCH_QUBITS[bi]
    place0 = tuple(place_of(q, N_QPU) for q in range(nq))
    channel = gen_channel(bi, TARGET["ri"], TARGET["seed"],
                          TARGET["rep"])
    return ops, N_QPU, place0, channel, PAIRS


def self_tests():
    out = {"ran": True, "failed": []}
    try:
        for bi in range(len(BENCHMARKS)):
            for rep in (0, 1):
                ok, _g = audit_gen(bi, 1, rep)
                if not ok:
                    out["failed"].append("gen-%d-%d" % (bi, rep))
        _ok, g1 = audit_gen(0, 1, 0)
        _ok, g1b = audit_gen(0, 1, 0)
        if g1 != g1b:
            out["failed"].append("gen-determinism")
        if list(TINY_OPS) != [(0, 1), (0, 1)]:
            out["failed"].append("tiny-fixture")
        tops, tnqpu, tplace, tchan, tpairs = tiny_setup()
        tm = run_m(tops, tnqpu, tplace, tchan, tpairs, None)
        if (not tm["valid"] or tm["stopped"]
                or abs(tm["cost"] - TINY_EXP_COST_M) > 1e-9):
            out["failed"].append("tiny-M-hand: %r" % (tm,))
        tg = run_g(tops, tnqpu, tplace, tchan, tpairs, None)
        if (not tg["valid"] or tg["stopped"]
                or abs(tg["cost"] - TINY_EXP_COST_G) > 1e-9):
            out["failed"].append("tiny-G-hand: %r" % (tg,))
        ta = run_a(tops, tnqpu, tplace, tchan, tpairs,
                   seed_rng(0, 0, 7, 7, 777), 50, None)
        if (ta["stopped"] or not ta["valid"]
                or ta["cost"] > tg["cost"] + 1e-9):
            out["failed"].append("tiny-A-invariant: %r" % (ta,))
        tr = run_r(tops, tnqpu, tplace, tchan, tpairs,
                   seed_rng(0, 0, 7, 7, 999), None)
        if tr["stopped"] or not tr["valid"]:
            out["failed"].append("tiny-R-valid: %r" % (tr,))
        if not verify_schedule(tops, tnqpu, tplace, tchan, tpairs,
                               tg):
            out["failed"].append("verify-G-record")
        mv_ops = [(0, 1), (0, 1)]
        mv_place = (0, 1)
        mv_chan = {p: [True] * MAX_SLOTS for p in TINY_PAIRS}
        mv = simulate(mv_ops, TINY_N_QPU, mv_place, mv_chan,
                      TINY_PAIRS, ["teledata", "telegate"], [0, 1],
                      None)
        if (not mv["valid"] or mv["emode"] != ["teledata", None]
                or abs(mv["cost"] - W_TD) > 1e-9):
            out["failed"].append(
                "relocation-repair: %r" % (mv,))
        late_chan = {(0, 1): [False] * 3 + [True] * (MAX_SLOTS - 3)}
        late = simulate([(0, 1)], TINY_N_QPU, (0, 1), late_chan,
                        TINY_PAIRS, ["telegate"], [0], None)
        if (not late["valid"] or late["exec_slot"] != [3]
                or late["wait"] != 3):
            out["failed"].append("consume-repair: %r" % (late,))
        bad = dict(tg)
        bad["exec_slot"] = [1, 0]
        if verify_schedule(tops, tnqpu, tplace, tchan, tpairs, bad):
            out["failed"].append("verify-missed-order")
        tex = exact_opt(tops, tnqpu, tplace, tchan, tpairs,
                        EXACT_CAP, None)
        if (tex["status"] != "solved" or tex["best"] is None
                or abs(tex["opt_cost"] - TINY_EXP_COST_G) > 1e-9):
            out["failed"].append("tiny-exact-opt: %r" % (tex,))
        for bi, ri in ((0, 1), (2, 0)):
            _ok, dg = audit_gen(bi, 3, 0)
            nq = BENCH_QUBITS[bi]
            dplace = tuple(place_of(q, N_QPU) for q in range(nq))
            dchan = gen_channel(bi, ri, 3, 0)
            for arm, fn in (
                    ("M", lambda: run_m(dg, N_QPU, dplace, dchan,
                                        PAIRS, None)),
                    ("G", lambda: run_g(dg, N_QPU, dplace, dchan,
                                        PAIRS, None)),
                    ("R", lambda: run_r(
                        dg, N_QPU, dplace, dchan, PAIRS,
                        seed_rng(bi, ri, 3, 0, 999), None))):
                r = fn()
                if not r["valid"] or r["stopped"]:
                    out["failed"].append(
                        "arm-valid-%s-%d-%d" % (arm, bi, ri))
                if not verify_schedule(dg, N_QPU, dplace, dchan,
                                       PAIRS, r):
                    out["failed"].append(
                        "arm-verify-%s-%d-%d" % (arm, bi, ri))
            ga = run_a(dg, N_QPU, dplace, dchan, PAIRS,
                       seed_rng(bi, ri, 3, 0, 777), 50, None)
            gg = run_g(dg, N_QPU, dplace, dchan, PAIRS, None)
            if (not ga["valid"] or ga["stopped"]
                    or ga["cost"] > gg["cost"] + 1e-9):
                out["failed"].append(
                    "a-beats-start-invariant-%d-%d" % (bi, ri))
            r1 = run_r(dg, N_QPU, dplace, dchan, PAIRS,
                       seed_rng(bi, ri, 3, 0, 999), None)
            r2 = run_r(dg, N_QPU, dplace, dchan, PAIRS,
                       seed_rng(bi, ri, 3, 0, 999), None)
            if r1["cost"] != r2["cost"]:
                out["failed"].append("determinism-random")
            g1a = run_g(dg, N_QPU, dplace, dchan, PAIRS, None)
            g1b = run_g(dg, N_QPU, dplace, dchan, PAIRS, None)
            if g1a["cost"] != g1b["cost"]:
                out["failed"].append("determinism-greedy")
        _ok, dag = audit_gen(0, 1, 0)
        dag_place = tuple(place_of(q, N_QPU)
                          for q in range(BENCH_QUBITS[0]))
        dag_chan = gen_channel(0, 1, 1, 0)
        stoppers = {
            "M": lambda: run_m(dag, N_QPU, dag_place, dag_chan,
                               PAIRS, lambda: True),
            "G": lambda: run_g(dag, N_QPU, dag_place, dag_chan,
                               PAIRS, lambda: True),
            "R": lambda: run_r(dag, N_QPU, dag_place, dag_chan,
                               PAIRS,
                               seed_rng(0, 1, 1, 0, 999),
                               lambda: True),
            "A": lambda: run_a(dag, N_QPU, dag_place, dag_chan,
                               PAIRS,
                               seed_rng(0, 1, 1, 0, 777), 50,
                               lambda: True),
        }
        for arm, fn in stoppers.items():
            if not fn().get("stopped"):
                out["failed"].append("stop-propagation-%s" % arm)
        for bi in range(len(BENCHMARKS)):
            for ri in range(len(EPR_RATES)):
                _ok, sw_g = audit_gen(bi, 2, 0)
                nq = BENCH_QUBITS[bi]
                sw_place = tuple(place_of(q, N_QPU)
                                 for q in range(nq))
                sw_chan = gen_channel(bi, ri, 2, 0)
                for arm, fn in (
                        ("M", lambda: run_m(sw_g, N_QPU, sw_place,
                                            sw_chan, PAIRS, None)),
                        ("G", lambda: run_g(sw_g, N_QPU, sw_place,
                                            sw_chan, PAIRS, None)),
                        ("R", lambda: run_r(
                            sw_g, N_QPU, sw_place, sw_chan, PAIRS,
                            seed_rng(bi, ri, 2, 0, 999), None)),
                        ("A", lambda: run_a(
                            sw_g, N_QPU, sw_place, sw_chan, PAIRS,
                            seed_rng(bi, ri, 2, 0, 777), 30,
                            None))):
                    r = fn()
                    if not r["valid"] or r["stopped"]:
                        out["failed"].append(
                            "sweep-valid-%s-%d-%d" % (arm, bi, ri))
        tsize = target_setup()
        stx = exact_opt(tsize[0], tsize[1], tsize[2], tsize[3],
                        tsize[4], EXACT_CAP, lambda: True)
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
        tops, tnqpu, tplace, tchan, tpairs = tiny_setup()
        ex = exact_opt(tops, tnqpu, tplace, tchan, tpairs,
                       EXACT_CAP, over)
        gate3tiny["arms"]["tiny"] = ex
        gate3tiny["total"] += 1
        if ex["status"] == "solved" and ex["best"] is not None \
                and abs(ex["opt_cost"] - TINY_EXP_COST_G) < 1e-9:
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
        tsize = target_setup()
        tex = exact_opt(tsize[0], tsize[1], tsize[2], tsize[3],
                        tsize[4], EXACT_CAP, over)
        gate3targets.append(dict(tex, bi=TARGET["bi"],
                                 ri=TARGET["ri"],
                                 seed=TARGET["seed"],
                                 rep=TARGET["rep"]))
        if tex["status"] == "stopped-guard":
            skipped.append({"what": "target-exact",
                            "reason": "stopped-guard",
                            "iters_done": tex.get("nodes", 0),
                            "n_evaluated": EXACT_CAP})
    with open(os.path.join(witdir, "gate3_targets.json"), "w") as f:
        json.dump(gate3targets, f, indent=1, default=str)
    checkpoint("targets")

    def run_cell(bi, ri, seed):
        rec = {"bench": BENCHMARKS[bi], "rate": EPR_RATES[ri],
               "seed": seed, "arms": {}}
        for arm in ARMS:
            if over():
                rec["blocked"] = "wall-guard"
                return rec
            cv, wv, nv = [], [], 0
            nstop = 0
            for rep in range(n_inst):
                if rep % 32 == 0 and over():
                    nstop += 1
                    break
                out = run_arm(bi, ri, seed, rep, arm, n_iters, over)
                if out.get("stopped"):
                    nstop += 1
                    break
                cv.append(out["cost"])
                wv.append(out["wait"])
                nv += 1 if out.get("valid") else 0
            if nstop:
                rec["blocked"] = "stopped-guard"
                rec["iters_done"] = len(cv)
                rec["n_evaluated"] = n_inst
                return rec
            rec["arms"][arm] = {
                "n": len(cv),
                "cost": pooled_stats(cv),
                "wait": pooled_stats(wv),
                "n_valid": int(nv)}
        return rec

    def record_cell(rec):
        if rec.get("blocked") is None and all(
                rec["arms"].get(a, {}).get("n") == n_inst
                for a in ARMS):
            for a in ARMS:
                key = (rec["bench"], rec["rate"], rec["seed"], a)
                cells.setdefault(key, {"cost": [], "wait": [],
                                       "valid": []})
                cells[key]["cost"].append(
                    rec["arms"][a]["cost"]["mean"])
                cells[key]["wait"].append(
                    rec["arms"][a]["wait"]["mean"])
                cells[key]["valid"].append(
                    rec["arms"][a]["n_valid"] / n_inst)
            cellrecs.append(rec)
            return True
        cellrecs.append(rec)
        skipped.append({"what": "cell %s/%s/%s" % (
            rec["bench"], rec["rate"], rec["seed"]),
            "reason": rec.get("blocked", "arm-incomplete"),
            "iters_done": rec.get("iters_done", 0),
            "n_evaluated": n_inst})
        return False

    for ri, rate in enumerate(EPR_RATES):
        rate_cells = [(bi, seed) for bi in range(len(BENCHMARKS))
                      for seed in SEEDS]
        if over():
            for (b2, sd2) in rate_cells:
                skipped.append({"what": "cell %s/%s/%s" % (
                    BENCHMARKS[b2], rate, sd2),
                    "reason": "wall-guard",
                    "iters_done": 0, "n_evaluated": n_inst})
        else:
            for (b2, sd2) in rate_cells:
                if over():
                    skipped.append({"what": "cell %s/%s/%s" % (
                        BENCHMARKS[b2], rate, sd2),
                        "reason": "wall-guard",
                        "iters_done": 0, "n_evaluated": n_inst})
                    continue
                rec = run_cell(b2, ri, sd2)
                record_cell(rec)
        with open(os.path.join(witdir, "cells.json"), "w") as f:
            json.dump(cellrecs, f, indent=1, default=str)
        checkpoint("rate%s" % ri)
    with open(os.path.join(witdir, "cells.json"), "w") as f:
        json.dump(cellrecs, f, indent=1, default=str)
    checkpoint("corpus")

    def cell_mean(bi, ri, seed, arm, field):
        return cells.get((BENCHMARKS[bi], EPR_RATES[ri], seed, arm),
                         {"cost": [], "wait": [],
                          "valid": []})[field]

    def pool(ri, arm, field):
        vals = []
        for bi in range(len(BENCHMARKS)):
            for seed in SEEDS:
                vals.extend(cell_mean(bi, ri, seed, arm, field))
        return pooled_stats(vals), len(vals) == (
            len(BENCHMARKS) * len(SEEDS))

    def valid_pool(ri, arm):
        vals = []
        for bi in range(len(BENCHMARKS)):
            for seed in SEEDS:
                vals.extend(cell_mean(bi, ri, seed, arm, "valid"))
        return vals

    det1 = run_arm(0, 1, 1, 0, "G", n_iters, None)
    det2 = run_arm(0, 1, 1, 0, "G", n_iters, None)
    det_r1 = run_arm(0, 1, 1, 0, "R", n_iters, None)
    det_r2 = run_arm(0, 1, 1, 0, "R", n_iters, None)
    determinism_ok = bool(
        det1["cost"] == det2["cost"]
        and det_r1["cost"] == det_r2["cost"])

    g1_cells, g1_beats = [], True
    for bi in range(len(BENCHMARKS)):
        for ri in range(len(EPR_RATES)):
            for seed in SEEDS:
                ms = cell_mean(bi, ri, seed, "G", "cost")
                mr = cell_mean(bi, ri, seed, "R", "cost")
                ok = (len(ms) == 1 and len(mr) == 1
                      and ms[0] < mr[0])
                g1_cells.append({"cell": "%s/%s/%s" % (
                    BENCHMARKS[bi], EPR_RATES[ri], seed),
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
    for ri, rate in enumerate(EPR_RATES):
        pools, pok = {}, True
        for arm in ("M", "G", "A"):
            pools[arm], oka = pool(ri, arm, "cost")
            pok = pok and oka
        se, spread, gp = spread_win(pools, pok)
        g2_fams.append({"rate": rate, "pools": pools, "SE": se,
                        "spread": spread, "pass": bool(gp)})
        if gp:
            g2_n += 1
        joint = {}
        if pok and all(
                pools[a]["se"] is not None and
                pools[a]["mean"] is not None for a in ("M", "G",
                                                      "A")):
            sse2 = math.sqrt(sum(pools[a]["se"] ** 2
                                 for a in ("M", "G", "A")) / 3.0)
            for a in ("G", "A"):
                cwin = pools[a]["mean"] < pools["M"]["mean"] - \
                    2.0 * sse2
                vpools = pooled_stats(valid_pool(ri, a))
                vpool_m = pooled_stats(valid_pool(ri, "M"))
                vwin = (vpools["mean"] is not None
                        and vpool_m["mean"] is not None
                        and vpools["mean"] >= vpool_m["mean"])
                joint[a] = bool(cwin and vwin)
        else:
            joint = {"G": False, "A": False}
        for a in ("G", "A"):
            if joint[a]:
                n_win[a] += 1
        winner = ("G" if joint["G"]
                  else ("A" if joint["A"] else None))
        wpass = winner is not None
        if pok and all(pools[a]["mean"] is not None
                       for a in ("M", "G", "A")):
            spass = (pools["G"]["mean"] < pools["M"]["mean"] or
                     pools["A"]["mean"] < pools["M"]["mean"])
        else:
            spass = False
            pools_all = False
        if not pok:
            pools_all = False
        if spass:
            n_strict += 1
        win_fams.append({"rate": rate, "win": bool(wpass),
                         "strict_win": bool(spass),
                         "pools_ok": bool(pok),
                         "joint": dict(joint), "winner": winner})
    g2_ok = g2_n >= 2

    tiny_solved = (gate3tiny["total"] == 1 and gate3tiny["solved"] == 1)
    target_cap = (len(gate3targets) == 1 and
                  gate3targets[0].get("status") == "cap-hit")
    g3pass = bool(tiny_solved and target_cap)

    complete = all(
        len(cell_mean(bi, ri, seed, arm, "cost")) == 1
        for bi in range(len(BENCHMARKS))
        for ri in range(len(EPR_RATES)) for seed in SEEDS
        for arm in ARMS)
    tiny_attempted = gate3tiny["total"] == 1
    targets_attempted = len(gate3targets) == 1
    wall = elapsed()
    clean = len(skipped) == 0
    g4_ok = bool(complete and tiny_attempted and targets_attempted
                 and wall < WALL_LIMIT_S and clean)

    selftest_ok = bool(tiny_ok)
    pursue = (max(n_win["G"], n_win["A"]) >= 2 and g1_ok and g2_ok
              and g3pass and g4_ok and selftest_ok)
    reject = (complete and tiny_solved and g1_ok and
              pools_all and n_strict == 0)
    if pursue:
        reason = "PURSUE-condition holds (joint stall+decoherence " \
            "win with matched-or-better validity on the SAME arm " \
            "at >=2 EPR rates + gates 1,2,3,4 + self-tests ok); " \
            "payload verdict stays unresolved-with-reason, " \
            "classification is coordinator-side."
    elif reject:
        reason = "REJECT-condition holds (complete cells, tiny " \
            "solved, Gate-1 controls pass, no strict pooled cost " \
            "win at any rate); payload verdict stays " \
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
        "gate2": {"pass": bool(g2_ok), "n_rates_pass": g2_n,
                  "rates": g2_fams},
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
                       "win_rates": win_fams, "n_strict_win": n_strict,
                       "pools_all": bool(pools_all),
                       "selftest_ok": bool(selftest_ok)},
        "reason": reason,
    }

    results = {
        "screen": "14",
        "verdict": "unresolved-with-reason: payload reports numbers "
                   "and gate evidence; classification is coordinator-side.",
        "design": {
            "model": "screen-authored deterministic multi-QPU "
                     "teledata/telegate scheduling model (stdlib + "
                     "numpy only; no external libs)",
            "qpus": N_QPU,
            "benchmarks": ["%s (%d qubits, %d remote ops)" % (
                BENCHMARKS[bi], BENCH_QUBITS[bi],
                N_REMOTE_OPS[bi])
                for bi in range(len(BENCHMARKS))],
            "epr_rates": list(EPR_RATES),
            "seeds": list(SEEDS),
            "cells": "3 benchmarks x 3 EPR rates x 5 seeds = "
                     "45 cells x 4 arms (seeds are replicates)",
            "reps_per_cell_arm": n_inst,
            "links": "all-to-all optical pairs, seeded Bernoulli "
                     "generation per slot, finite buffer LINK_BUF, "
                     "coherence cutoff COH_CUTOFF",
            "cost": "frozen: W_STALL x link waits + W_EXP x buffer "
                    "expiries + W_TD/W_TG per remote teledata/telegate",
            "weights": {"W_STALL": W_STALL, "W_EXP": W_EXP,
                        "W_TD": W_TD, "W_TG": W_TG},
            "link_params": {"LINK_BUF": LINK_BUF,
                            "COH_CUTOFF": COH_CUTOFF,
                            "GATE_OVERHEAD": GATE_OVERHEAD,
                            "MAX_SLOTS": MAX_SLOTS,
                            "LOOKAHEAD": LOOKAHEAD},
            "anneal": {"iters": n_iters, "t0": A_T0,
                       "alpha": A_ALPHA},
            "arms": {"M": "static baseline: frozen placement, all "
                          "telegate, program-order FIFO consumption",
                     "R": "random partition + random consumption "
                          "priority control",
                     "G": "greedy lookahead scheduler over the "
                          "teledata/telegate partition",
                     "A": "annealing over partition + consumption "
                          "order from G, best tracked"},
            "metrics": "circuit stall + EPR link decoherence cost "
                       "(frozen) + schedule validity (dep order, EPR "
                       "balance, relocation consistency)",
            "pareto": "PURSUE needs a cost win + matched-or-better "
                      "validity on the SAME arm; joint wins counted "
                      "PER ARM with bar max(G,A)>=2, never any-winner",
            "exact": "bounded-exact scheduling search on tiny (2 "
                     "QPUs, 2 ops, must solve, optimum cost %r) "
                     "+ target-scale instance (bench %d, rate %s, "
                     "seed %d rep %d, node cap %d, must cap-hit)" % (
                         TINY_EXP_COST_G, TARGET["bi"],
                         EPR_RATES[TARGET["ri"]], TARGET["seed"],
                         TARGET["rep"], EXACT_CAP),
        },
        "timing": {"wall_s": wall, "guards": {"wall_guard_s": WALL_GUARD_S,
                                              "limit_s": WALL_LIMIT_S}},
        "cells": {("%s/%s/%s/%s" % k): {"n": len(v["cost"]),
                                       **pooled_stats(v["cost"]),
                                       "wait": pooled_stats(
                                           v["wait"]),
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
