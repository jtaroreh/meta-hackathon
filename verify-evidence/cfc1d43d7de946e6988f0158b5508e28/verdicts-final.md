# Coordinator verdicts — run cfc1d43d (relay Run N+3)

Run: `cfc1d43d7de946e6988f0158b5508e28` (created 2026-10-30 ~06:46 PDT,
deadline ~14:46 PDT). Bootstrap: capabilities + tooling PASS (Wonder) +
prepare finished + pilot 18 finished + postpilot PASS. Classifications
derive from supervised receipts and `work/results.json` only.

Operating rule (proven): select → review → first launch must land inside
~890 s of select (launch admits only `min(900 − screen_wall_used, …) >
8.5 s` with the live select clock; repeat select never resets).

## 03 Floquet schedule optimization — UNRESOLVED

Attempt `03-a01` (finished exit 0, cleanup verified, wall ~2.7 s).

Gate vector: G1 ✗ G2 ✗ G3 ✓ G4 ✓.

- G1: pooled mean distance(G) == pooled mean distance(R) in all 9
  (size, defect) cells (2.0/1.4/1.0 pinned by defect count at every
  size); tiny hand-bound ok; witness re-verification ok; determinism
  repeat identical. Pipeline not discriminative on distance.
- G2: pooled {H,G,S} distance spread 0.0 in all 9 cells (0/9 pass,
  0 sizes) — no schedule gradient anywhere.
- G3: bounded-exact BFS solves tiny (optimum d=2, 1956 nodes,
  witness re-verified); 20-qubit target cap-hits at 50001/50000
  nodes, zero leaf evals. Solver started, tiny solved, solver's own
  cap-hit.
- G4: 45/45 cells x 4 arms complete (180 arm records, all with
  iters_done/n_evaluated), tiny + target records present, wall
  2.59 s < 500 s, zero skip records. Self-tests clean.
- Joint Pareto: no arm wins — H==G==R==S distance at every cell;
  G's exhaustive single-swap sweep found zero improving moves, so H
  is locally optimal everywhere. Depth responds to order (G cuts
  8-qubit cycle depth 36 -> 12) but distance does not: permutation
  relabels detector coordinates, leaving the detecting region
  invariant in this fault model.

Classification: PURSUE requires G1+G2 pass + joint wins (absent);
REJECT requires G1 controls pass (failed — G==R everywhere). Else
branch: UNRESOLVED + next experiment.

Decisive evidence: premise fails — detecting-region distance is
schedule-invariant in the modeled fault/schedule class, so no
schedule mutation can beat static cyclic on distance.

Next experiment (frozen): defect-aware check-type recoloring +
per-round schedule variation retest.

## 05 Magic-state cultivation schedules — PURSUE

Attempt `05-a01` (finished exit 0, cleanup verified, wall ~9.2 s).

Gate vector: G1 ✓ G2 ✓ G3 ✓ G4 ✓.

- G1: pooled mean W(G) strictly below pooled mean W(R) in all 9
  (stage, rate) cells; tiny hand-bound (L1 = 72, 0 w1 accepted);
  determinism repeat identical.
- G2: pooled W spread > 2×SE in 9/9 cells spanning 3/3 stages.
- G3: bounded-exact joint search solves tiny (optimum W = 7.22,
  1956 nodes); 12-qubit target cap-hits at 50001/50000 nodes.
  Solver started, tiny solved, solver's own cap-hit.
- G4: 45/45 cells x 4 arms complete (180 arm records), tiny +
  target records present, wall 9.05 s < 500 s, zero skip records.
  Self-tests clean.
- Joint Pareto: arm G jointly wins 3/3 noise regimes — pooled W
  beats F by 52%/45%/20% relative (0.001: 80.6 vs 167.6; 0.002:
  257.2 vs 470.2; 0.005: 3123.6 vs 3886.1) with pooled infidelity
  exactly matched to F on the SAME arm (identical means at all
  rates). (Arm A jointly wins at 2/3 rates, failing the infidelity
  match at p=0.005 as coded; winner prefers G per the frozen rule.)

Decisive evidence: adaptive abort cuts wasted spacetime volume by
>=20% relative at matched output infidelity across all three noise
regimes with all gates evidenced and exact-search cap-hit at
target scale.

Next experiment (frozen): check-order co-optimization + per-round
threshold variation retest.

## 08 Transversal entangling-gate scheduling — PURSUE

Attempt `08-a01` (finished exit 0, cleanup verified, wall ~0.3 s).

Gate vector: G1 ✓ G2 ✓ G3 ✓ G4 ✓.

- G1: mean latency(G) strictly below mean latency(R) in all 30
  (code, DAG, seed) cells; tiny hand-check (Q=6, G=4, A=4);
  determinism repeat identical.
- G2: pooled latency spread > 2×SE at 3/3 DAGs (S: spread 18.4
  vs SE 0.33; M: 32.0 vs 0.54; L: 46.2 vs 0.57).
- G3: bounded-exact layer-packing search solves tiny (optimum 2
  layers == hand value, 5 nodes); C12/L/seed-1 target cap-hits at
  50001/50000 nodes. Solver started, tiny solved, solver's own
  cap-hit.
- G4: 30/30 cells x 4 arms complete (120 arm records), tiny +
  target records present, wall 0.14 s < 500 s, zero skip records.
  Self-tests clean.
- Joint Pareto: arm G jointly wins 3/3 DAGs — pooled latency
  beats Q by > 2×SE (S: 5.6 vs 24.0; M: 8.0 vs 40.0; L: 9.8 vs
  56.0) with all 10 (code, seed) schedules verifying valid on the
  SAME arm. (Arm A also jointly wins 3/3 with identical means —
  annealing from G found no improving proposal; winner prefers G
  per the frozen rule.)

Decisive evidence: parallel automorphism-aligned packing cuts
syndrome-round latency ~4-6x over serialized addressing at all
three DAG sizes with all gates evidenced and exact-search cap-hit
at target scale.

Next experiment (frozen): logical-remapping co-optimization +
multi-shift gate retest.

## 09 Defect-tolerant patch routing — PURSUE

Attempt `09-a01` (finished exit 0, cleanup verified, wall ~1.7 s).

Gate vector: G1 ✓ G2 ✓ G3 ✓ G4 ✓.

- G1: mean volume(G) strictly below mean volume(R) in all 30
  (size, rate, seed) cells; tiny hand-check (B=18/d2, G=6/d2,
  A invariants); determinism repeat identical.
- G2: pooled volume spread > 2×SE at 3/3 sizes (7: spread 179.4
  vs SE 18.8; 9: 225.4 vs 38.4; 11: 354.7 vs 48.0). G2s distance
  spread 0/3 informational (floor pins distances equal, as
  designed).
- G3: bounded-exact subset search solves tiny (optimum 6 == hand
  value, 511 nodes); 9x9/4%/seed-1 target cap-hits at 50001/50000
  nodes. Solver started, tiny solved, solver's own cap-hit.
- G4: 30/30 cells x 4 arms complete (120 arm records, all valid
  patches), tiny + target records present, wall 1.62 s < 500 s,
  zero skip records. Self-tests clean.
- Joint Pareto: arm G jointly wins 3/3 grid sizes — pooled volume
  beats B by > 2×SE (7: 57.9 vs 237.3; 9: 43.8 vs 269.2; 11:
  64.5 vs 419.2) with pooled distance matched-or-better on the
  SAME arm. (Arm A also jointly wins 3/3 with identical means —
  annealing never improved greedy; winner prefers G per the
  frozen rule.)

Decisive evidence: irregular deformed patch routing recovers
~4-6x spacetime volume over bounding-box exclusion at kept
effective distance across all grid sizes and dropout masks, with
all gates evidenced and exact-search cap-hit at target scale.

Next experiment (frozen): wider gauge-fixing move families +
correlated-defect masks retest.

## 11 QCCD shuttling scheduler — PURSUE

Attempt `11-a01` (finished exit 0, cleanup verified, wall ~5.4 s).

Gate vector: G1 ✓ G2 ✓ G3 ✓ G4 ✓.

- G1: mean infidelity(G) strictly below mean infidelity(R) in all
  45 (size, circuit, seed) cells; tiny hand-check (S/G exact, A
  invariants, R valid); determinism repeat identical.
- G2: pooled infidelity spread > 2×SE at 3/3 sizes (3: spread
  0.159 vs SE 0.013; 4: 0.137 vs 0.021; 5: 0.166 vs 0.024).
- G3: bounded-exact routing search solves tiny (optimum 0.003 ==
  hand value, 13 nodes); 5x5/ring/seed-1 target cap-hits at
  50001/50000 nodes. Solver started, tiny solved, solver's own
  cap-hit.
- G4: 45/45 cells x 4 arms complete (180 arm records, all valid
  schedules), tiny + target records present, wall 5.24 s < 500 s,
  zero skip records. Self-tests clean (incl. displacement /
  co-location regression).
- Joint Pareto: arm G jointly wins 3/3 trap sizes — pooled
  infidelity beats S by > 2×SE (3: 0.110 vs 0.260; 4: 0.131 vs
  0.252; 5: 0.145 vs 0.300) with pooled validity matched-or-better
  on the SAME arm. (Arm A also jointly wins 3/3 with strictly
  better means than G at every size — 0.101/0.115/0.134 —
  annealing improves on greedy here; winner prefers G per the
  frozen rule.)

Decisive evidence: heating-aware scheduling cuts estimated
circuit infidelity ~2x over swap-count-only routing at all trap
sizes with all gates evidenced and exact-search cap-hit at target
scale.

Next experiment (frozen): sympathetic-cooling ion placement
co-optimization + correlated heating-noise retest.

## Carried (settled in prior runs — not re-run here)

- 18 Phase-polynomial pilot: INFRA ONLY — ok (f5ac1866).
- 02 Flag-gadget schedule search: PURSUE, d=3-bounded (f5ac1866).
- 20 Photonic fusion routing: REJECT on this screen (f5ac1866).
- 04 Erasure + biased hybrid: REJECT on this screen (f5ac1866).
- 01 qLDPC BP-guiding: UNRESOLVED, tail follow-up (f5ac1866).
- 06 Lattice-surgery routing: UNRESOLVED, tail autopsy (f5ac1866).
- 10 AOD vs OLSQA: BLOCKED (no freezable 20/40/60 tables in-metric).
- 15 ZX spider-fusion + gflow: DEFERRED, staged d1970c84 (tail relay).
- 07 AutoCCZ + buffer scheduling: PURSUE (run e2640228).
- 12 Mid-circuit reuse: PURSUE (run 47e2ef20).
- 19 Clifford tableau synthesis: PURSUE (run 47e2ef20).
- 24 Fermion-to-qubit ternary-tree mapping: PURSUE (run 47e2ef20).
- 03 staging: carried from run 47e2ef20 (staged, select-window
  expired there); reviewed + launched + classified here.

## Queued (clocks untouched)

Second wave: 13, 14, 16, 17, 21, 22, 23;
tail 15, 02 scale-up, 01, 06 (+10 if corpus frozen).
