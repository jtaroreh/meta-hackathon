# Screen 05 — Fault-tolerant magic-state cultivation / post-selection schedules

Design: screen-authored deterministic Clifford stabilizer-frame
simulator (stdlib + numpy only; no external physics, synthesis, or
solver libraries). Small cultivation stages (ring + chord cells, max
degree 3) on n in {6, 9, 12} qubits with C in {7, 11, 14} 2-body
checks (bond-type coloring X/Y/Z by edge index mod 3, one seeded
graft-disorder edge removed per stage/seed cell), measured over
T = 3/3/4 rounds. An abort policy holds per-checkpoint cumulative
syndrome-weight thresholds plus a final acceptance threshold
(post-select); the fixed baseline never aborts early. Faults are
single-qubit X/Z faults at interior slots (rounds 1..T-2, every
check position); each check's consecutive-round outcomes form
detectors. No MILP, SMT, OLSQA, Vandaele, Lau et al., PhasePoly, or
torch-policy code exists anywhere in this screen (named blockers,
same as all screens).

Hypothesis: adaptive mid-cultivation abort rules reduce wasted
spacetime volume at matched output infidelity versus fixed
post-selection schedules, across physical depolarizing error rates.

Model (screen-authored):
- Stages (frozen cultivation sizes): 6 qubits / 7 checks / 3 rounds,
  9 qubits / 11 checks / 3 rounds, 12 qubits / 14 checks / 4 rounds.
  Degree never exceeds 3 by construction (ring gives 2, chords at
  i, i+3 for i = 0 mod 4 are disjoint, adding at most 1, minus one
  seeded disorder edge per cell).
- Noise regimes (frozen physical depolarizing rates, per
  Pauli-resolved fault location): p in {0.001, 0.002, 0.005}.
- Policy = abort thresholds per checkpoint in {0,1,2,3,99}
  (99 = never abort) + final acceptance threshold in {0,1,2}.
- Arms (code truth):
- F: fixed post-selection — never abort early, strict final
  post-select (threshold 0) (the decomposed baseline).
- R: random abort-timing control — 3 seeded random abort policies
  under strict final post-select, mean reported.
- G: greedy adaptive abort — constrained first-improvement sweep
  from F (GREEDY_SWEEPS = 2), strictly lowering wasted volume at
  matched infidelity (inf <= F-inf x 1.10 + 1e-6).
- A: simulated annealing over policies — fixed A_ITERS = 40
  proposals from F, cost = W + LAMBDA x inf (frozen LAMBDA =
  5000.0, A_T0 = 1.0, A_ALPHA = 0.97), best tracked.
- Metric: wasted spacetime volume per accepted output
  W = E[spent]/P(accept) - V_full (fault-enumeration approximation:
  exact weights 0..2 binomial-weighted at p; tail w>=3 counted as
  rejected at full volume and non-logical, disclosed) + output
  infidelity (accepted-logical rate; accepted w1 always logical).
- Seeds SEEDS = (1, 2, 3, 4, 5); 45 (stage, rate, seed) cells x 4
  arms (180 arm evaluations; seeds are the replicates).
- Soundness: tiny n = 6 ring hand-checkable cell (L1 = 72 faults,
  known by type counting: every interior single fault flips at
  least one detector, so F accepts 0 weight-1 faults) + exact-joint
  optimum never above F volume + determinism (same seed repeated
  identical).

Controls:
- Gate 1: pooled mean W(G) strictly below pooled mean W(R) in every
  one of the 9 (stage, rate) cells (pipeline discriminative) AND
  tiny hand-bound (L1 = 72, 0 w1 accepted) AND determinism repeat
  identical. Coded exactly as `beats_all_9 && tiny_ok &&
  determinism_ok`.
- Gate 2: pooled W spread across {F,G,A} > 2*SE in >= 4 of the 9
  (stage, rate) cells spanning >= 2 stages (pools = 5 seed values
  per cell per arm). Coded exactly as `n_cells_spread_pass >= 4
  spanning >= 2 stages`.
- Gate 3: bounded-exact joint search over check schedules x abort
  policies solves the tiny instance (status solved, optimum
  recorded) AND the target-scale instance (12-qubit cell, seed 1,
  node cap 50000) reports exactly "cap-hit" (probed 50001 nodes).
  Only cap-hit counts as limit-expiry; a solved, stopped-guard, or
  skipped-guard target fails Gate 3. A wall-kill or missing
  baseline never counts. If exact search cannot reach limit-expiry
  at these scales, Gate 3 CANNOT pass and the screen caps at
  UNRESOLVED. Coded exactly as `tiny_solved &&
  target_caphit_only`.
- Gate 4: complete (all 45 cells x 4 arms with n == 1; tiny +
  target records present) AND payload wall < WALL_LIMIT_S = 500 s
  AND zero skip records. Coded exactly as `complete && wall < 500
  && zero skips`.

Budgets: wall 900 s, cpu 5400 s (reservation basis; same generous
staging as screens 02/20/07/12). Payload keeps wall to tens of
seconds via ordering (self-test, tiny-exact, target exact, corpus
by size) plus a WALL_GUARD_S = 300 s elapsed guard checked before
every size, every cell, every arm loop, every 32 search
candidates, and every 512 exact-solver nodes. Each batch publishes
its completed count (n alongside the configured total), and EVERY
guard exit appends an explicit skip record with
iters_done/n_evaluated, including tiny/target entry-guard failures
("tiny-exact", "target-exact") and per-cell / per-size guard exits,
so a guard-truncated run cannot pass G4 clean. results.json is
written at normal completion; witnesses/selftest.json is written
after the self-test, witnesses/gate3_tiny.json +
gate3_targets.json after the exact phases, witnesses/cells.json
after each size, and witnesses/checkpoint-<tag>.json after tiny,
targets, each size, and the corpus, so a supervisor stop still
leaves classifiable evidence. Every skip path publishes (guarded
lookups, default-empty records, no unbound variables).
WALL_LIMIT_S = 500 s is the Gate-4 wall bound. The payload accepts
test-only --anneal-iters / --r-samples overrides for dry-run
calibration; the supervised command line passes neither, so frozen
A_ITERS = 40 and R_SAMPLES = 3 govern.

Baseline disclosure: no MILP/SMT comparison anywhere in this
screen; the exact baseline is the bounded-exact joint search over
schedules x policies (own solved record on tiny counts as optimum
for the tiny instance; own cap-hit record at target scale counts
as limit-expiry, never as optimum). There is no OLSQA/Vandaele/
Lau/PhasePoly/torch implementation anywhere in this screen.

Limitation (disclosed): modeled cells only (ring+chord
cultivation-inspired graphs, not fabricated device maps),
synthetic bulk-only X/Z fault model (boundary slots excluded, Y
only via weight-2 pairs), check order fixed to canonical in the
corpus (schedule search only in the exact baseline), tail w>=3
censored (rejected at full volume, non-logical: absolute
infidelity optimistic at high p, arm comparisons share the
assumption), small cells, modeled disorder, no hardware claim;
volume is qubit-rounds under list-scheduled depth. Check-order
co-optimization + per-round threshold variation is the recorded
next experiment.

Acceptance (exact coded conditions): PURSUE iff some arm in {G,A}
jointly wins at >= 2 noise regimes, where arm X jointly wins a
rate iff pooled mean W(X) over stages x seeds beats F by >= 10%
relative AND pooled mean infidelity(X) <= pooled mean
infidelity(F) + 2*SE over {F,G,A} — both on the SAME arm; a
volume-only win with higher infidelity is NOT a joint win. Also
required: Gates 1, 2, 3, 4 pass AND self-tests ok. REJECT iff
complete AND tiny solved AND Gate-1 controls pass AND no strict
pooled W win (G or A mean < F mean) at any rate. Else UNRESOLVED
+ next experiment (check-order co-optimization + per-round
threshold variation retest).
Pursue/reject classification is coordinator-side; the payload
reports numbers + gate evidence and its verdict field is always
unresolved-with-reason. Deterministic given seeds.
