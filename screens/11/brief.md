# Screen 11 — Trapped-ion QCCD junction shuttling & split/merge scheduling

Design: screen-authored deterministic QCCD shuttling model (stdlib +
numpy only; no external physics, solver, or policy libraries). A 2D
trap grid with explicit per-site capacity, an X-junction trunk cross
(middle row + middle column), and per-ion motional phonon counters.
Operations: shuttle hops, junction
turns, crystal split/merge, adjacent ion swaps, and sympathetic cooling
rounds that reset phonon. Every arm is evaluated on the same 45 (size,
circuit, seed) cells, so arm equivalence holds by construction.
Transit through occupied segments is allowed at disturbance heat;
resting occupancy never exceeds TRAP_CAP (full targets cleared by
displacement to the first free site). No
MILP, SMT, OLSQA, Vandaele, Lau et al., PhasePoly, or torch code
exists anywhere in this screen (named blockers, same as all screens).

Hypothesis: optimizing ion-crystal split, merge, swap, and X-junction
turn sequences with phonon-heating awareness minimizes sympathetic
cooling overhead and total decoherence vs shortest-path trap routing.
First screen — heating-aware annealing vs greedy distance routing on
three benchmark circuits. Continue only if heating-aware schedules
reduce estimated infidelity over swap-count-only baselines at two sizes.

Model (screen-authored):
- Sizes (frozen trap grids, ions): 3x3 (4 ions), 4x4 (6 ions),
  5x5 (8 ions). Junctions: trunk cross (middle row + middle column);
  turns legal only at trunk cells, straight shuttling anywhere.
  Capacity TRAP_CAP = 2 ions per site, transit disturbance allowed.
- Circuits (frozen, N_GATES = 12 each): chain, star, ring pairs,
  each rotated by seed. Seeds SEEDS = (1, 2, 3, 4, 5); 45
  (size, circuit, seed) cells x 4 arms (180 evaluations; replicates).
- Phonon (frozen heat per event): HEAT_HOP = 1.0, HEAT_TURN = 2.0,
  HEAT_SPLIT = 3.0, HEAT_MERGE = 3.0, HEAT_SWAP = 4.0. Exposure =
  phonon pair-sum at each gate; cooling resets the pair.
- Infidelity (frozen weights): W_SWAP = 0.002, W_TURN = 0.001,
  W_HEAT = 0.0005, W_COOL = 0.004, W_GATE = 0.001; infid =
  W_SWAP*swaps + W_TURN*turns + W_HEAT*exposure + W_COOL*cooling +
  W_GATE*gates. S never cools; R cools per seeded draw; G cools the
  pair past COOL_THRESHOLD = 12.0; A anneals cooling insertion.
- Arms (code truth):
- S: shortest-path/swap-count-only baseline — always shuttle the
  first ion via the shortest turn-legal path, never cool.
- R: random control — seeded random detours (R_DETOUR = 3 legal hops
  per gate) + random legal mover/path + random cooling.
- G: greedy distance routing — per-gate minimum-immediate-heat legal
  option (split/merge/hops/turns/swap) + threshold cooling.
- A: heating-aware annealing over per-gate mover/path/cooling
  (ANNEAL_ITERS = 300, A_T0 = 1.0, A_ALPHA = 0.99) from the G
  schedule, best tracked, so A never exceeds G.
- Soundness: tiny 2x2 hand-checkable cell (ions (0,0),(0,1), one
  gate) with hand values exposure 4.0 / infid 0.003 / 0 swaps /
  0 turns / 0 cooling; S, G match, A invariant (<= G); R is
  recorded but random by design, so it is not hand-gated +
  exact-opt optimum 0.003 on tiny + determinism (same seed
  repeated gives identical G and R results).
- Frozen symbols (code identifiers match exactly): GRID_SIZES,
  N_IONS_PER_SIZE, CIRCUITS, N_GATES, SEEDS, ARMS, TRAP_CAP,
  HEAT_HOP, HEAT_TURN, HEAT_SPLIT, HEAT_MERGE, HEAT_SWAP,
  COOL_THRESHOLD, W_SWAP, W_TURN, W_HEAT, W_COOL, W_GATE,
  ANNEAL_ITERS, A_T0, A_ALPHA, R_DETOUR, EXACT_CAP,
  WALL_GUARD_S, WALL_LIMIT_S, TINY_SIZE, TINY_INIT, TINY_GATES,
  TINY_EXP_EXPOSURE, TINY_EXP_INFID, TARGET, NEXT_EXPERIMENT.

Controls:
- Gate 1: mean infidelity(G) strictly below mean infidelity(R) in
  every one of the 45 (size, circuit, seed) cells (pipeline
  discriminative) AND tiny hand-check (S/G exact, A invariants)
  AND determinism repeat identical. Coded exactly as
  `beats_all_45 && tiny_ok && determinism_ok`.
- Gate 2: pooled infidelity spread across {S,G,A} > 2*SE at >= 2
  sizes (pools = 15 values per (size, arm): 3 circuits x 5 seeds).
  Coded exactly as `n_sizes_spread_pass >= 2`.
- Gate 3: bounded-exact routing search solves the tiny instance
  (status solved, optimum 0.003 == hand value) AND the
  target-scale instance (5x5, ring circuit, seed 1, node cap 50000)
  reports exactly "cap-hit" (probed 50001 nodes). Only cap-hit
  counts as limit-expiry; a solved, stopped-guard, or skipped-guard
  target fails Gate 3. A wall-kill or missing baseline never
  counts. If exact search cannot reach limit-expiry at these scales,
  Gate 3 CANNOT pass and the screen caps at UNRESOLVED. Coded
  exactly as `tiny_solved && target_caphit_only`.
- Gate 4: complete (all 45 cells x 4 arms with valid schedules;
  tiny + target records present) AND payload wall < WALL_LIMIT_S
  = 500 s AND zero skip records. Coded exactly as
  `complete && wall < 500 && zero skips`.

Budgets: wall 900 s, cpu 5400 s (reservation basis; same generous
staging as screens 19/09). Payload keeps wall to seconds via tiny
corpus (180 fast 12-gate replays with small BFS) plus a
WALL_GUARD_S = 300 s elapsed guard checked before every size, every
cell, every arm loop, every gate replay, every 32 annealing
proposals, and every 512 exact-solver nodes. Each batch publishes
its completed count, and EVERY guard exit appends an explicit skip
record with iters_done/n_evaluated, including tiny/target
entry-guard failures ("tiny-exact", "target-exact"), tiny/target
stopped-guard returns, and per-cell / per-size guard exits, so a
guard-truncated run cannot pass G4 clean. All arms propagate
stopped=True on a mid-arm guard trip. results.json is written at
normal completion; witnesses/selftest.json after the self-test,
witnesses/gate3_tiny.json + gate3_targets.json after the exact
phases, witnesses/cells.json after each size, and
witnesses/checkpoint-<tag>.json after tiny, targets, each size,
and the corpus, so a supervisor stop still leaves classifiable
evidence. Every skip path publishes (guarded lookups,
default-empty records, no unbound variables). WALL_LIMIT_S =
500 s is the Gate-4 wall bound. The payload accepts a test-only
--anneal-iters override for dry-run calibration; the supervised
command line passes none, so frozen ANNEAL_ITERS = 300 governs.

Baseline disclosure: no MILP/SMT comparison anywhere in this
screen; the exact baseline is the bounded-exact routing search
over per-gate mover/path/cooling choices (own solved record on
tiny counts as optimum for the tiny instance; own cap-hit record
at target scale counts as limit-expiry, never as optimum). There
is no OLSQA/Vandaele/Lau/PhasePoly/torch implementation anywhere
in this screen.

Limitation (disclosed): modeled grids only (not fabricated QCCD
traps), synthetic frozen circuits, frozen linear infidelity weights
(no full motional-mode simulation), no hardware claim; wins come
from cooling-aware scheduling at kept validity, never new physics.
Next experiment: sympathetic-cooling ion placement co-optimization + correlated heating-noise retest.

Acceptance (exact coded conditions): PURSUE iff some arm in {G,A}
jointly wins at >= 2 trap sizes, where arm X jointly wins a size
iff pooled mean infidelity(X) beats S by > 2*SE over {S,G,A} AND
pooled mean validity(X) >= pooled mean validity(S) — both on the
SAME arm; an infidelity-only win with degraded validity is NOT a
joint win. Joint wins are counted PER ARM and the bar is
max(G,A) >= 2, never a per-instance any-winner count. Also
required: Gates 1, 2, 3, 4 pass AND self-tests ok. REJECT iff
complete AND tiny solved AND Gate-1 controls pass AND no strict
pooled infidelity win (G or A mean < S mean) at any size. Else
UNRESOLVED + next experiment (sympathetic-cooling ion placement co-optimization + correlated heating-noise retest).
Pursue/reject classification is coordinator-side; the payload
reports numbers + gate evidence and its verdict field is always
unresolved-with-reason. Deterministic given seeds.
