# Coordinator verdicts — run b8b625b2 (tail relay)

Bootstrap: capabilities 3/3 + tooling PASS (Wonder, 2/2) + prepare-a01
finished + pilot 18-a01 finished + postpilot PASS (Wonder, 1/2).
Bindings: input c9fcadda961ac05b, prep a18895c7410aa5bb, pilot
15b9599fc4f2e810.

Run 8ce03c2f closed: CPU 7800/28800 reserved; 15 UNRESOLVED.
Screen 02 scale-up carried with clock untouched (staged 06baea7; review
attempt-1 PASS in 8ce03c2f lapsed with that run's expiry — informational
only; fresh review + launch here).

## Carried (settled in prior runs — not re-run here)

- 01 Surface-code cultivation: UNRESOLVED, tail autopsy (f5ac1866).
- 02 LDPC surgery compilation: PURSUE at d=3 (f5ac1866); scale-up queued.
- 04 QLDPC surgery scheduling: REJECT (f5ac1866).
- 20 Surface-code MLD: REJECT (f5ac1866).
- 06 Lattice-surgery routing: UNRESOLVED, tail autopsy (f5ac1866).
- 10 AOD vs OLSQA: BLOCKED (no freezable 20/40/60 tables in-metric).
- 07 AutoCCZ + buffer scheduling: PURSUE (run e2640228).
- 12 Mid-circuit reuse: PURSUE (run 47e2ef20).
- 19 Clifford tableau synthesis: PURSUE (run 47e2ef20).
- 24 Fermion-to-qubit ternary-tree mapping: PURSUE (run 47e2ef20).
- 03 Floquet schedule optimization: UNRESOLVED (run cfc1d43d).
- 05 Magic-state cultivation schedules: PURSUE (run cfc1d43d).
- 08 Transversal entangling-gate scheduling: PURSUE (run cfc1d43d).
- 09 Defect-tolerant patch routing: PURSUE (run cfc1d43d).
- 11 QCCD shuttling scheduler: PURSUE (run cfc1d43d).
- 13 Crosstalk-aware gate coloring: PURSUE (run a424e539).
- 14 Multi-QPU teleportation scheduling: PURSUE (run a424e539).
- 16 Pauli-propagation truncation: UNRESOLVED (run a424e539).
- 17 Circuit-knitting cuts: PURSUE (run a424e539).
- 21 BDD variable-ordering: PURSUE (run a424e539).
- 22 Bosonic stabilization: PURSUE (run 8d95d5ea).
- 23 Adaptive QPE: UNRESOLVED (run 8d95d5ea).
- 15 ZX spider-fusion + gflow: UNRESOLVED (run 8ce03c2f; 15-a01, 192 s,
  G1/G2/G4 fail on 11 honest arm-blocked records, G3 solved, joint 0/3).

## 02 LDPC surgery compilation scale-up — PURSUE (extended to d=7)

Attempt `02-a01` (finished exit 0, cleanup verified, wall ~198 s).
Carried staging 06baea7; review attempt-1 PASS (Wonder, 1/2) in this run.

Gate vector: G1 ✓ G2 ✓ G3 ✓ G4 ✓.

- G1: PASS — d=3 anchor reproduced exactly (canonical 120/16 vs exact
  72/8 at d_eff=3, greedy 4/5 seeds, random valid fraction 0.0067);
  canonical valid at d=3/5/7; exact valid.
- G2: PASS — strict canonical LER gradient at all sizes (d=3
  0.0255<0.0637<0.1167; d=5 0.0452<0.1064<0.1900; d=7
  0.0686<0.1515<0.2559; 20k shots/point); transfer-best LER tracks
  canonical at every size (e.g. d=3 0.0268/0.0630/0.1111).
- G3: PASS — exact solves d=3 256/256 (best 72/8); d=5-class
  enumeration cap-hits cleanly at 150/150 (no skip, no stop).
- G4: PASS — complete: 51/51 cells present, zero skips, wall 198 s <
  500 s. Self-tests clean.
- Joint (§7.2): transfer (d=3 exact-optimum pattern lifted) wins at
  all three sizes with preserved d_eff: d=3 72/8 vs 120/16 (40% CNOT
  cut, half the ancillas), d=5 240/24 vs 384/48 (37.5% cut), d=7
  504/48 vs 792/96 (36% cut). Greedy independently confirms d=7
  504/48 at 5/5 seeds. No threshold/depth claim (never measured).

Decisive evidence: the overhead win survives larger distances — a
valid d_eff=7 schedule preserves a 36% CNOT advantage with gradient
plus d=5-class cap-hit evidence. 02 PURSUE extends beyond d=3 per
§7.2 (d=3/d=5/d=7 transfer win, LER tracks canonical throughout).

Next experiment (frozen): d=9 transfer + threshold measurement (does
the lifted pattern hold at d=9, and does the overhead cut move the
threshold at fixed distance?).

## 01 qLDPC BP-guiding follow-up — UNRESOLVED (solver-sufficiency attested)

Attempt `01-a01` (finished exit 0, cleanup verified, wall ~38 s).
Re-staged 64a9c12 + coordinator REVISE fix 7705902; review PASS
(Wonder, 2/2) in this run.

Gate vector: G1 ✓ G2 ✓ G3 ✗ G4 ✓.

- G1: PASS — arm A strictly beats R in all 25 pheno cells.
- G2: PASS — non-flat pooled spread >2xSE at ≥2 sizes (5 sizes
  measured: fail_A 0.097→0.813 strictly increasing).
- G3: FAIL (honest) — d3 MLD Optimal (0.07 s); all 28 frontier
  instances Optimal (d7x12 max 0.053 s, d9x8 max 0.075 s, d11x8
  max 0.066 s), zero TimeLimit. CBC demolishes everything through
  d11 (n=221): solver-sufficiency attested at these scales per §6.1.
- G4: PASS — complete: 210/210 cells (150 pheno + 60 circuit),
  zero skips, wall 38 s < 500 s. Self-tests clean (incl. both
  repair-path regression probes).
- Autopsy (§6.1a): mechanism SUPPORTED — boosted serial B3
  (serial/1.25) recovers +44%/+40%/+34%/+30% of the BP→BP-OSD gap
  at d3/d5/d7/d9 (same arm, per-arm counting holds at 4 sizes;
  d11 +19%), while B1 ≈ 0 and B2 stays weak-positive. Pooled
  circuit gap >0 at both sizes (d3, d5).

Decisive evidence: the convergence-budget mechanism is confirmed
(boosting recovers what damping lost), but Gate 3 has no
limit-expiry — CBC solves d11 MLD in milliseconds. PURSUE needs
real expiry; REJECT needs <25% recovery everywhere (falsified).
UNRESOLVED with solver-sufficiency attestation.

Next experiment (frozen): Sweep max_iter over {30,100,300} for the
winning B family at the two largest pheno sizes to separate
convergence-budget effects from schedule effects, holding all other
frozen symbols unchanged.

## 06 Lattice-surgery routing autopsy — UNRESOLVED (Pareto still blocked on phys significance)

Attempt `06-a01` (finished exit 0, cleanup verified, wall ~158 s).
Re-staged d80fa27; review attempt-1 PASS (Wonder, 1/2) in this run.

Gate vector: G1 ✓ G2 ✓ G2p ✗ G3 ✓ G4 ✓.

- G1: PASS — 15/15 (deficit closed: new joint-greedy A beats R by
  1.2–2.2 makespan units in every cell, e.g. 10/1 12.29 vs 14.25;
  prior fails were R-by-0.17–1.41 at 10/20).
- G2: PASS — 3/3 makespan spread significant (e.g. size 10 spread
  2.34 > 2SE 0.21).
- G2p: FAIL — 0/3 phys spread significant (size 10 spread 0.248 vs
  2SE 0.608; size 20 0.088 vs 0.683; size 30 0.080 vs 0.644).
  The phys leg is contestable now (pools 62.74/62.83/62.58, no
  longer a structural floor) but not significant.
- G3: PASS — tiny 4/4 sat/unsat pairs (T* sat + T*-1 unsat,
  verbatim); targets ti0–ti2 sat (0.07–0.61 s); ti3 40-op scale
  probe at T=23 yields solver's-own unknown/timeout (23.8 s vs
  20 s limit) alongside a sat solve — real limit-expiry.
- G4: PASS — complete: 60/60 cells with both metrics, zero skips,
  wall 157 s < 500 s. Self-tests 11/11.
- Joint: makespan wins 3/3 (strict 3/3); phys strict 3/3 but 2SE
  wins 0/3. PURSUE needs both legs at ≥2 sizes + G2p — not met.
  REJECT needs zero strict wins anywhere — falsified (strict wins
  on both metrics). Autopsy finding stands as evidence: route-0
  pile-up was the G1 driver (order/orientation fix closes it);
  joint pricing lifts arms off the phys floor but not past 2SE.

Decisive evidence: the reformulation fixes Gate 1 completely and
reaches a real z3 timeout, yet physical-cost wins stay below
significance at all sizes — the Pareto remains blocked on the
phys leg. UNRESOLVED.

Next experiment (frozen): joint-cost lookahead placement with wider
SA route neighborhoods; escalate z3 scale probe to 60-op stacked
instances with per-solve timeout 120 s.

## Screen 10 — BLOCKED (corpus, resolved without launch)

No OLSQA figure/data corpus exists to freeze: no paper titled
"OLSQA" (exact-term search returns noise only); the plausible
referent OLSQ-DPQA (Tan/Bluvstein/Lukin/Cong, Quantum 2024,
arXiv:2306.03487) Table 1 has no 40/60 rows and no movement-time
metrics, and its figure-only values are not freezable tables with
provenance. Re-verified 2026-10-31: no screens/10 staging, OLSQA
references prose-only. Per §6.3 / f5ac1866 precedent, missing
baselines resolve without launch. 10 stays BLOCKED with this named
blocker; no slot spent.

## Queued (clocks untouched)

None — tail drained. Proceed to Phase 6 synthesis.
