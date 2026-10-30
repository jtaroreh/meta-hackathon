# Screen 19 — Clifford tableau synthesis on restricted topologies

Design: screen-authored deterministic bitwise stabilizer-tableau
simulator (stdlib + numpy only; no external synthesis, physics, or
solver libraries). Random Clifford circuits (H/S/CNOT, CNOTs on
frozen layout edges) on n in {8, 12, 16} qubits at 6 gates/qubit
(48/72/96 gates); each rep is evaluated on a frozen grid layout or a
frozen heavy-hex-inspired layout (rep parity alternates grid/hex),
with all-pairs shortest-path distances precomputed by BFS. Tableaus
are bitwise stabilizer rows (x_mask/z_mask ints + phase),
canonicalized by deterministic row-sort signature; every arm
synthesizes the same logical gate list under a different
logical-to-physical placement, so arm equivalence holds by
construction. Routed cost per CNOT at graph distance d is 3d-2
CNOTs (one SWAP chain each way); two-qubit depth comes from list
scheduling (duration 2d-1 per CNOT, 1 per single-qubit gate) under a
fixed depth-round budget per size (40/60/80). No MILP, SMT, OLSQA,
Vandaele, Lau et al., PhasePoly, or torch-policy code exists
anywhere in this screen (named blockers, same as all screens).

Hypothesis: topology-native search over placements (greedy +
annealing) synthesizes stabilizer tableaus with lower routed
two-qubit count and depth than canonical Gaussian elimination +
SWAP routing, in regimes where exact synthesis hits a timeout wall.

Model (screen-authored):
- Sizes (frozen qubit counts, 6 gates/qubit): 8 qubits / 48 gates,
  12 qubits / 72 gates, 16 qubits / 96 gates. Layouts: grid
  (4x2, 4x3, 4x4) and heavy-hex-inspired (path backbone + frozen
  chords), alternating by rep parity; depth-round budgets 40/60/80.
- Arms (code truth):
- D: canonical Gaussian elimination + SWAP routing — identity
  placement (logical i -> node i), canonical gate order (the
  decomposed baseline).
- G: greedy local search — pairwise-swap placement descent
  (GREEDY_SWEEPS sweeps over all logical pairs, first-improvement
  on routed CNOTs) from the identity start.
- A: simulated annealing over placements — fixed ANNEAL_ITERS
  random-swap proposals from the identity start, cost = routed
  CNOTs + LAMBDA x depth (frozen LAMBDA = 5.0), best tracked.
- R: random control — seeded random placement, canonical order.
- Metric: total routed CNOT count + circuit depth at fixed layout.
- Seeds SEEDS = (1, 2, 3, 4, 5); N_INST = 1300 reps per (size,
  seed, arm) cell (60 cell-arms, 78000 arm evaluations over 19500
  circuits).
- Soundness: tiny n=2 hand-checkable Clifford [H0, CNOT(0,1)] with
  known-optimal synthesis by construction (adjacent pair: routed
  1 / depth 2). D, G, A match 2/2 (R is recorded but random by
  design, so it is not hand-gated) + exact-opt optimum 1 on tiny +
  determinism (same seed repeated gives identical G and R
  results).

Controls:
- Gate 1: mean CNOTs(G) strictly below mean CNOTs(R) in every one
  of the 15 (size, seed) cells (pipeline discriminative) AND tiny
  hand-check 2/2 AND determinism repeat identical. Coded exactly
  as `beats_all_15 && tiny_ok && determinism_ok`.
- Gate 2: pooled CNOT spread across {D,G,A} > 2*SE at >= 2 sizes
  (pools = 5 seed means per size per arm). Gate 2s (depth spread,
  informational): same rule on pooled depth. Coded exactly as
  `n_sizes_spread_pass >= 2`.
- Gate 3: bounded-exact branch-and-bound solves the tiny instance
  (status solved, optimum 1 == hand value) AND the target-scale
  instance (16-qubit family circuit, seed 1 rep 0, grid layout,
  node cap 50000) reports exactly "cap-hit" (probed 50001 nodes).
  Only cap-hit counts as limit-expiry; a solved, stopped-guard, or
  skipped-guard target fails Gate 3. A wall-kill or missing
  baseline never counts. If exact search cannot reach limit-expiry
  at these scales, Gate 3 CANNOT pass and the screen caps at
  UNRESOLVED. Coded exactly as `tiny_solved && target_caphit_only`.
- Gate 4: complete (all 15 cells x 4 arms with n == N_INST; tiny +
  target records present) AND payload wall < WALL_LIMIT_S = 500 s
  AND zero skip records. Coded exactly as
  `complete && wall < 500 && zero skips`.

Budgets: wall 900 s, cpu 5400 s (reservation basis; same generous
staging as screens 02/20/07/12). Payload keeps wall ~70-120 s via
ordering (self-test, tiny-exact, target exact, corpus by size)
plus a WALL_GUARD_S = 300 s elapsed guard checked before every
size, every cell, every arm loop, every 32 reps, and every 512
exact-solver nodes. Each batch publishes its completed count (n
alongside the configured total), and EVERY guard exit appends an
explicit skip record with iters_done/n_evaluated, including
tiny/target entry-guard failures ("tiny-exact", "target-exact")
and per-cell / per-size guard exits, so a guard-truncated run
cannot pass G4 clean. results.json is written at normal
completion; witnesses/selftest.json is written after the
self-test, witnesses/gate3_tiny.json + gate3_targets.json after
the exact phases, witnesses/cells.json after each size, and
witnesses/checkpoint-<tag>.json after tiny, targets, each size,
and the corpus, so a supervisor stop still leaves classifiable
evidence. Every skip path publishes (guarded lookups,
default-empty records, no unbound variables). WALL_LIMIT_S =
500 s is the Gate-4 wall bound. The payload accepts test-only
--n-inst / --anneal-iters overrides for dry-run calibration; the
supervised command line passes neither, so frozen N_INST = 1300
and ANNEAL_ITERS = 400 govern.

Baseline disclosure: no MILP/SMT comparison anywhere in this
screen; the exact baseline is the bounded-exact branch-and-bound
over placements (own solved record on tiny counts as optimum for
the tiny instance; own cap-hit record at target scale counts as
limit-expiry, never as optimum). There is no OLSQA/Vandaele/
Lau/PhasePoly/torch implementation anywhere in this screen.

Limitation (disclosed): modeled layouts only (grid + stylized
heavy-hex, not fabricated device maps), synthetic random Clifford
circuits, routed-cost model (3d-2 CNOTs / duration 2d-1 per CNOT),
no hardware claim; placement-only search (gate order fixed, so
wins come from SWAP reduction, never from gate-count reduction).
Explicit gate-reordering synthesis families with look-ahead, then
a depth-regularized annealing retest, is the recorded next
experiment.

Acceptance (exact coded conditions): PURSUE iff some arm in {G,A}
jointly wins at >= 2 sizes, where arm X jointly wins a size iff
pooled mean routed CNOTs(X) beats D by > 2*SE over {D,G,A} AND
pooled mean depth(X) <= pooled mean depth(D) — both on the SAME
arm; a CNOT-only win with higher depth is NOT a joint win. Also
required: Gates 1, 2, 3, 4 pass AND self-tests ok. REJECT iff
complete AND tiny solved AND Gate-1 controls pass AND no strict
pooled CNOT win (G or A mean < D mean) at any size. Else
UNRESOLVED + next experiment (gate-reordering synthesis families
with look-ahead + depth-regularized annealing retest).
Pursue/reject classification is coordinator-side; the payload
reports numbers + gate evidence and its verdict field is always
unresolved-with-reason. Deterministic given seeds.
