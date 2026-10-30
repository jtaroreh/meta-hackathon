# Screen 21 — Sparse quantum state preparation & unitary multiplexer decision trees

Design: screen-authored exact amplitude-loading decision-tree
builder (stdlib + numpy only; no external physics, solver, or
policy libraries). Sparse chemistry-like target states on n in
{10, 14, 18} qubits with frozen determinant counts S in {24, 48,
96} (all inside [16, 128]): seeded random determinant sets with
seeded normalized amplitudes (CISD / selected-CI families by
size). Each variable ordering induces an ordered decision tree
over the determinant set with BDD-style suffix merging (shared
CNOT-sharing paths); every two-sided branch node emits
CNOTS_PER_BRANCH = 2 logical CNOTs between the deciding qubit
and its ordering successor, routed on a frozen grid or frozen
heavy-hex-inspired layout (rep parity alternates grid/hex) with
all-pairs shortest-path distances precomputed by BFS. Routed
cost per CNOT at graph distance d is 3d-2 CNOTs; two-qubit
depth comes from list scheduling (duration 2 per CNOT-pair
block scaled as 2*(2d-1) per branch node). State validity
(reconstructed amplitudes match the target sparse vector) is
verified per rep. No MILP, SMT, OLSQA, Vandaele, Lau,
PhasePoly, or torch code exists anywhere in this screen (named
blockers, same as all screens).

Hypothesis: optimizing variable orderings and CNOT-sharing
paths on Binary Decision Diagrams (BDDs) minimizes routed CNOT
depth for sparse chemistry initial states (CISD/selected-CI
wavefunctions). Continue only if reordered decision trees beat
standard sparse-state synthesis baselines after routing on at
least two molecule sizes.

Model (screen-authored):
- Sizes (frozen qubit counts, frozen sparse families): 10
  qubits / 24 determinants (CISD), 14 qubits / 48 determinants
  (SELECTED_CI), 18 qubits / 96 determinants
  (SELECTED_CI_PLUS). Layouts: grid (n/2 x 2) and
  heavy-hex-inspired (path backbone + frozen chords),
  alternating by rep parity.
- Arms (code truth):
- M: standard Gray-code multiplexer / canonical ordering
  baseline — identity variable ordering, canonical
  amplitude-loading decision tree (the decomposed baseline).
- R: random ordering control — seeded random variable
  ordering, canonical tree build.
- G: greedy tree-rotation + qubit-reordering search — from the
  canonical ordering, GREEDY_SWEEPS first-improvement sweeps
  over adjacent swaps plus level-rotation (relocate) moves,
  strictly improving routed CNOTs (depth tie-break), best of
  the identity start and one seeded random restart.
- A: simulated annealing over variable orderings + CNOT-sharing
  paths — fixed ANNEAL_ITERS seeded adjacent/relocate proposals
  from the identity start, temperature ANNEAL_T0 decaying by
  ANNEAL_ALPHA, cost = routed CNOTs + LAMBDA x depth, best
  tracked.
- Metric: total routed CNOT count + two-qubit depth at fixed
  layout after frozen-layout routing + state-validity
  verification (prepared amplitudes match the target sparse
  vector exactly, tolerance 1e-9). Every cell is built with
  S >= 16 non-trivial sparse sets far above the single-product
  regime, so the metric has a live gradient and no cell ties
  across arms (dry-run verified).
- Seeds SEEDS = (1, 2, 3, 4, 5); N_INST = 12 reps per (size,
  seed, arm) cell (60 cell-arms, 720 arm evaluations over 180
  sparse states). Seeds are replicates.
- Soundness: tiny n=3 hand-checkable state (dets 000/111,
  amps 0.6/0.8) with known-optimum TINY_OPT = {cnots 2, depth
  2} by construction (one two-sided branch on an adjacent
  layout pair: 2 routed CNOTs / depth 2). M, G, A match 2/2
  (R is recorded but random by design, so it is not
  hand-gated) + exact-opt optimum 2 on tiny + determinism
  (same seed repeated gives identical G and R results).
- Frozen symbols (code identifiers match exactly): N_QUBITS,
  S_COUNTS, FAMILIES, SEEDS, ARMS, N_INST, GREEDY_SWEEPS,
  ANNEAL_ITERS, ANNEAL_T0, ANNEAL_ALPHA, LAMBDA,
  CNOTS_PER_BRANCH, EXACT_CAP, WALL_GUARD_S, WALL_LIMIT_S,
  TINY_N, TINY_DETS, TINY_AMPS, TINY_OPT, TARGET,
  NEXT_EXPERIMENT.

Controls:
- Gate 1: mean CNOTs(G) strictly below mean CNOTs(R) in every
  one of the 15 (size, seed) cells (pipeline discriminative)
  AND tiny hand-check 2/2 on M/G/A AND determinism repeat
  identical. Coded exactly as `beats_all_15 && tiny_ok &&
  determinism_ok`.
- Gate 2: pooled CNOT spread across {M,G,A} > 2*SE at >= 2
  sizes (pools = 5 seed means per size per arm). Gate 2s
  (depth spread, informational): same rule on pooled depth.
  Coded exactly as `n_sizes_spread_pass >= 2`.
- Gate 3: bounded-exact ordering branch-and-bound solves the
  tiny instance (status solved, optimum 2 == hand value) AND
  the target-scale instance (18-qubit family state, seed 1 rep
  0, grid layout, node cap 50000) reports exactly "cap-hit"
  (probed 50001 nodes). Only cap-hit counts as limit-expiry;
  a solved, stopped-guard, or skipped-guard target fails Gate
  3. A wall-kill or missing baseline never counts. If exact
  search cannot reach limit-expiry at these scales, Gate 3
  CANNOT pass and the screen caps at UNRESOLVED. Coded
  exactly as `tiny_solved && target_caphit_only`.
- Gate 4: complete (all 15 cells x 4 arms with n == N_INST;
  tiny + target records present) AND payload wall <
  WALL_LIMIT_S = 500 s AND zero skip records. Coded exactly
  as `complete && wall < 500 && zero skips`.

Budgets: wall 900 s, cpu 5400 s (reservation basis; same
generous staging as screens 19/17). Payload keeps wall ~10 s
via a compact corpus (12 reps per cell) plus a WALL_GUARD_S =
300 s elapsed guard checked before every size, every cell,
every arm loop, every 32 reps (and every 32 search evals),
and every 512 exact-solver nodes. Each batch publishes its
completed count (n alongside the configured total), and EVERY
guard exit appends an explicit skip record with
iters_done/n_evaluated, including tiny/target entry-guard
failures ("tiny-exact", "target-exact"), tiny/target
stopped-guard returns, and per-cell / per-size guard exits,
so a guard-truncated run cannot pass G4 clean. All arms
propagate stopped=True on a mid-arm guard trip. results.json
is written at normal completion; witnesses/selftest.json is
written after the self-test, witnesses/gate3_tiny.json +
gate3_targets.json after the exact phases, witnesses/cells.json
after each size, and witnesses/checkpoint-<tag>.json after
tiny, targets, each size, and the corpus, so a supervisor stop
still leaves classifiable evidence. Every skip path publishes
(guarded lookups, default-empty records, no unbound
variables). WALL_LIMIT_S = 500 s is the Gate-4 wall bound.
The payload accepts test-only --n-inst / --anneal-iters
overrides for dry-run calibration; the supervised command line
passes neither, so frozen N_INST = 12 and ANNEAL_ITERS = 80
govern.

Baseline disclosure: no MILP/SMT comparison anywhere in this
screen; the exact baseline is the bounded-exact
branch-and-bound over variable orderings (own solved record on
tiny counts as optimum for the tiny instance; own cap-hit
record at target scale counts as limit-expiry, never as
optimum). There is no OLSQA/Vandaele/Lau/PhasePoly/torch
implementation anywhere in this screen.

Limitation (disclosed): modeled layouts only (grid + stylized
heavy-hex, not fabricated device maps), synthetic sparse
amplitude sets (seeded random determinants, not ab initio
integrals), screen-authored multiplexer cost model (2 CNOTs
per two-sided branch, 3d-2 routing, list-scheduled depth), no
hardware claim; search is ordering-only (amplitude values
fixed, so wins come from BDD sharing + SWAP reduction, never
from gate-count reduction of the values). Explicit adaptive
variable-ordering search with look-ahead, then a
depth-regularized ordering annealing retest, is the recorded
next experiment.

Acceptance (exact coded conditions): PURSUE iff some arm in
{G,A} jointly wins at >= 2 sizes, where arm X jointly wins a
size iff pooled mean routed CNOTs(X) beats M by > 2*SE over
{M,G,A} AND pooled mean depth(X) <= pooled mean depth(M) —
both on the SAME arm; a CNOT-only win with higher depth is NOT
a joint win. Joint wins are counted PER ARM, bar max(G,A) >=
2, never a per-instance any-winner count. Also required:
Gates 1, 2, 3, 4 pass AND self-tests ok. REJECT iff complete
AND tiny solved AND Gate-1 controls pass AND no strict pooled
CNOT win (G or A mean < M mean) at any size. Else UNRESOLVED
+ next experiment (adaptive variable-ordering search with
look-ahead + depth-regularized ordering annealing retest).
Pursue/reject classification is coordinator-side; the payload
reports numbers + gate evidence and its verdict field is
always unresolved-with-reason. Deterministic given seeds.
