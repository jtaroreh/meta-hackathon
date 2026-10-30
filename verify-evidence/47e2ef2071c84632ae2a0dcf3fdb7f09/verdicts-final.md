# Coordinator verdicts — run 47e2ef20 (relay Run N+2)

Run: `47e2ef2071c84632ae2a0dcf3fdb7f09` (created 2026-10-30 ~05:46 PDT,
deadline ~13:46 PDT). Bootstrap: capabilities + tooling PASS (Wonder) +
prepare finished + pilot 18 finished + postpilot PASS. Classifications
derive from supervised receipts and `work/results.json` only.

Operating rule (proven): select → review → first launch must land inside
~890 s of select (launch admits only `min(900 − screen_wall_used, …) >
8.5 s` with the live select clock; repeat select never resets).

## 12 Mid-circuit reuse — PURSUE

Attempt `12-a01` (finished exit 0, cleanup verified, wall 74.7 s,
reservation 5400 CPU-capacity s vs 73.8 wait4 CPU s).

Gate vector: G1 ✓ G2 ✓ G3 ✓ G4 ✓.

- G1: mean CNOTs(G) strictly below mean CNOTs(R) in all 15
  (family, seed) cells (gaps ~200/300/370 CNOTs on 24/32/40 wires);
  tiny hand-check 6/6; determinism repeat identical.
- G2: pooled {G,B,A} CNOT spread > 2×SE at 3/3 wire counts
  (spreads 120.6/149.1/186.5 vs SE 3.16/5.46/3.61).
- G3: bounded-exact DFS solves tiny (optimum 2 == hand value, 256
  nodes); target-scale instance (24-wire, seed 1 rep 0) cap-hits at
  50001/50000 nodes. Solver started, tiny solved, solver's own cap-hit.
- G4: 60/60 cell-arms complete (36 reps each), tiny + target records
  present, wall 74.5 s < 500 s, zero skip records.
- Joint Pareto: arm B jointly wins 3/3 wire counts — pooled routed
  CNOTs beat G by > 2×SE (24: 890.8 vs 939.3; 32: 1198.8 vs 1236.4;
  40-wire family likewise per results.json) with depth no-regress on
  the SAME arm. (Arm A also jointly passes; winner prefers B per the
  frozen rule. Evictions costed +6 CNOTs/+2 depth, never free.)

Decisive evidence: joint routing-aware reuse wins at 3/3 wire counts
with all gates evidenced and exact-solver cap-hit at target scale.

Next experiment (frozen): live-range-split cone-block families with
wider beam, then a depth-regularized annealing retest.

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
- 12 staging: carried from run e2640228 (staged, select-window expired
  there); reviewed + launched + classified here.

## 19 Clifford tableau synthesis — PURSUE

Attempt `19-a01` (finished exit 0, cleanup verified, wall ~85.1 s).

Gate vector: G1 ✓ G2 ✓ G3 ✓ G4 ✓.

- G1: mean CNOTs(G) strictly below mean CNOTs(R) in all 15
  (size, seed) cells (gaps ~90/185/270 on n=8/12/16); tiny
  hand-check 2/2; determinism repeat identical.
- G2: pooled CNOT spread > 2×SE at 3/3 sizes
  (spreads 24.8/28.8/34.2 vs SE 0.11/0.33/0.26); depth spread 3/3.
- G3: bounded-exact B&B solves tiny (optimum 1 == hand value,
  5 nodes); n=16 target cap-hits at 50001/50000 nodes. Solver
  started, tiny solved, solver's own cap-hit.
- G4: 60/60 cell-arms complete (1300 reps each), tiny + target
  records present, wall 85.1 s < 500 s, zero skip records.
- Joint Pareto: arm G jointly wins 3/3 sizes — pooled CNOTs beat D
  by > 2×SE (8: 38.4 vs 63.2; 12: 74.9 vs 103.7; 16: 109.4 vs
  143.6) with pooled depth no-regress on the SAME arm
  (8: 23.5 vs 33.6; 12/16 likewise per gate2_s). (Arm A also
  jointly passes; winner prefers G per the frozen rule.)

Decisive evidence: joint topology-native search wins at 3/3 sizes
with all gates evidenced and exact search timeout at n=16.

Next experiment (frozen): explicit gate-reordering synthesis
families with look-ahead, then a depth-regularized annealing retest.

## 24 Fermion-to-qubit ternary-tree mapping — PURSUE

Attempt `24-a01` (finished exit 0, cleanup verified, wall ~60 s).

Gate vector: G1 ✓ G2 ✓ G3 ✓ G4 ✓.

- G1: mean CNOTs(G) strictly below mean CNOTs(R) in all 15
  (size, seed) cells; tiny hand-check (40 CNOTs / depth 42,
  independently arithmetically derived); determinism identical.
- G2: pooled CNOT-weight spread > 2×SE at 3/3 sizes
  (12: spread 1125.9 vs SE 3.27; 16/20 likewise).
- G3: bounded-exact B&B solves tiny (optimum 22 == hand value,
  65 nodes); 20-orbital target cap-hits at 50001/50000 nodes.
  Solver started, tiny solved, solver's own cap-hit.
- G4: 90/90 cell-arms complete, tiny + target records present,
  wall 60.0 s < 500 s, zero skip records.
- Joint Pareto: arm G jointly wins at 2/3 sizes (12, 16) — pooled
  routed weight beats ALL of {J,K,T} by > 2×SE on the same arm
  with depth no-regress (12: G 636.9 vs T 779.3 vs J 1215.0 vs
  K 1762.7; 16 likewise per results.json; 20: no win). (Arm A
  also jointly passes at 12/16; winner prefers G.)

Decisive evidence: joint tree-search mappings survive full
Pauli-network synthesis + routing at two molecular sizes with all
gates evidenced and exact search timeout at 20 orbitals.

Next experiment (frozen): parity-reuse baselines + wider rotation
neighborhoods, then a depth-regularized annealing retest.

## Queued (clocks untouched)

Second wave: 03, 05, 08, 09, 11, 13, 14, 16, 17, 21, 22, 23;
tail 15, 02 scale-up, 01, 06 (+10 if corpus frozen).
