# Screen 08 — Transversal entangling-gate scheduling in reconfigurable qLDPC blocks

Design: screen-authored deterministic transversal-layer scheduler
(stdlib + numpy only; no external solver, decoder, or policy
libraries). Two small block codes (C8: 8 qubits/block, C12: 12
qubits/block, two memory/compute patches each) with frozen cyclic
automorphism generators and frozen valid transversal shift subsets.
Three benchmark DAGs (S: 12 gates, M: 20 gates, L: 28 gates) built as
seeded parallel rounds sharing one transversal shift per round, plus
per-qubit chains and 2 extra forward edges. Each gate carries a
singleton required shift (pair difference mod n, inside the valid
subset by construction). A layer is valid iff all its gates share
the layer shift, touch disjoint physical qubits, and respect DAG
order. Arms schedule every DAG under these frozen conflict rules.
Metric: total syndrome-round latency (layers x ROUNDS_PER_LAYER=2)
plus schedule-validity verification. Writes results.json +
witnesses/ under cwd only. Deterministic given seeds. Verdict field
is always unresolved-with-reason; classification is coordinator-side.

Hypothesis: co-optimizing intra-block automorphism shifts and
cross-block transversal CNOT layers minimizes total syndrome-round
latency for circuits compiled onto reconfigurable qLDPC
memory/compute patches.

Model (screen-authored):
- Codes (frozen): C8 (n=8, valid shifts T={1,2,3}), C12 (n=12, valid
  shifts T={1,3,4}). Cyclic generator i -> i+1 mod n per block.
- DAGs (frozen gate counts): S=12, M=20, L=28 gates; kinds intra
  (block 0/1, seeded 50/50) vs cross-block CNOT (control block 0
  qubit a, target block 1 qubit a+s); rounds group disjoint pairs at
  one shift; deps = per-physical-qubit chains + 2 seeded forward edges.
- Arms (code truth):
- Q: sequential single-gate addressing — one gate per layer at its
  required shift (the decomposed baseline, always valid).
- R: random layer-packing control — seeded random linear extension,
  each gate to a uniformly random feasible layer (existing or new).
- G: greedy layer packing — earliest-fit in canonical topo order AND
  in one seeded random linear extension, best (fewest layers) tracked.
- A: simulated annealing over automorphism-shift + layer assignments
  — fixed A_ITERS=200 proposals (relocate / layer-shift-change with
  eject-reinsert repair, validity-checked, cost = layers) from the G
  solution, best tracked, so A never exceeds G.
- Metric: latency = layers x 2 syndrome rounds/layer + verification
  that every gate's automorphism alignment is legal (checker also
  rejects wrong-shift and order-violating schedules in self-tests).
- Seeds SEEDS = (1, 2, 3, 4, 5); 30 (code, DAG, seed) cells x 4 arms
  (120 arm evaluations; seeds are the replicates).
- Soundness: tiny n=4 hand-checkable cell (3 gates, optimum 2 layers
  / latency 4 by construction: Q gives 3 layers / 6, G and A give 2
  layers / 4) + bounded-exact layer-packing search optimum 2 on tiny
  + determinism (same seed repeated gives identical G and R results).

Controls:
- Gate 1: mean latency(G) strictly below mean latency(R) in every one
  of the 30 (code, DAG, seed) cells (pipeline discriminative) AND tiny
  hand-check (Q==6, G==4, A==4 latencies) AND determinism repeat
  identical. Coded exactly as `beats_all_30 && tiny_ok &&
  determinism_ok`.
- Gate 2: pooled latency spread across {Q,G,A} > 2*SE at >= 2 DAGs
  (pools = up to 10 values per (DAG, arm): 2 codes x 5 seeds).
  Gate 2s (layers, informational, proportional to latency): same rule
  on raw layer counts. Coded exactly as `n_dags_spread_pass >= 2`.
- Gate 3: bounded-exact layer-packing search solves the tiny instance
  (status solved, optimum 2 layers == hand value) AND the target-scale
  instance (C12 code, L DAG, seed 1, 28 gates, node cap 50000) reports
  exactly "cap-hit" (probed 50001 nodes). Only cap-hit counts as
  limit-expiry; a solved, stopped-guard, or skipped-guard target fails
  Gate 3. A wall-kill or missing baseline never counts. If exact search
  cannot reach limit-expiry at this scale, Gate 3 CANNOT pass and the
  screen caps at UNRESOLVED. Coded exactly as `tiny_solved &&
  target_caphit_only`.
- Gate 4: complete (all 30 cells x 4 arms evaluated; tiny + target
  records present) AND payload wall < WALL_LIMIT_S = 500 s AND zero
  skip records. Coded exactly as `complete && wall < 500 && zero
  skips`.

Budgets: wall 900 s, cpu 5400 s (reservation basis; same generous
staging as screens 19/05). Payload keeps wall to seconds via ordering
(self-test, tiny-exact, target exact, corpus by code) plus a
WALL_GUARD_S = 300 s elapsed guard checked before every code, every
cell, every arm, every 32 annealing proposals, and every 512
exact-solver nodes. Each batch publishes its completed count, and
EVERY guard exit appends an explicit skip record with
iters_done/n_evaluated, including tiny/target entry-guard failures
("tiny-exact", "target-exact") and per-cell guard exits, so a
guard-truncated run cannot pass G4 clean. All arms propagate
stopped=True on a mid-arm guard trip (a stopped:False value after a
guard trip fails review). results.json is written at normal
completion; witnesses/selftest.json is written after the self-test,
witnesses/gate3_tiny.json + gate3_targets.json after the exact
phases, witnesses/cells.json after each code, and
witnesses/checkpoint-<tag>.json after tiny, targets, each code, and
the corpus, so a supervisor stop still leaves classifiable evidence.
Every skip path publishes (guarded lookups, default-empty records, no
unbound variables). WALL_LIMIT_S = 500 s is the Gate-4 wall bound.
The payload accepts a test-only --anneal-iters override for dry-run
calibration; the supervised command line passes none, so frozen
A_ITERS = 200 governs.

Baseline disclosure: no MILP/SMT comparison anywhere in this screen;
the exact baseline is the bounded-exact layer-packing search (own
solved record on tiny counts as optimum for the tiny instance; own
cap-hit record at target scale counts as limit-expiry, never as
optimum). There is no Vandaele/Lau/PhasePoly/torch implementation and
no real qLDPC decoder (BP-OSD or similar) anywhere in this screen.

Limitation (disclosed): modeled codes only (cyclic-shift transversal
subsets, not real qLDPC Tanner graphs or fabricated device maps),
synthetic round-structured DAGs, singleton required shifts per gate
(no logical remapping), latency is layers x 2 rounds under frozen
conflict rules, no hardware claim; wins come from layer packing,
never from gate-count reduction. Logical-remapping co-optimization +
multi-shift gate families is the recorded next experiment.

Acceptance (exact coded conditions): PURSUE iff max(n_win_G, n_win_A)
>= 2, where n_win_X counts DAGs at which arm X in {G,A} jointly wins:
pooled mean latency(X) beats Q by > 2*SE over {Q,G,A} AND all 10
(code, seed) schedules of X at that DAG verify valid — both on the
SAME arm; a latency-only win with any invalid schedule is NOT a joint
win. Joint wins are counted PER ARM and the bar is max(G,A) >= 2,
never a per-instance any-winner count. Also required: Gates 1, 2, 3,
4 pass AND self-tests ok. REJECT iff complete AND tiny solved AND
Gate-1 controls pass AND no strict pooled latency win (G or A mean <
Q mean) at any DAG. Else UNRESOLVED + next experiment
(logical-remapping co-optimization + multi-shift gate retest).
Pursue/reject classification is coordinator-side; the payload reports
numbers + gate evidence and its verdict field is always
unresolved-with-reason. Deterministic given seeds.
