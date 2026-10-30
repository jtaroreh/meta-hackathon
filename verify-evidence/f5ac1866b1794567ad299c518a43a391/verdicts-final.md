# Per-path verdicts — run f5ac1866b1794567ad299c518a43a391 (LOOP run 3)

Envelope: created 1793312157 (≈15:19 PDT Oct 29 2026), deadline 1793340957
(≈23:15 PDT), no-launch cutoff ≈23:00 PDT. tool_hash `e10ce85a…`,
config_hash `3290f84f…`. Attested: pytest 62/62, capabilities PASS (fresh
live call), tooling-review PASS (rebind, identical bytes), prepare ok +
proof ok, pilot 18 ok, postpilot-review PASS (filed, check_review passes).

## Completed screens

- 06 (carried): UNRESOLVED in run 87b79c06 (v3 screen_files 581cd0a6…,
  ran clean 112.9 s). Makespan wins 3/3 strict but phys wins 0/3 —
  Pareto blocks pursue; Gate 1 fails 9/15 (random beats greedy A*);
  all Gate-3 targets solved, no solver timeout. Next: Gate-1 autopsy,
  phys-aware objective, harder exact instances.
- 01 (qLDPC BP-guiding, v4 screen_files 5c5b9760…, wall/cpu 900/5400):
  RAN CLEAN (attempt 01-939423c4…, finished exit:0, cleanup verified,
  wall 14.3 s, zero skips, all phase checkpoints + results.json written).
  Coordinated verdict: UNRESOLVED.
  Evidence: Gate 1 True; Gate 2 True (3/3 sizes); determinism True;
  Gate 4 True (150/150 cells x 300 tallies, wall 14.1 s). Gate 3 FALSE:
  d3 MLD Optimal (0.1 s) but all 20 d7 MLD solves Optimal in ~0.01–0.02 s
  — CBC demolishes 85-var MLD; zero TimeLimit → no limit-expiry evidence.
  Pheno gap recovery NEGATIVE at all sizes (B1/B2/B3 means d3
  −0.23/−0.23/−1.04, d5 −0.21/−0.45/−0.52, d7 +0.00/−0.22/−0.22).
  Circuit: A→C gaps positive (d3 ~0.05, d5 ~0.23–0.29); B1-serial recovers
  +79% (d3) / +68% (d5). PURSUE false (pheno recovery, Gate-3 expiry).
  REJECT false (gates not all evidenced).
  Next experiments: (1) pheno autopsy — why serial/damped schedules hurt
  on X-noise; try other perturbation families or re-scope to circuit noise
  where B1 wins. (2) Gate-3 hardness frontier: d=7 MLD in ~10 ms via CBC;
  push d=9/11 or denser noise, or record solver-sufficiency at these sizes.

## Queued / blocked

- 10 (AOD shuttling): BLOCKED — no OLSQA figure/data files exist anywhere
  in docs/screens/env (only prose mentions). Not selected. Next: source
  published OLSQA benchmark figures first.
- 15 (ZX spider-fusion + gflow): DEFERRED this run — 2/2 review attempts
  used (attempt 1 FAIL: unfuse/copy/DFS-terminal/Pareto/R/75-vs-45
  findings; attempt 2 FAIL on fixed files screen_files 5f8ab26a…: F1
  vacuous-solve hole, F3 arm-loop guard overclaim, F4 beam-dedupe brief
  sentence). Post-review staging fixes applied (solved requires
  optimum_twoq; stop() in all arm/fallback loops; brief corrected), new
  screen_files d1970c84…, carried to next run for fresh review. No PASS
  receipt filed. Evidence: receipts/screen-15-review-attempt2.txt +
  verify-evidence screen-15-review-attempt2-FAIL.txt.
- 20 (photonic fusion routing, from-scratch stochastic sim): RAN CLEAN
  (attempt 20-b768be37…, finished exit:0, cleanup verified, wall 70.1 s,
  cpu 69.7 s, zero skips, all phase checkpoints + results.json written).
  Coordinated verdict: REJECT-ON-THIS-SCREEN.
  Evidence: Gate 1 True; Gate 2 True (+informational cost spread True);
  Gate 3 True (tiny exact 3/3 solved + MC match; target N=16 enumeration
  cap-hit 50001 nodes); Gate 4 True (45/45 cells x B/C/F/R + tiny + target
  records, wall 69.9 s < 500, clean); selftest ok; acceptance wins 0/3
  sizes (no strict pooled adaptive yield win B or C over F at any size;
  pursue_condition false, reject_condition true).
  Next experiment: photon replenishment/multiplexing (finite pool grinds
  concentration policies — adaptive arms trailed static here), then an
  adaptive retest at 2 sizes.
- 02 (flag gadgets, stim schedule search): RAN CLEAN
  (attempt 02-64937e9c…, finished exit:0, cleanup verified, wall 74.4 s,
  cpu 74.2 s, zero skips, all phase checkpoints + results.json written).
  Coordinated verdict: PURSUE.
  Evidence: Gate 1 True (canonical d_eff 3 / 120 CNOTs; exact best 72
  CNOTs 0 flags 8 ancillas d_eff 3; random valid frac ~0.007 < 1);
  Gate 2 True (strict LER gradient d3 + d5 canonical over p=0.002/0.005/
  0.01); Gate 3 True (exact flag-subset 256/256 solved d=3; per-stab
  enum 150/150 cap-hit d=5); Gate 4 True (complete at configured counts,
  wall 74.3 s < 500, clean); selftest ok; acceptance pursue true /
  reject false (found valid d_eff==3 schedule at 72 vs 120 CNOTs).
  Next experiment: wider order neighborhoods, weight-6+ gadgets, d=7
  transfer to test whether the overhead win survives larger distances.
  Receipt note: filed screen-02-review.json initially carried a one-digit
  input_hash transcription slip (…4497 vs envelope …5497); corrected to
  the envelope value before run, gates re-verified PASS, no reviewed
  file changed.
- 04 (erasure + biased-noise hybrid, X-memory w/ 95% erasure flags):
  RAN CLEAN (attempt 04-4d71ad39…, finished exit:0, cleanup verified,
  wall 81.8 s, cpu 81.4 s, zero skips, all phase checkpoints +
  results.json written). Coordinated verdict: REJECT-ON-THIS-SCREEN.
  Evidence: Gate 1 FALSE (0/9 HYB two-SE wins; no hybrid win vs UF
  anywhere, no MWPM-subset majority); Gate 2 True (3/3 strict HYB
  gradients); Gate 3 True (tiny 6-defect solved in 36 nodes + pulp
  weight match; d=9 20-defect target cap-hit at 20001/20000 — solver's
  own cap); Gate 4 True (45/45 cells + 9/9 MWPM subsets, wall 81.7 s <
  500, clean); selftest ok; acceptance pursue false / reject true.
  Timing: HYB 0.53 ms/shot < MWPM 31.4 ms/shot < 50 ms budget, but no
  accuracy win. HYB edged UF directionally in 8/9 cells (~0.5–1 pt,
  never significant) — flag value exists but is sub-significant here.
  Next experiment: stronger bias/erasure regimes or larger d where
  hyperedge density grows; HYB==UF on flag-free shots isolates flag
  value cleanly. Staging history: attempt-1 review REVISE (MWPM-timeout
  None-guard crash) fixed + re-verified; attempt-2 PASS filed
  (screen_files 7e2454ee…; receipt filed).
- 07, 12, 19, 24, 03, 05, 08, 09, 11, 13, 14, 16, 17, 21,
  22, 23: QUEUED, clocks untouched. Run stopped here: CPU budget
  exhausted for further 5400-reservation screens (24000/28800 used,
  4800 remaining < 5400 minimum). Carry to next run with fresh reviews.

Screen 20: REJECT-on-this-screen claimed (coordinator-side, from supervised
evidence). Screen 02: PURSUE claimed (coordinator-side, from supervised
evidence). Screen 04: REJECT-on-this-screen claimed (coordinator-side,
from supervised evidence).

## Resource debits (run f5ac1866, final)

Reservations: prepare 1200 + pilot 1200 + screen-01 5400 + screen-20 5400
+ screen-02 5400 + screen-04 5400 = 24000 of 28800 global (payload walls:
01 14.3 s, 20 70.1 s, 02 74.4 s, 04 81.8 s; 4800 remaining — insufficient
for another 5400-reservation screen, loop ends here). Provider attempts:
postpilot review 1/2, screen-01 review 1/2 (PASS first round), screen-20
review 1/2 (PASS first round), screen-02 review 2/2 (REVISE then PASS),
screen-04 review 2/2 (REVISE then PASS).
