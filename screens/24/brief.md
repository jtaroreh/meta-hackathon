# Screen 24 — Fermion-to-qubit ternary-tree mapping optimization

Design: screen-authored deterministic ternary-tree encoding model
(stdlib + numpy only; no external chemistry, synthesis, physics, or
solver libraries). Synthetic frozen molecular Hamiltonians (1- and
2-body fermionic mode graphs) on n in {12, 16, 20} spin-orbitals;
each rep is a seeded Hamiltonian instance evaluated under six
encodings on a frozen 2D grid (4x3, 4x4, 5x4) with all-pairs
shortest-path distances precomputed by BFS. Encodings are ternary
trees with n internal nodes (= n qubits) and 2n+1 leaves;
leaf-to-mode assignment plus child-permutation rotations preserve
the anticommutation structure (O(1) pointer updates); every arm
compiles the same fermionic gadget list, so arm equivalence holds
by construction. Routed cost per Pauli gadget sums 2 CNOTs per
support link (ladder + reverse) at 3d-2 routed CNOTs each over
grid-ordered support qubits; depth is list-scheduled (duration
2*(2d-1) per link, +1 per gadget), gadgets sequential. No MILP,
SMT, OLSQA, Vandaele, Lau et al., PhasePoly, or torch-policy code
exists anywhere in this screen (named blockers, same as all
screens).

Hypothesis: tree-search over rotations and leaf-to-mode assignments
on ternary trees (generalizing Jordan-Wigner, Bravyi-Kitaev, and
balanced trees) minimizes total routed CNOT weight of electronic
structure Hamiltonians on 2D hardware grids, in regimes where exact
mapping search hits a timeout wall.

Model (screen-authored):
- Sizes (frozen orbital counts): 12 / 16 / 20 spin-orbitals on
  frozen grids 4x3 / 4x4 / 5x4 (qubit i at node i, row-major).
- Hamiltonians (frozen generator, documented): chain hopping on all
  n-1 adjacent mode pairs + HOP_LONG seeded long-range hopping
  pairs (6/8/10) + N_DENS seeded density pairs (14/20/26) + N_PAIR
  seeded pair-hopping quadruples (4/6/8); each hopping term yields
  2 Pauli gadgets, each density term 1, each pair term 2, all
  sharing the term's mode support (56/78/100 gadget instances).
  Seeded by (size, seed, rep); coverage of every mode audited.
- Arms (code truth):
- J: Jordan-Wigner interval baseline — term support is the
  contiguous qubit interval [min, max] over mode ranks.
- K: Fenwick (BK-inspired) log-weight baseline — per-mode
  update/parity sets from the Fenwick tree, unioned per term.
- T: balanced ternary baseline — full ternary tree
  (shallowest-leaf-first expansion), identity leaf-to-mode map.
- G: greedy leaf-swap descent from the T start (GREEDY_SWEEPS
  sweeps over all mode pairs, first-improvement on routed CNOTs)
  plus one seeded random restart, best tracked.
- A: simulated annealing over leaf swaps (70%) + tree rotations
  (30%) from the T start — fixed ANNEAL_ITERS proposals,
  cost = routed CNOTs + LAMBDA x depth (frozen LAMBDA = 5.0),
  best tracked.
- R: random control — seeded random map + seeded random rotations.
- Metric: total routed CNOT weight of the Pauli network + circuit
  depth at fixed grid.
- Seeds SEEDS = (1, 2, 3, 4, 5); N_INST = 120 reps per (size,
  seed, arm) cell (90 cell-arms, 10800 arm evaluations over 1800
  Hamiltonians).
- Soundness: tiny n=4 hand-checkable chain (hopping (0,1),(1,2),
  (2,3) x2 gadgets + density (0,2),(1,3) x1) with known-optimal
  ternary mapping by construction (identity map: routed 40 /
  depth 42, verified by hand from the leaf path masks). T, G
  match 40/42 (A never regresses past T by best-tracking; J, K, R
  are recorded but not hand-gated) + exact-opt unrouted optimum
  22 on tiny + determinism (same seed repeated gives identical G,
  A, and R results).

Controls:
- Gate 1: mean CNOTs(G) strictly below mean CNOTs(R) in every one
  of the 15 (size, seed) cells (pipeline discriminative) AND tiny
  hand-check (T, G exact; A no-regress; exact solved) AND
  determinism repeat identical. Coded exactly as
  `beats_all_15 && tiny_ok && determinism_ok`.
- Gate 2: pooled CNOT spread across {J,K,T,G,A} > 2*SE at >= 2 sizes
  (pools = 5 seed means per size per arm). Gate 2s (depth spread,
  informational): same rule on pooled depth. Coded exactly as
  `n_sizes_spread_pass >= 2`.
- Gate 3: bounded-exact branch-and-bound over leaf assignments
  solves the tiny instance (status solved, unrouted optimum 22)
  AND the target-scale instance (20-orbital family Hamiltonian,
  seed 1 rep 0, node cap 50000) reports exactly "cap-hit"
  (probed 50001 nodes). Only cap-hit counts as limit-expiry; a
  solved, stopped-guard, or skipped-guard target fails Gate 3.
  A wall-kill or missing baseline never counts. If exact search
  cannot reach limit-expiry at these scales, Gate 3 CANNOT pass
  and the screen caps at UNRESOLVED. Coded exactly as
  `tiny_solved && target_caphit_only`.
- Gate 4: complete (all 15 cells x 6 arms with n == N_INST; tiny +
  target records present) AND payload wall < WALL_LIMIT_S = 500 s
  AND zero skip records. Coded exactly as
  `complete && wall < 500 && zero skips`.

Budgets: wall 900 s, cpu 5400 s (reservation basis; same generous
staging as screens 02/20/07/12/19). Payload keeps wall ~70-120 s
via ordering (self-test, tiny-exact, target exact, corpus by size)
plus a WALL_GUARD_S = 300 s elapsed guard checked before every
size, every cell, every arm loop, every 32 reps, and every 512
exact-solver nodes. Each batch publishes its completed count (n
alongside the configured total), and EVERY guard exit appends an
explicit skip record with iters_done/n_evaluated, including
tiny/target entry-guard failures ("tiny-exact", "target-exact")
and per-cell / per-size guard exits, so a guard-truncated run
cannot pass G4 clean. results.json is written at normal
completion; witnesses/selftest.json is written after the
self-test, witnesses/gate3_tiny.json + gate3_targets.json after
the exact phases, witnesses/cells.json after each size, and
witnesses/checkpoint-<tag>.json after tiny, targets, each size,
and the corpus, so a supervisor stop still leaves classifiable
evidence. Every skip path publishes (guarded lookups,
default-empty records, no unbound variables). WALL_LIMIT_S =
500 s is the Gate-4 wall bound. The payload accepts test-only
--n-inst / --anneal-iters overrides for dry-run calibration; the
supervised command line passes neither, so frozen N_INST = 120
and ANNEAL_ITERS = 150 govern.

Baseline disclosure: no MILP/SMT comparison anywhere in this
screen; the exact baseline is the bounded-exact branch-and-bound
over leaf assignments (own solved record on tiny counts as
optimum for the tiny instance; own cap-hit record at target scale
counts as limit-expiry, never as optimum). There is no
OLSQA/Vandaele/Lau/PhasePoly/torch implementation anywhere in
this screen.

Limitation (disclosed): synthetic Hamiltonians only (seeded mode
graphs, not ab-initio integrals), modeled 2D grids (not
fabricated device maps), modeled Pauli-gadget routing without
parity-reuse optimization (each gadget synthesized independently,
so wins come from support shrinkage, never from cross-gadget
cancellation), no hardware claim; search is over maps/rotations
at fixed identity qubit placement. Pauli-gadget resynthesis with
parity-reuse routing plus a larger active-space retest is the
recorded next experiment.

Acceptance (exact coded conditions): PURSUE iff some arm in {G,A}
jointly wins at >= 2 sizes, where arm X jointly wins a size iff
pooled mean routed CNOTs(X) beats ALL of {J,K,T} by > 2*SE (SE
over the four pooled means) AND pooled mean depth(X) <= the best
(smallest) pooled mean depth over {J,K,T} — both on the SAME arm;
a CNOT-only win with higher depth is NOT a joint win. Also
required: Gates 1, 2, 3, 4 pass AND self-tests ok. REJECT iff
complete AND tiny solved AND Gate-1 controls pass AND no strict
pooled CNOT win (G or A mean < best {J,K,T} mean) at any size.
Else UNRESOLVED + next experiment (Pauli-gadget resynthesis with
parity-reuse routing + larger active-space retest).
Pursue/reject classification is coordinator-side; the payload
reports numbers + gate evidence and its verdict field is always
unresolved-with-reason. Deterministic given seeds.
