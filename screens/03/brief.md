# Screen 03 — Floquet / dynamical code schedule optimization

Design: screen-authored deterministic detector simulator
(stdlib + numpy only; no external physics, synthesis, or solver
libraries). Small heavy-hex cells (ring + chords, max degree 3) on
n in {8, 14, 20} data qubits with C in {10, 18, 25} 2-body Pauli
checks (bond-type coloring X/Y/Z by edge index mod 3), measured over
T = 4 rounds. A schedule is one permutation of the check set used
every round. Faults are single-qubit X/Z faults at interior slots
(rounds 1..T-2); each check's consecutive-round outcomes form
detectors. No MILP, SMT, OLSQA, Vandaele, Lau et al., PhasePoly, or
torch-policy code exists anywhere in this screen (named blockers,
same as all screens).

Hypothesis: mutated check schedules (greedy + annealing) achieve
higher exact detecting-region distance at no greater cycle depth
than static Hastings–Haah cyclic schedules, in regimes where 1–2
edges are penalized/removed.

Model (screen-authored):
- Sizes (frozen data-qubit counts): 8 / 14 / 20 qubits (C = 10/18/25
  checks). Degree never exceeds 3 by construction (ring gives 2,
  chords at i, i+3 for i = 0 mod 4 are disjoint, adding at most 1).
- Defect conditions (frozen per size, seeded, nested): no defect +
  1 edge removed + 2 edges removed (defect-1 is the first of the
  defect-2 pair).
- Schedule = one permutation of the check set, used every round.
- Arms (code truth):
- H: static Hastings–Haah cyclic schedule — canonical check order
  (the decomposed baseline).
- R: random schedule control — 3 seeded random permutations per
  (size, defect, seed) cell, mean reported.
- G: greedy local search — single first-improvement sweep over all
  pairwise swaps from the H start, strictly improving distance,
  depth tiebreak.
- S: simulated annealing over check order — fixed S_ITERS swaps
  from the H start, cost = -distance + LAMBDA x depth (frozen
  LAMBDA = 0.05), best tracked.
- Metric: exact detecting-region distance (minimum fault weight
  with empty detector syndrome and nontrivial residual Pauli, by
  exhaustive fault enumeration exact at weights 1..3; above that
  censored ">3" mapped to 4, disclosed) + cycle depth (T x
  list-scheduled layers under shared-qubit conflicts).
- Seeds SEEDS = (1, 2, 3, 4, 5); 45 (size, defect, seed) cells x 4
  arms (180 arm evaluations; seeds are the replicates).
- Soundness: tiny single-hexagon hand-checkable cell (n = 6 ring,
  C = 6, known distance >= 2 by hand: every interior single fault
  anticommutes with at least one incident check by type counting,
  so no weight-1 undetectable fault exists) + independent
  direct-syndrome witness re-verification + exhaustive-schedule
  optimum on tiny + determinism (same seed repeated identical).

Controls:
- Gate 1: pooled mean distance(G) strictly above pooled mean
  distance(R) in every one of the 9 (size, defect) cells
  (pipeline discriminative) AND tiny hand-bound 2 AND witness
  re-verification AND determinism repeat identical. Coded exactly
  as `beats_all_9 && tiny_ok && determinism_ok`.
- Gate 2: pooled distance spread across {H,G,S} > 2*SE in >= 4 of
  the 9 (size, defect) cells spanning >= 2 sizes (pools = 5 seed
  values per cell per arm). Coded exactly as
  `n_cells_spread_pass >= 4 spanning >= 2 sizes`.
- Gate 3: bounded-exact BFS over schedules solves the tiny
  instance (status solved, optimum recorded) AND the target-scale
  instance (20-qubit no-defect cell, seed 1, node cap 50000)
  reports exactly "cap-hit". Only cap-hit counts as limit-expiry;
  a solved, stopped-guard, or skipped-guard target fails Gate 3.
  A wall-kill or missing baseline never counts. If exact search
  cannot reach limit-expiry at these scales, Gate 3 CANNOT pass
  and the screen caps at UNRESOLVED. Coded exactly as
  `tiny_solved && target_caphit_only`.
- Gate 4: complete (all 45 cells x 4 arms with n == 1; tiny +
  target records present) AND payload wall < WALL_LIMIT_S = 500 s
  AND zero skip records. Coded exactly as
  `complete && wall < 500 && zero skips`.

Budgets: wall 900 s, cpu 5400 s (reservation basis; same generous
staging as screens 02/20/07/12). Payload keeps wall ~70-120 s via
ordering (self-test, tiny-exact, target exact, corpus by size)
plus a WALL_GUARD_S = 300 s elapsed guard checked before every
size, every cell, every arm loop, every 32 search candidates, and
every 512 exact-solver nodes. Each batch publishes its completed
count (n alongside the configured total), and EVERY guard exit
appends an explicit skip record with iters_done/n_evaluated,
including tiny/target entry-guard failures ("tiny-exact",
"target-exact") and per-cell guard exits, so a guard-truncated
run cannot pass G4 clean. results.json is written at normal
completion; witnesses/selftest.json is written after the
self-test, witnesses/gate3_tiny.json + gate3_targets.json after
the exact phases, witnesses/cells.json after each size, and
witnesses/checkpoint-<tag>.json after tiny, targets, each size,
and the corpus, so a supervisor stop still leaves classifiable
evidence. Every skip path publishes (guarded lookups,
default-empty records, no unbound variables). WALL_LIMIT_S =
500 s is the Gate-4 wall bound. The payload accepts test-only
--s-iters / --r-samples overrides for dry-run calibration; the
supervised command line passes neither, so frozen S_ITERS = 30
and R_SAMPLES = 3 govern.

Baseline disclosure: no MILP/SMT comparison anywhere in this
screen; the exact baseline is the bounded-exact BFS over
schedules (own solved record on tiny counts as optimum for the
tiny instance; own cap-hit record at target scale counts as
limit-expiry, never as optimum). There is no OLSQA/Vandaele/
Lau/PhasePoly/torch implementation anywhere in this screen.

Limitation (disclosed): modeled cells only (ring+chord
heavy-hex-inspired graphs, not fabricated device maps),
synthetic bulk-only fault model (boundary slots excluded,
X/Z faults only), check-type coloring frozen (not co-optimized),
schedule shared across rounds (no per-round variation), small
cells, modeled defects, no hardware claim; distance censored
above weight 3 (reported as 4). Defect-aware check-type
recoloring + per-round schedule variation is the recorded next
experiment.

Acceptance (exact coded conditions): PURSUE iff some arm in {G,S}
jointly wins at >= 2 sizes under defect conditions, where arm X
jointly wins a size iff pooled mean distance(X) over seeds x
{1-edge, 2-edge} defects beats H by > 2*SE over {H,G,S} AND
pooled mean depth(X) <= pooled mean depth(H) — both on the SAME
arm; a distance-only win with higher depth is NOT a joint win.
Also required: Gates 1, 2, 3, 4 pass AND self-tests ok. REJECT iff
complete AND tiny solved AND Gate-1 controls pass AND no strict
pooled distance win (G or S mean > H mean) at any size. Else
UNRESOLVED + next experiment (defect-aware check-type recoloring
+ per-round schedule variation retest).
Pursue/reject classification is coordinator-side; the payload
reports numbers + gate evidence and its verdict field is always
unresolved-with-reason. Deterministic given seeds.
