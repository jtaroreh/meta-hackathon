# Screen 09 — Defect-tolerant surface-code compilation around fabrication dropouts

Design: screen-authored deterministic defect-tolerant patch model
(stdlib + numpy only; no external physics, solver, or policy
libraries). Fixed 2D superconducting grids (7x7, 9x9, 11x11 data
qubits) with seeded random fabrication-dropout masks at 2% and 4%
rates (1/2, 2/3, 2/5 dead qubits); frozen super-plaquette
gauge-fixing rule (rounds = d_eff + dead qubits 4-adjacent to the
patch). Logical patch = connected live-cell set; effective distance
is the exact shortest live path (BFS, steps + 1) between the patch's
own north/south and west/east extent edges, d_eff = min, valid iff
d_eff >= 2. Metric: logical spacetime volume (patch area x rounds
under frozen rules) + effective-distance verification. Every arm is
evaluated on the same 30 (size, rate, seed) cells, so arm equivalence
holds by construction. No MILP, SMT, OLSQA, Vandaele, Lau et al.,
PhasePoly, or torch code exists anywhere in this screen (named
blockers, same as all screens).

Hypothesis: jointly optimizing stabilizer super-plaquette
gauge-fixing and logical patch routing around random 2%-5%
fabrication dropouts recovers logical spacetime efficiency lost by
uniform rectangular patch shrinkage.

Model (screen-authored):
- Grids (frozen): 7x7 / 9x9 / 11x11 data qubits (49/81/121).
  Dropout rates 2%/4% give k = max(1, round(rate*N)) dead qubits:
  1/2, 2/3, 2/5 per (size, rate). Seeds SEEDS = (1, 2, 3, 4, 5);
  30 (size, rate, seed) cells x 4 arms (120 arm evaluations; seeds
  are the replicates). Masks are seeded rng choices, deterministic.
- Rounds (frozen gauge rule): ROUNDS = d_eff + n_adj_dead, where
  n_adj_dead counts dead qubits 4-adjacent to the patch (one extra
  syndrome round per neighboring super-plaquette). Spacetime volume
  V = patch area x ROUNDS.
- Arms (code truth):
- B: bounding-box defect exclusion baseline — naive deterministic
  shave-to-clean-rectangle (kill the max-dead row/column, rows
  before columns then smaller index; interior kills keep the larger
  piece, top/left on ties).
- R: random deformed-patch control — seeded random boundary
  notches (NOTCH_ATTEMPTS = 6, width 1..3, depth 1..2) carved from
  the full live grid, undo-on-invalid, largest-component repair, B
  fallback, so R is always valid.
- G: greedy irregular patch routing — from the B rectangle under a
  d >= d_B floor: shrink-to-improve sweeps (GREEDY_SHRINK_SWEEPS =
  3 over the four extent sides) + irregular single-cell hill-climb
  (GREEDY_ANNEX_SWEEPS = 2, row-major, first-improvement); volume
  strictly decreases, distance never degrades, so G never exceeds
  B's volume.
- A: simulated annealing over gauge-fixing + boundary allocation —
  fixed ANNEAL_ITERS = 300 proposals (single-cell flips +
  extent-side shave/annex, T0 = 1.0, alpha = 0.99) from the G patch,
  validity + floor enforced per proposal, cost = volume, best
  tracked, so A never exceeds G.
- Soundness: tiny 3x3 hand-checkable cell (corner dropout) with
  hand values B = 18/d2, G = 6/d2, A <= 6 with d >= 2 + exact-opt
  optimum 6 on tiny + determinism (same seed repeated gives
  identical G and R results).

Controls:
- Gate 1: mean volume(G) strictly below mean volume(R) in every one
  of the 30 (size, rate, seed) cells (pipeline discriminative) AND
  tiny hand-check (B/G exact, A invariants) AND determinism repeat
  identical. Coded exactly as `beats_all_30 && tiny_ok &&
  determinism_ok`.
- Gate 2: pooled volume spread across {B,G,A} > 2*SE at >= 2 sizes
  (pools = 10 values per (size, arm): 2 rates x 5 seeds). Gate 2s
  (distance spread, informational): same rule on pooled distances.
  Coded exactly as `n_sizes_spread_pass >= 2`.
- Gate 3: bounded-exact subset search solves the tiny instance
  (status solved, optimum 6 == hand value) AND the target-scale
  instance (9x9, 4% dropout, seed 1, node cap 50000) reports exactly
  "cap-hit" (probed 50001 nodes). Only cap-hit counts as
  limit-expiry; a solved, stopped-guard, or skipped-guard target
  fails Gate 3. A wall-kill or missing baseline never counts. If
  exact search cannot reach limit-expiry at these scales, Gate 3
  CANNOT pass and the screen caps at UNRESOLVED. Coded exactly as
  `tiny_solved && target_caphit_only`.
- Gate 4: complete (all 30 cells x 4 arms with valid patches; tiny +
  target records present) AND payload wall < WALL_LIMIT_S = 500 s
  AND zero skip records. Coded exactly as
  `complete && wall < 500 && zero skips`.

Budgets: wall 900 s, cpu 5400 s (reservation basis; same generous
staging as screens 19/08). Payload keeps wall to seconds via tiny
corpus (120 fast arm evaluations) plus a WALL_GUARD_S = 300 s
elapsed guard checked before every size, every cell, every arm
loop, every 32 annealing proposals, and every 512 exact-solver
nodes. Each batch publishes its completed count, and EVERY guard
exit appends an explicit skip record with iters_done/n_evaluated,
including tiny/target entry-guard failures ("tiny-exact",
"target-exact"), tiny/target stopped-guard returns, and per-cell /
per-size guard exits, so a guard-truncated run cannot pass G4
clean. All arms propagate stopped=True on a mid-arm guard trip (a
stopped:False value after a guard trip fails review); the tiny and
target exact-search callers append skip records when the exact
search returns stopped-guard (both prior findings). results.json is
written at normal completion; witnesses/selftest.json is written
after the self-test, witnesses/gate3_tiny.json +
gate3_targets.json after the exact phases, witnesses/cells.json
after each size, and witnesses/checkpoint-<tag>.json after tiny,
targets, each size, and the corpus, so a supervisor stop still
leaves classifiable evidence. Every skip path publishes (guarded
lookups, default-empty records, no unbound variables).
WALL_LIMIT_S = 500 s is the Gate-4 wall bound. The payload accepts
a test-only --anneal-iters override for dry-run calibration; the
supervised command line passes none, so frozen ANNEAL_ITERS = 300
governs.

Baseline disclosure: no MILP/SMT comparison anywhere in this
screen; the exact baseline is the bounded-exact subset search over
patch configurations (own solved record on tiny counts as optimum
for the tiny instance; own cap-hit record at target scale counts
as limit-expiry, never as optimum). There is no OLSQA/Vandaele/
Lau/PhasePoly/torch implementation anywhere in this screen.

Limitation (disclosed): modeled square grids only (not fabricated
device maps), synthetic seeded dropout masks (no correlated
defects), frozen gauge rule (rounds = d + adjacent dead, no
full stabilizer simulation), no hardware claim; wins come from
smaller balanced patches at kept distance, never from new physics.
Wider gauge-fixing move families + correlated-defect masks is the
recorded next experiment.

Acceptance (exact coded conditions): PURSUE iff some arm in {G,A}
jointly wins at >= 2 grid sizes, where arm X jointly wins a size
iff pooled mean volume(X) beats B by > 2*SE over {B,G,A} AND pooled
mean distance(X) >= pooled mean distance(B) — both on the SAME
arm; a volume-only win with degraded distance is NOT a joint win.
Joint wins are counted PER ARM and the bar is max(G,A) >= 2, never
a per-instance any-winner count. Also required: Gates 1, 2, 3, 4
pass AND self-tests ok. REJECT iff complete AND tiny solved AND
Gate-1 controls pass AND no strict pooled volume win (G or A mean
< B mean) at any size. Else UNRESOLVED + next experiment (wider
gauge-fixing move families + correlated-defect masks).
Pursue/reject classification is coordinator-side; the payload
reports numbers + gate evidence and its verdict field is always
unresolved-with-reason. Deterministic given seeds.
