# Screen 23 — Adaptive QPE under T2 dephasing, fixed time/shots budget

Design: screen-authored adaptive quantum phase estimation simulator
(stdlib + numpy only; no external physics, solver, or policy libraries).
Unknown phase phi in [0, 2pi); each shot picks an evolution multiplier k
in 1..K_MAX plus a feedback angle theta on a frozen N_THETA grid; outcome
0/1 from P = (1 + C(k) cos(k(phi-theta)))/2 with T2 contrast
C(k) = exp(-k*TAU/T2_VAL). The posterior is tracked on a frozen N_PART
particle grid with exact renormalizing Bayes updates (likelihoods are
strictly interior since C(k) < 1, so weights never collapse to zero).
Every rep gets exactly N_SHOTS shots AND total time sum(k) <= TIME_BUDGET
(feasible k reserves 1 unit per future shot), so adaptivity must trade
per-shot information against budget and dephasing. Every arm estimates the
same phase from the same coupled outcome draws, so arm equivalence holds
by construction. No MILP, SMT, OLSQA, Vandaele, Lau et al., PhasePoly, or
torch code exists anywhere in this screen (named blockers, same as all
screens).

Hypothesis: multi-step lookahead (depth-2 search over future measurement
settings) beats myopic one-step adaptive rules on Holevo variance of the
final estimator at fixed time/shots budget, in regimes where exact search
over setting sequences hits a node cap.

Model (screen-authored):
- Sizes (frozen max Ramsey order K_MAX per size): SIZES = (2, 4, 6) with
  T2_VAL = 8.0, TAU = 1.0 fixed (contrasts C(1..6) = 0.88..0.47);
  N_SHOTS = 12 shots, TIME_BUDGET = 16 time units, N_THETA = 6 feedback
  angles, N_PART = 64 particles.
- Arms (code truth):
- M: myopic one-step adaptive baseline — each shot maximizes the expected
  posterior resultant over feasible (k, theta); ties keep the smallest k
  then smallest theta via SCORE_TOL (the decomposed baseline).
- R: random control — seeded uniform (k, theta) among feasible settings
  with the same outcome-draw coupling as the other arms.
- G: depth-2 lookahead — every shot scores all feasible first settings by
  expected two-step resultant (top LOOK_B = 6 by myopic score get the full
  nested rollout; the rest carry their myopic score as proxy), picks the
  argmax with SCORE_TOL ties-to-first, then replans (receding horizon).
- A: simulated annealing over closed-loop policies (flat k-schedule plus
  feedback offset theta_t = snap(mean_t + off)) — ANNEAL_ITERS proposals,
  budget-repaired, cost = mean 1-cos(err) over N_ROLL = 3 seeded rollouts,
  ANNEAL_T0 x ANNEAL_ALPHA decay, best tracked with strict improvement so
  the start is never regressed past.
- Metric: Holevo variance V = 1/S^2-1 with S = |mean exp(i err)| over the
  cell reps (primary, lower is better) + mean posterior concentration
  (secondary, higher is better) + posterior-normalization
  estimator-validity audit (norm/finite/sharp per rep; any invalid rep
  flags its cell and blocks pursue). Every cell keeps a live gradient:
  coupled draws plus distinct policies keep all four arms separated.
- Seeds SEEDS = (1, 2, 3, 4, 5); N_INST = 24 reps per (size, seed, arm)
  cell (60 cell-arms, 1440 arm evaluations over 360 phases).
- Soundness: tiny single-shot zero-dephasing instance (TINY_KMAX = 1,
  TINY_SHOTS = 1, TINY_PHI = 0.0, TINY_C = 1.0) with known optimum
  TINY_OPT_V = 0.0 by construction (outcome 0 with probability 1, posterior
  mean exactly the true phase). M, G, A match within 1e-9 (R is recorded
  but random by design, so it is not hand-gated) + exact-opt optimum 0.0
  on tiny with exactly 1 + TINY_NCOMBOS = 7 nodes + determinism (same seed
  repeats identical G, R, A results).
- Frozen symbols (code identifiers match exactly): SIZES, SEEDS, ARMS,
  N_SHOTS, TIME_BUDGET, TAU, T2_VAL, N_THETA, N_PART, LOOK_B,
  ANNEAL_ITERS, ANNEAL_T0, ANNEAL_ALPHA, N_ROLL, N_INST, EXACT_CAP,
  WALL_GUARD_S, WALL_LIMIT_S, TINY_KMAX, TINY_SHOTS, TINY_PHI,
  TINY_OPT_V, TINY_NCOMBOS, TINY_C, SCORE_TOL, VALID_TOL,
  VALID_SHARP_MIN, TARGET, NEXT_EXPERIMENT.

Controls:
- Gate 1: mean Holevo(G) strictly below mean Holevo(R) in every one of
  the 15 (size, seed) cells (pipeline discriminative) AND tiny hand-check
  M/G/A within 1e-9 AND determinism repeat identical. Coded exactly as
  `beats_all_15 && tiny_ok && determinism_ok`.
- Gate 2: pooled Holevo spread across {M,G,A} > 2*SE at >= 2 sizes
  (pools = 5 seed cell values per size per arm). Gate 2s (concentration
  spread, informational): same rule on pooled concentration. Coded exactly
  as `n_sizes_spread_pass >= 2`.
- Gate 3: bounded-exact level-order branch-and-bound solves the tiny
  instance (status solved, optimum 0.0 == hand value, exactly 7 nodes) AND
  the target-scale instance (size-6 family, seed 1 rep 0, node cap 50000)
  reports exactly "cap-hit" (probed 50001 nodes). Only cap-hit counts as
  limit-expiry; a solved, stopped-guard, or skipped-guard target fails
  Gate 3. A wall-kill or missing baseline never counts. If exact search
  cannot reach limit-expiry at these scales, Gate 3 CANNOT pass and the
  screen caps at UNRESOLVED. Coded exactly as
  `tiny_solved && target_caphit_only`.
- Gate 4: complete (all 15 cells x 4 arms with n == N_INST; tiny +
  target records present) AND payload wall < WALL_LIMIT_S = 500 s
  AND zero skip records. Coded exactly as
  `complete && wall < 500 && zero skips`.

Budgets: wall 900 s, cpu 5400 s (reservation basis; same generous staging
as screens 19/22). Payload keeps wall ~15-30 s via the compact corpus
(24 reps per cell) plus a WALL_GUARD_S = 300 s elapsed guard checked before
every size, every cell, every arm loop, every 32 reps, every 8 annealing
iters, and every 512 exact-solver nodes. Each batch publishes its completed
count (n alongside the configured total), and EVERY guard exit appends an
explicit skip record with iters_done/n_evaluated, including tiny/target
entry-guard failures ("tiny-exact", "target-exact"), stopped-guard exact
returns, and per-cell / per-size guard exits, so a guard-truncated run
cannot pass G4 clean. All arms propagate stopped=True on a mid-arm guard
trip. results.json is written at normal completion; witnesses/selftest.json
after the self-test, witnesses/gate3_tiny.json + gate3_targets.json after
the exact phases, witnesses/cells.json after each size, and
witnesses/checkpoint-<tag>.json after tiny, targets, each size, and the
corpus, so a supervisor stop still leaves classifiable evidence. Gates are
computed from the reloaded serialized cell block (witnesses/cells.json),
never from live-only state. Every skip path publishes (guarded lookups,
default-empty records, no unbound variables). WALL_LIMIT_S = 500 s is the
Gate-4 wall bound. The payload accepts test-only --n-inst / --anneal-iters
overrides for dry-run calibration; the supervised command line passes
neither, so frozen N_INST = 24 and ANNEAL_ITERS = 40 govern.

Baseline disclosure: no MILP/SMT comparison anywhere in this screen; the
exact baseline is the bounded-exact level-order branch-and-bound over
setting sequences (own solved record on tiny counts as optimum for the
tiny instance; own cap-hit record at target scale counts as limit-expiry,
never as optimum). There is no OLSQA/Vandaele/Lau/PhasePoly/torch
implementation anywhere in this screen.

Limitation (disclosed): single-phase screen-authored toy model (binary
outcomes, exponential-T2 contrast, particle-grid posterior, no SPAM,
no drift, no multi-parameter fields), synthetic uniform phases, fixed
shots+time budget, screen-authored cost model, no hardware claim;
depth-2-only lookahead with LOOK_B shortlist. The recorded next experiment
is depth-3 sparse lookahead with learned rollout policy plus closed-loop
annealed feedback-gain retest under stronger T2 dephasing.

Acceptance (exact coded conditions): PURSUE iff some arm in {G,A} jointly
wins at >= 2 sizes, where arm X jointly wins a size iff pooled mean
Holevo(X) beats M by > 2*SE over {M,G,A} AND pooled mean
concentration(X) >= pooled mean concentration(M) — both on the SAME arm;
a Holevo-only win with lower concentration is NOT a joint win. Joint wins
are counted PER ARM, bar max(G,A) >= 2, never a per-instance any-winner
count. Also required: zero invalid-estimator cells AND Gates 1, 2, 3, 4
pass AND self-tests ok. REJECT iff complete AND tiny solved AND Gate-1
controls pass AND no strict pooled Holevo win (G or A mean < M mean) at
any size. Else UNRESOLVED + next experiment (depth-3 sparse lookahead with
learned rollout policy plus closed-loop annealed feedback-gain retest
under stronger T2 dephasing). Pursue/reject classification is
coordinator-side; the payload reports numbers + gate evidence and its
verdict field is always unresolved-with-reason. Deterministic given seeds.
NEXT_EXPERIMENT = depth-3 sparse lookahead with learned rollout policy plus closed-loop annealed feedback-gain retest under stronger T2 dephasing
