"""Screen 06 payload: lattice-surgery routing autopsy (re-staged v4).

Joint-objective reformulation: every greedy decode minimizes per-placement
J_place = finish + LAMBDA * route_length; SA selects by per-program
J_prog = makespan + LAMBDA * phys_total (LAMBDA = 0.5 frozen). Arm R keeps
its spread-seeking random decode. Gate-3 scale probe stacks 2 full
programs (40 ops) at a tightened horizon (heuristic - 4).

Self-contained: stdlib + numpy + z3 only (z3 imported lazily inside the
Gate-3 step so module import needs numpy alone).
Writes ALL output under cwd (the attempt work dir): results.json + witnesses/.
Deterministic given seeds. Never claims pursue/reject: verdict is always
unresolved-with-reason; classification is coordinator-side.
"""

import argparse
import heapq
import json
import math
import os
import time
from collections import deque

import numpy as np

W = 5
H = 5
NPATCH = W * H
FACTORIES = (0, NPATCH - 1)  # (0,0) and (4,4) in row-major indexing
FACTORY_PERIOD = 2
QUBITS_LIST = (10, 20, 30)
N_GATES = 20
N_TARGET_GATES = 6
N_STACKED = 2
SEEDS = (1, 2, 3, 4, 5)
N_PROG = 100
KINDS = ("ZZ-split", "ZZ-merge", "XX-split", "XX-merge")
MERGE_KINDS = {"ZZ-merge", "XX-merge"}
K_ROUTES = 4
SA_ITERS = 1500
SA_T0 = 2.0
SA_ALPHA = 0.995
LAMBDA = 0.5
WALL_GUARD_S = 420.0
WALL_LIMIT_S = 500.0
START_SCAN_CAP = 10000
K_ENUM_CAP = 60000
Z3_TIMEOUT_MS = 20000
Z3_TINY_TIMEOUT_MS = 10000
Z3_TINY_CAP = 12
Z3_TARGET_CAP = 16
Z3_SCALE_CAP = 28
Z3_TIGHTEN = 4
Z3_MAX_LINK_CONDS = 200000
ARMS = ("A", "B", "C", "R")
N_TINY = 4
N_TARGETS = 4
NEXT_EXPERIMENT = ("joint-cost lookahead placement with wider SA route "
                    "neighborhoods; escalate z3 scale probe to 60-op "
                    "stacked instances with per-solve timeout 120 s.")

# Fixed neighbour order (up, right, down, left) keeps every enumeration
# deterministic.
NB_DELTAS = ((-1, 0), (0, 1), (1, 0), (0, -1))


def make_skip_record(what, reason, iters_done, n_evaluated):
    """Shared pure constructor for EVERY skip record (no hand-rolled dicts).

    Schema: what / reason / iters_done / n_evaluated / stopped=True.
    """
    return {"what": str(what), "reason": str(reason),
            "iters_done": int(iters_done),
            "n_evaluated": int(n_evaluated), "stopped": True}


class SkipLog:
    """Single owner of skip records and the stopped flag.

    First guard trip sets stopped=True; every later guard entry point
    skips immediately instead of attempting work.
    """

    def __init__(self):
        self.records = []
        self.stopped = False

    def add(self, what, reason, iters_done, n_evaluated):
        rec = make_skip_record(what, reason, iters_done, n_evaluated)
        self.records.append(rec)
        self.stopped = True
        return rec


def blocked_solve_record(status, T, extra=None):
    """Shared constructor for blocked z3 solve records (fixed schema)."""
    rec = {"status": status, "seconds": 0.0, "T": T, "starts": None,
           "routes": None, "factories": None}
    if extra:
        rec.update(extra)
    return rec


def guarded_solve(log, what, fn, iters_done, n_evaluated):
    """None-guard on solver calls: None / exception / malformed result.

    Records a why '-none' skip and returns None instead of crashing.
    Callers check the log's stopped flag before attempting further work.
    """
    try:
        r = fn()
    except Exception:
        r = None
    if r is None or not isinstance(r, dict) or "status" not in r:
        log.add(what + "-none", "solver-returned-None", iters_done,
                n_evaluated)
        return None
    return r


def rc(v):
    return divmod(v, W)


def in_grid(r, c):
    return 0 <= r < H and 0 <= c < W


def nbrs(v):
    r, c = rc(v)
    out = []
    for dr, dc in NB_DELTAS:
        rr, cc = r + dr, c + dc
        if in_grid(rr, cc):
            out.append(rr * W + cc)
    return out


def manhattan(a, b):
    ra, ca = rc(a)
    rb, cb = rc(b)
    return abs(ra - rb) + abs(ca - cb)


def astar(u, v):
    """Shortest vertex path u -> v on the empty grid (A*, Manhattan)."""
    if u == v:
        return [u]
    openh = [(manhattan(u, v), 0, 0, u)]
    gcost = {u: 0}
    parent = {}
    closed = set()
    ctr = 1
    while openh:
        _, g, _, x = heapq.heappop(openh)
        if x in closed:
            continue
        closed.add(x)
        if x == v:
            path = [v]
            while path[-1] != u:
                path.append(parent[path[-1]])
            path.reverse()
            return path
        for w in nbrs(x):
            ng = g + 1
            if ng < gcost.get(w, 10 ** 9):
                gcost[w] = ng
                parent[w] = x
                heapq.heappush(openh, (ng + manhattan(w, v), ng, ctr, w))
                ctr += 1
    raise RuntimeError("astar: no path %d -> %d" % (u, v))


def bfs_k_shortest(u, v, k, cap=K_ENUM_CAP):
    """First k shortest simple paths u -> v by path-space BFS (fixed order)."""
    out = []
    q = deque([[u]])
    pops = 0
    while q and len(out) < k and pops < cap:
        p = q.popleft()
        pops += 1
        last = p[-1]
        if last == v:
            out.append(p)
            continue
        for w in nbrs(last):
            if w in p:
                continue
            q.append(p + [w])
    return out


EDGE_ID = {}
for a in range(NPATCH):
    for b in nbrs(a):
        if b > a:
            EDGE_ID[(a, b)] = len(EDGE_ID)
NEDGE = len(EDGE_ID)


def edge_id(a, b):
    return EDGE_ID[(a, b)] if a < b else EDGE_ID[(b, a)]


def qubit_placement(n_qubits, seed):
    """Deterministic patch per logical qubit: perm[q % NPATCH].

    perm is the seeded permutation of the 25 patches. When
    n_qubits > NPATCH, patches are shared; endpoints are exempt from
    vertex capacity, so co-location is legal in the model.
    """
    rng = arm_rng(60606, n_qubits, seed)
    perm = [int(x) for x in rng.permutation(NPATCH)]
    return [perm[q % NPATCH] for q in range(n_qubits)]


def gen_program(n_qubits, n_gates, seed, pi):
    """Deterministic program: list of (kind, u, v) two-qubit gates.

    Gates connect distinct qubits; endpoints are their placed patches.
    The repair loop guarantees patch-distinct endpoints (matters when
    n_qubits > NPATCH forces patch sharing). A different patch always
    exists (at least min(n_qubits, NPATCH) >= 10 distinct patches), so
    the loop terminates.
    """
    place = qubit_placement(n_qubits, seed)
    rng = np.random.default_rng(
        (int(seed * 100003 + pi * 1009 + n_qubits * 917 + n_gates * 131)
         % (2 ** 63 - 1)))
    kinds = [KINDS[int(x)] for x in rng.integers(0, len(KINDS), size=n_gates)]
    a = rng.integers(0, n_qubits, size=n_gates)
    step = rng.integers(1, n_qubits, size=n_gates)
    ops = []
    for i in range(n_gates):
        aa = int(a[i])
        bb = (aa + int(step[i])) % n_qubits
        guard = 0
        while place[bb] == place[aa] and guard <= n_qubits:
            bb = (bb + 1) % n_qubits
            guard += 1
        ops.append((kinds[i], place[aa], place[bb]))
    return ops


def stacked_scale_program():
    """Gate-3 ti-3 scale probe: N_STACKED full Q=20 programs, 40 ops."""
    ops = []
    for pi in range(N_STACKED):
        ops.extend(gen_program(20, N_GATES, 1, pi))
    return ops


def scale_horizon(ams):
    """ti-3 horizon: heuristic-A makespan minus Z3_TIGHTEN, capped."""
    return min(int(ams) - Z3_TIGHTEN, Z3_SCALE_CAP)


def needs_factory(op):
    return op[0] in MERGE_KINDS


class SchedState:
    def __init__(self):
        self.edge_occ = [set() for _ in range(NEDGE)]
        self.vert_occ = [set() for _ in range(NPATCH)]
        self.factory_next = [0, 0]

    def earliest(self, cand, need):
        """Earliest (start, factory-or-None, finish) for cand, or None."""
        edges = cand["edges"]
        internal = cand["internal"]
        L = cand["length"]
        eo = self.edge_occ
        vo = self.vert_occ
        for s in range(START_SCAN_CAP + 1):
            ok = True
            for i, e in enumerate(edges):
                if (s + i) in eo[e]:
                    ok = False
                    break
            if not ok:
                continue
            for (vv, off) in internal:
                if (s + off) in vo[vv]:
                    ok = False
                    break
            if not ok:
                continue
            fchoice = None
            if need:
                for f in (0, 1):
                    if self.factory_next[f] <= s:
                        fchoice = f
                        break
                if fchoice is None:
                    continue
            return (s, fchoice, s + L)
        return None

    def apply(self, cand, need, s, fchoice):
        for i, e in enumerate(cand["edges"]):
            self.edge_occ[e].add(s + i)
        for (vv, off) in cand["internal"]:
            self.vert_occ[vv].add(s + off)
        if need:
            self.factory_next[fchoice] = s + FACTORY_PERIOD


def grouped_candidates(u, v, k=K_ROUTES):
    """Per-op candidate structure: list of route groups.

    Group g = list of orientation dicts (forward first, then reversed) for
    one simple path. `cands[o][g]` is the group; route index = group index.
    """
    groups = []
    for p in bfs_k_shortest(u, v, k):
        L = len(p) - 1
        if L <= 0:
            continue
        grp = []
        for rev in (False, True):
            q = p if not rev else p[::-1]
            edges = tuple(edge_id(q[i], q[i + 1]) for i in range(L))
            internal = tuple((q[j], j) for j in range(1, L))
            cand = {"edges": edges, "internal": internal,
                    "length": L, "rev": rev}
            if not any((c["edges"], c["internal"]) ==
                       (cand["edges"], cand["internal"]) for c in grp):
                grp.append(cand)
        if grp:
            groups.append(grp)
    return groups


def place_sequence(ops, cands, order, routes, try_both=True):
    """Greedy earliest-start placement in `order` with route idx per op.

    With try_both, both orientations of the chosen route group are tried
    and earliest-finishing wins (ties keep forward); otherwise only the
    forward orientation is used. Returns
    (starts, facs, route_used, orient_used, makespan).
    Used by arms R and C (fixed-route decodes).
    """
    st = SchedState()
    n = len(ops)
    starts = [0] * n
    facs = [None] * n
    route_used = [0] * n
    orient_used = [False] * n
    for o in order:
        ko = len(cands[o])
        k = int(routes[o]) % ko if ko > 0 else 0
        cands_k = cands[o][k] if try_both else cands[o][k][:1]
        best = None
        for cand in cands_k:
            got = st.earliest(cand, needs_factory(ops[o]))
            if got is None:
                continue
            if best is None or got[2] < best[0][2]:
                best = (got, cand)
        if best is None:
            raise RuntimeError("place_sequence: no feasible start")
        (s, fchoice, _fin), cand = best
        st.apply(cand, needs_factory(ops[o]), s, fchoice)
        starts[o] = s
        facs[o] = fchoice
        route_used[o] = k
        orient_used[o] = bool(cand["rev"])
    makespan = 0
    for o in range(n):
        L = 0
        for cand in cands[o][route_used[o]]:
            if bool(cand["rev"]) == orient_used[o]:
                L = cand["length"]
                break
        makespan = max(makespan, starts[o] + L)
    return starts, facs, route_used, orient_used, makespan


def place_sequence_j(ops, cands, order):
    """Greedy joint-cost placement in `order` (arms A and B).

    Per op, choose over all K_ROUTES route groups x both orientations
    the placement minimizing J_place = finish + LAMBDA * route_length;
    ties break by shorter route, then forward orientation. Returns
    (starts, facs, route_used, orient_used, makespan).
    """
    st = SchedState()
    n = len(ops)
    starts = [0] * n
    facs = [None] * n
    route_used = [0] * n
    orient_used = [False] * n
    for o in order:
        best = None  # (key, got, k, cand); key = (J, L, rev_rank)
        for k, grp in enumerate(cands[o]):
            for cand in grp:
                got = st.earliest(cand, needs_factory(ops[o]))
                if got is None:
                    continue
                key = (got[2] + LAMBDA * cand["length"], cand["length"],
                       1 if cand["rev"] else 0)
                if best is None or key < best[0]:
                    best = (key, got, k, cand)
        if best is None:
            raise RuntimeError("place_sequence_j: no feasible start")
        _, got, k, cand = best
        st.apply(cand, needs_factory(ops[o]), got[0], got[1])
        starts[o] = got[0]
        facs[o] = got[1]
        route_used[o] = k
        orient_used[o] = bool(cand["rev"])
    makespan = 0
    for o in range(n):
        L = 0
        for cand in cands[o][route_used[o]]:
            if bool(cand["rev"]) == orient_used[o]:
                L = cand["length"]
                break
        makespan = max(makespan, starts[o] + L)
    return starts, facs, route_used, orient_used, makespan


def verify_schedule(ops, cands, starts, facs, route_used, orient_used):
    """Independent from-scratch check of edge/vertex/factory/horizon rules."""
    edge_use = {}
    vert_use = {}
    fac_starts = {0: [], 1: []}
    makespan = 0
    for o, op in enumerate(ops):
        grp = cands[o][route_used[o]]
        cand = None
        for c in grp:
            if bool(c["rev"]) == bool(orient_used[o]):
                cand = c
                break
        if cand is None:
            return False, "op %d: orientation not found" % o, 0
        s = starts[o]
        for i, e in enumerate(cand["edges"]):
            key = (e, s + i)
            edge_use[key] = edge_use.get(key, 0) + 1
            if edge_use[key] > 1:
                return False, "edge capacity at %r" % (key,), 0
        for (vv, off) in cand["internal"]:
            key = (vv, s + off)
            vert_use[key] = vert_use.get(key, 0) + 1
            if vert_use[key] > 1:
                return False, "vertex capacity at %r" % (key,), 0
        if needs_factory(op):
            f = facs[o]
            if f not in (0, 1):
                return False, "op %d: merge without factory" % o, 0
            fac_starts[f].append(s)
        makespan = max(makespan, s + cand["length"])
    for f, ss in fac_starts.items():
        ss = sorted(ss)
        for a, b in zip(ss, ss[1:]):
            if b - a < FACTORY_PERIOD:
                return False, "factory %d rate" % f, 0
    return True, "ok", makespan


def arm_rng(*ints):
    h = 1469598103934665603
    for x in ints:
        h = ((h ^ (int(x) & 0xFFFFFFFFFFFFFFFF)) * 1099511628211) & \
            0xFFFFFFFFFFFFFFFF
    return np.random.default_rng(h % (2 ** 63 - 1))


def run_A(ops, cands):
    order = list(range(len(ops)))
    return place_sequence_j(ops, cands, order) + (order,)


def run_B(ops, cands, short_len):
    order = sorted(range(len(ops)), key=lambda o: (-short_len[o], o))
    return place_sequence_j(ops, cands, order) + (order,)


def run_R(ops, cands, rng):
    n = len(ops)
    order = list(rng.permutation(n).astype(int))
    routes = [int(rng.integers(0, len(cands[o]))) for o in range(n)]
    return place_sequence(ops, cands, order, routes) + (order,)


def run_C(ops, cands, short_len, rng):
    """SA over (order permutation + route choice), joint-cost selector.

    Same fixed cooling schedule as before; selection and acceptance use
    J_prog = makespan + LAMBDA * phys_total instead of makespan alone.
    Decode = greedy earliest-start placement in perm order with chosen
    routes (both orientations tried, earliest-finishing kept).
    """
    n = len(ops)
    order = sorted(range(n), key=lambda o: (-short_len[o], o))
    routes = [0] * n
    _s, _f, _ru, _ou, cms = place_sequence(ops, cands, order, routes)
    cur = cms + LAMBDA * program_phys(cands, _ru, _ou)
    best = (list(order), list(routes), cur)
    T = SA_T0
    for _it in range(SA_ITERS):
        no = list(order)
        nr = list(routes)
        if n >= 2 and rng.random() < 0.5:
            i, j = int(rng.integers(0, n)), int(rng.integers(0, n))
            while j == i:
                j = int(rng.integers(0, n))
            no[i], no[j] = no[j], no[i]
        else:
            o = int(rng.integers(0, n))
            ko = len(cands[o])
            if ko > 1:
                nn = int(rng.integers(0, ko - 1))
                nr[o] = nn if nn < routes[o] else nn + 1
            elif n >= 2:
                i, j = int(rng.integers(0, n)), int(rng.integers(0, n))
                while j == i:
                    j = int(rng.integers(0, n))
                no[i], no[j] = no[j], no[i]
        try:
            _s, _f, _ru, _ou, nms = place_sequence(ops, cands, no, nr)
            new = nms + LAMBDA * program_phys(cands, _ru, _ou)
        except RuntimeError:
            T *= SA_ALPHA
            continue
        delta = new - cur
        if delta <= 0 or (T > 0 and
                          rng.random() < math.exp(-delta / T)):
            order, routes, cur = no, nr, new
            if new < best[2]:
                best = (list(no), list(nr), new)
        T *= SA_ALPHA
    _s, _f, _ru, _ou, _ms = place_sequence(ops, cands, best[0], best[1])
    return _s, _f, _ru, _ou, _ms, best[0]


def program_phys(cands, route_used, orient_used):
    """Physical cost proxy: total traversed edges summed over ops."""
    total = 0
    for o, grp in enumerate(cands):
        for cand in grp[route_used[o]]:
            if bool(cand["rev"]) == bool(orient_used[o]):
                total += cand["length"]
                break
    return int(total)


def program_joint(makespan, phys):
    """Joint program cost: J_prog = makespan + LAMBDA * phys_total."""
    return float(makespan) + LAMBDA * float(phys)


def self_tests():
    """Supervised-run self-tests (recorded in results.json)."""
    res = {}
    # 1. A* shortest-path length == Manhattan distance on empty grid.
    rng = np.random.default_rng(60601)
    worst = 0
    for _ in range(200):
        u, v = int(rng.integers(0, NPATCH)), int(rng.integers(0, NPATCH))
        if u == v:
            continue
        L = len(astar(u, v)) - 1
        worst = max(worst, abs(L - manhattan(u, v)))
        assert L == manhattan(u, v), (u, v, L)
    res["astar_manhattan"] = True
    res["astar_max_abs_dev"] = worst
    # 2. Factory token accounting exact against hand-set placements.
    st = SchedState()
    assert st.factory_next == [0, 0]
    st.factory_next[0] = 5
    assert st.factory_next == [5, 0]
    st2 = SchedState()
    cand = {"edges": (edge_id(0, 1),), "internal": (), "length": 1,
            "rev": False}
    got = st2.earliest(cand, True)
    assert got is not None and got[0] == 0 and got[1] == 0, got
    st2.apply(cand, True, 0, 0)
    assert st2.factory_next == [FACTORY_PERIOD, 0], st2.factory_next
    got = st2.earliest(cand, True)
    # Same edge busy at t=0; factory 0 busy until t=2. Next feasible start
    # on this one-edge candidate is s=1 via factory 1.
    assert got is not None and got[0] == 1 and got[1] == 1, got
    res["factory_accounting"] = True
    # 3. Checker agrees with construction on random instances (joint too).
    ncheck = 0
    for trial in range(30):
        trng = np.random.default_rng(60600 + trial)
        n = int(trng.integers(2, 7))
        ops = []
        for _ in range(n):
            uu = int(trng.integers(0, NPATCH))
            vv = (uu + int(trng.integers(1, NPATCH))) % NPATCH
            kk = KINDS[int(trng.integers(0, len(KINDS)))]
            ops.append((kk, uu, vv))
        cands = [grouped_candidates(uu, vv) for (_k, uu, vv) in ops]
        order = list(trng.permutation(n).astype(int))
        routes = [int(trng.integers(0, len(c))) for c in cands]
        starts, facs, ru, ou, ms = place_sequence(ops, cands, order,
                                                  routes)
        ok, msg, ms2 = verify_schedule(ops, cands, starts, facs, ru, ou)
        assert ok, msg
        assert ms2 == ms, (ms2, ms)
        jstarts, jfacs, jru, jou, jms = place_sequence_j(
            ops, cands, order)
        jok, jmsg, jms2 = verify_schedule(ops, cands, jstarts, jfacs,
                                          jru, jou)
        assert jok, jmsg
        assert jms2 == jms, (jms2, jms)
        ncheck += 1
    res["checker_agrees"] = True
    res["checker_instances"] = ncheck
    # 4. Skip-record schema probe (pure helper; touches no live log).
    probe = make_skip_record("probe", "probe-reason", 3, 3)
    assert set(probe) == {"what", "reason", "iters_done", "n_evaluated",
                          "stopped"}, probe
    assert probe["stopped"] is True and probe["iters_done"] == 3 \
        and probe["n_evaluated"] == 3, probe
    res["skip_schema"] = True
    # 5. Stopped-guard probe on a local skip log (entry guard skips
    # immediately, no work attempted).
    loc = SkipLog()
    assert loc.stopped is False and loc.records == []
    loc.add("phase-entry", "stopped-guard-entry", 0, 0)
    assert loc.stopped is True and len(loc.records) == 1, loc.records
    assert loc.records[0]["iters_done"] == 0 \
        and loc.records[0]["n_evaluated"] == 0, loc.records
    res["stopped_guard"] = True
    # 6. Solver-None guard probe (forced-None mock): None / exception /
    # malformed results become skips, never crashes; a good dict passes
    # through untouched with no skip recorded.
    loc2 = SkipLog()
    assert guarded_solve(loc2, "probe-solve", lambda: None, 2, 2) is None
    assert len(loc2.records) == 1 and loc2.stopped is True, loc2.records
    assert loc2.records[0]["reason"] == "solver-returned-None"
    assert loc2.records[0]["iters_done"] == 2 \
        and loc2.records[0]["n_evaluated"] == 2, loc2.records
    loc2b = SkipLog()

    def _boom():
        raise RuntimeError("probe-timeout")
    assert guarded_solve(loc2b, "probe-raise", _boom, 1, 1) is None
    assert len(loc2b.records) == 1 and loc2b.stopped is True
    loc3 = SkipLog()
    good = {"status": "sat", "T": 1}
    assert guarded_solve(loc3, "probe-good", lambda: good, 1,
                         1) is good
    assert loc3.records == [] and loc3.stopped is False
    res["none_guard"] = True
    # 7. Joint-cost sanity: single-op instance picks route 0 forward and
    # J_prog equals makespan + LAMBDA * phys on a hand-built placement.
    tops = [("XX-split", 0, 1)]
    tc = [grouped_candidates(0, 1)]
    _s, _f, _ru, _ou, _ms = place_sequence_j(tops, tc, [0])
    assert _ms == 1 and _ru == [0] and _ou == [False], (_ms, _ru, _ou)
    assert program_joint(13, 64) == 13 + LAMBDA * 64 == 45.0
    assert LAMBDA == 0.5
    res["joint_cost"] = True
    # 8. Determinism probe: generation + arm A repeat byte-identical.
    p1 = gen_program(20, N_GATES, 2, 7)
    p2 = gen_program(20, N_GATES, 2, 7)
    assert p1 == p2
    cc = [cached_candidates(uu, vv) for (_k, uu, vv) in p1]
    r1 = run_A(p1, cc)[:5]
    r2 = run_A(p1, cc)[:5]
    assert r1 == r2, (r1, r2)
    res["determinism"] = True
    # 9. Scale-probe builder probe: stacked instance has 40 ops and the
    # scale horizon equals heuristic minus Z3_TIGHTEN.
    sc = stacked_scale_program()
    assert len(sc) == N_STACKED * N_GATES == 40, len(sc)
    assert N_STACKED == 2 and Z3_TIGHTEN == 4
    assert scale_horizon(27) == 23
    assert scale_horizon(27) == min(27 - Z3_TIGHTEN, Z3_SCALE_CAP)
    res["scale_probe"] = True
    return res


_CAND_CACHE = {}


def cached_candidates(u, v):
    key = (u, v)
    c = _CAND_CACHE.get(key)
    if c is None:
        c = grouped_candidates(u, v)
        _CAND_CACHE[key] = c
    return c


# ---- Gate 3: z3 time-expanded feasibility (same hardware) ----
def loc_nbrs(v, W_, H_):
    r, c = divmod(v, W_)
    out = []
    for dr, dc in NB_DELTAS:
        rr, cc = r + dr, c + dc
        if 0 <= rr < H_ and 0 <= cc < W_:
            out.append(rr * W_ + cc)
    return out


def loc_k_paths(u, v, k, W_, H_, cap=K_ENUM_CAP):
    out = []
    q = deque([[u]])
    pops = 0
    while q and len(out) < k and pops < cap:
        p = q.popleft()
        pops += 1
        last = p[-1]
        if last == v:
            out.append(p)
            continue
        for w in loc_nbrs(last, W_, H_):
            if w in p:
                continue
            q.append(p + [w])
    return out


def loc_edge_map(W_, H_):
    eid = {}
    for a in range(W_ * H_):
        for b in loc_nbrs(a, W_, H_):
            if b > a:
                eid[(a, b)] = len(eid)
    return eid


def loc_candidates(u, v, W_, H_, k=K_ROUTES):
    emap = loc_edge_map(W_, H_)

    def eid(a, b):
        return emap[(a, b)] if a < b else emap[(b, a)]

    groups = []
    for p in loc_k_paths(u, v, k, W_, H_):
        L = len(p) - 1
        if L <= 0:
            continue
        grp = []
        for rev in (False, True):
            q = p if not rev else p[::-1]
            edges = tuple(eid(q[i], q[i + 1]) for i in range(L))
            internal = tuple((q[j], j) for j in range(1, L))
            cand = {"edges": edges, "internal": internal, "length": L,
                    "rev": rev}
            if not any((c["edges"], c["internal"]) ==
                       (cand["edges"], cand["internal"]) for c in grp):
                grp.append(cand)
        if grp:
            groups.append(grp)
    return groups, emap


def z3_feas(W_, H_, ops, T, timeout_ms):
    """Feasibility of makespan <= T over the candidate-route model.

    Returns dict with verbatim solver status string ('sat' / 'unsat' /
    'unknown', or 'blocked-...'), wall seconds, horizon, and model iff sat.
    Blocked paths use the shared blocked_solve_record constructor.
    """
    from z3 import Solver, Bool, Int, Sum, If, And, Or, Implies, is_true
    t0 = time.perf_counter()
    cand_of = []
    for (_k, uu, vv) in ops:
        groups, _emap = loc_candidates(uu, vv, W_, H_)
        if not groups:
            return blocked_solve_record("blocked-no-route", T)
        cand_of.append(groups)
    n = len(ops)
    link_est = 0
    for groups in cand_of:
        for grp in groups:
            for cand in grp:
                link_est += (len(cand["edges"]) + len(cand["internal"])) * \
                    (T + 1)
    if link_est > Z3_MAX_LINK_CONDS:
        return blocked_solve_record("blocked-encoding-too-large", T,
                                    {"link_est": link_est})
    s = Solver()
    s.set("timeout", int(timeout_ms))
    # One Bool per (op, route group, orientation): exactly one orientation
    # of exactly one route is active per op. Activating a whole group at
    # once would enforce both orientations' resources simultaneously.
    y = []
    for o in range(n):
        yo = []
        for g, grp in enumerate(cand_of[o]):
            yg = [Bool("y_%d_%d_%d" % (o, g, k))
                  for k in range(len(grp))]
            yo.append(yg)
        y.append(yo)
    st = [Int("s_%d" % o) for o in range(n)]
    merge_idx = [o for o, op in enumerate(ops) if op[0] in MERGE_KINDS]
    f = {}
    for o in merge_idx:
        f[o] = Int("f_%d" % o)
        s.add(f[o] >= 0, f[o] <= 1)
    for o in range(n):
        s.add(Sum([If(b, 1, 0) for yg in y[o] for b in yg]) == 1)
        s.add(st[o] >= 0, st[o] <= T)
        for g, grp in enumerate(cand_of[o]):
            for k, cand in enumerate(grp):
                L = cand["length"]
                s.add(Implies(y[o][g][k], st[o] + L <= T))
    occ = {}
    vocc = {}
    for o in range(n):
        for g, grp in enumerate(cand_of[o]):
            for k, cand in enumerate(grp):
                base = y[o][g][k]
                L = cand["length"]
                for i, e in enumerate(cand["edges"]):
                    for t in range(T + 1):
                        tau = t - i
                        if 0 <= tau <= T:
                            occ.setdefault((e, t), []).append(
                                And(base, st[o] == tau))
                for (vv, off) in cand["internal"]:
                    for t in range(T + 1):
                        tau = t - off
                        if 0 <= tau <= T:
                            vocc.setdefault((vv, t), []).append(
                                And(base, st[o] == tau))
    for (_e, _t), conds in occ.items():
        if len(conds) >= 2:
            s.add(Sum([If(c, 1, 0) for c in conds]) <= 1)
    for (_v, _t), conds in vocc.items():
        if len(conds) >= 2:
            s.add(Sum([If(c, 1, 0) for c in conds]) <= 1)
    for ii in range(len(merge_idx)):
        for jj in range(ii + 1, len(merge_idx)):
            o, p = merge_idx[ii], merge_idx[jj]
            s.add(Implies(f[o] == f[p],
                          Or(st[o] - st[p] >= FACTORY_PERIOD,
                             st[p] - st[o] >= FACTORY_PERIOD)))
    r = s.check()
    dt = time.perf_counter() - t0
    status = str(r)  # verbatim: 'sat' | 'unsat' | 'unknown'
    out = {"status": status, "seconds": dt, "T": T, "starts": None,
           "routes": None, "factories": None}
    if status == "sat":
        try:
            m = s.model()
            starts, routes, facs = [], [], []
            for o in range(n):
                gsel, ksel = 0, 0
                for g in range(len(cand_of[o])):
                    for k in range(len(cand_of[o][g])):
                        if is_true(m.eval(y[o][g][k],
                                          model_completion=True)):
                            gsel, ksel = g, k
                            break
                    else:
                        continue
                    break
                starts.append(m.eval(st[o], model_completion=True).as_long())
                routes.append([gsel, ksel])
                if o in f:
                    facs.append(
                        m.eval(f[o], model_completion=True).as_long())
                else:
                    facs.append(None)
            out["starts"] = starts
            out["routes"] = routes
            out["factories"] = facs
        except Exception as e:  # model read must not kill the payload
            out["model_error"] = repr(e)
    else:
        try:
            out["reason_unknown"] = str(s.reason_unknown())
        except Exception:
            out["reason_unknown"] = "n/a"
    return out


def cell_stats(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0, "mean": None, "std": None, "se": None}
    a = np.asarray(vals, dtype=float)
    mean = float(a.mean())
    std = float(a.std(ddof=1)) if n > 1 else 0.0
    se = std / math.sqrt(n) if n > 0 else None
    return {"n": n, "mean": mean, "std": std, "se": se}


def pooled_stats(lists):
    vals = []
    for v in lists:
        if isinstance(v, (list, tuple)):
            vals.extend(v)
        else:
            vals.append(v)
    return cell_stats(vals)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--attempt", default="")
    ap.add_argument("--data", default="")
    args = ap.parse_args()
    t_start = time.perf_counter()
    outdir = os.getcwd()
    witdir = os.path.join(outdir, "witnesses")
    try:
        os.makedirs(witdir, exist_ok=True)
    except Exception:
        pass
    LOG = SkipLog()
    cells = {}   # (size, seed, arm) -> {"makespans": [...], "phys": [...]}
    arm_wall = {a: 0.0 for a in ARMS}
    gate3_tiny = []
    gate3_targets = []
    selftest = {"ran": False}
    verdict_bits = {}

    def elapsed():
        return time.perf_counter() - t_start

    def over():
        return elapsed() >= WALL_GUARD_S

    def publish(extra):
        payload = {
            "screen": "06",
            "attempt": args.attempt,
            "data": args.data,
            "design": {
                "model": "screen-authored lattice-surgery routing "
                         "(no surgery code in frozen closure)",
                "grid": [W, H],
                "factories": list(FACTORIES),
                "factory_period": FACTORY_PERIOD,
                "qubits": list(QUBITS_LIST),
                "gates_per_program": N_GATES,
                "physical_cost": "sum of chosen route lengths over ops "
                                 "(total traversed edges)",
                "joint_objective": "J_place = finish + LAMBDA * "
                                   "route_length per placement; J_prog = "
                                   "makespan + LAMBDA * phys_total",
                "lambda": LAMBDA,
                "autopsy": "route-0 pile-up + forward-only + fixed order "
                           "explain old-A 9/15 Gate-1 fails; A/B phys "
                           "identical proves route-0 control is the phys "
                           "floor; size-10/20-vs-30 pattern empirical",
                "next_experiment": "NEXT_EXPERIMENT: " + NEXT_EXPERIMENT,
                "pareto": "PURSUE needs makespan win AND physical-cost "
                          "win; a makespan-only win at higher physical "
                          "cost is not a Pareto win",
                "seeds": list(SEEDS),
                "n_programs": N_PROG,
                "K_routes": K_ROUTES,
                "sa": {"iters": SA_ITERS, "T0": SA_T0, "alpha": SA_ALPHA},
                "gate3_scale": {"stacked_programs": N_STACKED,
                                "tighten": Z3_TIGHTEN,
                                "scale_cap": Z3_SCALE_CAP,
                                "target_cap": Z3_TARGET_CAP},
                "milp_baseline": "none available; exact baseline is "
                                 "z3-SMT with set('timeout', ms); only "
                                 "unknown-with-reason-timeout = limit-expiry,"
                                 " never optimum",
                "channel_priors": "n/a (routing screen)",
                "candidate_model": "z3 exactness is relative to the "
                                   "K-route x 2-orientation candidate set "
                                   "+ horizon model",
            },
            "self_tests": selftest,
            "cells": {"%d/%d/%s" % k: {"n": len(v["makespans"]),
                                       **cell_stats(v["makespans"]),
                                       "phys": cell_stats(
                                           v.get("phys", [])),
                                       "diag": v.get("diag", {})}
                      for k, v in cells.items()},
            "arm_wall_sec": arm_wall,
            "gate3_tiny": gate3_tiny,
            "gate3_targets": gate3_targets,
            "skipped": LOG.records,
            "wall_sec": elapsed(),
            "verdict": "unresolved-with-reason",
        }
        payload.update(extra)
        try:
            with open(os.path.join(outdir, "results.json"), "w") as fh:
                json.dump(payload, fh, indent=2, default=str)
        except Exception as e:
            with open(os.path.join(outdir, "results.json"), "w") as fh:
                fh.write(json.dumps({"verdict": "unresolved-with-reason",
                                     "publish_error": repr(e),
                                     "skipped": LOG.records}))
        return payload

    try:
        # Self-tests first (recorded; failure does not kill the payload).
        try:
            selftest.update(self_tests())
            selftest["ran"] = True
        except Exception as e:
            selftest["ran"] = True
            selftest["failed"] = repr(e)
        try:
            with open(os.path.join(witdir, "selftests.json"), "w") as fh:
                json.dump(selftest, fh, indent=2, default=str)
        except Exception:
            pass

        def empty_cell():
            return {"makespans": [], "phys": [], "wall_sec": 0.0,
                    "diag": {}}

        def run_cell(size, seed, arm):
            key = (size, seed, arm)
            if LOG.stopped:
                LOG.add("cell %d/%d/%s" % key, "stopped-guard-entry",
                        0, 0)
                cells[key] = empty_cell()
                return
            t0 = time.perf_counter()
            ms_list = []
            ph_list = []
            det_list = []
            flip_list = []
            wait_list = []
            cands_cache = {}
            for pi in range(N_PROG):
                if over() and pi > 0:
                    LOG.add("cell %d/%d/%s prog %d/%d"
                            % (size, seed, arm, pi, N_PROG),
                            "wall-guard", pi, pi)
                    break
                ops = gen_program(size, N_GATES, seed, pi)
                cands = []
                short_len = []
                for (_k, uu, vv) in ops:
                    if (uu, vv) not in cands_cache:
                        cands_cache[(uu, vv)] = cached_candidates(uu, vv)
                    g = cands_cache[(uu, vv)]
                    cands.append(g)
                    short_len.append(g[0][0]["length"] if g else 0)
                if arm == "A":
                    _s, _f, _ru, _ou, ms, _o = run_A(ops, cands)
                elif arm == "B":
                    _s, _f, _ru, _ou, ms, _o = run_B(ops, cands,
                                                     short_len)
                elif arm == "R":
                    rng = arm_rng(size, seed, pi, 4)
                    _s, _f, _ru, _ou, ms, _o = run_R(ops, cands, rng)
                else:
                    rng = arm_rng(size, seed, pi, 3)
                    _s, _f, _ru, _ou, ms, _o = run_C(ops, cands,
                                                     short_len, rng)
                ms_list.append(int(ms))
                ph_list.append(program_phys(cands, _ru, _ou))
                nops = len(ops)
                det_list.append(sum(1 for o in range(nops)
                                    if _ru[o] > 0) / nops)
                flip_list.append(sum(1 for o in range(nops)
                                     if _ou[o]) / nops)
                maxlen = 0
                for o in range(nops):
                    for cand in cands[o][_ru[o]]:
                        if bool(cand["rev"]) == bool(_ou[o]):
                            maxlen = max(maxlen, cand["length"])
                            break
                wait_list.append(int(ms) - maxlen)
                if pi == 0 and size == QUBITS_LIST[0] and seed == SEEDS[0] \
                        and arm == "A":
                    try:
                        with open(os.path.join(
                                witdir, "sample_schedule.json"), "w") as fh:
                            json.dump({"ops": ops, "starts": _s, "facs": _f,
                                       "routes": _ru, "orient": _ou,
                                       "makespan": int(ms)}, fh, indent=2,
                                      default=str)
                    except Exception:
                        pass
            n_done = len(ms_list)
            diag = {}
            if n_done > 0:
                diag = {"detour_share": float(sum(det_list) / n_done),
                        "flip_share": float(sum(flip_list) / n_done),
                        "wait_mean": float(sum(wait_list) / n_done),
                        "n_evaluated": n_done}
            cells[key] = {"makespans": ms_list, "phys": ph_list,
                          "wall_sec": time.perf_counter() - t0,
                          "diag": diag}
            arm_wall[arm] += cells[key]["wall_sec"]

        # Order: cheap arms A/R/B everywhere, then z3 tiny, then C, then
        # z3 targets. Guard checked before every cell and every solve.
        # EVERY guard exit records all omitted planned cells explicitly:
        # a single fill-in path covers loop-top, mid-loop and post-loop
        # exits, so no return can silently drop remaining cells.
        def run_phase(phase_arms):
            plan = [(size, seed, arm) for size in QUBITS_LIST
                    for seed in SEEDS for arm in phase_arms]
            for idx, (size, seed, arm) in enumerate(plan):
                if LOG.stopped or over():
                    for (s2, sd2, a2) in plan[idx:]:
                        kk = (s2, sd2, a2)
                        if kk not in cells:
                            LOG.add("cell %d/%d/%s" % kk,
                                    "stopped-guard-entry"
                                    if LOG.stopped else "wall-guard",
                                    0, 0)
                            cells[kk] = empty_cell()
                    return
                run_cell(size, seed, arm)

        run_phase(("A", "R", "B"))

        def cell_mean(size, seed, arm):
            v = cells.get((size, seed, arm), {"makespans": []})["makespans"]
            if not v:
                return None
            return float(np.mean(np.asarray(v, dtype=float)))

        def cell_phys_mean(size, seed, arm):
            v = cells.get((size, seed, arm), {"phys": []})["phys"]
            if not v:
                return None
            return float(np.mean(np.asarray(v, dtype=float)))

        # Gate-3 tiny: 3x3 / 2-op instances, ascending T to T*, then T*-1.
        if LOG.stopped or over():
            for ti in range(N_TINY):
                LOG.add("tiny-%d" % ti,
                        "stopped-guard-entry"
                        if LOG.stopped else "wall-guard-entry", 0, 0)
        else:
            trng = np.random.default_rng(6306)
            for ti in range(N_TINY):
                if LOG.stopped or over():
                    LOG.add("tiny-%d" % ti,
                            "stopped-guard-entry"
                            if LOG.stopped else "wall-guard", 0, 0)
                    continue
                uu = int(trng.integers(0, 9))
                vv = (uu + int(trng.integers(1, 9))) % 9
                uu2 = int(trng.integers(0, 9))
                vv2 = (uu2 + int(trng.integers(1, 9))) % 9
                tops = [("ZZ-merge", uu, vv), ("XX-split", uu2, vv2)]
                ra, ca = divmod(uu, 3)
                rb, cb = divmod(vv, 3)
                lb = abs(ra - rb) + abs(ca - cb)
                rec = {"ops": tops, "W": 3, "H": 3, "solves": [],
                       "T_star": None}
                for T in range(lb, Z3_TINY_CAP + 1):
                    if LOG.stopped or over():
                        LOG.add("tiny-%d-T%d" % (ti, T),
                                "stopped-guard-entry"
                                if LOG.stopped else "wall-guard",
                                len(rec["solves"]), len(rec["solves"]))
                        break
                    r = guarded_solve(LOG, "tiny-%d-T%d" % (ti, T),
                                      lambda: z3_feas(3, 3, tops, T,
                                                      Z3_TINY_TIMEOUT_MS),
                                      len(rec["solves"]),
                                      len(rec["solves"]))
                    if r is None:
                        break
                    rec["solves"].append(r)
                    if r["status"] == "sat":
                        rec["T_star"] = T
                        break
                if rec["T_star"] is not None and rec["T_star"] >= 1:
                    if LOG.stopped or over():
                        LOG.add("tiny-%d-Tbelow" % ti,
                                "stopped-guard-entry"
                                if LOG.stopped else "wall-guard",
                                len(rec["solves"]), len(rec["solves"]))
                    else:
                        tb = rec["T_star"] - 1
                        r = guarded_solve(LOG, "tiny-%d-Tbelow" % ti,
                                          lambda: z3_feas(
                                              3, 3, tops, tb,
                                              Z3_TINY_TIMEOUT_MS),
                                          len(rec["solves"]),
                                          len(rec["solves"]))
                        if r is not None:
                            rec["solves_below"] = r
                gate3_tiny.append(rec)
            try:
                with open(os.path.join(witdir, "gate3_tiny.json"),
                          "w") as fh:
                    json.dump(gate3_tiny, fh, indent=2, default=str)
            except Exception:
                pass

        run_phase(("C",))

        # Gate-3 targets: ti 0 is a 6-gate Q=20 program; ti 1 is the full
        # 20-gate first program of the Q=20 corpus; ti 2 is the full
        # 20-gate first program of the Q=30 corpus; ti 3 (scale probe)
        # stacks N_STACKED full programs (40 ops) at heuristic - TIGHTEN.
        if LOG.stopped or over():
            for ti in range(N_TARGETS):
                LOG.add("target-%d" % ti,
                        "stopped-guard-entry"
                        if LOG.stopped else "wall-guard-entry", 0, 0)
        else:
            for ti in range(N_TARGETS):
                if LOG.stopped or over():
                    LOG.add("target-%d" % ti,
                            "stopped-guard-entry"
                            if LOG.stopped else "wall-guard", 0, 0)
                    continue
                if ti == 0:
                    tops = gen_program(20, N_TARGET_GATES, 1, 0)
                elif ti == 1:
                    tops = gen_program(20, N_GATES, 1, 0)
                elif ti == 2:
                    tops = gen_program(30, N_GATES, 1, 0)
                else:
                    tops = stacked_scale_program()
                tc = [cached_candidates(uu, vv) for (_k, uu, vv) in tops]
                try:
                    _s, _f, _ru, _ou, ams, _o = run_A(tops, tc)
                except RuntimeError as e:
                    gate3_targets.append(
                        {"ops": tops, "heuristic_A": None,
                         "note": "arm-A construction failed: %r" % e,
                         "solves": []})
                    continue
                if ti < N_TARGETS - 1:
                    Theur = min(int(ams), Z3_TARGET_CAP)
                else:
                    Theur = scale_horizon(ams)
                rec = {"ops": tops, "heuristic_A": int(ams),
                       "horizon_used": Theur, "solves": []}
                r = guarded_solve(LOG, "target-%d" % ti,
                                  lambda: z3_feas(5, 5, tops, Theur,
                                                  Z3_TIMEOUT_MS),
                                  len(rec["solves"]), len(rec["solves"]))
                if r is None:
                    gate3_targets.append(rec)
                    continue
                rec["solves"].append(r)
                if r["status"] == "sat" and Theur > 0:
                    if LOG.stopped or over():
                        LOG.add("target-%d-Tbelow" % ti,
                                "stopped-guard-entry"
                                if LOG.stopped else "wall-guard",
                                len(rec["solves"]), len(rec["solves"]))
                    else:
                        tb = Theur - 1
                        r2 = guarded_solve(LOG, "target-%d-Tbelow" % ti,
                                           lambda: z3_feas(5, 5, tops, tb,
                                                           Z3_TIMEOUT_MS),
                                           len(rec["solves"]),
                                           len(rec["solves"]))
                        if r2 is not None:
                            rec["solves"].append(r2)
                gate3_targets.append(rec)
            try:
                with open(os.path.join(witdir, "gate3_targets.json"),
                          "w") as fh:
                    json.dump(gate3_targets, fh, indent=2, default=str)
            except Exception:
                pass

        # ---- Gates ----
        def pooled_for(field, size):
            pools = {}
            pools_ok = True
            for arm in ("A", "B", "C"):
                vals = []
                for seed in SEEDS:
                    vals.extend(cells.get((size, seed, arm),
                                          {"makespans": [],
                                           "phys": []})[field])
                pools[arm] = pooled_stats(vals)
                if pools[arm]["n"] != len(SEEDS) * N_PROG:
                    pools_ok = False
            return pools, pools_ok

        def spread_win(pools, pools_ok):
            if pools_ok and all(pools[a]["se"] is not None
                                for a in ("A", "B", "C")):
                se_size = math.sqrt(sum(pools[a]["se"] ** 2
                                        for a in ("A", "B", "C")) / 3.0)
                means = [pools[a]["mean"] for a in ("A", "B", "C")]
                spread = max(means) - min(means)
                gpass = spread > 2.0 * se_size
                wpass = pools["A"]["mean"] - min(pools["B"]["mean"],
                                                 pools["C"]["mean"]) > \
                    2.0 * se_size
                spass = min(pools["B"]["mean"],
                            pools["C"]["mean"]) < pools["A"]["mean"]
                return se_size, spread, gpass, wpass, spass
            return None, None, False, False, False

        g1_cells, g1_ok = [], True
        for size in QUBITS_LIST:
            for seed in SEEDS:
                ma, mr = cell_mean(size, seed, "A"), cell_mean(
                    size, seed, "R")
                pa, pr = cell_phys_mean(size, seed, "A"), cell_phys_mean(
                    size, seed, "R")
                ok = (ma is not None and mr is not None and ma < mr)
                g1_cells.append({"cell": "%d/%d" % (size, seed),
                                 "mean_A": ma, "mean_R": mr, "pass": ok,
                                 "phys_A": pa, "phys_R": pr})
                if not ok:
                    g1_ok = False
        g2_sizes, g2_npass = [], 0
        g2p_sizes, g2p_npass = [], 0
        win_sizes, win_n = [], 0
        winp_sizes, winp_n = [], 0
        for size in QUBITS_LIST:
            pools, pools_ok = pooled_for("makespans", size)
            se_size, spread, gpass, wpass, spass = spread_win(pools,
                                                             pools_ok)
            ppools, ppools_ok = pooled_for("phys", size)
            pse, pspread, pgpass, pwpass, pspass = spread_win(ppools,
                                                             ppools_ok)
            g2_sizes.append({"size": size, "pools": pools, "SE": se_size,
                             "spread": spread, "pass": gpass})
            if gpass:
                g2_npass += 1
            g2p_sizes.append({"size": size, "pools": ppools, "SE": pse,
                              "spread": pspread, "pass": pgpass})
            if pgpass:
                g2p_npass += 1
            win_sizes.append({"size": size, "win": wpass,
                              "strict_win": spass, "pools_ok": pools_ok})
            if wpass:
                win_n += 1
            winp_sizes.append({"size": size, "win": pwpass,
                               "strict_win": pspass,
                               "pools_ok": ppools_ok})
            if pwpass:
                winp_n += 1
        g2_ok = g2_npass >= 2
        g2p_ok = g2p_npass >= 2
        tiny_pairs = 0
        for rec in gate3_tiny:
            st = [sv["status"] for sv in rec.get("solves", [])]
            below = rec.get("solves_below", {}).get("status")
            if "sat" in st and below == "unsat":
                tiny_pairs += 1
        unknowns = sum(1 for rec in gate3_targets for sv in
                       rec.get("solves", [])
                       if sv["status"] == "unknown"
                       and sv.get("reason_unknown") == "timeout")
        target_solved = any(sv["status"] in ("sat", "unsat")
                            for rec in gate3_targets
                            for sv in rec.get("solves", []))
        g3_target_timeout = unknowns >= 1
        g3 = {"tiny_pairs_sat_unsat": tiny_pairs,
              "target_unknowns": unknowns,
              "target_any_solved": target_solved,
              "target_timeout_pass": g3_target_timeout}
        complete = all(
            len(cells.get((size, seed, arm),
                          {"makespans": [], "phys": []})["makespans"])
            == N_PROG and len(cells.get((size, seed, arm),
                                        {"makespans": [],
                                         "phys": []})["phys"]) == N_PROG
            for size in QUBITS_LIST for seed in SEEDS
            for arm in ARMS)
        wall = elapsed()
        clean = len(LOG.records) == 0
        g4_ok = complete and wall < WALL_LIMIT_S and clean
        win_ok = win_n >= 2
        winp_ok = winp_n >= 2
        tiny_full = len(gate3_tiny) == N_TINY and tiny_pairs == N_TINY
        selftest_ok = bool(selftest.get("ran")) and \
            not selftest.get("failed")
        strict_n = sum(1 for w in win_sizes if w.get("strict_win"))
        strictp_n = sum(1 for w in winp_sizes if w.get("strict_win"))
        pools_all_ok = all(w.get("pools_ok") for w in win_sizes)
        ppools_all_ok = all(w.get("pools_ok") for w in winp_sizes)
        pursue_condition = win_ok and winp_ok and g3_target_timeout and \
            g1_ok and g2_ok and g2p_ok and g4_ok and tiny_full and selftest_ok
        reject_condition = complete and tiny_full and g1_ok and \
            pools_all_ok and ppools_all_ok and strict_n == 0 and \
            strictp_n == 0 and clean
        if pursue_condition:
            reason = "PURSUE-condition holds (makespan win + physical-cost " \
                "win, each best(B,C) over A by >2SE at >=2 sizes, + " \
                "target timeout + tiny sat/unsat 4/4 pairs + self-tests " \
                "ok + gates 1,2,2p,4 pass); payload verdict stays " \
                "unresolved-with-reason, classification is coordinator-side."
        elif reject_condition:
            reason = "REJECT-condition holds (complete cells on both " \
                "metrics, full tiny sat/unsat evidence, Gate 1 controls " \
                "pass, no strict pooled win on either metric at any " \
                "size); payload verdict stays unresolved-with-reason, " \
                "classification is coordinator-side."
        else:
            reason = "UNRESOLVED + next experiment (makespan wins=%d/3 " \
                "(strict %d/3), phys wins=%d/3 (strict %d/3), g1=%s g2=%s " \
                "g2p=%s g3timeout=%s tiny_full=%s selftest=%s g4=%s " \
                "complete=%s skipped=%d). NEXT_EXPERIMENT: %s." % \
                (win_n, strict_n, winp_n, strictp_n, g1_ok, g2_ok,
                 g2p_ok, g3_target_timeout, tiny_full, selftest_ok,
                 g4_ok, complete, len(LOG.records), NEXT_EXPERIMENT)
        verdict_bits = {
            "gate1": {"pass": g1_ok, "cells": g1_cells},
            "gate2": {"pass": g2_ok, "n_sizes_pass": g2_npass,
                      "sizes": g2_sizes},
            "gate2_phys": {"pass": g2p_ok, "n_sizes_pass": g2p_npass,
                           "sizes": g2p_sizes},
            "gate3": g3,
            "gate4": {"pass": g4_ok, "complete": complete,
                      "wall_sec": wall},
            "acceptance": {"pursue_condition": pursue_condition,
                           "reject_condition": reject_condition,
                           "win_sizes": win_sizes, "n_win": win_n,
                           "n_strict_win": strict_n,
                           "winp_sizes": winp_sizes, "n_win_phys": winp_n,
                           "n_strict_win_phys": strictp_n,
                           "tiny_full": tiny_full,
                           "clean": clean,
                           "n_skipped": len(LOG.records),
                           "selftest_ok": selftest_ok},
            "reason": reason,
        }
        payload = publish({"gates": {k: v for k, v in verdict_bits.items()
                                     if k != "reason"},
                           "reason": reason})
        return payload
    except Exception as e:
        LOG.add("main", "exception: %r" % e, 0, 0)
        return publish({"gates": verdict_bits, "reason":
                        "unresolved-with-reason: main exception %r; "
                        "classification is coordinator-side. "
                        "NEXT_EXPERIMENT: %s." % (e, NEXT_EXPERIMENT),
                        "fatal": repr(e)})


if __name__ == "__main__":
    main()
