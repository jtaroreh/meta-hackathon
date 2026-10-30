"""Screen 21 payload: sparse state preparation & unitary multiplexer decision trees.

Screen-authored exact amplitude-loading decision-tree builder
(stdlib + numpy only; no external physics/solver libs): sparse
chemistry-like target states on n in {10, 14, 18} qubits with
frozen determinant counts S in {24, 48, 96}; each variable
ordering induces an ordered decision tree with BDD-style suffix
merging (shared CNOT-sharing paths); every two-sided branch
node emits CNOTS_PER_BRANCH logical CNOTs routed on frozen
grid / heavy-hex layouts. Arms: M canonical ordering Gray-code
multiplexer baseline, R random ordering control, G greedy
tree-rotation + qubit-reordering search, A simulated annealing
over orderings (cost = routed CNOTs + LAMBDA * depth). Metric:
routed CNOT count + two-qubit depth after frozen-layout
routing + state-validity verification. A bounded-exact
branch-and-bound over orderings validates the tiny instance
(solved, optimum by construction) and cap-hits at target scale
(limit-expiry). Writes ALL output under cwd (the attempt work
dir): results.json + witnesses/. Deterministic given seeds.
Verdict is always unresolved-with-reason; classification is
coordinator-side.
"""

import argparse
import json
import math
import os
import time

import numpy as np

N_QUBITS = (10, 14, 18)
S_COUNTS = {10: 24, 14: 48, 18: 96}
FAMILIES = {10: "CISD", 14: "SELECTED_CI", 18: "SELECTED_CI_PLUS"}
SEEDS = (1, 2, 3, 4, 5)
ARMS = ("M", "R", "G", "A")

N_INST = 12
GREEDY_SWEEPS = 2
ANNEAL_ITERS = 80
ANNEAL_T0 = 2.0
ANNEAL_ALPHA = 0.985
LAMBDA = 5.0
CNOTS_PER_BRANCH = 2

WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0
EXACT_CAP = 50000

TINY_N = 3
TINY_DETS = ("000", "111")
TINY_AMPS = (0.6, 0.8)
TINY_OPT = {"cnots": 2, "depth": 2}
TARGET = {"size_idx": 2, "seed": 1, "rep": 0, "layout": "grid"}
NEXT_EXPERIMENT = ("adaptive variable-ordering search with look-ahead + "
                   "depth-regularized ordering annealing retest")

TINY_DIST = ((0, 1, 2), (1, 0, 1), (2, 1, 0))


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
for _n in N_QUBITS:
    LAYOUT_EDGES[(_n, "grid")] = grid_edges(_n, _n // 2)
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


def mask_of_str(s):
    mask = 0
    for q, ch in enumerate(s):
        if ch == "1":
            mask |= 1 << q
    return mask


def gen_state(size_idx, seed, rep):
    """Seeded sparse chemistry-like target: S distinct determinants
    with seeded normalized amplitudes. Deterministic given inputs."""
    n = N_QUBITS[size_idx]
    s = S_COUNTS[n]
    gen_rng = seed_rng(size_idx, seed, rep, 11)
    pool = gen_rng.choice(1 << n, size=s, replace=False)
    mag_vals = gen_rng.random(s) + 0.25
    sign_vals = np.where(gen_rng.random(s) < 0.5, -1.0, 1.0)
    raw_amps = mag_vals * sign_vals
    raw_amps = raw_amps / np.linalg.norm(raw_amps)
    paired = sorted((int(pool[i]), float(raw_amps[i])) for i in range(s))
    det_masks = tuple(p[0] for p in paired)
    det_amps = tuple(p[1] for p in paired)
    return {"dets": det_masks, "amps": det_amps, "n": n,
            "family": FAMILIES[n], "layout": layout_of(rep)}


def tiny_state():
    det_masks = tuple(mask_of_str(s) for s in TINY_DETS)
    norm = math.sqrt(sum(a * a for a in TINY_AMPS))
    det_amps = tuple(a / norm for a in TINY_AMPS)
    return {"dets": det_masks, "amps": det_amps, "n": TINY_N,
            "family": "TINY", "layout": "line"}


def build_plan(order, dets, n):
    """Ordered decision tree with BDD-style suffix merging. Returns
    the list of (control, target) logical CNOT pairs, one per
    two-sided branch node. Merging key = projected suffix set, so
    shared CNOT-sharing paths emit once."""
    det_list = list(dets)
    cur_nodes = [frozenset(det_list)]
    plan_pairs = []
    for lvl in range(n):
        ctrl_qubit = order[lvl]
        tgt_qubit = order[(lvl + 1) % n]
        rem_mask = 0
        for qq in order[lvl + 1:]:
            rem_mask |= 1 << qq
        next_by_key = {}
        for node_set in cur_nodes:
            lo_set = frozenset(
                d for d in node_set if not (d >> ctrl_qubit) & 1)
            hi_set = frozenset(
                d for d in node_set if (d >> ctrl_qubit) & 1)
            if lo_set and hi_set:
                plan_pairs.append((ctrl_qubit, tgt_qubit))
                child_sets = (lo_set, hi_set)
            else:
                child_sets = (lo_set | hi_set,)
            for child_set in child_sets:
                if len(child_set) <= 1:
                    continue
                merge_key = frozenset(
                    d & rem_mask for d in child_set)
                if merge_key not in next_by_key:
                    next_by_key[merge_key] = child_set
        cur_nodes = list(next_by_key.values())
        if not cur_nodes:
            break
    return plan_pairs


def route_plan(plan_pairs, dist, n):
    """Route logical CNOT pairs: 3d-2 routed CNOTs per CNOT at graph
    distance d, list-scheduled with block duration 2*(2d-1)."""
    free_time = [0] * n
    routed_total = 0
    for ctrl_qubit, tgt_qubit in plan_pairs:
        graph_d = dist[ctrl_qubit][tgt_qubit]
        for _ in range(CNOTS_PER_BRANCH):
            routed_total += 3 * graph_d - 2
        block_dur = CNOTS_PER_BRANCH * (2 * graph_d - 1)
        start_t = (free_time[ctrl_qubit]
                   if free_time[ctrl_qubit] >= free_time[tgt_qubit]
                   else free_time[tgt_qubit])
        end_t = start_t + block_dur
        free_time[ctrl_qubit] = end_t
        free_time[tgt_qubit] = end_t
    return int(routed_total), int(max(free_time)) if free_time else 0


def eval_ordering(order, dets, dist, n):
    plan_pairs = build_plan(order, dets, n)
    routed_cnots, sched_depth = route_plan(plan_pairs, dist, n)
    return routed_cnots, sched_depth


def verify_state(order, dets, amps):
    """Exact amplitude-loading check: walk each determinant down the
    ordering, multiplying branch mass ratios (telescoping, so the
    leaf probability must equal amp^2). Returns max abs error."""
    idx_all = frozenset(range(len(dets)))
    mass_of = {}
    worst_err = 0.0
    for det_i in range(len(dets)):
        cur_set = idx_all
        leaf_prob = 1.0
        for lvl in range(len(order)):
            ctrl_qubit = order[lvl]
            lo_set = frozenset(
                j for j in cur_set if not (dets[j] >> ctrl_qubit) & 1)
            hi_set = frozenset(
                j for j in cur_set if (dets[j] >> ctrl_qubit) & 1)
            if det_i in lo_set and det_i in hi_set:
                return 1.0
            side_set = lo_set if det_i in lo_set else hi_set
            if det_i not in cur_set:
                return 1.0
            if lo_set and hi_set:
                if cur_set not in mass_of:
                    mass_of[cur_set] = sum(amps[j] ** 2 for j in cur_set)
                if side_set not in mass_of:
                    mass_of[side_set] = sum(amps[j] ** 2
                                           for j in side_set)
                leaf_prob *= mass_of[side_set] / mass_of[cur_set]
            cur_set = side_set
            if len(cur_set) <= 1:
                break
        target_prob = amps[det_i] ** 2
        err = abs(leaf_prob - target_prob)
        if err > worst_err:
            worst_err = err
    return worst_err


def repair_ordering(prop, n):
    """Deterministic repair: map any proposal to a valid permutation
    (first occurrences of in-range ints, then missing in order)."""
    seen_vals = set()
    fixed_order = []
    for v in prop:
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, np.integer)) and 0 <= v < n \
                and int(v) not in seen_vals:
            v = int(v)
            seen_vals.add(v)
            fixed_order.append(v)
    for q in range(n):
        if q not in seen_vals:
            fixed_order.append(q)
    return fixed_order


def run_m(dets, dist, n):
    canon_order = list(range(n))
    base_cnots, base_depth = eval_ordering(canon_order, dets, dist, n)
    return {"cnots": base_cnots, "depth": base_depth, "stopped": False}


def run_r(dets, dist, n, shuffle_rng):
    rand_order = list(range(n))
    shuffle_rng.shuffle(rand_order)
    rand_cnots, rand_depth = eval_ordering(rand_order, dets, dist, n)
    return {"cnots": rand_cnots, "depth": rand_depth, "stopped": False}


def greedy_moves(n):
    adj_moves = [("swap", i, i + 1) for i in range(n - 1)]
    rot_moves = [("move", 0, j) for j in range(1, n)]
    return adj_moves + rot_moves


def apply_move(work_order, move):
    kind, move_i, move_j = move
    cand_order = list(work_order)
    if kind == "swap":
        cand_order[move_i], cand_order[move_j] = (
            cand_order[move_j], cand_order[move_i])
    else:
        val = cand_order.pop(move_i)
        cand_order.insert(move_j, val)
    return repair_ordering(cand_order, len(work_order))


def run_g(dets, dist, n, start_rng, stop):
    """Greedy tree-rotation + qubit-reordering search from the
    canonical ordering plus one seeded restart; strictly improving
    routed CNOTs (depth tie-break), so the result never exceeds the
    canonical cost. Distinct names per role; no reuse."""
    init_start = list(range(n))
    restart_start = list(range(n))
    start_rng.shuffle(restart_start)
    move_list = greedy_moves(n)
    best_cnots_overall = None
    best_depth_overall = None
    evals_since_guard = [0]

    def guard_tripped():
        evals_since_guard[0] += 1
        if evals_since_guard[0] % 32 == 0 and stop is not None \
                and stop():
            return True
        return False

    for start_order in (init_start, restart_start):
        work_order = list(start_order)
        work_cnots, work_depth = eval_ordering(
            work_order, dets, dist, n)
        for _ in range(GREEDY_SWEEPS):
            for move in move_list:
                if guard_tripped():
                    return {"cnots": None, "depth": None,
                            "stopped": True}
                cand_order = apply_move(work_order, move)
                cand_cnots, cand_depth = eval_ordering(
                    cand_order, dets, dist, n)
                if cand_cnots < work_cnots or (
                        cand_cnots == work_cnots
                        and cand_depth < work_depth):
                    work_order = cand_order
                    work_cnots = cand_cnots
                    work_depth = cand_depth
        if best_cnots_overall is None or work_cnots < best_cnots_overall \
                or (work_cnots == best_cnots_overall
                    and work_depth < best_depth_overall):
            best_cnots_overall = work_cnots
            best_depth_overall = work_depth
    return {"cnots": int(best_cnots_overall),
            "depth": int(best_depth_overall), "stopped": False}


def run_a(dets, dist, n, prop_rng, n_iters, stop):
    """Simulated annealing over variable orderings + CNOT-sharing
    paths; cost = routed CNOTs + LAMBDA * depth (frozen LAMBDA).
    Starts at identity; tracks best. Distinct names per role."""
    anneal_order = list(range(n))
    anneal_cnots, anneal_depth = eval_ordering(
        anneal_order, dets, dist, n)
    anneal_cost = anneal_cnots + LAMBDA * anneal_depth
    best_cost_seen = anneal_cost
    best_cnots_seen = anneal_cnots
    best_depth_seen = anneal_depth
    anneal_temp = ANNEAL_T0
    for iter_idx in range(n_iters):
        if iter_idx % 32 == 0 and stop is not None and stop():
            return {"cnots": None, "depth": None, "stopped": True}
        move_pick = int(prop_rng.integers(2 * (n - 1)))
        if move_pick < n - 1:
            raw_proposal = list(anneal_order)
            swap_i = move_pick
            raw_proposal[swap_i], raw_proposal[swap_i + 1] = (
                raw_proposal[swap_i + 1], raw_proposal[swap_i])
        else:
            raw_proposal = list(anneal_order)
            rot_j = move_pick - (n - 1) + 1
            rot_val = raw_proposal.pop(0)
            raw_proposal.insert(rot_j, rot_val)
        prop_order = repair_ordering(raw_proposal, n)
        prop_cnots, prop_depth = eval_ordering(
            prop_order, dets, dist, n)
        prop_cost = prop_cnots + LAMBDA * prop_depth
        accept_draw = float(prop_rng.random())
        if prop_cost < anneal_cost or bool(
                accept_draw < math.exp(-(prop_cost - anneal_cost)
                                       / anneal_temp)):
            anneal_order = prop_order
            anneal_cnots = prop_cnots
            anneal_depth = prop_depth
            anneal_cost = prop_cost
            if prop_cost < best_cost_seen or (
                    prop_cost == best_cost_seen
                    and prop_cnots < best_cnots_seen):
                best_cost_seen = prop_cost
                best_cnots_seen = prop_cnots
                best_depth_seen = prop_depth
        anneal_temp *= ANNEAL_ALPHA
    return {"cnots": int(best_cnots_seen),
            "depth": int(best_depth_seen), "stopped": False}


def exact_opt(dets, n, dist, cap, stop):
    """Bounded-exact branch-and-bound over variable orderings,
    minimizing routed CNOTs. Determinant subsets are bitmasks over
    det indices (S <= 96 fits a Python int); the frontier carries
    forward so each node costs O(S). Lower bound = built branches
    x CNOTS_PER_BRANCH x 1 (min routed cost per CNOT at d=1),
    admissible since branch count only grows. Statuses: solved /
    cap-hit / stopped-guard."""
    det_list = list(dets)
    s_count = len(det_list)
    has_bit = []
    for qq in range(n):
        mask_q = 0
        for det_i, det_m in enumerate(det_list):
            if (det_m >> qq) & 1:
                mask_q |= 1 << det_i
        has_bit.append(mask_q)
    all_mask = (1 << s_count) - 1
    canon_cnots, _canon_depth = eval_ordering(
        list(range(n)), det_list, dist, n)
    best_routed = [canon_cnots]
    prefix_order = [-1] * n
    used_qubit = bytearray(n)
    node_count = [0]
    capped_flag = [False]
    stopped_flag = [False]

    def rec(prefix_depth, frontier_masks, built_branches):
        if capped_flag[0] or stopped_flag[0]:
            return
        node_count[0] += 1
        if node_count[0] > cap:
            capped_flag[0] = True
            return
        if node_count[0] % 512 == 0 and stop is not None and stop():
            stopped_flag[0] = True
            return
        if prefix_depth == n:
            leaf_cnots, _leaf_depth = eval_ordering(
                list(prefix_order), det_list, dist, n)
            if leaf_cnots < best_routed[0]:
                best_routed[0] = leaf_cnots
            return
        if built_branches * CNOTS_PER_BRANCH * 1 >= best_routed[0]:
            return
        rem_after_base = 0
        for qq in range(n):
            if not used_qubit[qq]:
                rem_after_base |= 1 << qq
        for cand_q in range(n):
            if used_qubit[cand_q]:
                continue
            rem_after = rem_after_base ^ (1 << cand_q)
            child_frontier = []
            child_seen = set()
            added_branches = 0
            for node_bits in frontier_masks:
                hi_bits = node_bits & has_bit[cand_q]
                lo_bits = node_bits & (~has_bit[cand_q]) & all_mask
                if hi_bits and lo_bits:
                    added_branches += 1
                    side_list = (lo_bits, hi_bits)
                else:
                    side_list = (lo_bits | hi_bits,)
                for side_bits in side_list:
                    if side_bits.bit_count() <= 1:
                        continue
                    proj_vals = []
                    tmp_bits = side_bits
                    det_i = 0
                    while tmp_bits:
                        if tmp_bits & 1:
                            proj_vals.append(
                                det_list[det_i] & rem_after)
                        det_i += 1
                        tmp_bits >>= 1
                    proj_key = frozenset(proj_vals)
                    if proj_key not in child_seen:
                        child_seen.add(proj_key)
                        child_frontier.append(side_bits)
            prefix_order[prefix_depth] = cand_q
            used_qubit[cand_q] = 1
            rec(prefix_depth + 1, child_frontier,
                built_branches + added_branches)
            used_qubit[cand_q] = 0
            prefix_order[prefix_depth] = -1
            if capped_flag[0] or stopped_flag[0]:
                return

    rec(0, [all_mask], 0)
    if stopped_flag[0]:
        return {"status": "stopped-guard", "nodes": node_count[0],
                "opt_cnots": best_routed[0], "cap": cap,
                "started": True}
    if capped_flag[0]:
        return {"status": "cap-hit", "nodes": node_count[0],
                "opt_cnots": best_routed[0], "cap": cap,
                "started": True}
    return {"status": "solved", "nodes": node_count[0],
            "opt_cnots": best_routed[0], "cap": cap, "started": True}


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


def audit_state(size_idx, seed, rep):
    st = gen_state(size_idx, seed, rep)
    dets = st["dets"]
    amps = st["amps"]
    n = st["n"]
    norm_sq = sum(a * a for a in amps)
    dist = LAYOUT_DIST[(n, st["layout"])]
    connected = all(dist[a][b] < 10 ** 9
                    for a in range(n) for b in range(n))
    return {"count_ok": len(dets) == S_COUNTS[n],
            "distinct_ok": len(set(dets)) == len(dets),
            "range_ok": all(0 <= d < (1 << n) for d in dets),
            "norm_ok": abs(norm_sq - 1.0) < 1e-12,
            "family_ok": st["family"] == FAMILIES[n],
            "connected": bool(connected)}


def self_tests():
    out = {"ran": True, "failed": [], "gradient_probe": []}
    try:
        for si in range(len(N_QUBITS)):
            for rep in (0, 1):
                au = audit_state(si, 1, rep)
                for key in ("count_ok", "distinct_ok", "range_ok",
                            "norm_ok", "family_ok", "connected"):
                    if not au[key]:
                        out["failed"].append(
                            "gen-%s-%d-%d" % (key, si, rep))
        if LAYOUT_DIST[(10, "grid")] == LAYOUT_DIST[(10, "hex")]:
            out["failed"].append("layouts-identical")
        tstate = tiny_state()
        tdist = TINY_DIST
        tiny_results = {}
        tiny_results["M"] = run_m(tstate["dets"], tdist, TINY_N)
        tiny_results["G"] = run_g(
            tstate["dets"], tdist, TINY_N,
            seed_rng(0, 7, 7, 5), None)
        tiny_results["A"] = run_a(
            tstate["dets"], tdist, TINY_N,
            seed_rng(0, 7, 7, 5), 50, None)
        tiny_results["R"] = run_r(
            tstate["dets"], tdist, TINY_N,
            seed_rng(0, 7, 7, 999))
        for arm in ("M", "G", "A"):
            if tiny_results[arm]["cnots"] != TINY_OPT["cnots"] or \
                    tiny_results[arm]["depth"] != TINY_OPT["depth"]:
                out["failed"].append("tiny-%s-hand" % arm)
        tiny_err = verify_state(list(range(TINY_N)), tstate["dets"],
                                tstate["amps"])
        if tiny_err > 1e-9:
            out["failed"].append("tiny-validity")
        tex = exact_opt(tstate["dets"], TINY_N, tdist, EXACT_CAP,
                        None)
        if tex["status"] != "solved" or tex["opt_cnots"] != \
                TINY_OPT["cnots"]:
            out["failed"].append("tiny-exact-opt")
        if repair_ordering([0, 0, 7, 2], 3) != [0, 2, 1]:
            out["failed"].append("repair-dedupe")
        if repair_ordering([2, 0, 1], 3) != [2, 0, 1]:
            out["failed"].append("repair-identity")
        if repair_ordering([], 3) != [0, 1, 2]:
            out["failed"].append("repair-empty")
        if repair_ordering([2, 2, 2], 3) != [2, 0, 1]:
            out["failed"].append("repair-single")
        repaired_once = repair_ordering([1, 3, 1, 9, 0], 4)
        if repair_ordering(repaired_once, 4) != repaired_once:
            out["failed"].append("repair-idempotent")
        if sorted(repaired_once) != [0, 1, 2, 3]:
            out["failed"].append("repair-permutation")
        probe_all_tied = True
        for probe_rep in range(4):
            probe_state = gen_state(0, 1, probe_rep)
            probe_dist = LAYOUT_DIST[(probe_state["n"],
                                     probe_state["layout"])]
            probe_m = run_m(probe_state["dets"], probe_dist,
                            probe_state["n"])
            probe_r = run_r(probe_state["dets"], probe_dist,
                            probe_state["n"],
                            seed_rng(0, 1, probe_rep, 999))
            probe_g = run_g(probe_state["dets"], probe_dist,
                            probe_state["n"],
                            seed_rng(0, 1, probe_rep, 555), None)
            probe_a = run_a(probe_state["dets"], probe_dist,
                            probe_state["n"],
                            seed_rng(0, 1, probe_rep, 777), 20,
                            None)
            probe_vals = (probe_m["cnots"], probe_r["cnots"],
                          probe_g["cnots"], probe_a["cnots"])
            out["gradient_probe"].append(
                {"rep": probe_rep, "cnots": list(probe_vals)})
            if min(probe_vals) < 0:
                out["failed"].append("negative-cost")
            if not (probe_vals[0] == probe_vals[1] == probe_vals[2]
                    == probe_vals[3]):
                probe_all_tied = False
        if probe_all_tied:
            out["failed"].append("gradient-degenerate")
        circ = gen_state(0, 1, 0)
        cdist = LAYOUT_DIST[(circ["n"], circ["layout"])]
        c1 = eval_ordering(list(range(circ["n"])), circ["dets"],
                           cdist, circ["n"])
        c2 = eval_ordering(list(range(circ["n"])), circ["dets"],
                           cdist, circ["n"])
        if c1 != c2:
            out["failed"].append("determinism")
        g1 = run_g(circ["dets"], cdist, circ["n"],
                   seed_rng(0, 1, 0, 555), None)
        g2 = run_g(circ["dets"], cdist, circ["n"],
                   seed_rng(0, 1, 0, 555), None)
        if (g1["cnots"], g1["depth"]) != (g2["cnots"], g2["depth"]):
            out["failed"].append("determinism-greedy")
        r1 = run_r(circ["dets"], cdist, circ["n"],
                   seed_rng(0, 1, 0, 999))
        r2 = run_r(circ["dets"], cdist, circ["n"],
                   seed_rng(0, 1, 0, 999))
        if (r1["cnots"], r1["depth"]) != (r2["cnots"], r2["depth"]):
            out["failed"].append("determinism-random")
    except Exception as ex:
        out["failed"].append("raise: %r" % ex)
    return out


def run_arm(size_idx, seed, rep, arm, n_iters, stop):
    st = gen_state(size_idx, seed, rep)
    dets = st["dets"]
    n = st["n"]
    dist = LAYOUT_DIST[(n, st["layout"])]
    if arm == "M":
        return run_m(dets, dist, n)
    if arm == "R":
        return run_r(dets, dist, n,
                     seed_rng(size_idx, seed, rep, 999))
    if arm == "G":
        return run_g(dets, dist, n,
                     seed_rng(size_idx, seed, rep, 555), stop)
    return run_a(dets, dist, n,
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
                        "iters_done": 0, "n_evaluated": EXACT_CAP})
    else:
        tstate = tiny_state()
        ex = exact_opt(tstate["dets"], TINY_N, TINY_DIST, EXACT_CAP,
                       over)
        gate3tiny["arms"]["tiny"] = ex
        gate3tiny["total"] += 1
        if ex["status"] == "solved" and ex["opt_cnots"] == \
                TINY_OPT["cnots"]:
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
        tcirc = gen_state(TARGET["size_idx"], TARGET["seed"],
                          TARGET["rep"])
        tdist = LAYOUT_DIST[(tcirc["n"], TARGET["layout"])]
        tex = exact_opt(tcirc["dets"], tcirc["n"], tdist, EXACT_CAP,
                        over)
        gate3targets.append(dict(tex, layout=TARGET["layout"],
                                 size=tcirc["n"]))
        if tex["status"] == "stopped-guard":
            skipped.append({"what": "target-exact",
                            "reason": "stopped-guard",
                            "iters_done": tex.get("nodes", 0),
                            "n_evaluated": EXACT_CAP})
    with open(os.path.join(witdir, "gate3_targets.json"), "w") as f:
        json.dump(gate3targets, f, indent=1, default=str)
    checkpoint("targets")

    def run_cell(si, seed):
        n = N_QUBITS[si]
        rec = {"size": n, "seed": seed, "arms": {},
               "family": FAMILIES[n], "validity": []}
        for arm in ARMS:
            if over():
                rec["blocked"] = "wall-guard"
                rec["iters_done"] = 0
                rec["n_evaluated"] = n_inst
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
        for rep in range(n_inst):
            vst = gen_state(si, seed, rep)
            verr = verify_state(list(range(n)), vst["dets"],
                                vst["amps"])
            rec["validity"].append(bool(verr <= 1e-9))
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

    for si, n in enumerate(N_QUBITS):
        siz_cells = [(si, seed) for seed in SEEDS]
        if over():
            for (s2, sd2) in siz_cells:
                skipped.append({"what": "cell %d/%d" % (
                    N_QUBITS[s2], sd2), "reason": "wall-guard",
                    "iters_done": 0, "n_evaluated": n_inst})
        else:
            for (s2, sd2) in siz_cells:
                if over():
                    skipped.append({"what": "cell %d/%d" % (
                        N_QUBITS[s2], sd2), "reason": "wall-guard",
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
    for n in N_QUBITS:
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
    win_fams = []
    win_counts = {"G": 0, "A": 0}
    for n in N_QUBITS:
        pools, pok = {}, True
        for arm in ("M", "G", "A"):
            pools[arm], oka = pool(n, arm, "cnots")
            pok = pok and oka
        se, spread, gp = spread_win(pools, pok)
        g2_fams.append({"size": n, "pools": pools, "SE": se,
                        "spread": spread, "pass": bool(gp)})
        if gp:
            g2_n += 1
        spools, spok = {}, True
        for arm in ("M", "G", "A"):
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
                pools[a]["mean"] is not None for a in ("M", "G", "A")):
            sse2 = math.sqrt(sum(pools[a]["se"] ** 2
                                 for a in ("M", "G", "A")) / 3.0)
            for a in ("G", "A"):
                cwin = pools[a]["mean"] < pools["M"]["mean"] - 2.0 * sse2
                cok = spools[a]["mean"] <= spools["M"]["mean"]
                joint[a] = bool(cwin and cok)
        else:
            joint = {"G": False, "A": False}
        for a in ("G", "A"):
            if joint[a]:
                win_counts[a] += 1
        if pok and all(pools[a]["mean"] is not None
                       for a in ("M", "G", "A")):
            spass = (pools["G"]["mean"] < pools["M"]["mean"] or
                     pools["A"]["mean"] < pools["M"]["mean"])
        else:
            spass = False
        win_fams.append({"size": n, "strict_win": bool(spass),
                         "pools_ok": bool(pok),
                         "joint": dict(joint)})
    g2_ok = g2_n >= 2

    tiny_solved = (gate3tiny["total"] == 1 and gate3tiny["solved"] == 1)
    target_cap = (len(gate3targets) == 1 and
                  gate3targets[0].get("status") == "cap-hit")
    g3pass = bool(tiny_solved and target_cap)

    complete = all(
        len(cell_mean(n, seed, arm, "cnots")) == 1
        for n in N_QUBITS for seed in SEEDS for arm in ARMS)
    tiny_attempted = gate3tiny["total"] == 1
    targets_attempted = len(gate3targets) == 1
    wall = elapsed()
    clean = len(skipped) == 0
    g4_ok = bool(complete and tiny_attempted and targets_attempted and
                 wall < WALL_LIMIT_S and clean)

    selftest_ok = bool(tiny_ok)
    n_win = max(win_counts["G"], win_counts["A"])
    strict_n = sum(1 for wrec in win_fams if wrec.get("strict_win"))
    pools_all = all(wrec.get("pools_ok") for wrec in win_fams)
    pursue = (n_win >= 2 and g1_ok and g2_ok and g3pass and g4_ok and
              selftest_ok)
    reject = (complete and tiny_solved and g1_ok and
              pools_all and strict_n == 0)
    if pursue:
        reason = ("PURSUE-condition holds (joint routed-CNOT win "
                  "+ depth no-regress on the SAME arm at >=2 sizes "
                  "+ gates 1,2,3,4 + self-tests ok); payload verdict "
                  "stays unresolved-with-reason, classification is "
                  "coordinator-side.")
    elif reject:
        reason = ("REJECT-condition holds (complete cells, tiny "
                  "solved, Gate-1 controls pass, no strict pooled "
                  "routed-CNOT win at any size); payload verdict stays "
                  "unresolved-with-reason, classification is "
                  "coordinator-side.")
    else:
        reason = ("UNRESOLVED + next experiment (joint wins G=%d/3, "
                  "A=%d/3, strict wins=%d/3, g1=%s g2=%s "
                  "g2s(depth-spread)=%s g3=%s (tiny solved=%s, target "
                  "cap-hit=%s) selftest=%s g4=%s complete=%s skipped=%d; "
                  "next: %s)." % (
                      win_counts["G"], win_counts["A"], strict_n, g1_ok,
                      g2_ok, g2s_n >= 2, g3pass, tiny_solved,
                      target_cap, selftest_ok, g4_ok, complete,
                      len(skipped), NEXT_EXPERIMENT))
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
                       "win_sizes": win_fams,
                       "win_counts": win_counts,
                       "n_win_max_arm": n_win,
                       "n_strict_win": strict_n,
                       "selftest_ok": bool(selftest_ok)},
        "reason": reason,
    }

    results = {
        "screen": "21",
        "verdict": "unresolved-with-reason: payload reports numbers "
                   "and gate evidence; classification is coordinator-side.",
        "design": {
            "model": "screen-authored exact amplitude-loading "
                     "decision-tree builder (stdlib + numpy only; no "
                     "external libs)",
            "sizes": list(N_QUBITS),
            "families": {str(k): v for k, v in FAMILIES.items()},
            "s_counts": {str(k): v for k, v in S_COUNTS.items()},
            "layouts": ["grid", "hex"],
            "seeds": list(SEEDS),
            "reps_per_cell_arm": n_inst,
            "greedy": {"sweeps": GREEDY_SWEEPS},
            "anneal": {"iters": n_iters, "t0": ANNEAL_T0,
                       "alpha": ANNEAL_ALPHA, "lambda": LAMBDA},
            "cnots_per_branch": CNOTS_PER_BRANCH,
            "arms": {"M": "standard Gray-code multiplexer / canonical "
                          "ordering baseline",
                     "R": "random ordering control",
                     "G": "greedy tree-rotation + qubit-reordering "
                          "search (canonical + one seeded restart)",
                     "A": "simulated annealing over variable orderings "
                          "+ CNOT-sharing paths "
                          "(CNOTs + LAMBDA*depth)"},
            "metrics": "total routed CNOTs (3d-2 per CNOT at graph "
                       "distance d) + two-qubit depth (list-scheduled, "
                       "2*(2d-1) per branch node) + state-validity "
                       "verification (tolerance 1e-9)",
            "pareto": "PURSUE needs a routed-CNOT win + depth "
                      "no-regress on the SAME arm; a CNOT-only win with "
                      "higher depth is NOT a joint win; joint wins "
                      "counted PER ARM, bar max(G,A) >= 2",
            "exact": "bounded-exact branch-and-bound over variable "
                     "orderings on tiny (must solve, optimum %d) + "
                     "target-scale instance (%d-qubit family, %s "
                     "layout, node cap %d, must cap-hit)" % (
                         TINY_OPT["cnots"], N_QUBITS[TARGET["size_idx"]],
                         TARGET["layout"], EXACT_CAP),
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
