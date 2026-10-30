# Screen 20 — photonic fusion routing (staged in run f5ac1866b1794567ad299c518a43a391)

Design: from-scratch stochastic cluster-growth simulator (numpy + stdlib
only; no external physics libraries), static raster versus adaptive
largest-component policies, true terminal yield and fusion-attempt cost.
No MILP, SMT, OLSQA, Vandaele, Lau et al., PhasePoly or torch-policy code
exists anywhere in this screen (named blockers, same as all screens).

Hypothesis: herald-conditioned adaptive fusion order (largest-component
first, optionally discarding stale photons past an age cutoff) assembles
larger terminal clusters at no extra fusion cost than a static raster
order — across multiple loss rates.

Model (screen-authored):
- Pool: N microclusters of M = 6 photons each (N in {16, 36, 64}).
  A photon is a birth-round stamp; age = attempt index minus birth.
- One fusion attempt per time step (attempt index t = 0, 1, ...):
  policy picks an ordered pair of distinct non-empty components; the
  youngest photon of each is consumed. Each survives independently with
  probability (1 - p_loss) * DECAY**age (DECAY = 0.99). If both survive,
  the fusion gate succeeds with probability P_FUSION = 0.5 and the
  remainders merge; otherwise (any loss or gate failure) the two photons
  are destroyed with no merge. Rounds cap = 6*N attempts.
- Trial ends when fewer than 2 non-empty components remain, the raster
  completes a full cycle with no valid pair, or the rounds cap hits.
- Arms (pair choice; loss/decay/fusion mechanics identical):
- F: static raster — fixed cyclic order over all initial index pairs;
  each step takes the next pair with both slots non-empty, advancing
  the pointer past the used pair; ends on a full cycle with no valid pair.
- B: adaptive largest-component-first — the two currently largest
  non-empty components (size, then lowest index tie-break).
- C: B plus age cutoff — before each pick, photons with age > AGE_CUT
  = 40 are discarded (emptied components drop out); then the B rule.
  The cutoff binds only when trial attempts exceed 40 (larger sizes).
- R: random control — uniform random valid pair (up to 64 resamples),
  1000 rollouts per cell.
- Metrics per trial: yield = terminal largest-component photon count;
  cost = fusion attempts used.
- Soundness: bounded-exact outcome enumeration on a tiny config
  (N = 3, M = 2, rounds = 6, loss 5%) for F/B/C must SOLVE within node
  cap 50000, and Monte Carlo (1000 trials) must agree with the exact
  expected yield within 3SE per arm.

Controls:
- Gate 1: static mean yield strictly beats random-mean yield in every
  (size, loss, seed) cell (pipeline discriminative) AND tiny exact
  solved 3/3 AND tiny MC-vs-exact agreement 3/3 (sim sound).
- Gate 2: pooled yield spread across {F,B,C} > 2*SE at >= 2 sizes
  (pools = 15 cell means per size: 3 loss rates x 5 seeds).
  Gate 2c (cost spread, informational): same rule on pooled attempts.
- Gate 3: tiny exact 3/3 solved + 3/3 MC match AND the target
  enumeration (N = 16, loss 7.5%, arm B, node cap 50000) CAP-HITS
  (nodes exceed cap with best-so-far kept; probed 50001 nodes / 0.2 s).
  Only cap-hit counts as limit-expiry; a solved or stopped-guard target
  fails Gate 3. The wall guard is checked every 512 enumeration nodes
  (stopped-guard, distinct from cap-hit) and every 32 trial attempts.
- Gate 4: every planned cell complete (yield + attempts for F/B/C/R on
  all 45 cells; tiny + target records present) AND payload wall < 500 s
  AND zero skip records.

Budgets: wall 900 s, cpu 5400 s (reservation basis; staged generous after
the 01 window lesson). The supervisor admits min(wall - screen_wall_used,
run-remaining, cpu-remaining/capacity) minus 8.5 s overhead — prompt
select->launch keeps the admitted window near ~540 s. Payload keeps wall
~70 s (probed 68 s) via ordering (self-tests, tiny-exact + tiny-MC,
target enumeration, corpus blocks) plus a 300 s elapsed guard checked
before every cell, every arm loop, every 32 trial attempts, and every
512 enumeration nodes. EVERY guard exit records the omitted work
explicitly (remaining cells filled as skipped; whole-phase omissions
append one skip record per planned item — per tiny arm, per target, per
cell). results.json is written at normal completion;
witnesses/checkpoint-<phase>.json is written after tiny, after targets,
after each (size,loss) block, and after the corpus, so a supervisor stop
still leaves classifiable evidence. Every skip path publishes (guarded
lookups, default-empty records, no unbound variables, no zero-division).

Baseline disclosure: no MILP/SMT comparison anywhere in this screen; the
exact baseline is outcome enumeration (own cap-hit record counts as
limit-expiry, never as optimum). There is no OLSQA/Vandaele/Lau/
PhasePoly/torch implementation anywhere in this screen.

Limitation (disclosed): the pool has no photon replenishment or
multiplexing, so concentration policies grind a finite pool — adaptive
arms trail static here. Photon replenishment/multiplexing, then an
adaptive retest, is the recorded next experiment.

Acceptance (frozen joint Pareto, per arm): PURSUE iff some arm in {B,C}
jointly wins at >= 2 sizes, where arm X jointly wins a size iff pooled
mean yield(X) beats F by > 2*SE over {F,B,C} AND pooled mean
attempts(X) <= pooled mean attempts(F) — both on the SAME arm; a win
split across arms is NOT a Pareto win. A yield-only win with higher cost
is NOT a Pareto win. Also required: Gates 1, 2, 3, 4 pass AND
self-tests ok. REJECT iff cells complete AND tiny solved + matched AND
Gate-1 controls pass AND no strict pooled adaptive yield win (B or C
mean > F mean) at any size. Else UNRESOLVED + next experiment.
Pursue/reject classification is coordinator-side; the payload reports
numbers + gate evidence and its verdict field is always
unresolved-with-reason. Deterministic given seeds.
