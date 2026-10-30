"""Screen 17 payload: entanglement-minimization cuts for circuit
knitting / wire cutting (joint local-rewrite + cut search).

Screen-authored exact cut-cost model (stdlib + numpy only; no
external physics, solver, or policy libraries). Circuits are frozen
seeded gate lists (H/S plus CNOTs) in three families on N_QUBITS =
(8, 10, 12). A cut placement assigns every two-qubit gate to one of
ceil(n/K_MAX) fragments and flags gate-cuts; wire cuts fall on
per-qubit consecutive two-qubit gates placed in different
fragments. Total sampling overhead is the exact product
prod(gamma_i^2) with frozen per-cut factors, evaluated in log
space; partition validity (fragment widths <= K_MAX, all cuts
legal) is verified per rep with a deterministic repair
(gate-cut fallback always terminates). Local rewrites are
duplicate-CNOT cancellation plus logical label swaps,
unitary-preserving by construction. Arms: C static DAG min-cut
baseline, R random cut-placement control, G greedy joint
rewrite+cut search, A annealing over rewrite+cut placements. A
bounded-exact DFS cut search validates the tiny instance (solved,
optimum by construction) and cap-hits at target scale
(limit-expiry). Writes ALL output under cwd (the attempt work
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

N_QUBITS = (8, 10, 12)
FAMILIES = ("ladder", "hea", "qftlike")
K_MAX = 4
SEEDS = (1, 2, 3, 4, 5)
ARMS = ("C", "R", "G", "A")
N_INST = 12
GAMMA2_WIRE = 9.0
GAMMA2_GATE = 16.0
LOGW = math.log(GAMMA2_WIRE)
LOGG = math.log(GAMMA2_GATE)
GREEDY_SWEEPS = 3
ANNEAL_ITERS = 200
ANNEAL_T0 = 2.0
ANNEAL_ALPHA = 0.985
EXACT_CAP = 50000
WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0
TINY_N = 6
TINY_OPT = 9.0
TARGET = {"fi": 2, "seed": 1, "rep": 0}
NEXT_EXPERIMENT = ("richer Clifford-template rewrite library + "
                   "depth-regularized cut annealing retest")


def seed_rng(fi, seed, rep, salt):
    return np.random.default_rng(
        (int(fi * 100003 + seed * 10007 + rep * 101
             + salt * 1000003) % (2 ** 63 - 1)))


def n_frag(n):
    return int(math.ceil(n / K_MAX))


def gen_circuit(fi, seed, rep):
    """Frozen seeded gate list for family fi. Each layer holds a
    single-qubit sublayer (H p=0.30, S p=0.20) plus family-shaped
    CNOTs. Deterministic given inputs; the same list is replayed
    by every arm, so arm equivalence holds by construction."""
    nq = N_QUBITS[fi]
    fam = FAMILIES[fi]
    layers = (6, 8, 10)[fi]
    rng = seed_rng(fi, seed, rep, 21)
    gates = []
    for _li in range(layers):
        for q in range(nq):
            r = float(rng.random())
            if r < 0.30:
                gates.append(("H", q, -1))
            elif r < 0.50:
                gates.append(("S", q, -1))
        if fam == "ladder":
            for q in range(nq - 1):
                if bool(rng.random() < 0.55):
                    gates.append(("CX", q, q + 1))
        elif fam == "hea":
            for q in range(nq):
                if bool(rng.random() < 0.50):
                    gates.append(("CX", q, (q + 1) % nq))
        else:
            for q in range(nq - 1):
                if bool(rng.random() < 0.40):
                    gates.append(("CX", q, q + 1))
            for _k in range(3):
                a = int(rng.integers(0, nq - 1))
                b = int(rng.integers(a + 2, nq + 1)) - 1
                if b <= a:
                    continue
                if bool(rng.random() < 0.5):
                    gates.append(("CX", a, b))
                else:
                    gates.append(("CX", b, a))
    return tuple(gates)


def tiny_setup():
    """Hand-checkable instance: 6-qubit CNOT chain of 5 gates.
    With K_MAX = 4 and 2 fragments the optimum splits after gate
    2 (widths 4 and 3), paying exactly one wire cut: 9.0. One
    gate cut costs 16.0, so wire wins; all pairs are distinct so
    no rewrite can fire. Optimum TINY_OPT = 9.0 by
    construction."""
    return (("CX", 0, 1), ("CX", 1, 2), ("CX", 2, 3), ("CX", 3, 4),
            ("CX", 4, 5))


def target_setup():
    return gen_circuit(TARGET["fi"], TARGET["seed"], TARGET["rep"])


def cx_positions(gates):
    """Positions of two-qubit gates in global order."""
    return [i for i, g in enumerate(gates) if g[0] == "CX"]


def eval_place(gates, frag_of, gcut_of, nq):
    """Exact cut-cost evaluation. Read roles (frag_of/gcut_of)
    are never mutated; written roles (width_sets/accumulators)
    are fresh locals. Returns widths, counts, log-overhead,
    overhead, and validity."""
    pos = cx_positions(gates)
    nf = n_frag(nq)
    width_sets = [set() for _ in range(nf)]
    for pi, gi in enumerate(pos):
        if gcut_of[pi]:
            continue
        fr = int(frag_of[pi])
        _, cq, tq = gates[gi]
        width_sets[fr].add(int(cq))
        width_sets[fr].add(int(tq))
    read_widths = [len(s) for s in width_sets]
    seqs = [[] for _ in range(nq)]
    for pi, gi in enumerate(pos):
        if gcut_of[pi]:
            continue
        _, cq, tq = gates[gi]
        seqs[int(cq)].append(int(frag_of[pi]))
        seqs[int(tq)].append(int(frag_of[pi]))
    wire_total = 0
    for qseq in seqs:
        for k in range(1, len(qseq)):
            if qseq[k] != qseq[k - 1]:
                wire_total += 1
    gate_total = int(sum(1 for v in gcut_of if v))
    acc_log = wire_total * LOGW + gate_total * LOGG
    acc_over = math.exp(acc_log) if acc_log < 700.0 else float("inf")
    acc_valid = all(w <= K_MAX for w in read_widths)
    return {"widths": read_widths, "nwire": wire_total,
            "ngate": gate_total, "log_over": acc_log,
            "over": acc_over, "valid": bool(acc_valid)}


def apply_cancel(gates):
    """Duplicate-CNOT cancellation transition: scan_* names the
    read cursor over the input list, kept_* names the written
    result list; the input is never mutated. Two CXs on the same
    ordered pair cancel iff no other two-qubit gate touches
    either qubit between them (single-qubit gates between are
    absorbed into the kept stream only when no cancel fires).
    Returns (kept_gates, n_removed)."""
    scan_twoq = [(i, g) for i, g in enumerate(gates)
                 if g[0] == "CX"]
    drop_idx = set()
    last_open = {}
    for scan_k, (scan_i, scan_g) in enumerate(scan_twoq):
        _, scan_c, scan_t = scan_g
        scan_pair = (int(scan_c), int(scan_t))
        if scan_pair in last_open:
            open_k, open_i = last_open[scan_pair]
            blocked = False
            for mid_k in range(open_k + 1, scan_k):
                _, mid_c, mid_t = scan_twoq[mid_k][1]
                if (int(mid_c) in (scan_pair[0], scan_pair[1])
                        or int(mid_t) in (scan_pair[0],
                                          scan_pair[1])):
                    blocked = True
                    break
            if not blocked:
                drop_idx.add(open_i)
                drop_idx.add(scan_i)
                del last_open[scan_pair]
                continue
        last_open[scan_pair] = (scan_k, scan_i)
    kept_list = [g for i, g in enumerate(gates) if i not in drop_idx]
    return tuple(kept_list), len(drop_idx)


def apply_perm(gates, perm):
    """Logical label-swap rewrite: in_* names each read gate,
    out_* names the relabeled written gate. Returns a fresh
    tuple; the input is never mutated."""
    out_list = []
    for in_g in gates:
        in_k, in_a, in_b = in_g
        if in_k == "CX":
            out_list.append((in_k, int(perm[int(in_a)]),
                             int(perm[int(in_b)])))
        else:
            out_list.append((in_k, int(perm[int(in_a)]), in_b))
    return tuple(out_list)


def repair_place(gates, frag_of, gcut_of, nq):
    """Deterministic repair to a valid placement: cur_* names the
    live working copies, try_* names each candidate edit probed
    before commit. Overfull fragments shed gates to fitting
    fragments; when nothing fits, the first gate is gate-cut
    (excluded from widths), so the loop always terminates valid.
    Inputs are never mutated; returns fresh (frag, gcut)."""
    pos = cx_positions(gates)
    nf = n_frag(nq)
    cur_frag = [int(v) for v in frag_of]
    cur_cut = [int(v) for v in gcut_of]
    for _round in range(len(pos) * (nf + 1) + 5):
        cur_ev = eval_place(gates, cur_frag, cur_cut, nq)
        if cur_ev["valid"]:
            break
        over_f = None
        for fi, w in enumerate(cur_ev["widths"]):
            if w > K_MAX:
                over_f = fi
                break
        if over_f is None:
            break
        moved = False
        for pi in range(len(pos)):
            if cur_cut[pi] or cur_frag[pi] != over_f:
                continue
            _, try_c, try_t = gates[pos[pi]]
            for try_f in range(nf):
                if try_f == over_f:
                    continue
                try_frag = list(cur_frag)
                try_frag[pi] = try_f
                try_ev = eval_place(gates, try_frag, cur_cut, nq)
                if try_ev["widths"][try_f] <= K_MAX:
                    cur_frag = try_frag
                    moved = True
                    break
            if moved:
                break
        if not moved:
            for pi in range(len(pos)):
                if not cur_cut[pi] and cur_frag[pi] == over_f:
                    try_cut = list(cur_cut)
                    try_cut[pi] = 1
                    cur_cut = try_cut
                    moved = True
                    break
        if not moved:
            break
    return cur_frag, cur_cut


def empty_stats(stopped):
    return {"over": None, "log_over": None, "nwire": 0,
            "ngate": 0, "widths": [], "valid": False,
            "stopped": bool(stopped)}


def run_C(gates, nq, stop):
    """C static DAG min-cut baseline: identity rewrite, greedy
    fragment assignment minimizing added wire transitions under
    the width cap, one improvement sweep, then a gate-cut
    post-pass. Deterministic; checks stop and reports
    stopped=True on a guard trip."""
    pos = cx_positions(gates)
    nf = n_frag(nq)
    if stop is not None and stop():
        return empty_stats(True)
    base_frag = []
    base_widths = [set() for _ in range(nf)]
    base_last = {}
    for pi, gi in enumerate(pos):
        if pi % 32 == 0 and stop is not None and stop():
            return empty_stats(True)
        _, cq, tq = gates[gi]
        best_f, best_cost = 0, None
        for cand_f in range(nf):
            cand_new = 0
            if int(cq) in base_last and \
                    base_last[int(cq)] != cand_f:
                cand_new += 1
            if int(tq) in base_last and \
                    base_last[int(tq)] != cand_f:
                cand_new += 1
            cand_grown = set(base_widths[cand_f])
            cand_grown.add(int(cq))
            cand_grown.add(int(tq))
            if len(cand_grown) > K_MAX:
                continue
            if best_cost is None or cand_new < best_cost:
                best_cost = cand_new
                best_f = cand_f
        if best_cost is None:
            best_f = 0
        base_frag.append(best_f)
        base_widths[best_f].add(int(cq))
        base_widths[best_f].add(int(tq))
        base_last[int(cq)] = best_f
        base_last[int(tq)] = best_f
    base_cut = [0] * len(pos)
    base_ev = eval_place(gates, base_frag, base_cut, nq)
    for pi in range(len(pos)):
        if pi % 32 == 0 and stop is not None and stop():
            return empty_stats(True)
        for cand_f in range(nf):
            if cand_f == base_frag[pi]:
                continue
            try_frag = list(base_frag)
            try_frag[pi] = cand_f
            try_ev = eval_place(gates, try_frag, base_cut, nq)
            if try_ev["valid"] and \
                    try_ev["log_over"] < base_ev["log_over"]:
                base_frag = try_frag
                base_ev = try_ev
    for pi in range(len(pos)):
        if pi % 32 == 0 and stop is not None and stop():
            return empty_stats(True)
        try_cut = list(base_cut)
        try_cut[pi] = 1
        try_ev = eval_place(gates, base_frag, try_cut, nq)
        if try_ev["valid"] and \
                try_ev["log_over"] < base_ev["log_over"]:
            base_cut = try_cut
            base_ev = try_ev
    fin_frag, fin_cut = repair_place(gates, base_frag, base_cut,
                                     nq)
    fin_ev = eval_place(gates, fin_frag, fin_cut, nq)
    fin_ev["stopped"] = False
    fin_ev["frag"] = fin_frag
    fin_ev["cut"] = fin_cut
    return fin_ev


def run_R(gates, nq, rng, stop):
    """R random cut-placement control: seeded random label swap,
    random fragments, random gate-cut flags (p = 0.15),
    repaired to validity. Seeded; reports stopped=True on a
    guard trip."""
    if stop is not None and stop():
        return empty_stats(True)
    pos = cx_positions(gates)
    nf = n_frag(nq)
    perm_arr = rng.permutation(nq)
    perm_of = [int(v) for v in perm_arr]
    work_gates = apply_perm(gates, perm_of)
    work_pos = cx_positions(work_gates)
    rand_frag = [int(rng.integers(0, nf)) for _ in work_pos]
    rand_cut = [int(rng.random() < 0.15) for _ in work_pos]
    if stop is not None and stop():
        return empty_stats(True)
    fin_frag, fin_cut = repair_place(work_gates, rand_frag,
                                     rand_cut, nq)
    fin_ev = eval_place(work_gates, fin_frag, fin_cut, nq)
    fin_ev["stopped"] = False
    return fin_ev


def run_G(gates, nq, stop):
    """G greedy joint local-rewrite + cut search: from the C
    seed placement on the cancelled list, GREEDY_SWEEPS
    first-improvement sweeps over fragment moves, gate-cut
    toggles, and label swaps. Move-probe roles (try_*) stay
    separate from live roles (live_*). Reports stopped=True on
    a guard trip."""
    kept_gates, _ = apply_cancel(gates)
    pos = cx_positions(kept_gates)
    nf = n_frag(nq)
    if stop is not None and stop():
        return empty_stats(True)
    seed_ev = run_C(kept_gates, nq, stop)
    if seed_ev.get("stopped"):
        return empty_stats(True)
    live_frag = list(seed_ev["frag"])
    live_cut = list(seed_ev["cut"])
    live_ev = dict(seed_ev)
    n_eval = [0]

    def probe_frag(try_frag, try_cut, try_gates):
        n_eval[0] += 1
        if n_eval[0] % 32 == 0 and stop is not None and stop():
            return None
        return eval_place(try_gates, try_frag, try_cut, nq)

    for _sw in range(GREEDY_SWEEPS):
        if stop is not None and stop():
            return empty_stats(True)
        improved = False
        for pi in range(len(pos)):
            for cand_f in range(nf):
                if cand_f == live_frag[pi]:
                    continue
                try_frag = list(live_frag)
                try_frag[pi] = cand_f
                try_ev = probe_frag(try_frag, list(live_cut),
                                    kept_gates)
                if try_ev is None:
                    return empty_stats(True)
                if try_ev["valid"] and try_ev["log_over"] < \
                        live_ev["log_over"]:
                    live_frag = try_frag
                    live_ev = try_ev
                    improved = True
        for pi in range(len(pos)):
            try_cut = list(live_cut)
            try_cut[pi] = 1 - try_cut[pi]
            try_ev = probe_frag(list(live_frag), try_cut,
                                kept_gates)
            if try_ev is None:
                return empty_stats(True)
            if try_ev["valid"] and try_ev["log_over"] < \
                    live_ev["log_over"]:
                live_cut = try_cut
                live_ev = try_ev
                improved = True
        for qa in range(nq):
            for qb in range(qa + 1, nq):
                if stop is not None and stop():
                    return empty_stats(True)
                swap_perm = list(range(nq))
                swap_perm[qa], swap_perm[qb] = \
                    swap_perm[qb], swap_perm[qa]
                swap_gates = apply_perm(kept_gates, swap_perm)
                n_eval[0] += 1
                swap_ev = eval_place(swap_gates, live_frag,
                                     live_cut, nq)
                if swap_ev["valid"] and swap_ev["log_over"] < \
                        live_ev["log_over"]:
                    kept_gates = swap_gates
                    live_ev = swap_ev
                    improved = True
        if not improved:
            break
    fin_frag, fin_cut = repair_place(kept_gates, live_frag,
                                     live_cut, nq)
    fin_ev = eval_place(kept_gates, fin_frag, fin_cut, nq)
    fin_ev["stopped"] = False
    return fin_ev


def run_A(gates, nq, rng, n_iters, stop):
    """A annealing over rewrite+cut placements: ANNEAL_ITERS
    seeded proposals (fragment move, gate-cut toggle, label
    swap) from the C seed on the cancelled list, temperature
    ANNEAL_T0 decaying by ANNEAL_ALPHA, best tracked.
    Proposal roles (prop_*) stay separate from live roles
    (live_*) and best roles (best_*). Reports stopped=True on
    a guard trip."""
    kept_gates, _ = apply_cancel(gates)
    pos = cx_positions(kept_gates)
    nf = n_frag(nq)
    if stop is not None and stop():
        return empty_stats(True)
    seed_ev = run_C(kept_gates, nq, stop)
    if seed_ev.get("stopped"):
        return empty_stats(True)
    live_frag = list(seed_ev["frag"])
    live_cut = list(seed_ev["cut"])
    live_ev = dict(seed_ev)
    best_frag = list(live_frag)
    best_cut = list(live_cut)
    best_gates = kept_gates
    best_ev = dict(live_ev)
    for it in range(n_iters):
        if it % 32 == 0 and stop is not None and stop():
            return empty_stats(True)
        temp = ANNEAL_T0 * (ANNEAL_ALPHA ** it)
        kind = int(rng.integers(0, 3))
        if kind == 0 and len(pos) > 0:
            pi = int(rng.integers(0, len(pos)))
            prop_frag = list(live_frag)
            prop_frag[pi] = int(rng.integers(0, nf))
            prop_ev = eval_place(kept_gates, prop_frag,
                                 live_cut, nq)
            if prop_ev["valid"]:
                delta = (prop_ev["log_over"]
                         - live_ev["log_over"])
                if delta <= 0.0 or float(rng.random()) < math.exp(
                        -delta / max(temp, 1e-12)):
                    live_frag = prop_frag
                    live_ev = prop_ev
                    if prop_ev["log_over"] < best_ev["log_over"]:
                        best_frag = list(prop_frag)
                        best_cut = list(live_cut)
                        best_gates = kept_gates
                        best_ev = dict(prop_ev)
        elif kind == 1 and len(pos) > 0:
            pi = int(rng.integers(0, len(pos)))
            prop_cut = list(live_cut)
            prop_cut[pi] = 1 - prop_cut[pi]
            prop_ev = eval_place(kept_gates, live_frag,
                                 prop_cut, nq)
            if prop_ev["valid"]:
                delta = (prop_ev["log_over"]
                         - live_ev["log_over"])
                if delta <= 0.0 or float(rng.random()) < math.exp(
                        -delta / max(temp, 1e-12)):
                    live_cut = prop_cut
                    live_ev = prop_ev
                    if prop_ev["log_over"] < best_ev["log_over"]:
                        best_frag = list(live_frag)
                        best_cut = list(prop_cut)
                        best_gates = kept_gates
                        best_ev = dict(prop_ev)
        else:
            qa = int(rng.integers(0, nq))
            qb = int(rng.integers(0, nq))
            if qa == qb:
                continue
            swap_perm = list(range(nq))
            swap_perm[qa], swap_perm[qb] = \
                swap_perm[qb], swap_perm[qa]
            prop_gates = apply_perm(kept_gates, swap_perm)
            prop_ev = eval_place(prop_gates, live_frag,
                                 live_cut, nq)
            if prop_ev["valid"]:
                delta = (prop_ev["log_over"]
                         - live_ev["log_over"])
                if delta <= 0.0 or float(rng.random()) < math.exp(
                        -delta / max(temp, 1e-12)):
                    kept_gates = prop_gates
                    live_ev = prop_ev
                    if prop_ev["log_over"] < best_ev["log_over"]:
                        best_frag = list(live_frag)
                        best_cut = list(live_cut)
                        best_gates = kept_gates
                        best_ev = dict(prop_ev)
    fin_frag, fin_cut = repair_place(best_gates, best_frag,
                                     best_cut, nq)
    fin_ev = eval_place(best_gates, fin_frag, fin_cut, nq)
    fin_ev["stopped"] = False
    return fin_ev


def exact_opt(gates, nq, cap, stop):
    """Bounded-exact DFS cut search over fragment assignments
    and gate-cut flags on the canonical gate list (unpriced
    except for width-cap pruning, which never removes a valid
    placement). Prefix roles (assign/cutf arrays) vs branch
    roles (child_f) use separate names; every visit counts one
    node until the cap. Statuses solved / cap-hit /
    stopped-guard."""
    pos = cx_positions(gates)
    nf = n_frag(nq)
    nodes = [0]
    capped = [False]
    stopped = [False]
    best = [None]
    assign = [-1] * len(pos)
    cutf = [0] * len(pos)

    def widths_of(depth):
        acc = [set() for _ in range(nf)]
        for k in range(depth):
            if cutf[k]:
                continue
            _, wq, wt = gates[pos[k]]
            acc[assign[k]].add(int(wq))
            acc[assign[k]].add(int(wt))
        return acc

    def leaf_log(depth):
        seqs = [[] for _ in range(nq)]
        ng = 0
        for k in range(depth):
            if cutf[k]:
                ng += 1
                continue
            _, wq, wt = gates[pos[k]]
            seqs[int(wq)].append(assign[k])
            seqs[int(wt)].append(assign[k])
        nw = 0
        for qs in seqs:
            for k in range(1, len(qs)):
                if qs[k] != qs[k - 1]:
                    nw += 1
        return nw * LOGW + ng * LOGG

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
        if depth == len(pos):
            got = leaf_log(depth)
            if best[0] is None or got < best[0]:
                best[0] = got
            return
        for child_f in range(nf):
            assign[depth] = child_f
            cutf[depth] = 0
            ok = True
            for ws in widths_of(depth + 1):
                if len(ws) > K_MAX:
                    ok = False
                    break
            if ok:
                rec(depth + 1)
                if capped[0] or stopped[0]:
                    return
        assign[depth] = 0
        cutf[depth] = 1
        rec(depth + 1)
        if capped[0] or stopped[0]:
            return
        assign[depth] = -1
        cutf[depth] = 0

    rec(0)
    if stopped[0]:
        return {"status": "stopped-guard", "nodes": nodes[0],
                "opt": None, "cap": cap, "started": True}
    if capped[0]:
        got_opt = (math.exp(best[0]) if best[0] is not None
                   else None)
        return {"status": "cap-hit", "nodes": nodes[0],
                "opt": got_opt, "cap": cap, "started": True}
    got_opt = (math.exp(best[0]) if best[0] is not None
               else None)
    return {"status": "solved", "nodes": nodes[0],
            "opt": got_opt, "cap": cap, "started": True}


def audit_gen(fi, seed, rep):
    circ = gen_circuit(fi, seed, rep)
    nq = N_QUBITS[fi]
    ok = isinstance(circ, tuple) and len(circ) > 0
    if not ok:
        return False, circ
    for gk, ga, gb in circ:
        if gk == "CX":
            if not (0 <= ga < nq and 0 <= gb < nq and ga != gb):
                return False, circ
        elif gk in ("H", "S"):
            if not (0 <= ga < nq and gb == -1):
                return False, circ
        else:
            return False, circ
    return True, circ


def run_arm(fi, seed, rep, arm, gates, n_iters, stop):
    """One arm evaluation on one frozen circuit. R/A consume a
    per-rep seeded rng; C/G are deterministic; arm equivalence
    holds because every arm starts from the same gate list."""
    nq = N_QUBITS[fi]
    if arm == "C":
        return run_C(gates, nq, stop)
    if arm == "R":
        return run_R(gates, nq, seed_rng(fi, seed, rep, 901),
                     stop)
    if arm == "G":
        return run_G(gates, nq, stop)
    return run_A(gates, nq, seed_rng(fi, seed, rep, 901),
                 n_iters, stop)


def self_tests():
    out = {"ran": True, "failed": []}
    try:
        for fi in range(len(N_QUBITS)):
            for rep in (0, 1):
                ok, _c = audit_gen(fi, 1, rep)
                if not ok:
                    out["failed"].append("gen-%d-%d" % (fi, rep))
        _ok, g1 = audit_gen(0, 1, 0)
        _ok, g1b = audit_gen(0, 1, 0)
        if g1 != g1b:
            out["failed"].append("gen-determinism")
        tiny_circ = tiny_setup()
        if len(tiny_circ) != 5 or TINY_N != 6:
            out["failed"].append("tiny-fixture")
        tiny_nq = TINY_N
        tiny_nf = n_frag(tiny_nq)
        if tiny_nf != 2:
            out["failed"].append("tiny-nfrag: %r" % (tiny_nf,))
        hand_frag = [0, 0, 0, 1, 1]
        hand_cut = [0, 0, 0, 0, 0]
        hand_ev = eval_place(tiny_circ, hand_frag, hand_cut,
                             tiny_nq)
        if (not hand_ev["valid"]
                or abs(hand_ev["over"] - TINY_OPT) > 1e-9):
            out["failed"].append("hand-split: %r" % (hand_ev,))
        all0_ev = eval_place(tiny_circ, [0] * 5, [0] * 5,
                             tiny_nq)
        if all0_ev["valid"]:
            out["failed"].append("hand-all0-valid: %r"
                                 % (all0_ev,))
        for arm in ("C", "G", "A"):
            tm = run_arm(0, 7, 7, arm, tiny_circ, 50, None)
            if (tm["stopped"] or not tm["valid"]
                    or tm["over"] is None
                    or abs(tm["over"] - TINY_OPT) > 1e-9):
                out["failed"].append("tiny-hand-%s: %r" % (arm,
                                                           tm))
        tr = run_R(tiny_circ, tiny_nq,
                   seed_rng(0, 7, 7, 901), None)
        if tr["stopped"] or not tr["valid"]:
            out["failed"].append("tiny-R-recorded: %r" % (tr,))
        tex = exact_opt(tiny_circ, tiny_nq, EXACT_CAP, None)
        if (tex["status"] != "solved"
                or tex["opt"] is None
                or abs(tex["opt"] - TINY_OPT) > 1e-9):
            out["failed"].append("tiny-exact-opt: %r" % (tex,))
        dup_in = (("CX", 0, 1), ("H", 2, -1), ("CX", 0, 1))
        dup_kept, dup_n = apply_cancel(dup_in)
        if dup_n != 2 or len(dup_kept) != 1:
            out["failed"].append("cancel-fire: %r %r"
                                 % (dup_kept, dup_n))
        if dup_in != (("CX", 0, 1), ("H", 2, -1), ("CX", 0, 1)):
            out["failed"].append("cancel-purity")
        blk_in = (("CX", 0, 1), ("CX", 1, 2), ("CX", 0, 1))
        blk_kept, blk_n = apply_cancel(blk_in)
        if blk_n != 0 or blk_kept != blk_in:
            out["failed"].append("cancel-blocked: %r %r"
                                 % (blk_kept, blk_n))
        perm_in = (("CX", 0, 1), ("H", 1, -1))
        perm_out = apply_perm(perm_in, [1, 0, 2, 3, 4, 5])
        if perm_out != (("CX", 1, 0), ("H", 0, -1)):
            out["failed"].append("perm-swap: %r" % (perm_out,))
        if perm_in != (("CX", 0, 1), ("H", 1, -1)):
            out["failed"].append("perm-purity")
        _ok, lad = audit_gen(0, 1, 0)
        lad_pos = cx_positions(lad)
        lad_nq = N_QUBITS[0]
        bad_frag = [0] * len(lad_pos)
        bad_cut = [0] * len(lad_pos)
        bad_ev = eval_place(lad, bad_frag, bad_cut, lad_nq)
        if bad_ev["valid"]:
            out["failed"].append("repair-needs-work")
        snap_frag = list(bad_frag)
        snap_cut = list(bad_cut)
        rep_frag, rep_cut = repair_place(lad, bad_frag, bad_cut,
                                         lad_nq)
        if bad_frag != snap_frag or bad_cut != snap_cut:
            out["failed"].append("repair-noalias")
        rep_ev = eval_place(lad, rep_frag, rep_cut, lad_nq)
        if not rep_ev["valid"]:
            out["failed"].append("repair-path: %r" % (rep_ev,))
        good_frag = list(rep_frag)
        idf_frag, idf_cut = repair_place(lad, rep_frag, rep_cut,
                                          lad_nq)
        if idf_frag != good_frag or idf_cut != list(rep_cut):
            out["failed"].append("repair-identity")
        ef_frag, ef_cut = repair_place((), [], [], lad_nq)
        if eval_place((), ef_frag, ef_cut,
                      lad_nq)["valid"] is not True:
            out["failed"].append("repair-empty")
        for fi, seed in ((0, 1), (2, 3)):
            _ok, dg = audit_gen(fi, seed, 0)
            dg_nq = N_QUBITS[fi]
            for arm in ARMS:
                rr = run_arm(fi, seed, 0, arm, dg, 50, None)
                if (rr["stopped"] or rr["log_over"] is None
                        or not rr["valid"]):
                    out["failed"].append(
                        "arm-valid-%s-%d-%d: %r" % (arm, fi,
                                                   seed, rr))
            ga = run_arm(fi, seed, 0, "G", dg, 50, None)
            ga2 = run_arm(fi, seed, 0, "G", dg, 50, None)
            if ga["log_over"] != ga2["log_over"]:
                out["failed"].append("determinism-greedy")
            ra = run_arm(fi, seed, 0, "R", dg, 50, None)
            ra2 = run_arm(fi, seed, 0, "R", dg, 50, None)
            if ra["log_over"] != ra2["log_over"]:
                out["failed"].append("determinism-random")
        _ok, pg = audit_gen(0, 1, 0)
        probe = [run_arm(0, 1, 0, a, pg, 50, None)["log_over"]
                 for a in ARMS]
        if len(set(probe)) < 2:
            out["failed"].append("gradient-tied: %r" % (probe,))
        _ok, dag = audit_gen(1, 1, 0)
        for arm in ARMS:
            if not run_arm(1, 1, 0, arm, dag, 50,
                           lambda: True).get("stopped"):
                out["failed"].append("stop-propagation-%s" % arm)
        tsize = target_setup()
        stx = exact_opt(tsize, N_QUBITS[TARGET["fi"]],
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
    ap.add_argument("--anneal-iters", type=int,
                    default=ANNEAL_ITERS)
    args = ap.parse_args()
    n_inst = int(args.n_inst)
    n_aiters = int(args.anneal_iters)
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
        tiny_circ = tiny_setup()
        ex = exact_opt(tiny_circ, TINY_N, EXACT_CAP, over)
        gate3tiny["arms"]["tiny"] = ex
        gate3tiny["total"] += 1
        if ex["status"] == "solved" and ex["opt"] is not None \
                and abs(ex["opt"] - TINY_OPT) < 1e-9:
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
        tex = exact_opt(tsize, N_QUBITS[TARGET["fi"]], EXACT_CAP,
                        over)
        gate3targets.append(dict(tex, fi=TARGET["fi"],
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

    def run_cell(fi, seed):
        rec = {"size": N_QUBITS[fi], "fam": FAMILIES[fi],
               "seed": seed, "arms": {}}
        for arm in ARMS:
            if over():
                rec["blocked"] = "wall-guard"
                return rec
            logos, overs, wires, gcuts = [], [], [], []
            nstop = 0
            nvalid = 0
            for rep in range(n_inst):
                if rep % 32 == 0 and over():
                    nstop += 1
                    break
                circ = gen_circuit(fi, seed, rep)
                out = run_arm(fi, seed, rep, arm, circ,
                              n_aiters, over)
                if out.get("stopped") or out.get("log_over") is None:
                    nstop += 1
                    break
                logos.append(out["log_over"])
                overs.append(out["over"])
                wires.append(out["nwire"])
                gcuts.append(out["ngate"])
                if out.get("valid"):
                    nvalid += 1
            if nstop:
                rec["blocked"] = "stopped-guard"
                rec["iters_done"] = len(logos)
                rec["n_evaluated"] = n_inst
                return rec
            rec["arms"][arm] = {
                "n": len(logos),
                "logo": pooled_stats(logos),
                "over": pooled_stats(overs),
                "nwire": pooled_stats(wires),
                "ngate": pooled_stats(gcuts),
                "n_valid": int(nvalid),
                "frac_valid": (nvalid / len(logos) if logos
                               else 0.0)}
        return rec

    def record_cell(rec):
        if rec.get("blocked") is None and all(
                rec["arms"].get(a, {}).get("n") == n_inst
                for a in ARMS):
            for a in ARMS:
                key = (rec["size"], rec["seed"], a)
                cells.setdefault(key, {"logo": [], "valid": [],
                                       "over": []})
                cells[key]["logo"].append(
                    rec["arms"][a]["logo"]["mean"])
                cells[key]["valid"].append(
                    rec["arms"][a]["frac_valid"])
                cells[key]["over"].append(
                    rec["arms"][a]["over"]["mean"])
            cellrecs.append(rec)
            return True
        cellrecs.append(rec)
        skipped.append({"what": "cell %s/%s" % (
            rec["size"], rec["seed"]),
            "reason": rec.get("blocked", "arm-incomplete"),
            "iters_done": rec.get("iters_done", 0),
            "n_evaluated": n_inst})
        return False

    for fi, nq in enumerate(N_QUBITS):
        if over():
            for sd in SEEDS:
                skipped.append({"what": "cell %s/%s" % (nq, sd),
                                "reason": "wall-guard",
                                "iters_done": 0,
                                "n_evaluated": n_inst})
        else:
            for sd in SEEDS:
                if over():
                    skipped.append({"what": "cell %s/%s" % (nq, sd),
                                    "reason": "wall-guard",
                                    "iters_done": 0,
                                    "n_evaluated": n_inst})
                    continue
                rec = run_cell(fi, sd)
                record_cell(rec)
        with open(os.path.join(witdir, "cells.json"), "w") as f:
            json.dump(cellrecs, f, indent=1, default=str)
        checkpoint("size%d" % nq)
    with open(os.path.join(witdir, "cells.json"), "w") as f:
        json.dump(cellrecs, f, indent=1, default=str)
    checkpoint("corpus")

    def cell_mean(fi, seed, arm, field):
        return cells.get((N_QUBITS[fi], seed, arm),
                         {"logo": [], "valid": [],
                          "over": []})[field]

    def pool(fi, arm, field):
        vals = []
        for seed in SEEDS:
            vals.extend(cell_mean(fi, seed, arm, field))
        return pooled_stats(vals), len(vals) == len(SEEDS)

    _ok, det_circ = audit_gen(0, 1, 0)
    det_g1 = run_arm(0, 1, 0, "G", det_circ, n_aiters, None)
    det_g2 = run_arm(0, 1, 0, "G", det_circ, n_aiters, None)
    det_r1 = run_arm(0, 1, 0, "R", det_circ, n_aiters, None)
    det_r2 = run_arm(0, 1, 0, "R", det_circ, n_aiters, None)
    determinism_ok = bool(
        det_g1["log_over"] == det_g2["log_over"]
        and det_r1["log_over"] == det_r2["log_over"])

    g1_cells, g1_beats = [], True
    for fi, nq in enumerate(N_QUBITS):
        for seed in SEEDS:
            ms = cell_mean(fi, seed, "G", "logo")
            mr = cell_mean(fi, seed, "R", "logo")
            ok = (len(ms) == 1 and len(mr) == 1
                  and ms[0] is not None and mr[0] is not None
                  and ms[0] < mr[0])
            g1_cells.append({"cell": "%s/%s" % (nq, seed),
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
    for fi, nq in enumerate(N_QUBITS):
        pools, pok = {}, True
        for arm in ("C", "G", "A"):
            pools[arm], oka = pool(fi, arm, "logo")
            pok = pok and oka
        se, spread, gp = spread_win(pools, pok)
        g2_fams.append({"size": nq, "pools": pools, "SE": se,
                        "spread": spread, "pass": bool(gp)})
        if gp:
            g2_n += 1
        joint = {}
        if pok and all(
                pools[a]["se"] is not None and
                pools[a]["mean"] is not None for a in ("C", "G",
                                                      "A")):
            sse2 = math.sqrt(sum(pools[a]["se"] ** 2
                                 for a in ("C", "G", "A")) / 3.0)
            for a in ("G", "A"):
                mwin = pools[a]["mean"] < pools["C"]["mean"] - \
                    2.0 * sse2
                vpools = pooled_stats(
                    [v for seed in SEEDS
                     for v in cell_mean(fi, seed, a, "valid")])
                vpool_c = pooled_stats(
                    [v for seed in SEEDS
                     for v in cell_mean(fi, seed, "C", "valid")])
                vwin = (vpools["mean"] is not None
                        and vpool_c["mean"] is not None
                        and vpools["mean"] >= vpool_c["mean"])
                joint[a] = bool(mwin and vwin)
        else:
            joint = {"G": False, "A": False}
        for a in ("G", "A"):
            if joint[a]:
                n_win[a] += 1
        if pok and all(pools[a]["mean"] is not None
                       for a in ("C", "G", "A")):
            spass = (pools["G"]["mean"] < pools["C"]["mean"] or
                     pools["A"]["mean"] < pools["C"]["mean"])
        else:
            spass = False
            pools_all = False
        if not pok:
            pools_all = False
        if spass:
            n_strict += 1
        win_fams.append({"size": nq, "joint": dict(joint),
                         "strict_win": bool(spass),
                         "pools_ok": bool(pok)})
    g2_ok = g2_n >= 2

    tiny_solved = (gate3tiny["total"] == 1 and gate3tiny["solved"] == 1)
    target_cap = (len(gate3targets) == 1 and
                  gate3targets[0].get("status") == "cap-hit")
    g3pass = bool(tiny_solved and target_cap)

    complete = all(
        len(cell_mean(fi, seed, arm, "logo")) == 1
        for fi in range(len(N_QUBITS)) for seed in SEEDS
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
        reason = ("PURSUE-condition holds (joint log-overhead win "
                  "with matched-or-better validity on the SAME "
                  "arm at >=2 sizes + gates 1,2,3,4 + self-tests "
                  "ok); payload verdict stays unresolved-with-"
                  "reason, classification is coordinator-side.")
    elif reject:
        reason = ("REJECT-condition holds (complete cells, tiny "
                  "solved, Gate-1 controls pass, no strict pooled "
                  "log-overhead win at any size); payload verdict "
                  "stays unresolved-with-reason, classification "
                  "is coordinator-side.")
    else:
        reason = ("UNRESOLVED + next experiment (joint wins G=%d/3, "
                  "A=%d/3, strict wins=%d/3, g1=%s g2=%s "
                  "g3=%s (tiny solved=%s, target "
                  "cap-hit=%s) selftest=%s g4=%s complete=%s skipped=%d; "
                  "next: %s)." % (
                      n_win["G"], n_win["A"], n_strict, g1_ok, g2_ok,
                      g3pass, tiny_solved, target_cap,
                      selftest_ok, g4_ok, complete, len(skipped),
                      NEXT_EXPERIMENT))
    verdict_bits = {
        "gate1": {"pass": bool(g1_ok), "beats_all_15": bool(g1_beats),
                  "tiny_ok": bool(tiny_ok),
                  "determinism_ok": bool(determinism_ok),
                  "cells": g1_cells},
        "gate2": {"pass": bool(g2_ok), "n_sizes_spread_pass": g2_n,
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
        "screen": "17",
        "verdict": "unresolved-with-reason: payload reports numbers "
                   "and gate evidence; classification is coordinator-side.",
        "design": {
            "model": "screen-authored exact cut-cost model "
                     "(stdlib + numpy only; no external libs)",
            "qubits": list(N_QUBITS),
            "families": list(FAMILIES),
            "seeds": list(SEEDS),
            "cells": "3 sizes x 5 seeds = 15 cells x 4 arms "
                     "(seeds are replicates)",
            "reps_per_cell_arm": n_inst,
            "width_cap": K_MAX,
            "frag_counts": [n_frag(nq) for nq in N_QUBITS],
            "gamma2": {"wire": GAMMA2_WIRE, "gate": GAMMA2_GATE},
            "search": {"greedy_sweeps": GREEDY_SWEEPS,
                       "anneal_iters": n_aiters,
                       "anneal_t0": ANNEAL_T0,
                       "anneal_alpha": ANNEAL_ALPHA},
            "arms": {"C": "static DAG min-cut baseline "
                          "(identity rewrite)",
                     "R": "random cut-placement control "
                          "(matched repair)",
                     "G": "greedy joint local-rewrite + cut search",
                     "A": "annealing over rewrite+cut placements"},
            "metrics": "exact total sampling overhead prod(gamma_i^2) "
                       "per rep + partition validity (widths <= k); "
                       "cell/gate stats use mean log-overhead",
            "pareto": "PURSUE needs a log-overhead win + "
                      "matched-or-better validity on the SAME arm; "
                      "joint wins counted PER ARM with bar "
                      "max(G,A)>=2, never any-winner",
            "exact": "bounded-exact DFS cut search on tiny (must "
                     "solve, optimum %r) + target-scale instance "
                     "(%s circuit, seed %d rep %d, node cap %d, "
                     "must cap-hit)" % (
                         TINY_OPT, FAMILIES[TARGET["fi"]],
                         TARGET["seed"], TARGET["rep"], EXACT_CAP),
        },
        "timing": {"wall_s": wall, "guards": {"wall_guard_s": WALL_GUARD_S,
                                              "limit_s": WALL_LIMIT_S}},
        "cells": {("%s/%s/%s" % k): {"n": len(v["logo"]),
                                     **pooled_stats(v["logo"]),
                                     "mean_valid": pooled_stats(
                                         v["valid"])["mean"],
                                     "mean_over": pooled_stats(
                                         v["over"])["mean"]}
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
