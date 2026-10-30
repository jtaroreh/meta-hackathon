# Screen 13 — Crosstalk-aware parallel two-qubit gate coloring on tunable couplers

Design: screen-authored deterministic crosstalk-aware two-qubit
layering model (stdlib + numpy only; no external physics, solver, or
policy libraries). Qubits sit on frozen square grids (3x3/4x4/5x5 =
9/16/25 qubits, all <= 64 modeled) with tunable couplers on grid
edges; each cell schedules N_GATES = 12 frozen CZ/iSWAP gates on
seeded random couplers. The hardware conflict hypergraph has hard
edges (two gates sharing a qubit can never share a layer) and soft
spectator edges (concurrent gates on edge-adjacent couplers pay a
frequency-collision penalty). Every arm colors the same gate list
under the same hypergraph, so arm equivalence holds by
construction. Metric is expected circuit survival probability
(frozen product of per-gate fidelities x spectator-crosstalk
penalties x idle T1/T2 decay per layer) plus layer-validity
verification. No MILP, SMT, OLSQA, Vandaele, Lau et al., PhasePoly,
or torch code exists anywhere in this screen (named
blockers, same as all screens).

Hypothesis: scheduling simultaneous CZ/iSWAP layers under explicit
spectator frequency-collision and parasitic ZZ-crosstalk penalties
yields higher total circuit fidelity than naive minimum-depth layer
packing. Continue only if the idle-decoherence vs crosstalk-penalty
tradeoff creates a non-trivial optimum beating both extremes at
two sizes.

Model (screen-authored):
- Sizes (frozen grids, ≤64 qubits modeled): 3x3 (9 qubits), 4x4
  (16 qubits), 5x5 (25 qubits). N_GATES = 12 CZ/iSWAP gates per
  cell on seeded random grid edges (kind alternates CZ/iSWAP by
  seeded index parity). Seeds SEEDS = (1, 2, 3, 4, 5);
  N_INST = 400 reps per (size, seed, arm) cell (60 cell-arms,
  24000 arm evaluations over 6000 gate lists).
- Survival (frozen product): per-gate F_CZ = 0.995 / F_ISWAP =
  0.996, times X_TALK = 0.997 per spectator pair (concurrent gates
  on edge-adjacent couplers), times IDLE_DECAY = 0.9999 per idle
  qubit per layer (T1/T2 proxy). Gate product is arm-constant;
  arms trade crosstalk pairs against idle qubit-layers.
- Arms (code truth):
- D: naive minimum-depth packing baseline — fixed gate order,
  first-fit into the earliest layer with no shared qubit
  (depth-minimal, crosstalk-blind).
- R: random control — seeded shuffled gate order, each gate to a
  seeded uniform legal layer (existing or new; the new layer is
  always legal, so validity holds; deeper than D on average,
  the idle-heavy extreme).
- G: greedy crosstalk-penalized list scheduling — fixed order,
  each gate into the layer minimizing incremental -log survival
  (created spectator pairs + added idle), new layer allowed.
- A: crosstalk-penalized annealing from the G coloring
  (ANNEAL_ITERS = 300, A_T0 = 1.0, A_ALPHA = 0.99) over
  single-gate relocations with validity repair, best tracked,
  so A never regresses G.
- Soundness: tiny 2x2 hand-checkable cell (CZ(0,1) + iSWAP(0,2)
  sharing qubit 0) with known-optimum 2 layers, survival
  0.9906236514572361. D, G match; A invariant (>= G); R recorded
  but random by design (not hand-gated) + exact-opt optimum ==
  hand value + determinism (same seed gives identical G, R).
- Frozen symbols (code identifiers match exactly): GRID_SIZES,
  N_QUBITS_PER_SIZE, N_GATES, SEEDS, ARMS, F_CZ, F_ISWAP,
  X_TALK, IDLE_DECAY, ANNEAL_ITERS, A_T0, A_ALPHA, N_INST,
  EXACT_CAP, WALL_GUARD_S, WALL_LIMIT_S, TINY_SIZE,
  TINY_GATES, TINY_EXP_SURVIVAL, TINY_EXP_LAYERS, TARGET,
  NEXT_EXPERIMENT.

Controls:
- Gate 1: mean survival(G) strictly above mean survival(R) in
  every one of the 15 (size, seed) cells (pipeline
  discriminative) AND tiny hand-check (D/G exact, A
  invariants) AND determinism repeat identical. Coded exactly
  as `beats_all_15 && tiny_ok && determinism_ok`.
- Gate 2: pooled survival spread across {D,G,A} > 2*SE at >= 2
  sizes (pools = 5 cell means per size per arm). Coded exactly
  as `n_sizes_spread_pass >= 2`.
- Gate 3: bounded-exact coloring search solves the tiny instance
  (status solved, optimum survival == hand value) AND the target
  instance (5x5, seed 1 rep 0, node cap 50000) reports exactly
  "cap-hit" (probed 50001 nodes). Only cap-hit counts as
  limit-expiry; a solved/stopped-guard/skipped-guard target fails,
  and a wall-kill or missing baseline never counts. If exact search
  cannot reach limit-expiry, Gate 3 CANNOT pass and the screen caps
  at UNRESOLVED. Coded exactly as `tiny_solved && target_caphit_only`.
- Gate 4: complete (all 15 cells x 4 arms with n == N_INST;
  tiny + target records present) AND payload wall <
  WALL_LIMIT_S = 500 s AND zero skip records. Coded exactly
  as `complete && wall < 500 && zero skips`.

Budgets: wall 900 s, cpu 5400 s (reservation basis; same generous
staging as screens 19/11). Payload keeps wall to ~1-3 min via a
tiny corpus (fast 12-gate replays on small grids) plus a
WALL_GUARD_S = 300 s elapsed guard checked before every size,
every cell, every arm loop, every 32 reps, every 32 annealing
proposals, and every 512 exact-solver nodes. Each batch publishes
its completed count, and EVERY guard exit appends an explicit skip
record with iters_done/n_evaluated, including tiny/target
entry-guard failures ("tiny-exact", "target-exact"), tiny/target
stopped-guard returns, and per-cell / per-size guard exits, so a
guard-truncated run cannot pass G4 clean. All arms propagate
stopped=True on a mid-arm guard trip. results.json is written at
normal completion; witnesses/selftest.json, gate3_tiny.json,
gate3_targets.json, per-size cells.json, and
witnesses/checkpoint-<tag>.json (tiny, targets, each size,
corpus) leave classifiable evidence after a supervisor stop.
WALL_LIMIT_S = 500 s is the Gate-4 wall bound. Test-only
--n-inst / --anneal-iters overrides exist for dry-run
calibration; the supervised command line passes neither, so frozen
N_INST = 400 and ANNEAL_ITERS = 300 govern.

Baseline disclosure: no MILP/SMT comparison anywhere in this
screen; the exact baseline is the bounded-exact coloring search
over layer assignments (own solved record on tiny counts as
optimum for the tiny instance; own cap-hit record at target
scale counts as limit-expiry, never as optimum). There is no
OLSQA/Vandaele/Lau/PhasePoly/torch implementation anywhere in
this screen.

Limitation (disclosed): modeled grids only (not fabricated coupler
maps), synthetic random gate lists, frozen scalar fidelity weights
(no full T1/T2 frequency model), no hardware claim; wins come from
crosstalk/idle tradeoffs only, never gate-count changes.
Next experiment: frequency-aware qubit placement co-optimization + correlated crosstalk-noise retest.

Acceptance (exact coded conditions): PURSUE iff some arm in {G,A}
jointly wins at >= 2 grid sizes, where arm X jointly wins a size
iff pooled mean survival(X) beats D by > 2*SE over {D,G,A} AND
pooled mean validity(X) >= pooled mean validity(D) — both on the
SAME arm; a survival-only win with degraded validity is NOT joint.
Joint wins are counted PER ARM, bar is max(G,A) >= 2, never a
per-instance any-winner count. Also required: Gates 1-4 pass AND
self-tests ok. REJECT iff complete AND tiny solved AND Gate-1
controls pass AND no strict pooled survival win (G/A mean > D
mean) at any size. Else UNRESOLVED + next experiment (frequency-aware qubit placement co-optimization + correlated crosstalk-noise retest). Classification is coordinator-side; the
payload verdict field is always unresolved-with-reason.
Deterministic given seeds.
