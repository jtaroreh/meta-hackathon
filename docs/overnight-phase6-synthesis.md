# Phase 6 — Portfolio synthesis, funding decisions, and close

Date: 2026-10-31. Scope: all 24 paths from run `f5ac1866` through tail
relay run `b8b625b2`. Method: every classification below is re-derived
from supervised evidence files (`results/verdicts.md` per run,
`work/results.json` per attempt, binding receipts) — never from payload
self-verdicts. Standing answers from the handoff apply unless noted.

Final tally: **14 PURSUE, 6 UNRESOLVED, 2 REJECT, 1 BLOCKED, 1 INFRA.**

## 1. Decision matrix (one row per ID)

Columns: verdict | gate vector | decisive numbers | CPU reservation /
actual wall | classifying run | exact next experiment.

| ID | Screen | Verdict | Gates | Decisive numbers | CPU res / wall | Run | Next experiment |
|---|---|---|---|---|---|---|---|
| 01 | qLDPC BP-guiding follow-up | UNRESOLVED (solver-sufficiency) | G1✓ G2✓ G3✗ G4✓ | B3 serial/1.25 recovers +44/+40/+34/+30% at d3–d9 (same arm); CBC 28/28 Optimal ≤0.075 s thru d11 | 3590 / 38 s | b8b625b2 | max_iter sweep {30,100,300}, winning B, two largest pheno sizes |
| 02 | LDPC surgery compilation (+d7 scale-up) | PURSUE (d3/d5/d7) | G1✓ G2✓ G3✓ G4✓ | transfer 72/8 vs 120/16 (d3), 240/24 vs 384/48 (d5), 504/48 vs 792/96 (d7) at preserved d_eff; LER tracks canonical; exact 256/256, enum cap-hit | 5400 / 198 s | b8b625b2 | d=9 transfer + threshold measurement |
| 03 | Floquet schedule optimization | UNRESOLVED | G1✗ G2✗ G3✓ G4✓ | distance schedule-invariant (H==G==R==S everywhere); G depth 36→12 but distance flat | 5400 / 3 s | cfc1d43d | defect-aware check-type recoloring + per-round variation |
| 04 | QLDPC surgery scheduling | REJECT on this screen | G1✗ G2✓ G3✓ G4✓ | 0/9 2×SE wins vs UF; HYB 0.53 ms/shot vs MWPM 31.4 ms/shot — speed w/o accuracy | 5400 / 82 s | f5ac1866 | reopen only in new regime (§7.4: higher erasure/stronger bias) |
| 05 | Magic-state cultivation | PURSUE | G1✓ G2✓ G3✓ G4✓ | adaptive abort cuts wasted volume 52/45/20% at matched infidelity, 3/3 regimes | 5400 / 9 s | cfc1d43d | check-order co-optimization + per-round thresholds |
| 06 | Lattice-surgery routing autopsy | UNRESOLVED (Pareto phys) | G1✓ G2✓ G2p✗ G3✓ G4✓ | G1 15/15 (deficit closed); makespan 3/3, phys strict 3/3 but 2SE 0/3; ti3 40-op unknown/timeout | 3600 / 158 s | b8b625b2 | joint-cost lookahead + 60-op probe @120 s |
| 07 | AutoCCZ + buffer scheduling | PURSUE | G1✓ G2✓ G3✓ G4✓ | dynamic buffer wins 3/3 regimes (vol + stalls, same arm B); DFS cap-hit | 2745 / 87 s | e2640228 | burst-heavier fronts + wider ready window |
| 08 | Transversal entangling scheduling | PURSUE | G1✓ G2✓ G3✓ G4✓ | aligned packing cuts latency ~4–6x (5.6 vs 24.0 … 9.8 vs 56.0), 100% valid | 5400 / 0.3 s | cfc1d43d | logical-remapping co-optimization + multi-shift gates |
| 09 | Defect-tolerant patch routing | PURSUE | G1✓ G2✓ G3✓ G4✓ | irregular routing recovers ~4–6x volume at kept d_eff, 3/3 sizes | 5400 / 2 s | cfc1d43d | wider gauge-fixing moves + correlated-defect masks |
| 10 | AOD vs OLSQA | BLOCKED (corpus) | — | no OLSQA paper; OLSQ-DPQA lacks 40/60 rows + movement metrics; re-verified 2026-10-31 | 0 (no slot) | — | freeze OLSQA 20/40/60 tables w/ provenance+SHA-256, else stays BLOCKED |
| 11 | QCCD shuttling scheduler | PURSUE | G1✓ G2✓ G3✓ G4✓ | heating-aware cuts infidelity ~2x (0.110 vs 0.260 …), A<G<S | 5400 / 5 s | cfc1d43d | sympathetic-cooling placement + correlated heating noise |
| 12 | Mid-circuit reuse | PURSUE | G1✓ G2✓ G3✓ G4✓ | routing-aware reuse wins 3/3 widths on CNOTs + depth at fixed width | 5400 / 75 s | 47e2ef20 | live-range-split cone-block + depth-regularized annealing |
| 13 | Crosstalk-aware coloring | PURSUE | G1✓ G2✓ G3✓ G4✓ | interior optimum beats both extremes 3/3 (0.9418 vs 0.9232 …) | 5400 / 24 s | a424e539 | frequency-aware placement + correlated crosstalk noise |
| 14 | Multi-QPU teleportation | PURSUE | G1✓ G2✓ G3✓ G4✓ | lookahead cuts cost ~40–55% (52.9 vs 84.2 …), A<G<M | 5400 / 8 s | a424e539 | adaptive EPR buffering + distillation retries |
| 15 | ZX spider-fusion + gflow | UNRESOLVED | G1✗ G2✗ G3✓ G4✗ | F never beats R; 11/45 arm-blocked; exact solves everywhere in caps | 5400 / 192 s | 8ce03c2f | 12q depth-6 DFS cap-hit regime (20k nodes/~125 s probe) |
| 16 | Pauli-propagation truncation | UNRESOLVED | G1✗ G2✗ G3✓ G4✓ | adaptive never beats static at matched budget (joint 0/3); depth-6 lossless | 5400 / 270 s | a424e539 | weight-aware damping + multi-observable transfer |
| 17 | Circuit-knitting cuts | PURSUE | G1✓ G2✓ G3✓ G4✓ | pre-cut rewrites cut γ² below static cuts (log gaps 21–25 nats), 3/3 | 5400 / 9 s | a424e539 | richer Clifford rewrites + depth-regularized annealing |
| 18 | Phase-polynomial pilot | INFRA ONLY — ok | G1✓ G2✓ G3— G4✓ | pilot ok, proof chain ok; never a verdict | 1200 / ~5 s | each run | n/a (infrastructure) |
| 19 | Clifford tableau synthesis | PURSUE | G1✓ G2✓ G3✓ G4✓ | search beats routed decomposition (38.4 vs 63.2 …), SAT out at n≥12 | 5400 / 85 s | 47e2ef20 | gate-reordering synthesis + depth-regularized annealing |
| 20 | Photonic fusion routing | REJECT on this screen | G1✓ G2✓ G3✓ G4✓ | adaptive wins 0/3; yields →0 at N=64 (finite pool starves) | 5400 / 70 s | f5ac1866 | reopen only with replenishment (§7.4) |
| 21 | BDD variable-ordering | PURSUE | G1✓ G2✓ G2s✓ G3✓ G4✓ | reordered trees cut routed CNOT 14–42% (60.4 vs 104.6 …) | 5400 / 7 s | a424e539 | adaptive ordering + depth-regularized annealing |
| 22 | Bosonic stabilization | PURSUE | G1✓ G2✓ G3✓ G4✓ | discrete sequences beat SNAP-echo 30–45%, zero boundary artifacts | 5400 / 18 s | 8d95d5ea | closed-loop adaptive SNAP + Kerr-regularized annealing |
| 23 | Adaptive QPE | UNRESOLVED | G1✗ G2✓ G3✓ G4✓ | depth-2 lookahead ≡ 1-step greedy (zero effect, sensitive instrument) | 5400 / 8 s | 8d95d5ea | depth-3 sparse lookahead + learned rollout, stronger T2 |
| 24 | Ternary-tree fermion mapping | PURSUE | G1✓ G2✓ G3✓ G4✓ | tree search survives synthesis+routing at 2 sizes (636.9 vs 779.3 …) | 5400 / 60 s | 47e2ef20 | parity-reuse baselines + wider rotation neighborhoods |

Debits read "reservation CPU-s / supervised wall s" (actual wait4 CPU ≈
wall for these single-threaded payloads; 07 reservation 2744.9 and 01
3590.2 reflect admitted-window scaling, not the 5400 class max).

## 2. Standing answers disposition

- `02 PURSUE` extended beyond d=3 via §7.2 only — DONE under
  supervision (d=7 transfer win, gradient + cap-hit evidence). No
  threshold/depth claim (never measured).
- `20/04 REJECT` — regimes unchanged; no guarded reopen launched.
- `01/06 HOLD` — resolved as UNRESOLVED with terminal autopsy
  evidence (01: convergence-budget mechanism confirmed + CBC
  solver-sufficiency thru d11; 06: G1 fixed + real z3 timeout, Pareto
  blocked on phys significance). Both keep their frozen next
  experiments; neither is pursue-or-reject on current evidence.
- RL training recommendation: **NO**. No screen meets the §1.4 bar
  (all 4 gates on physical end-to-end metrics at ≥2 sizes with
  independent checkable evidence *for an RL-training claim*):
  winners are greedy/annealing/search, annealing improves on greedy
  only at 11/14, and no screen compares a trained policy against
  these certified search baselines. Pursue verdicts fund their
  stated next experiments, not RL training.
- Full-engine independent-review blocker: out of screening scope —
  kept separate from these results (no full-engine build was
  attempted in this loop).

## 3. Final report

### What fit per run

| Run | Classified here | CPU used / 28800 | Outcome |
|---|---|---|---|
| f5ac1866 (LOOP 3) | 18 INFRA, 02 PURSUE(d3), 20/04 REJECT, 01/06 UNRESOLVED | 24000 (stranded 4800 < 5400 min — loop correctly stopped) | sealed, expired 2026-10-29 23:15 PDT |
| 52491511 | — (stillborn: prepare-a01 resource_killed on memory dip) | 1200 stranded | sealed |
| e2640228 (N+1) | 07 PURSUE; 12 staged+carried (window expired) | 5145 | sealed |
| 47e2ef20 (N+2) | 12/19/24 PURSUE; 03 staged+carried | 15462 | sealed |
| cfc1d43d (N+3) | 03 UNRESOLVED, 05/08/09/11 PURSUE | 28800 (exact) | sealed (budget-exhausted; 13 carried) |
| a424e539 (N+4) | 13/14/17/21 PURSUE, 16 UNRESOLVED | 28800 (exact) | sealed (budget-exhausted; 22 carried) |
| 8d95d5ea (N+5) | 22 PURSUE, 23 UNRESOLVED; 15 fix landed, window expired | 13200 | sealed |
| 8ce03c2f (tail) | 15 UNRESOLVED; 02 staged+reviewed, run expired in pause | 7800 | sealed (deadline-expiry during pause) |
| b8b625b2 (tail) | 02 PURSUE(d7), 01/06 UNRESOLVED, 10 BLOCKED recorded | 14990 | this run (sealed below) |

Portfolio drained: 24/24 paths terminal. Queued/deferred: none.
Blocked: 10 (named corpus blocker). Guarded reopens (20/04) not
triggered — regimes unchanged.

### Resource debits

Total reserved across 9 envelopes: 24000+1200+5145+15462+28800+
28800+13200+7800+14990 = **146,397 CPU-s** (~40.7 CPU-h capacity)
against 9×28800 = 259,200 budgeted. Payload actuals are 1–2 orders
of magnitude below reservations (longest supervised wall: 16-a01
270 s against 5400 reserved). Stranded remainders: 4800 (f5ac1866),
1200 (52491511), and per-run unused balances — all by rule (no
budget extension after a negative, no reuse of expired runs).

### Host-gate incidents

- f5ac1866: battery halt (80%→63%) + 3.8 GiB memory block (prior loop).
- 52491511: stillborn on memory dip (4.17 probe → sub-4.0 mid-run
  kill); lesson recorded — require 3 consecutive ≥4.3 GiB probes.
- e2640228: memory jitter gate before init (waited, cleared).
- 8ce03c2f: AC-power gate blocked select at pause (80%,
  discharging); deadline passed overnight → sealed expired.
- b8b625b2: sustained host load 22–27 during 06 staging/dry-runs
  (user batch jobs); payloads held zero skips; supervised walls
  nominal (02: 198 s, 01: 38 s, 06: 158 s).
- No protected user process was ever signaled.

### Review history (attempt counts per screen, launching run)

- 1/2 clean PASS: 07, 12, 13, 14, 16, 17, 19, 21, 22, 24 (1/2 or
  clean first-PASS per run records), 02 scale-up (b8b625b2), 06
  (b8b625b2), 01/20 (f5ac1866).
- 2/2 REVISE→PASS: 02 d=3, 04 (f5ac1866); 03, 05, 08, 09, 11
  (cfc1d43d); 01 (b8b625b2); tooling b8b625b2.
- 15: FAIL,FAIL in f5ac1866 (deferred); REVISE+fix in 8d95d5ea;
  PASS in 8ce03c2f (fresh budget).
- 23: PASS 1/2 (8d95d5ea). Postpilot/tooling: PASS every run
  (tooling 2/2 once, b8b625b2).
- No screen exceeded 2 attempts per run; no reviewer fallback ever
  used (Wonder max throughout; TARGETS exact).

### Reproduction

`sh screens/<id>/run.sh` reproduces a supervised attempt ONLY with a
filed PASS receipt matching the exact `screen_files` SHA-256 in a
live envelope; modified sources are rejected until re-reviewed.
Evidence: `overnight-data/<run>/attempts/<screen>-<uuid>/`
(`execution.json`, `worker-result.json`, `receipt.json`,
`stdout.log`, `work/results.json`); archives in
`verify-evidence/<run>/`.

*Synthesis generated from supervised evidence 2026-10-31. Next
operator: the portfolio is terminal; any new work is a new loop
(new envelope, new reviews) driven by the frozen next experiments
above.*
