# Screen 22 — Bosonic stabilization, Fock N≤32

Design: screen-authored truncated-Fock (N≤32) bosonic-mode
stabilization simulator (stdlib + numpy only; no external
physics, solver, or policy libraries). One bosonic mode per
rep is prepared in a seeded logical superposition of frozen
code words (two cat-code families, one binomial-code family),
then subjected to a photon-loss channel at one of two frozen
loss regimes per rep plus photon-number dephasing (rate grid
KAPPA_PHI), interleaved with a discrete L_SEQ-slot
stabilization sequence. Each slot picks one of N_COMBOS
combos: a SNAP-like diagonal phase kick (phase alphabet
PHASE_VALS times PHASE_SCALE on n(n-1)/2, which echoes out
dephasing) plus an optional engineered-dissipation refill
(split-step: precomputed no-jump damping plus a recovery
jump at rate REFILL_R; cat jump (a^2-alpha^2)/alpha^2,
binomial error-word jumps). Every arm stabilizes the same
state under a different schedule, so arm equivalence holds
by construction. Metric: fixed-time infidelity (primary,
lower is better) plus integrated-fidelity lifetime
(secondary, higher is better). A truncation-artifact guard
records peak boundary population (top BOUND_EDGE levels,
fewer for the tiny space) per rep; any rep above
BOUND_THRESH flags its cell, and any flagged cell blocks
pursue. No MILP, SMT, OLSQA, Vandaele, Lau, PhasePoly, or
torch code exists anywhere in this screen (named blockers,
same as all screens).

Hypothesis: optimized discrete sequences (greedy +
annealed) beat a fixed SNAP-echo standard control on
fixed-time infidelity at matched-or-better lifetime, where
exact search hits a node budget, with no truncation-boundary
artifacts at N≤32.

Model (screen-authored):
- Sizes (frozen truncation dims, frozen code families):
  N_TRUNC = (16, 24, 32) with FAMILIES {16: CAT_A2, 24:
  CAT_A4, 32: BINOM_11} and ALPHA_SQ {16: 2.0, 24: 4.0, 32:
  6.0}. Two loss regimes KAPPA_GRID = (0.03, 0.08) with
  dephasing KAPPA_PHI = (0.015, 0.04), alternating by rep
  parity; DT = 0.25 per macro-step, T_STEPS = 8 steps.
  L_SEQ = 7 slots; N_PHASE = 3 phases PHASE_VALS =
  (-1.0, 0.0, 1.0) with PHASE_SCALE = 0.3; N_PUMP = 2 refill
  flags at rate REFILL_R = 0.12; N_COMBOS = 6 combos/slot.
- Arms (code truth):
- S: standard fixed SNAP-echo schedule (refill off) — frozen
  S_SEQ = (0, 2, 4, 2, 0, 2, 4) (the decomposed baseline).
- R: random control — seeded random sequence over N_COMBOS.
- G: greedy first-improvement descent from the S start
  (GREEDY_SWEEPS sweeps, strict improvement, never regresses).
- A: simulated annealing from IDENT_SEQ = (2, 2, 2, 2, 2,
  2, 2) — ANNEAL_ITERS proposals, ANNEAL_T0 x ANNEAL_ALPHA
  decay, cost = infidelity + LAMBDA x boundary, best tracked.
- Metric: fixed-time infidelity (primary) + lifetime
  (secondary) + boundary guard. Every cell keeps a live
  gradient: echo, random, and optimized arms never tie.
- Seeds SEEDS = (1, 2, 3, 4, 5); N_INST = 8 reps per (size,
  seed, arm) cell (60 cell-arms, 480 arm evaluations over 120
  bosonic states). Seeds are replicates.
- Soundness: tiny N=4 hand-checkable zero-loss instance
  (TINY_N = 4, TINY_ALPHA_SQ = 0.25, TINY_KAPPA = 0.0,
  TINY_T = 2, TINY_L = 1, TINY_PHASES = (0.0, 0.5),
  TINY_NCOMBOS = 4, TINY_OPT_INFID = 0.0, TINY_S_SEQ = (1,),
  TINY_TH = 1.1, TINY_PHI = 0.4) with known optimum 0.0 by
  construction (identity schedule under zero loss/dephasing).
  G, A match 0.0 (S off-optimum by design, not hand-gated;
  R random by design) + exact-opt optimum 0.0 on tiny +
  determinism (same seed repeats G and R) + N-convergence
  (size-0 rep at N vs N-4 differs by CONV_TOL = 0.05 max).
- Frozen symbols (code identifiers match exactly): N_TRUNC,
  FAMILIES, ALPHA_SQ, SEEDS, ARMS, KAPPA_GRID, KAPPA_PHI, DT,
  T_STEPS, L_SEQ, N_PHASE, PHASE_VALS, PHASE_SCALE, N_PUMP,
  REFILL_R, N_COMBOS, S_SEQ, IDENT_SEQ, GREEDY_SWEEPS,
  ANNEAL_ITERS, ANNEAL_T0, ANNEAL_ALPHA, LAMBDA,
  BOUND_EDGE, BOUND_THRESH, CONV_TOL, N_INST, EXACT_CAP,
  WALL_GUARD_S, WALL_LIMIT_S, TINY_N, TINY_ALPHA_SQ,
  TINY_KAPPA, TINY_T, TINY_L, TINY_PHASES, TINY_NCOMBOS,
  TINY_OPT_INFID, TINY_S_SEQ, TINY_TH, TINY_PHI, TARGET,
  NEXT_EXPERIMENT.

Controls:
- Gate 1: mean infidelity(G) strictly below mean
  infidelity(R) in all 15 (size, seed) cells AND tiny
  hand-check G/A at 0.0 AND determinism repeat identical.
  Coded exactly as `beats_all_15 && tiny_ok &&
  determinism_ok`.
- Gate 2: pooled infidelity spread across {S,G,A} > 2*SE at
  >= 2 sizes (pools = 5 seed means per size per arm). Gate 2s
  (lifetime spread, informational): same rule on pooled
  lifetime. Coded exactly as `n_sizes_spread_pass >= 2`.
- Gate 3: bounded-exact level-order branch-and-bound solves
  the tiny instance (status solved, optimum 0.0 == hand
  value, exactly 5 nodes) AND the target-scale instance
  (32-mode BINOM family, seed 1 rep 0, node cap 50000)
  reports exactly "cap-hit" (probed 50001 nodes). Only
  cap-hit counts as limit-expiry; a solved, stopped-guard,
  or skipped-guard target fails Gate 3, as does a wall-kill
  or missing baseline. Coded exactly as
  `tiny_solved && target_caphit_only`.
- Gate 4: complete (all 15 cells x 4 arms with n == N_INST;
  tiny + target records present) AND payload wall <
  WALL_LIMIT_S = 500 s AND zero skip records. Coded exactly
  as `complete && wall < 500 && zero skips`.

Budgets: wall 900 s, cpu 5400 s (reservation basis; same
generous staging as screens 19/21). Payload keeps wall
~30-60 s via a compact corpus (8 reps per cell) plus a
WALL_GUARD_S = 300 s elapsed guard checked before every
size, cell, and arm loop, every 32 reps/search evals, and
every 512 exact-solver nodes. EVERY guard exit appends an
explicit skip record with iters_done/n_evaluated (tiny /
target entry-guard failures, stopped-guard returns, and
per-cell / per-size exits), so a guard-truncated run cannot
pass G4 clean. All arms propagate stopped=True on a mid-arm
guard trip. results.json is written at normal completion;
witnesses/selftest.json after the self-test,
witnesses/gate3_tiny.json + gate3_targets.json after the
exact phases, witnesses/cells.json after each size, and
witnesses/checkpoint-<tag>.json after tiny, targets, each
size, and the corpus. WALL_LIMIT_S = 500 s is the Gate-4
wall bound. The payload accepts test-only --n-inst /
--anneal-iters overrides for dry-run calibration; the
supervised command line passes neither, so frozen N_INST = 8
and ANNEAL_ITERS = 60 govern.

Baseline disclosure: no MILP/SMT comparison anywhere in this
screen; the exact baseline is the bounded-exact level-order
branch-and-bound over sequences (own solved record on tiny
counts as optimum for the tiny instance; own cap-hit record
at target scale counts as limit-expiry, never as optimum).
There is no OLSQA/Vandaele/Lau/PhasePoly/torch
implementation anywhere in this screen.

Limitation (disclosed): single-mode truncated-Fock toy model
(binomial loss + dephasing, SNAP + split-step refill slots,
no back-action or Kerr nonlinearity), synthetic seeded
superpositions, screen-authored cost model, no hardware
claim; stationary-sequence-only search (slot choice, never
per-shot adaptivity). The recorded next experiment is
explicit closed-loop per-shot adaptive sequencing with
feedback, then a Kerr-regularized retest.

Acceptance (exact coded conditions): PURSUE iff some arm in
{G,A} jointly wins at >= 2 sizes, where arm X jointly wins
a size iff pooled mean infidelity(X) beats S by > 2*SE over
{S,G,A} AND pooled mean lifetime(X) >= pooled mean
lifetime(S) — both on the SAME arm; an infidelity-only win
with lower lifetime is NOT a joint win. Joint wins are
counted PER ARM, bar max(G,A) >= 2, never a per-instance
any-winner count. Also required: zero truncation-artifact
cells AND Gates 1, 2, 3, 4 pass AND self-tests ok. REJECT
iff complete AND tiny solved AND Gate-1 controls pass AND
no strict pooled infidelity win (G or A mean < S mean) at
any size. Else UNRESOLVED + next experiment
(closed-loop per-shot adaptive SNAP-displacement sequencing
with photon-number-resolved feedback plus Kerr-regularized
annealing retest). Pursue/reject classification is
coordinator-side; the payload reports numbers + gate
evidence and its verdict field is always
unresolved-with-reason. Deterministic given seeds.
