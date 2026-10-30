# Screen 16 — Pauli-propagation & surrogate expectation-value truncation

Design: screen-authored bitwise Heisenberg-picture Pauli
back-propagation (stdlib + numpy only; no external physics,
solver, or policy libraries). Observables are X/Z-mask dicts
(Python ints) propagated backwards through Clifford layers
(H/S/CNOT with exact matrix-verified sign rules) plus
non-Clifford Rz rotation layers (each X-bearing string branches
in two) under per-layer depolarizing damping (1-p)^w. Every arm
replays the SAME frozen seeded circuit per rep under a matched
tracked-string budget, so arm equivalence holds by construction.
No MILP, SMT, OLSQA, Vandaele, Lau, PhasePoly, or torch code
exists anywhere in this screen (named blockers, same as all
screens).

Hypothesis: an adaptive truncation policy inside
Heisenberg-picture Pauli back-propagation maximizes observable
accuracy per tracked Pauli string on noisy utility circuits vs
static weight or coefficient-magnitude cutoffs. Continue only if
adaptive truncation beats static coefficient and Pauli-weight
thresholds at two circuit depths under matched string budgets.

Model (screen-authored):
- Qubits/depths (frozen): N_QUBITS = 14; DEPTHS = (6, 12, 18)
  layers. Each layer: random Clifford sublayer (H p=0.30, S
  p=0.20, CNOT chain p=0.40 per edge) + rotation sublayer (Rz
  angle uniform(-pi, pi) p=0.80 per qubit, else no rotation)
  followed by depolarizing noise DEPOL_P = 0.01. Observable: Z
  on OBS_Q = 0.
- Arms (code truth):
- W: static Pauli-weight cutoff baseline — keep the lowest-weight
  strings (magnitude-blind, deterministic mask tie-break).
- R: random truncation control — seeded random keep-set under the
  matched string budget.
- G: greedy magnitude-cutoff scheduling — keep the largest-|coeff|
  strings (deterministic mask tie-break).
- A: adaptive lookahead path-importance pruning — score each
  string by |coeff| x damped next-layer branch mass (product of
  |cos|+|sin| over rotated X-bearing qubits, peeking LOOKAHEAD =
  1 layers ahead) and keep the top scorers.
- Budgets: K_BUDGET = 64 tracked strings for every arm at every
  truncation (every cell binds: shallowest natural sizes are
  ~100 strings, so all 15 cells exercise truncation); K_REF =
  8192 for the converged large-budget
  reference (magnitude-kept; n_dropped == 0 is the convergence
  witness that the reference never truncated, hence is exact).
- Metric: mean-squared observable error vs the converged
  large-budget reference at the matched string budget +
  budget-validity verification (tracked strings <= cap).
- Seeds SEEDS = (1, 2, 3, 4, 5); N_INST = 16 reps per (depth,
  seed, arm) cell (15 cell-arms per depth, 60 cell-arms, 960 arm
  evaluations over 240 circuits). Seeds are replicates.
- Soundness: tiny 2-qubit hand-check [H0, Rz0(pi/3), H0],
  TINY_N = 2, TINY_THETA = pi/3, no noise, with known optimum
  TINY_EXP = 0.5 by construction (Z->X->cos X + sin Y->cos Z -
  sin Y). All four arms match 0.5; reference is exact
  (n_dropped == 0); exact-opt optimum 0.5 on tiny + determinism
  (same seed repeated gives identical G and R results).
- Frozen symbols (code identifiers match exactly): N_QUBITS,
  DEPTHS, SEEDS, ARMS, K_BUDGET, K_REF, DEPOL_P, N_INST,
  LOOKAHEAD, OBS_Q, EXACT_CAP, WALL_GUARD_S, WALL_LIMIT_S,
  TINY_N, TINY_THETA, TINY_EXP, TARGET, NEXT_EXPERIMENT.

Controls:
- Gate 1: mean MSE(G) strictly below mean MSE(R) in every one of
  the 15 (depth, seed) cells (pipeline discriminative) AND tiny
  hand-check 0.5 on all arms AND determinism repeat identical.
  Coded exactly as `beats_all_15 && tiny_ok && determinism_ok`.
- Gate 2: pooled MSE spread across {W,G,A} > 2*SE at >= 2 depths
  (pools = 5 seed means per depth per arm). Coded exactly as
  `n_depths_pass >= 2`.
- Gate 3: bounded-exact Pauli-path search solves the tiny
  instance (status solved, optimum == 0.5 hand value) AND the
  target instance (depth-18 circuit, seed 1 rep 0, node cap
  50000) reports exactly "cap-hit" (probed 50001 nodes). Only
  cap-hit counts as limit-expiry; a solved, stopped-guard, or
  skipped-guard target fails Gate 3. A wall-kill or missing
  baseline never counts. If exact search cannot reach
  limit-expiry at these scales, Gate 3 CANNOT pass and the screen
  caps at UNRESOLVED. Coded exactly as
  `tiny_solved && target_caphit_only`.
- Gate 4: complete (all 15 cells x 4 arms with n == N_INST; tiny +
  target records present) AND payload wall < WALL_LIMIT_S = 500 s
  AND zero skip records. Coded exactly as
  `complete && wall < 500 && zero skips`.

Budgets: wall 900 s, cpu 5400 s (reservation basis; same generous
staging as screens 19/14). Payload keeps wall to ~2 min via a
compact corpus (16 reps per cell) plus a WALL_GUARD_S = 300 s
elapsed guard checked before every depth, every cell, every arm
loop, every 32 reps, and every 512 exact-solver nodes. Each batch
publishes its completed count, and EVERY guard exit appends an
explicit skip record with iters_done/n_evaluated, including
tiny/target entry-guard failures ("tiny-exact", "target-exact"),
tiny/target stopped-guard returns, and per-cell / per-depth guard
exits, so a guard-truncated run cannot pass G4 clean. All arms
propagate stopped=True on a mid-arm guard trip (the reference
does too). results.json is written at normal completion;
witnesses/selftest.json after the self-test,
witnesses/gate3_tiny.json + gate3_targets.json after the exact
phases, witnesses/cells.json after each depth, and
witnesses/checkpoint-<tag>.json after tiny, targets, each depth,
and the corpus, so a supervisor stop still leaves classifiable
evidence. Every skip path publishes (guarded lookups,
default-empty records, no unbound variables). WALL_LIMIT_S =
500 s is the Gate-4 wall bound. The payload accepts a test-only
--n-inst override for dry-run calibration; the supervised command
line passes none, so frozen N_INST = 16 governs.

Baseline disclosure: no MILP/SMT comparison anywhere in this
screen; the exact baseline is the bounded-exact Pauli-path search
over Rz-branch children (own solved record on tiny counts as
optimum for the tiny instance; own cap-hit record at target
scale counts as limit-expiry, never as optimum; the noiseless
path enumeration is exact because damping never changes the
branch tree). There is no OLSQA/Vandaele/Lau/PhasePoly/torch
implementation anywhere in this screen.

Limitation (disclosed): modeled utility circuits only (seeded
random Clifford + Rz layers, scalar depolarizing damping, no
device maps), surrogate large-budget reference instead of a
density-matrix exact (convergence witnessed per rep by
n_dropped == 0), single-qubit Z observable only, no hardware
claim; wins come from truncation choice only. Next experiment:
weight-aware damping reweighting + multi-observable transfer
retest.

Acceptance (exact coded conditions): PURSUE iff some arm in {G,A}
jointly wins at >= 2 depths, where arm X jointly wins a depth iff
pooled mean MSE(X) beats W by > 2*SE over {W,G,A} AND pooled mean
validity(X) >= pooled mean validity(W) — both on the SAME arm; an
MSE-only win with degraded validity is NOT a joint win. Joint
wins are counted PER ARM, bar is max(G,A) >= 2, never a
per-instance any-winner count. Also required: Gates 1, 2, 3, 4
pass AND self-tests ok. REJECT iff complete AND tiny solved AND
Gate-1 controls pass AND no strict pooled MSE win (G or A mean <
W mean) at any depth. Else UNRESOLVED + next experiment
(weight-aware damping reweighting + multi-observable transfer
retest). Pursue/reject classification is coordinator-side; the
payload reports numbers + gate evidence and its verdict field is
always unresolved-with-reason. Deterministic given seeds.
