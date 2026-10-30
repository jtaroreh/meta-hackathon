# Screen 06 — lattice-surgery routing (re-staged in run a0268985 after 06-review-attempt1 FAIL)

Re-stage notes (bounded corrections addressing the FAIL findings;
same wall/cpu allowance, same command, same seeds/programs-per-cell shape;
files brief.md + src/run06.py only; v3 adds the tiny-Tbelow skip record
and the clean flag after 06-review-attempt2 FAIL):
- Corpus is now QUBITS in {10,20,30} logical qubits on placed patches
  (was N_OPS op counts on uniform random patches).
- Gate 4 is now physical end-to-end cost AND completion AND wall
  (was completion + wall only).
- Skip accounting is airtight: every guard exit records the omitted
  cells/solves explicitly (run_phase fills all remaining planned cells;
  whole-phase omissions append tiny-i/target-i skip records; tiny_full
  requires exactly the 4 planned instances).

Hypothesis: smarter route+scheduling (prioritized planning, annealing over
order+route) shortens lattice-surgery makespan AND physical error-exposure
volume versus greedy sequential A*.

Model (screen-authored, disclosed as such — no surgery code exists in the
frozen closure; everything below is implemented in `src/run06.py`):
- 5x5 patch grid, 4-neighbourhood. Factories at (0,0) and (4,4); each serves
  1 merge-op per 2 time units: per-factory `next_free` starts at 0, a merge-op
  starting at `s` on factory `f` requires `s >= next_free[f]`, then sets
  `next_free[f] = s + 2`.
- Qubit placement: Q logical qubits mapped to patches deterministically:
  patch[q] = perm[q % 25] where perm is the seeded permutation of the 25
  patches from (Q, seed). Q = 30 shares 5 patches; endpoints are exempt
  from vertex capacity, so co-location is legal in the model.
- Workload sizes QUBITS in {10,20,30}. A program is N_GATES = 20 two-qubit
  gates between distinct qubits (kinds uniform; pairs uniform with a
  patch-distinct redraw so endpoints never coincide). Seeds 1-5, 100
  programs per (size, seed): 60 cells, 6000 programs total.
- Routing: path = simple grid path between endpoints. Edge capacity 1 op per
  step. Vertex capacity 1 op per step for internal vertices; endpoints are
  exempt (never recorded, never checked). Ops scheduled at integer starts.
  Cost = makespan = max over ops of (start + len(path)).
- Physical cost per program = total traversed edges summed over ops (sum of
  chosen route lengths) — proxy for physical error exposure / movement
  volume. Recorded per cell alongside makespan.
- Traversal timing (directional): forward path v0..vL occupies edge e_i at
  step s+i and internal vertex v_j at step s+j; the reversed orientation
  occupies the reversed edge order at s+i and internal vertex v_j at
  s+(L-j). Hence endpoint orientation changes edge/vertex timing and is a
  real degree of freedom. A route+start is feasible iff all its edges and
  internal vertices are free at every step of traversal (traversal takes
  len(path) steps) and a factory token is free at start if needed.
- Self-tests (recorded in payload): A* shortest-path length == Manhattan
  distance on empty grid; factory token accounting exact against hand-set
  placements; schedule feasibility checker agrees with construction on random
  instances (construct-then-verify returns ok).

Arms (K = 4 shortest simple paths per op, BFS enumeration in fixed neighbour
order, both orientations tried at placement unless noted):
- A: greedy sequential A*. Ops in generated order, per-op shortest A* path
  (route 0, forward orientation), earliest feasible start.
- B: prioritized planning + rotation. Order ops by descending shortest-path
  length, tie-break by generated (seed) order. Per op try both endpoint
  orientations on route 0, keep earliest-finishing (ties keep forward).
- C: simulated annealing over (order permutation + route choice among the K
  per op), 1500 iterations, seeded rng, accept by makespan delta with fixed
  cooling (T0 = 2.0, alpha = 0.995, T <- T0 * alpha^iter). Decode = greedy
  earliest-start placement in perm order with chosen routes (both
  orientations tried, earliest-finishing kept). Neighbour move: with prob
  0.5 swap two perm positions, else re-pick one op's route index.
- R: random control. Seeded random op order + seeded uniform random route
  among the K per op, same earliest-start decode with orientation try.
- Gate 1: A must beat R in every (size, seed) cell (strictly smaller mean
  makespan over the cell's 100 programs).

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
  Tiny: 3x3 grid / 2-op instances (4 seeded instances), solve ascending from
  the shortest-path lower bound to find T* (cap T <= 12); expect sat at T* and
  unsat at T*-1, record both statuses verbatim and both wall times. Target:
  4 instances on qubit-framed programs over Q = 20 placed patches —
  ti 0..2 are 6-gate first-seed programs; ti 3 (scale probe) is the full
  20-gate first program of the Q = 20 corpus — horizon = min(heuristic-A
  makespan, 16), each solve with `set('timeout', 20000)`; need >= 1
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
  recorded as blocked honestly rather than shrunk silently. Only
  unknown-with-reason-timeout counts as limit-expiry (other reasons fail
  the gate).
  Limitation (disclosed): small targets alone do not prove corpus-scale
  hardness; the ti-3 scale probe addresses this; classification stays
  coordinator-side either way.
- Gate 4: every planned (size, seed, arm) cell complete with BOTH makespan
  and physical-cost lists (100 programs each) AND payload wall time < 500 s
  AND zero skip records (clean). Any recorded skip makes the run unclean,
  fails Gate 4, and fails both PURSUE and REJECT (which also require clean),
  forcing UNRESOLVED + next experiment.

Budgets: wall 600 s, cpu 3600 s (reservation basis). Payload keeps wall
< 500 s via work ordering (self-tests, arms A/R/B, Gate-3 tiny, arm C,
Gate-3 targets) plus an elapsed guard at 420 s checked at every
(size, seed, arm) cell and before each z3 solve. EVERY guard exit records
the omitted work explicitly: run_phase fills all remaining planned cells
as skipped; whole-phase omissions append tiny-i/target-i skip records;
the tiny T*-1 solve records a tiny-i-Tbelow skip and the target follow-up
solve records a target-i-Tbelow skip instead of omitting silently. Skips
are never silent, and no skip is benign: mid-cell and fill-in skips
shorten lists (completeness fails); tiny skips break tiny_full and target
skips reduce the timeout evidence (a target skip need not by itself
invalidate completed tiny pairs or an earlier timeout — the counters are
stated exactly as implemented); independently of those mechanisms, the
clean flag (zero skip records) is required by Gate 4, PURSUE and REJECT
alike — so any guard exit forces UNRESOLVED + next experiment via clean
even where the specific counters still pass. Every path
publishes results.json (guarded lookups, default-empty records,
no unbound variables, no zero-division).

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
