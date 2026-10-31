# Coordinator verdicts — run 8ce03c2f (tail relay)

Bootstrap: capabilities 3/3 + tooling PASS (Wonder, 1/2) + prepare-a01
finished + pilot 18-a01 finished + postpilot PASS (Wonder, 1/2).
Bindings: input 0ebe0adecc95c510, prep 3dd3ca33d75321db, pilot
ba5573301e7b7bff.

Run 8d95d5ea closed: CPU 13200/28800 reserved; 22 PURSUE, 23 UNRESOLVED.
Screen 15 carried with clock untouched (select window expired before
attempt-2 review); reviewed + launched + classified here.

## 15 ZX spider-fusion + gflow — UNRESOLVED

Attempt `15-a01` (finished exit 0, cleanup verified, wall ~192 s).

Gate vector: G1 ✗ G2 ✗ G2t ✗ G3 ✓ G4 ✗.

- G1: FAIL — F does not strictly beat R in every cell (R wins
  e.g. 8/1: F 24.67 vs R 17.15; 8/3: F 29.67 vs R 21.52).
- G2/G2t: FAIL — pooled spread null at all sizes: 11/45
  instances arm-blocked (extraction failures on B/C finals and
  R rollouts), so complete pooled cells cannot form (n=11-12
  of 15) and spread is conservatively null.
- G3: PASS — tiny 4/4 solved with optima; both Q=8 targets
  solved within caps (606 nodes/opt 11; 3536 nodes/opt 19;
  0 cap-hits; terminals extracted within the 8000 cap).
  Solver started, tiny solved, optima non-vacuous.
- G4: FAIL — complete false: 11 honest arm-blocked skip
  records with iters_done/n_evaluated counts (e.g. instance
  10/3/2 iters_done 39 / n_evaluated 45). Wall 191.9 s <
  500 s. Self-tests clean ({'ran': True, 'failed': []}).
- Joint: 0/3 sizes; strict CNOT wins 0/3. Reject condition
  also false (G3 solved, instrument sensitive, blocks are
  genuine search outcomes on untouched beam code).

Decisive evidence: temporary-inflation search does not beat
full_reduce on extracted two-qubit count at any size, and
extraction blocks on 11/45 instances prevent complete pooled
cells — while exact solving succeeds everywhere within caps.
UNRESOLVED (hardness boundary not reached within caps), not
REJECT.

Next experiment (frozen): 12q depth-6 DFS cap-hit regime
(probed 20k nodes / ~125 s on 12q seed-2, beyond this screen's
300 s wall-guard budget).

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

## Queued (clocks untouched)

Tail: 02 scale-up, 01, 06 (+10 if corpus frozen).
