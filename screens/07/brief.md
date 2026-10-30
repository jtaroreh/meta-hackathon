# Screen 07 — AutoCCZ + buffer scheduling

Design: screen-authored deterministic 2D tile-and-buffer scheduling model
(stdlib + numpy only; no external scheduling, physics, or solver
libraries). Factories emit T / AutoCCZ states with seeded Bernoulli
stochasticity at frozen factory:compute ratios; a shared-or-partitioned
staging buffer holds states; a width-limited corridor delivers them to a
compute front of T/CCZ demands seen through a 2-wide ready window. No
MILP, SMT, OLSQA, Vandaele, Lau et al., PhasePoly, or torch-policy code
exists anywhere in this screen (named blockers, same as all screens).

Hypothesis: joint buffer-allocation + corridor scheduling beats static
FIFO on active tiles x code cycles under plausible factory stochasticity.

Model (screen-authored):
- Front: deterministic length-240 demand sequence (10-motif with 30% CCZ
  plus an 8-wide CCZ burst every 50 ops), identical for all arms in a
  cell; per-rep factory traces are shared across arms (common random
  numbers) so arm gaps are policy, not luck.
- Regimes (frozen factory:compute ratios, buffer capacities, corridor
  widths; TILE_COMPUTE = 64, corridor 8 tiles/width, 2 tiles/state):
- small: p_T = 1/3, p_CCZ = 1/6 per cycle; shared pool 10 (static split
  5/5); corridor W = 2; factory tiles 20 (footprint 120).
- base: p_T = 1/5, p_CCZ = 1/10; shared pool 8 (static split 4/4);
  corridor W = 1; factory tiles 14 (footprint 102).
- stressed: p_T = 1/8, p_CCZ = 1/16; shared pool 6 (static split 3/3);
  corridor W = 1; factory tiles 10 (footprint 94).
- Active tiles = provisioned footprint (compute + factory + corridor +
  buffer-capacity tiles), fixed per regime and identical across arms;
  arms compete on time. Volume = footprint x code cycles.
- Arms (code truth):
- S: static FIFO — fixed buffer partition, FIFO serve order.
- B: dynamic buffer-aware — shared pool, demand-aware eviction on full
  (evict the relatively abundant type by next-8 need), abundant-first
  serve.
- C: joint buffer+corridor — B rules plus a one-step corridor rollout
  (3-cycle greedy lookahead per candidate) with deeper lookahead
  (K = 16 vs 8). At these widths/windows C matches B exactly (recorded
  finding, not a separate win).
- R: random control — static partition, single random transfer per
  cycle, 35% idle under contention (genuine-choice situations only, so
  R is identical to S on choice-free instances by construction).
- Metric: provisioned active tiles x code cycles (footprint volume) +
  stall counts (+ waste/peak recorded).
- Seeds SEEDS = (1, 2, 3, 4, 5); N_REP = 400 reps per (regime, seed,
  arm) cell (60 cell-arms, 24000 sims).
- Soundness: two tiny hand-checkable instances solved by construction
  (front [T,T] with arrivals t = 0,1 gives cycles 2 / stalls 0 /
  volume 108 on every arm; front [CCZ] with arrival t = 2 gives cycles
  3 / stalls 2 / volume 156 on every arm) + determinism (same seed
  repeated gives identical results, probed twice: self-test base/seed-1
  arm-B full-front repeat + main small/seed-1 arm-S repeat).

Controls:
- Gate 1: mean volume(S) strictly below mean volume(R) in every one of
  the 15 (regime, seed) cells (pipeline discriminative) AND tiny
  hand-check 8/8 AND determinism repeat identical. Coded exactly as
  `beats_all_15 && tiny_ok && determinism_ok`.
- Gate 2: pooled volume spread across {S,B,C} > 2*SE at >= 2 regimes
  (pools = 5 seed means per regime per arm). Gate 2s (stall spread,
  informational): same rule on pooled stalls. Coded exactly as
  `n_regimes_spread_pass >= 2`.
- Gate 3: bounded-exact DFS scheduler solves the tiny instance
  (status solved, optimum 156 == hand value) AND the target-scale
  instance (front 20, horizon 120, stressed rates, node cap 50000)
  reports exactly "cap-hit" (probed 50001 nodes / 0.1 s). Only cap-hit
  counts as limit-expiry; a solved, stopped-guard, or skipped-guard
  target fails Gate 3. A wall-kill or missing baseline never counts.
  Coded exactly as `tiny_solved && target_caphit_only`.
- Gate 4: complete (all 15 cells x 4 arms with n == N_REP; tiny +
  target records present) AND payload wall < WALL_LIMIT_S = 500 s AND
  zero skip records. Coded exactly as
  `complete && wall < 500 && zero skips`.
- Dry-run probe (/tmp/s07dry, frozen params): wall 87.4 s, zero skips.
  G1 pass (S < R in 15/15 cells; tiny 8/8; determinism identical). G2
  pass 3/3 (spreads 2928/6386/11469 vs SE 79/146/194). G3 pass (tiny
  solved optimum 156; target cap-hit 50001 nodes). G4 pass (complete,
  wall < 500, clean). Pursue-condition true (joint B wins 3/3 regimes).

Gates (exact coded definitions):
- G1: `beats_all_15 && tiny_ok && determinism_ok`.
- G2: `pooled volume spread > 2*SE at >= 2 regimes`.
- G3: `tiny_solved && target_caphit_only` — a solved or stopped-guard
  target fails.
- G4: `complete && wall < 500 && zero skips`.

Budgets: wall 900 s, cpu 5400 s (reservation basis; same generous
staging as screens 02/20). Payload keeps wall ~87 s (probed 87.4 s)
via ordering (self-test, tiny-exact, target enumeration, corpus by
regime) plus a WALL_GUARD_S = 300 s elapsed guard checked before every
regime, every cell, every arm loop, every 32 reps, every 32 sim cycles,
and every 512 exact-solver nodes. Each batch publishes its completed
count (n/iters_done alongside the configured total), and EVERY guard
exit appends an explicit skip record with iters_done/n_evaluated,
including tiny/target entry-guard failures ("tiny-exact",
"target-exact") and per-cell regime guard exits, so a guard-truncated
run cannot pass G4 clean. results.json is written at normal
completion; witnesses/selftest.json is written after the self-test,
witnesses/gate3_tiny.json + gate3_targets.json after the exact phases,
and witnesses/checkpoint-<tag>.json after tiny, targets, each regime,
and the corpus, so a supervisor stop still leaves classifiable
evidence. Every skip path publishes (guarded lookups, default-empty
records, no unbound variables). WALL_LIMIT_S = 500 s is the Gate-4
wall bound. The payload accepts test-only --n-rep/--front-len overrides
for dry-run calibration; the supervised command line passes neither, so
frozen N_REP = 400 governs.

Baseline disclosure: no MILP/SMT comparison anywhere in this screen;
the exact baseline is the bounded-exact DFS scheduler (own solved
record on tiny counts as optimum for the tiny instance; own cap-hit
record at target scale counts as limit-expiry, never as optimum).
There is no OLSQA/Vandaele/Lau/PhasePoly/torch implementation anywhere
in this screen.

Limitation (disclosed): modeled results only, no hardware claim; the
front is synthetic (motif + periodic CCZ bursts), factory stochasticity
is Bernoulli, and the corridor binds only through the ready window, so
the C rollout adds no further gain over B here (C matches B on all
probed reps). Burst-heavier fronts with larger shared buffers, then a
wider ready window / narrower corridor retest, is the recorded next
experiment.

Acceptance (exact coded conditions): PURSUE iff some arm in {B,C}
jointly wins at >= 2 regimes, where arm X jointly wins a regime iff
pooled mean volume(X) beats S by > 2*SE over {S,B,C} AND pooled mean
stalls(X) <= pooled mean stalls(S) — both on the SAME arm; a
volume-only win with higher stalls is NOT a joint win. Also required:
Gates 1, 2, 3, 4 pass AND self-tests ok. REJECT iff complete AND tiny
solved AND Gate-1 controls pass AND no strict pooled dynamic volume win
(B or C mean < S mean) at any regime. Else UNRESOLVED + next experiment
(burst-heavier fronts with larger shared buffers). Pursue/reject
classification is coordinator-side; the payload reports numbers + gate
evidence and its verdict field is always unresolved-with-reason.
Deterministic given seeds.
