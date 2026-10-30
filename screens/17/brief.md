# Screen 17 — Entanglement-minimization cuts for circuit knitting / wire cutting

Design: screen-authored exact cut-cost model (stdlib + numpy only;
no external physics, solver, or policy libraries). Circuits are
frozen seeded gate lists (H/S single-qubit gates plus CNOTs) in
three families on N_QUBITS = (8, 10, 12) qubits: ladder (chain
CNOTs, 6 layers), hea (ring CNOTs, 8 layers), qftlike (chain plus
long-range CNOTs, 10 layers). A cut placement assigns every
two-qubit gate to one of ceil(n/K_MAX) fragments and flags
gate-cuts; wire cuts fall on per-qubit consecutive two-qubit gates
in different fragments. Total sampling overhead is the exact
product prod(gamma_i^2) with frozen GAMMA2_WIRE = 9.0 per wire cut
and GAMMA2_GATE = 16.0 per gate cut, computed in log space.
Partition validity (every fragment width <= K_MAX = 4, all cuts
legal) is verified per rep; a deterministic repair maps any
placement to a valid one (gate-cut fallback always terminates).
Local rewrites are duplicate-CNOT cancellation plus logical label
swaps, unitary-preserving by construction. No MILP, SMT, OLSQA,
Vandaele, Lau, PhasePoly, or torch code exists anywhere in this
screen (named blockers, same as all screens).

Hypothesis: co-optimizing local Clifford/swap rewrites with
wire- and gate-cut placements minimizes total quasi-probability
sampling overhead (gamma^2) across subcircuits constrained to k
qubits. Continue only if local pre-cut rewrites reduce gamma^2
below optimal static-DAG cuts at two benchmark sizes.

Model (screen-authored):
- Sizes (frozen qubit counts): 8 (ladder, ~24 CNOTs), 10 (hea,
  ~40 CNOTs), 12 (qftlike, ~70 CNOTs). Width cap K_MAX = 4;
  fragment counts ceil(n/4) = (2, 3, 3). Seeds SEEDS = (1, 2, 3,
  4, 5); N_INST = 12 reps per (size, seed, arm) cell (60
  cell-arms, 720 arm evaluations over 180 circuits). Seeds are
  replicates.
- Arms (code truth):
- C: static DAG min-cut baseline — identity rewrite, greedy
  fragment assignment minimizing added wire transitions under the
  width cap, one improvement sweep, then a gate-cut post-pass.
- R: random cut-placement control — seeded random label swap,
  random fragments, random gate-cut flags (p = 0.15), repaired.
- G: greedy joint local-rewrite + cut search — from the C
  solution, GREEDY_SWEEPS = 3 first-improvement sweeps over
  fragment moves, gate-cut toggles, label swaps, after
  deterministic duplicate-CNOT cancellation.
- A: simulated annealing over rewrite+cut placements —
  ANNEAL_ITERS = 200 seeded proposals from the C solution,
  temperature ANNEAL_T0 = 2.0 decaying by ANNEAL_ALPHA = 0.985,
  best tracked.
- Metric: exact total sampling overhead prod(gamma_i^2) per rep
  with frozen per-cut factors + partition-validity verification
  (fragment widths <= K_MAX, all cuts legal). Cell and gate
  statistics use mean log-overhead (monotone in the product,
  exact in float64); every cell is built so the metric has a
  live gradient (dense entangling circuits far above the width
  cap, so no cell ties losslessly across arms).
- Soundness: tiny 6-qubit CNOT chain (5 gates) with known-optimum
  TINY_OPT = 9.0 by construction (one wire cut beats one gate
  cut, 9.0 < 16.0; rewrites cannot fire on distinct pairs). C,
  G, A match 9.0/9.0 (R is recorded but random by design, so it
  is not hand-gated) + exact-opt optimum 9.0 on tiny +
  determinism (same seed repeated gives identical G and R
  results).
- Frozen symbols (code identifiers match exactly): N_QUBITS,
  FAMILIES, K_MAX, SEEDS, ARMS, N_INST, GAMMA2_WIRE,
  GAMMA2_GATE, GREEDY_SWEEPS, ANNEAL_ITERS, ANNEAL_T0,
  ANNEAL_ALPHA, EXACT_CAP, WALL_GUARD_S, WALL_LIMIT_S, TINY_N,
  TINY_OPT, TARGET, NEXT_EXPERIMENT.

Controls:
- Gate 1: mean log-overhead(G) strictly below mean
  log-overhead(R) in every one of the 15 (size, seed) cells
  (pipeline discriminative) AND tiny hand-check 9.0 on C/G/A AND
  determinism repeat identical. Coded exactly as
  `beats_all_15 && tiny_ok && determinism_ok`.
- Gate 2: pooled log-overhead spread across {C,G,A} > 2*SE at
  >= 2 sizes (pools = 5 seed means per size per arm). Coded
  exactly as `n_sizes_spread_pass >= 2`.
- Gate 3: bounded-exact unpriced DFS cut search solves the tiny
  instance (status solved, optimum 9.0 == hand value) AND the
  target-scale instance (qftlike circuit, seed 1 rep 0, node cap
  50000) reports exactly "cap-hit" (probed 50001 nodes). Only
  cap-hit counts as limit-expiry; a solved, stopped-guard, or
  skipped-guard target fails Gate 3. A wall-kill or missing
  baseline never counts. If exact search cannot reach
  limit-expiry at these scales, Gate 3 CANNOT pass and the
  screen caps at UNRESOLVED. Coded exactly as
  `tiny_solved && target_caphit_only`.
- Gate 4: complete (all 15 cells x 4 arms with n == N_INST;
  tiny + target records present) AND payload wall <
  WALL_LIMIT_S = 500 s AND zero skip records. Coded exactly as
  `complete && wall < 500 && zero skips`.

Budgets: wall 900 s, cpu 5400 s (reservation basis; same generous
staging as screens 19/16). Payload keeps wall ~2 min via a
compact corpus (12 reps per cell) plus a WALL_GUARD_S = 300 s
elapsed guard checked before every size, every cell, every arm
loop, every 32 reps (and every 32 search evals), and every 512
exact-solver nodes. Each batch publishes its completed count (n
alongside the configured total), and EVERY guard exit appends an
explicit skip record with iters_done/n_evaluated, including
tiny/target entry-guard failures ("tiny-exact", "target-exact"),
tiny/target stopped-guard returns, and per-cell / per-size guard
exits, so a guard-truncated run cannot pass G4 clean. All arms
propagate stopped=True on a mid-arm guard trip. results.json is
written at normal completion; witnesses/selftest.json is written
after the self-test, witnesses/gate3_tiny.json +
gate3_targets.json after the exact phases, witnesses/cells.json
after each size, and witnesses/checkpoint-<tag>.json after tiny,
targets, each size, and the corpus, so a supervisor stop still
leaves classifiable evidence. Every skip path publishes (guarded
lookups, default-empty records, no unbound variables).
WALL_LIMIT_S = 500 s is the Gate-4 wall bound. The payload
accepts test-only --n-inst / --anneal-iters overrides for
dry-run calibration; the supervised command line passes neither,
so frozen N_INST = 12 and ANNEAL_ITERS = 200 govern.

Baseline disclosure: no MILP/SMT comparison anywhere in this
screen; the exact baseline is the bounded-exact DFS cut search
over fragment assignments and gate-cut flags on the canonical
gate list (own solved record on tiny counts as optimum for the
tiny instance; own cap-hit record at target scale counts as
limit-expiry, never as optimum; the DFS is unpriced except for
width-cap pruning, which never removes a valid placement). There
is no OLSQA/Vandaele/Lau/PhasePoly/torch implementation
anywhere in this screen.

Limitation (disclosed): modeled gate lists only (seeded random
Clifford + CNOT circuits, no device maps), screen-authored
gamma factors (9.0/16.0, not calibrated to hardware), wire cuts
counted over consecutive two-qubit gates per qubit, placement
only splits two-qubit gates (single-qubit gates never cut), no
hardware claim; wins come from cut placement and rewrite choice
only. Next experiment: richer Clifford-template rewrite library
+ depth-regularized cut annealing retest.

Acceptance (exact coded conditions): PURSUE iff some arm in {G,A}
jointly wins at >= 2 sizes, where arm X jointly wins a size iff
pooled mean log-overhead(X) beats C by > 2*SE over {C,G,A} AND
pooled mean validity(X) >= pooled mean validity(C) — both on the
SAME arm; a gamma^2-only win with degraded validity is NOT a
joint win. Joint wins are counted PER ARM, bar max(G,A) >= 2,
never a per-instance any-winner count. Also required: Gates 1,
2, 3, 4 pass AND self-tests ok. REJECT iff complete AND tiny
solved AND Gate-1 controls pass AND no strict pooled gamma^2 win
(G or A mean < C mean) at any size. Else UNRESOLVED + next
experiment (richer Clifford-template rewrite library +
depth-regularized cut annealing retest). Pursue/reject
classification is coordinator-side; the payload reports numbers
+ gate evidence and its verdict field is always
unresolved-with-reason. Deterministic given seeds.
