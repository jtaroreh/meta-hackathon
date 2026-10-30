# Screen 12 — Mid-circuit measurement & qubit-reuse topological scheduling

Design: screen-authored deterministic reuse-scheduling simulator
(stdlib + numpy only; no external scheduling, physics, or solver
libraries). A birth/death active-pool generator emits logical CNOT
circuits on W in {24, 32, 40} wires at 8 gates/wire (192/256/320
gates); causal cones are the per-wire gate chains, and cone extraction
is the predecessor/successor DAG plus live-range (first/last use)
analysis that drives reset-and-reuse targets on a frozen 4x4 2D grid
(16 physical qubits). Routed cost per gate at Manhattan distance d is
3d-2 CNOTs (one SWAP chain each way, +6 per eviction move); two-qubit
depth comes from list scheduling (duration 2d-1 per gate, +2 per
eviction). No MILP, SMT, OLSQA, Vandaele, Lau et al., PhasePoly, or
torch-policy code exists anywhere in this screen (named blockers, same
as all screens).

Hypothesis: jointly selecting DAG topological orderings and physical
reset-and-reuse targets compresses width (40 logical wires onto 16
physical) without blowing up SWAP routing depth.

Model (screen-authored):
- Families (frozen wire counts, 16 physical on a frozen 4x4 grid):
  24 wires / 192 gates, 32 wires / 256 gates, 40 wires / 320 gates.
  The generator holds a 12-wire active pool (birth on retirement, forced
  births so exactly W distinct wires appear); canonical live width peaks
  at 12 (audited 12/12 max over all 540 corpus circuits).
- Arms (code truth):
- G: greedy earliest-reuse — canonical gate order, newborn logical wire
  takes the lowest-index free physical (width-minimizing baseline).
- B: routing-aware beam search — width 10, branch 5 over ready gates,
  newborn takes the free physical minimizing summed grid distance to
  already-placed neighbors; state score = routed CNOTs + 5 x makespan.
- A: routing-aware annealing — 500 iterations over priority-key
  topological orders with the same co-locating placement and cost
  (routed CNOTs + 5 x depth), best tracked from the canonical start.
- R: random control — random topological order (seeded Kahn) + random
  free physical.
- Metric: total routed CNOT count + two-qubit depth at fixed physical
  width 16.
- Seeds SEEDS = (1, 2, 3, 4, 5); N_INST = 36 reps per (family, seed,
  arm) cell (60 cell-arms, 2160 arm evaluations over 540 circuits).
- Soundness: tiny hand-checkable circuit [(0,1),(1,2)] with
  known-optimal reuse by construction (wire 2 reuses wire 0's physical
  after its last use; hand values routed 2 / depth 2). G, B, A match
  6/6 (R is recorded but random by design, so it is not hand-gated) +
  exact-opt optimum 2 on tiny + determinism (same seed repeated
  gives identical G and R results).

Controls:
- Gate 1: mean CNOTs(G) strictly below mean CNOTs(R) in every one of
  the 15 (family, seed) cells (pipeline discriminative) AND tiny
  hand-check 6/6 AND determinism repeat identical. Coded exactly as
  `beats_all_15 && tiny_ok && determinism_ok`.
- Gate 2: pooled CNOT spread across {G,B,A} > 2*SE at >= 2 wire counts
  (pools = 5 seed means per family per arm). Gate 2s (depth spread,
  informational): same rule on pooled depth. Coded exactly as
  `n_families_spread_pass >= 2`.
- Gate 3: bounded-exact DFS solves the tiny instance (status solved,
  optimum 2 == hand value) AND the target-scale instance (24-wire
  family circuit, seed 1 rep 0, node cap 50000) reports exactly
  "cap-hit" (probed 50001 nodes). Only cap-hit counts as limit-expiry;
  a solved, stopped-guard, or skipped-guard target fails Gate 3. A
  wall-kill or missing baseline never counts. Coded exactly as
  `tiny_solved && target_caphit_only`.
- Gate 4: complete (all 15 cells x 4 arms with n == N_INST; tiny +
  target records present) AND payload wall < WALL_LIMIT_S = 500 s AND
  zero skip records. Coded exactly as
  `complete && wall < 500 && zero skips`.
- Dry-run probe (/tmp/s12dry, frozen params): wall 74.4 s, zero skips.
  G1 pass (G < R in 15/15 cells; tiny 6/6; determinism identical). G2
  pass 3/3 (spreads 120.6/149.1/186.5 vs SE 3.16/5.46/3.61). G3 pass
  (tiny solved optimum 2; target cap-hit 50001 nodes). G4 pass
  (complete, wall < 500, clean). Pursue-condition true (joint B wins
  3/3 families).

Gates (exact coded definitions):
- G1: `beats_all_15 && tiny_ok && determinism_ok`.
- G2: `pooled CNOT spread > 2*SE at >= 2 wire counts`.
- G3: `tiny_solved && target_caphit_only` — a solved or stopped-guard
  target fails.
- G4: `complete && wall < 500 && zero skips`.

Budgets: wall 900 s, cpu 5400 s (reservation basis; same generous
staging as screens 02/20/07). Payload keeps wall ~74 s (probed
74.4 s) via ordering (self-test, tiny-exact, target exact, corpus by
family) plus a WALL_GUARD_S = 300 s elapsed guard checked before every
family, every cell, every arm loop, every 32 reps, and every 512 exact
solver nodes. Each batch publishes its completed count (n alongside
the configured total), and EVERY guard exit appends an explicit skip
record with iters_done/n_evaluated, including tiny/target entry-guard
failures ("tiny-exact", "target-exact") and per-cell / per-family
guard exits, so a guard-truncated run cannot pass G4 clean.
results.json is written at normal completion; witnesses/selftest.json
is written after the self-test, witnesses/gate3_tiny.json +
gate3_targets.json after the exact phases, witnesses/cells.json after
each family, and witnesses/checkpoint-<tag>.json after tiny, targets,
each family, and the corpus, so a supervisor stop still leaves
classifiable evidence. Every skip path publishes (guarded lookups,
default-empty records, no unbound variables). WALL_LIMIT_S = 500 s is
the Gate-4 wall bound. The payload accepts test-only --n-inst /
--anneal-iters overrides for dry-run calibration; the supervised
command line passes neither, so frozen N_INST = 36 and
ANNEAL_ITERS = 500 govern.

Baseline disclosure: no MILP/SMT comparison anywhere in this screen;
the exact baseline is the bounded-exact DFS scheduler (own solved
record on tiny counts as optimum for the tiny instance; own cap-hit
record at target scale counts as limit-expiry, never as optimum).
There is no OLSQA/Vandaele/Lau/PhasePoly/torch implementation anywhere
in this screen.

Limitation (disclosed): modeled routing cost only (3d-2 CNOTs /
duration 2d-1 per gate, +6/+2 per eviction move), synthetic birth/death
families, no hardware claim; beam search reorders live ranges so rare
evictions occur under reordering (recorded: B 0.33/instance,
R 0.37/instance; G/A zero here) — moves are costed, never free.
Explicit live-range-split cone-block families with wider beam, then a
depth-regularized annealing retest, is the recorded next experiment.

Acceptance (exact coded conditions): PURSUE iff some arm in {B,A}
jointly wins at >= 2 wire counts, where arm X jointly wins a wire
count iff pooled mean routed CNOTs(X) beats G by > 2*SE over {G,B,A}
AND pooled mean depth(X) <= pooled mean depth(G) — both on the SAME
arm; a CNOT-only win with higher depth is NOT a joint win. Also
required: Gates 1, 2, 3, 4 pass AND self-tests ok. REJECT iff complete
AND tiny solved AND Gate-1 controls pass AND no strict pooled
routing-aware CNOT win (B or A mean < G mean) at any wire count. Else
UNRESOLVED + next experiment (live-range-split cone-block families,
wider beam, depth-regularized annealing retest). Pursue/reject
classification is coordinator-side; the payload reports numbers + gate
evidence and its verdict field is always unresolved-with-reason.
Deterministic given seeds.
