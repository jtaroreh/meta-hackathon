# Screen 02 — flag-gadget schedule search (staged in run f5ac1866b1794567ad299c518a43a391)

Design: screen-authored schedule search on a stim-transcribed
rotated-surface-code tiling (stim 1.16.0 + stdlib + numpy only; no
external search or physics libraries). Per stabilizer a CNOT order
(data-qubit to layer-slot assignment within the transcribed layer
skeleton) and a flag bit {0,1} (full-bracket flag: open before the
first data CNOT, close after the last). No Vandaele, Lau et al.,
PhasePoly, torch-policy, MILP, SMT, or OLSQA code exists anywhere in
this screen (named blockers, same as all screens).

Hypothesis: some transcribed schedule with reordered data-CNOT
assignment and/or dropped flags preserves effective distance d_eff == 3
at strictly lower CNOT overhead than the all-flags canonical — on d=3
at fixed circuit noise, with gradient and transfer checks on d=5.

Model (screen-authored):
- Layout MUST be transcribed: `transcribe_layers` derives data qubits,
  per-stabilizer layer slots, and the logical set from
  `stim.Circuit.generated("surface_code:rotated_memory_x")`. Hand-tiling
  broke commutation; the self-test asserts the transcribed d=3 layout
  (9 data, 8 stabilizers) commutes and the canonical schedule is valid.
- Schedule space per stabilizer: data-qubit to layer-slot assignment
  (transcribed layer skeleton fixed) x flag {0,1}, full-bracket flags.
- Canonical schedule = transcribed order + flags everywhere
  (screen-authored transcription of the Reichardt/Chamberland flag
  prescription, verified valid in-sim with d_eff == 3).
- Metric: effective distance d_eff via stim `shortest_graphlike_error`
  at fixed circuit noise (`ValueError` = nondeterministic = invalid),
  then total CNOT overhead at preserved d_eff. `better(a, b)` = higher
  d_eff wins, ties break to fewer CNOTs.
- Noise (circuit-level, as coded in `build_memory`): DEPOLARIZE1(p)
  after each 1q gate, DEPOLARIZE2(p) after each CNOT, X_ERROR(p) after
  each measurement; prep RX/R. ROUNDS = 3, P_NOISE = 0.005.
- Arms (code truth; later constant block governs):
- canonical point (transcribed order + flags everywhere).
- random: N_RANDOM_SEED = 60 rollouts/seed over the full space
  (module docstring still says "1000 random rollouts" — stale; code
  truth is 60/seed). Top-of-file N_RANDOM = 1000 is a shadowed dead
  constant, never used by the search loops.
- greedy: single-stabilizer moves from canonical, GREEDY_ITERS = 60
  iters/seed (top-of-file GREEDY_STEPS = 50 is dead).
- SA: single-stabilizer moves from a random start, SA_ITERS = 50
  iters/seed, SA_T0 = 1.0, SA_ALPHA = 0.97 (top-of-file SA_ITERS = 100
  is dead; the later SA_ITERS = 50 governs).
- exact: flag-subset enumeration 2^8 = 256 on d=3 (transcribed order
  fixed, flag mask swept).
- enum_d5: per-stabilizer capped enumeration on d=5, cap
  ENUM_CAP_EVALS = 150 (top-of-file ENUM_CAP = 200000 is dead).
- threshold: pseudo-threshold sampling on d=3 (canonical, best) and d=5
  (canonical, noflag) over P_GRID = (0.002, 0.005, 0.01), N_SHOTS =
  20000 via `compile_sampler` + `compile_m2d_converter` with
  `separate_observables=True`.
- Seeds SEEDS = (1, 2, 3, 4, 5).
- Soundness: determinism check (canonical evaluated twice, must match);
  eval-shape check; layout-counts and commute checks in `self_tests`.

Controls:
- Gate 1: canon_valid (canonical ok and d_eff == 3) AND exact_valid
  (exact best d_eff == 3) AND random valid fraction < 1.0 (search space
  is discriminative, not all-valid). Coded exactly as
  `canon_valid && exact_valid && rand_frac < 1.0`.
- Gate 2: gradient-only — LER strictly increasing over the p grid on the
  d3 canonical row AND on the d5 canonical row. Best (d3) and noflag
  (d5) rows are recorded but do not gate. Coded exactly as
  `grad(d3 canonical) && grad(d5 canonical)`.
- Gate 3: exact solved (256/256 evaluated on d=3) AND enum_d5 status is
  exactly "cap-hit" (150/150, limit-expiry). A solved or stopped-guard
  d5 target fails Gate 3. Coded exactly as
  `exact solved && enum_d5 cap-hit only`.
- Gate 4: complete (canonical ok; 5/5 random, greedy, SA batches with
  per-seed completed counts equal to N_RANDOM_SEED/GREEDY_ITERS/SA_ITERS;
  exact solved with full 256 evaluated; enum_d5 cap-hit with full cap or
  solved; all threshold rows length 3) AND payload wall < WALL_LIMIT_S =
  500 s AND zero skip records. Coded exactly as
  `complete && wall < 500 && zero skips`.
- Dry-run probe (/tmp/s02dry2, reconfirmed clean): wall 71.9 s, zero
  skips. G1 pass (canonical d_eff 3, 120 CNOTs; exact best 72 CNOTs
  0 flags; greedy reaches 72 on 4/5 seeds; random valid frac 0.0067).
  G2 pass gradient-only (d3 canonical LER strictly increasing over
  p = 0.002/0.005/0.01; d5 canonical strictly increasing; best/noflag
  rows recorded). G3 pass (exact 256/256 solved d=3; enum_d5 cap-hit
  150/150). G4 pass (complete, wall < 500, clean). Pursue-condition
  true (found valid d_eff == 3 schedule with fewer CNOTs than
  canonical).

Gates (exact coded definitions):
- G1: `canon_valid && exact_valid && rand_frac < 1.0`.
- G2: `grad strictly increasing d3 canonical AND d5 canonical`.
- G3: `exact solved AND enum_d5 cap-hit only` — a solved d5 target
  fails.
- G4: `complete && wall < 500 && zero skips`.

Budgets: wall 900 s, cpu 5400 s (reservation basis; same generous
staging as screen 20). Payload keeps wall ~72 s (probed 71.9 s) via
ordering (self-test, layout, random, greedy, SA, exact, enum_d5,
threshold d3, threshold d5) plus a WALL_GUARD_S = 300 s elapsed guard
checked before every seed batch, every mutation iteration, every exact
mask, every enum_d5 step, and every threshold point. Each batch publishes
its completed count (n_evaluated/iters_done) alongside the configured
total, and EVERY truncated batch or segment appends a wall-guard skip
record, including exact entry-guard failure ("exact-remaining") and enum
guard exits ("enum-d5-remaining"), so a guard-truncated run cannot pass
G4 clean. results.json is written
at normal completion; witnesses/selftest.json is written after the
self-test and witnesses/checkpoint-<tag>.json after layout, random,
greedy, sa, exact, enum, thr-d3, and thr-d5, so a supervisor stop still
leaves classifiable evidence. Every skip path publishes (guarded
lookups, default-empty records, no unbound variables). WALL_LIMIT_S =
500 s is the Gate-4 wall bound.

Baseline disclosure: no MILP/SMT comparison anywhere in this screen; the
exact baseline is flag-subset enumeration on d=3 (solved 256/256 counts
as optimum) and the per-stabilizer capped enumeration on d=5 (cap-hit
record counts as limit-expiry, never as optimum). There is no
OLSQA/Vandaele/Lau/PhasePoly/torch implementation anywhere in this
screen.

Limitation (disclosed): the search moves are single-stabilizer only
(swap two order positions or flip one flag bit); joint multi-stabilizer
order structure is unexplored. Wider order neighborhoods, weight-6+
gadgets, and d=7 transfer are the recorded next experiments.

Acceptance (exact coded conditions): PURSUE iff found_better (a valid
d_eff == 3 schedule with strictly fewer CNOTs than canonical on d=3)
AND g1 AND g2 AND g3 AND g4 AND selftest_ok. REJECT iff complete AND
canon_valid AND NOT found_better. Else UNRESOLVED + next experiment
(wider order neighborhoods, weight-6+ gadgets, d=7 transfer).
Pursue/reject classification is coordinator-side; the payload reports
numbers + gate evidence and its verdict field is always
unresolved-with-reason. Deterministic given seeds.
