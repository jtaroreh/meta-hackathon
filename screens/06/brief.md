# Screen 06 — lattice-surgery routing autopsy (re-staged v4)

Re-stage notes (bounded corrections; same wall/cpu allowance 600/3600):
- v4 executes the three frozen steps from §6.2 in one screen: (1) Gate-1
  autopsy with the prior 9/15 failure frozen below, (2) physical-cost-aware
  joint-objective reformulation of every greedy decode plus the C selector,
  (3) harder exact instances with a 40-op stacked scale probe at a
  tightened horizon.
- Corpus, arms families, seeds, sizes, and acceptance-rule FORM are
  unchanged: 5x5 patch grid, factories (0,0)/(4,4), QUBITS in {10,20,30},
  N_GATES = 20, seeds 1-5, 100 programs/cell, arms A/B/C/R, Gate 1 strict
  per (size,seed) cell, joint Pareto pursue at >= 2 sizes, z3 timeout-only
  Gate 3. What changes is the DECIDE rule inside the decodes (joint cost
  with frozen LAMBDA) and the Gate-3 scale probe (stacked instance +
  tightened horizon). No MILP/SMT-as-optimum/OLSQA/Vandaere/Lau/PhasePoly/
  torch anywhere (named blockers, same as all screens).

Hypothesis (reformulated, physical-cost-aware): route search that prices
physical error exposure jointly with latency — per-placement joint cost
J_place = finish + LAMBDA * route_length and per-program joint cost
J_prog = makespan + LAMBDA * phys_total with frozen LAMBDA = 0.5 —
recovers the Gate-1 makespan deficit versus random spreading while keeping
physical cost near the shortest-path floor, so makespan AND physical cost
can win jointly (Pareto) at >= 2 sizes.

## 1. Gate-1 autopsy (frozen carried evidence, run 87b79c06 files 581cd0a6)

Prior Gate 1 (mean_A < mean_R strictly, makespan, 15 cells): FAILS 9/15.
Fails (A vs R means): 10/1 14.57 vs 14.25; 10/2 14.94 vs 14.42;
10/3 15.69 vs 14.28; 10/4 14.18 vs 13.93; 20/1 14.87 vs 14.30;
20/2 14.77 vs 14.25; 20/3 14.30 vs 14.10; 20/4 14.70 vs 14.53;
20/5 14.88 vs 14.17. Random wins by 0.17-1.41 units, all at sizes 10/20.
Passes: 10/5 by 0.02; 30/1-30/5 all pass by 0.01-0.30 (razor margins).
Physical cost in the same cells: phys_A 57.5-71.2 vs phys_R 75.2-86.3 —
greedy is physical-efficient but makespan-sloppy in every failing cell
(e.g. 10/1: 64.5 vs 80.5).

Frozen finding (mechanism, verified against the feasibility checker):
- Suspect (a) route-0 pile-up CONFIRMED as dominant: old arm A used only
  route 0 (one shortest path) in generated order, so every op sharing an
  edge/internal vertex serializes (capacity 1). Arm B kept route 0 but
  fixed order (descending shortest length) and orientation, and recovered
  ~3.5-4.5 pooled makespan units over A at every size (Q10: 11.30 vs
  14.82; Q20: 11.10 vs 14.70; Q30: 10.83 vs 14.00). Order + orientation
  alone explain the systematic gap; construction is verified by the
  from-scratch checker (construct-then-verify returns ok on 30 random
  instances, self-test 3).
- Suspect (b) forward-only orientation CONFIRMED contributory: reversed
  orientation changes edge/vertex occupancy timing (s+i vs s+(L-j)) and is
  a real degree of freedom; the payload records per-cell orientation-flip
  shares for arms A/B/C as direct evidence.
- Suspect (c) placement patch[q] = perm[q % 25] co-location NOT the driver:
  Q = 30 shares 5 patches yet size 30 passes 5/5; failures concentrate at
  Q = 10/20. The size-10/20-vs-30 pattern is frozen as an empirical pattern
  (denser endpoint packing at Q = 30 shifts the contention baseline; razor
  margins 0.01-0.30 at Q = 30 vs 0.17-1.41 at Q = 10/20); its mechanism is
  recorded as hypothesis, not claimed.
- Structural phys-floor proof (motivates step 2): pooled physical means of
  old arms A and B are IDENTICAL to 3 decimals at every size (Q10:
  62.578/62.578; Q20: 67.776/67.776; Q30: 65.320/65.320) because both use
  route 0 only and orientation never changes route length. A route-0-locked
  control is per-op physical-minimal (sum of Manhattan lengths), so no arm
  can ever beat it on physical cost: phys wins were 0/3 structurally, and
  Gate-2p spread came only from C detours. The reformulation below lifts
  every greedy arm off the phys floor by pricing detours jointly.

## 2. Joint-objective reformulation (frozen BEFORE running)

- J_place(op placement) = finish + LAMBDA * route_length, LAMBDA = 0.5.
  Traversal of length L takes L steps, so route length and finish share
  time-step units; LAMBDA = 0.5 prices one extra edge-step of physical
  exposure at half a time-step. Value frozen before running; sensitivity
  to LAMBDA is future work (see NEXT_EXPERIMENT), not explored here.
- J_prog(program) = makespan + LAMBDA * phys_total with the same LAMBDA.
- Arm A (greedy sequential, control for Gate 1): generated op order;
  per op, choose over all K_ROUTES route groups x both orientations the
  placement minimizing J_place (ties: shorter route, then forward
  orientation); earliest feasible start for the chosen placement.
- Arm B (prioritized + rotation, makespan-leaning): order ops by
  descending shortest-path length, tie-break by generated (seed) order;
  per op, same J_place choice over K_ROUTES x orientations.
- Arm C (simulated annealing, joint selector): SA over (order
  permutation + route choice), SA_ITERS = 1500 iterations, seeded rng,
  accept by J_prog delta with fixed cooling (T0 = 2.0,
  alpha = 0.995, T <- T0 * alpha^iter). Decode = greedy earliest-start
  placement in perm order with SA-chosen routes (both orientations tried,
  earliest-finishing kept). Neighbour move: with prob 0.5 swap two perm
  positions, else re-pick one op's route index.
- Arm R (random control, UNCHANGED decode): seeded random op order +
  seeded uniform random route among the K per op, same earliest-start
  decode with orientation try. R is the spread-seeking reference.
- Gate 1 is unchanged in form: mean_A < mean_R strictly (makespan) in
  every (size,seed) cell. A is no longer route-0-locked, so the phys leg
  is contestable and Gate 1 re-tests whether joint-greedy closes the
  0.17-1.41-unit deficit.

Model (screen-authored, disclosed as such — no surgery code exists in the
frozen closure; everything below is implemented in `src/run06.py`):
- 5x5 patch grid, 4-neighbourhood. Factories at (0,0) and (4,4); each
  serves 1 merge-op per 2 time units: per-factory `next_free` starts at 0,
  a merge-op starting at `s` on factory `f` requires `s >= next_free[f]`,
  then sets `next_free[f] = s + 2`.
- Qubit placement: Q logical qubits mapped to patches deterministically:
  patch[q] = perm[q % 25] where perm is the seeded permutation of the 25
  patches from (Q, seed). Q = 30 shares 5 patches; endpoints are exempt
  from vertex capacity, so co-location is legal in the model.
- Workload sizes QUBITS in {10,20,30}. A program is N_GATES = 20 two-qubit
  gates between distinct qubits (kinds uniform; pairs uniform with a
  patch-distinct redraw so endpoints never coincide). Seeds 1-5, 100
  programs per (size, seed): 60 cells, 6000 programs total.
- Routing: path = simple grid path between endpoints. Edge capacity 1 op
  per step. Vertex capacity 1 op per step for internal vertices; endpoints
  are exempt (never recorded, never checked). Ops scheduled at integer
  starts. Cost = makespan = max over ops of (start + len(path)).
- Physical cost per program = total traversed edges summed over ops (sum
  of chosen route lengths) — proxy for physical error exposure / movement
  volume. Recorded per cell alongside makespan.
- Traversal timing (directional): forward path v0..vL occupies edge e_i
  at step s+i and internal vertex v_j at step s+j; the reversed
  orientation occupies the reversed edge order at s+i and internal vertex
  v_j at s+(L-j). Hence endpoint orientation changes edge/vertex timing
  and is a real degree of freedom. A route+start is feasible iff all its
  edges and internal vertices are free at every step of traversal
  (traversal takes len(path) steps) and a factory token is free at start
  if needed.
- Autopsy diagnostics recorded per (size, seed, arm) cell: detour share
  (fraction of ops with route index > 0), orientation-flip share
  (fraction with reversed orientation), mean waiting (makespan minus max
  chosen route length, per program then averaged). These verify suspects
  (a)/(b) on the new decodes.
- Self-tests (recorded in payload): A* shortest-path length == Manhattan
  distance on empty grid; factory token accounting exact against hand-set
  placements; schedule feasibility checker agrees with construction on
  random instances (construct-then-verify returns ok); skip-record schema
  probe (pure helper carries what/reason/iters_done/n_evaluated/stopped);
  stopped-guard probe on a local skip log (entry guard skips immediately,
  no solve attempted); solver-None guard probe (forced-None mock returns
  a skip, never a crash); joint-cost sanity (J_place prefers the shorter
  route on a finish tie; J_prog equals makespan + LAMBDA * phys on a
  hand-built placement); determinism probe (program generation + arm A
  repeated byte-identical); scale-probe builder probe (stacked instance
  has 40 ops; scale horizon equals heuristic minus TIGHTEN).

Frozen constants (byte-identical to `src/run06.py`):
W = 5; H = 5; NPATCH = W * H = 25; FACTORIES = (0, NPATCH - 1) = (0, 24);
FACTORY_PERIOD = 2; QUBITS_LIST = (10, 20, 30); N_GATES = 20;
N_TARGET_GATES = 6; N_STACKED = 2; SEEDS = (1, 2, 3, 4, 5);
N_PROG = 100; KINDS = ("ZZ-split", "ZZ-merge", "XX-split", "XX-merge");
MERGE_KINDS = {"ZZ-merge", "XX-merge"}; K_ROUTES = 4; SA_ITERS = 1500;
SA_T0 = 2.0; SA_ALPHA = 0.995; LAMBDA = 0.5; WALL_GUARD_S = 420.0;
WALL_LIMIT_S = 500.0; START_SCAN_CAP = 10000; K_ENUM_CAP = 60000;
Z3_TIMEOUT_MS = 20000; Z3_TINY_TIMEOUT_MS = 10000; Z3_TINY_CAP = 12;
Z3_TARGET_CAP = 16; Z3_SCALE_CAP = 28; Z3_TIGHTEN = 4;
Z3_MAX_LINK_CONDS = 200000; ARMS = ("A", "B", "C", "R"); N_TINY = 4;
N_TARGETS = 4. Neighbour order (up, right, down, left). BFS route
enumeration in fixed neighbour order; K = 4 shortest simple paths per
op, both orientations tried at placement unless noted.

Gates (payload-computed, evidence-linked in results.json):
- Gate 1: per (size, seed) cell, mean_A < mean_R strictly, makespan (15 cells).
- Gate 2: pooled per size across seeds (n = 500/arm/size). Per-arm
  SE_a = std_a / sqrt(n); SE_size = sqrt(mean(SE_a^2)) over {A,B,C}.
  Pass iff (max - min) of the three pooled means > 2 * SE_size at >= 2 sizes.
  (Multiplicative comparison only; no division by SE, so no zero-division.)
- Gate 2p: identical rule applied to pooled physical-cost means with its
  own SE_size recomputed on physical-cost pools. Pass iff spread
  > 2 * SE_phys at >= 2 sizes.
- Gate 3 (z3 exact, same hardware): time-expanded feasibility makespan <= T.
  Tiny: 3x3 grid / 2-op instances (4 seeded instances, N_TINY = 4), solve
  ascending from the shortest-path lower bound to find T* (cap T <= 12);
  expect sat at T* and unsat at T*-1, record both statuses verbatim and
  both wall times. Targets (N_TARGETS = 4) on qubit-framed programs over
  placed patches — ti 0 is a 6-gate Q = 20 first-seed program; ti 1 is
  the full 20-gate first program of the Q = 20 corpus; ti 2 is the full
  20-gate first program of the Q = 30 corpus; ti 3 (scale probe) stacks
  N_STACKED = 2 full 20-gate Q = 20 programs (pi = 0, 1) into one 40-op
  instance — horizons min(heuristic-A makespan, 16) for ti 0-2 and
  min(heuristic-A makespan - 4, 28) for ti 3, i.e. Z3_TIGHTEN = 4 below
  the heuristic into the hard near-optimum region, capped at
  Z3_SCALE_CAP = 28; each solve with `set('timeout', 20000)`; need >= 1
  `unknown` whose recorded reason is exactly `timeout` as the solver's own
  limit-expiry. Solved targets (sat/unsat) are permitted alongside but do
  not count toward it; without a timeout-reason unknown the gate fails.
  Formulation: boolean occupy[e,t] per grid-edge per step within horizon +
  per-op integer start vars + per-merge-op factory selector vars over the
  candidate route set (K BFS shortest x 2 orientations, deduped);
  constraints: one-hot choice over (route, orientation) pairs (exactly one
  orientation active per op — a group selector would enforce both
  orientations at once), path contiguity via chosen-orientation edge /
  internal-vertex occupancy linking, edge capacity <= 1 per (edge, step),
  internal-vertex capacity <= 1 per (vertex, step), same-factory starts
  separated by >= 2, horizon start + route length <= T. The sat witness
  records the selected (route, orientation) pair. Exactness is relative
  to this candidate-route + horizon model (disclosed, not full path-space
  exactness). If the encoding exceeds its size guard, the instance is
  recorded blocked honestly rather than shrunk silently. Only
  unknown-with-reason-timeout counts as limit-expiry (other reasons fail
  the gate).
  Limitation (disclosed): tiny + ti 0-2 targets alone do not prove
  corpus-scale hardness; the ti-3 scale probe addresses this; if z3 still
  solves everything, the payload records solver-sufficiency honestly
  (never a fabricated timeout). Classification stays coordinator-side.
- Gate 4: every planned (size, seed, arm) cell complete with BOTH makespan
  and physical-cost lists (100 programs each) AND payload wall time < 500 s
  AND zero skip records (clean). Any recorded skip makes the run unclean,
  fails Gate 4, and fails both PURSUE and REJECT (which also require clean),
  forcing UNRESOLVED + next experiment.

Budgets: wall 600 s, cpu 3600 s (reservation basis). Payload keeps wall
< 500 s via work ordering (self-tests, arms A/R/B, Gate-3 tiny, arm C,
Gate-3 targets) plus an elapsed guard at 420 s checked at every
(size, seed, arm) cell and before each z3 solve. EVERY guard exit records
the omitted work explicitly with iters_done/n_evaluated counts and
stopped = True: run_phase fills all remaining planned cells as skipped;
whole-phase omissions append tiny-i/target-i skip records; stopped entry
guards skip immediately without attempting work; the tiny T*-1 solve
records a tiny-i-Tbelow skip and the target follow-up solve records a
target-i-Tbelow skip instead of omitting silently; a solver returning
None records a -none skip instead of crashing. Skips are never silent,
and no skip is benign: mid-cell and fill-in skips shorten lists
(completeness fails); tiny skips break tiny_full and target skips reduce
the timeout evidence (a target skip need not by itself invalidate
completed tiny pairs or an earlier timeout — the counters are stated
exactly as implemented); independently of those mechanisms, the clean
flag (zero skip records) is required by Gate 4, PURSUE and REJECT alike
— so any guard exit forces UNRESOLVED + next experiment via clean even
where the specific counters still pass. Every path publishes results.json
(guarded lookups, default-empty records, no unbound variables, no
zero-division). Skip/blocked records are built only by the shared helpers
(make_skip_record / blocked_solve_record); no hand-rolled dicts at any
site. Per-arm pursue counters use distinct variables per role (no
aliasing across makespan/physical roles).

Baseline disclosure: no MILP solver is invoked anywhere in this screen;
the exact baseline is z3-SMT (`z3.Solver` with `set('timeout', ms)`; only
`unknown` with recorded reason `timeout` counts as limit-expiry, never as
optimum). There is no MILP comparison anywhere in this screen.

Acceptance (frozen Pareto): PURSUE iff makespan-win (best(B,C) pooled
makespan beats A by > 2*SE_size, same SE_size as Gate 2, at >= 2 sizes)
AND phys-win (same rule on pooled physical cost with its own SE_phys at
>= 2 sizes) AND Gate-3 target timeout-reason expiry (>= 1 unknown with
reason timeout) AND full tiny sat/unsat pairs (exactly 4/4) AND self-tests
ok AND Gates 1, 2, 2p, 4 pass. A makespan-only win at higher physical
cost is NOT a Pareto win (routing analog of the rejected 136-to-140 CNOT
tradeoff). REJECT iff cells complete (both metrics) AND full tiny
sat/unsat evidence AND Gate-1 controls pass AND no strict pooled win on
EITHER metric at any size (min(B,C) mean never < A mean for makespan and
for physical cost). Else UNRESOLVED + next experiment. Pursue/reject
classification is coordinator-side; the payload reports numbers + gate
evidence and its verdict field is always unresolved-with-reason.
Deterministic given seeds.

NEXT_EXPERIMENT: joint-cost lookahead placement with wider SA route neighborhoods; escalate z3 scale probe to 60-op stacked instances with per-solve timeout 120 s.
