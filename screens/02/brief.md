# Screen 02 scale-up — flag-gadget schedule search at d=3/5/7 (staged scale-up payload)

Design: screen-authored schedule search on a stim-transcribed
rotated-surface-code tiling (stim 1.16.0 + stdlib + numpy only; no
external search or physics libraries). Per stabilizer a CNOT order
(data-qubit to layer-slot assignment within the transcribed layer
skeleton) and a flag bit {0,1} (full-bracket flag: open before the
first data CNOT, close after the last). No Vandaele, Lau et al.,
PhasePoly, torch-policy, MILP, SMT, or OLSQA code exists anywhere in
this screen (named blockers, same as all screens).

Hypothesis: the d=3 overhead win (transcribed order + zero flags:
72 CNOTs/8 ancillas at d_eff == 3 vs canonical 120/16) transfers to
d=5 and d=7 — wider commutation-order neighborhoods (pair moves
spanning 6+ data qubits) and weight-6+ stabilizer gadget contexts
preserve effective distance at strictly lower CNOT overhead than the
all-flags canonical at larger distances, with LER tracking canonical
across matched p and cap-hit evidence at d=5-class enumeration.

Anchor record to beat/reproduce (certified d=3): canonical 120
CNOTs/16 ancillas vs exact 72 CNOTs/8 ancillas at d_eff == 3 (256/256,
greedy 4/5 seeds, random valid fraction 0.0067, LER tracks canonical
across p in (0.002, 0.005, 0.010)).

Model (screen-authored):
- Layout MUST be transcribed: `transcribe_layers` derives data qubits,
  per-stabilizer layer slots, and the logical set from
  `stim.Circuit.generated("surface_code:rotated_memory_x")`. Hand-tiling
  broke commutation; the self-test asserts the transcribed layouts
  commute at d=3/5/7 (9/8, 25/24, 49/48 data/stabilizers), asserts
  per-stabilizer layer fidelity against an independent parse of stim's
  own TICK-layer CNOT blocks at the exact layer index, and asserts a
  naive hand-tiling slot assignment differs from the transcribed slots.
- Schedule space per stabilizer: data-qubit to layer-slot assignment
  (transcribed layer skeleton fixed) x flag {0,1}, full-bracket flags.
  The emitted d=3 canonical circuit is parsed back to bracket events
  and asserted full-bracket (open first, close last on every flagged
  stabilizer; middle-placement predicate false), with synthetic
  positive/negative controls proving the predicate discriminates.
- Canonical schedule = transcribed order + flags everywhere
  (screen-authored transcription of the Reichardt/Chamberland flag
  prescription, verified valid in-sim with d_eff == d at all sizes).
- Transfer schedule = transcribed order + zero flags (the d=3
  exact-optimum pattern lifted to d=5/d=7).
- Metric: effective distance d_eff via stim `shortest_graphlike_error`
  at fixed circuit noise (`ValueError` = nondeterministic = invalid),
  then total CNOT overhead at preserved d_eff. `better(a, b)` = higher
  d_eff wins, ties break to fewer CNOTs.
- Noise (circuit-level, as coded in `build_memory`): DEPOLARIZE1(p)
  after each 1q gate, DEPOLARIZE2(p) after each CNOT, X_ERROR(p) after
  each measurement; prep RX/R. ROUNDS = 3, P_NOISE = 0.005.
- Arms per size (code truth; later constant block governs):
- canonical point (transcribed order + flags everywhere) at d=3/5/7.
- transfer point (transcribed order + zero flags) at d=3/5/7.
- random: N_RANDOM_SEED_D3/D5/D7 = 60/20/8 rollouts/seed over the full
  space (single-stabilizer-plus-flag sampling; pair structure enters
  only via greedy/SA wide moves).
- greedy: from canonical at d=3 (GREEDY_ITERS_D3 = 60 iters/seed,
  single-stabilizer moves, byte-identical RNG stream to the certified
  screen) and d=5 (GREEDY_ITERS_D5 = 20, single+pair moves); from
  transfer at d=7 (GREEDY_ITERS_D7 = 10, single+pair moves).
- SA: from a random start, SA_ITERS_D3/D5/D7 = 50/20/10 iters/seed,
  SA_T0 = 1.0, SA_ALPHA = 0.97; single moves at d=3, single+pair at
  d>=5. Pair moves span joint data support of up to 8 qubits (6+
  recorded in self-tests + results).
- exact: flag-subset enumeration 2^8 = 256 on d=3 (transcribed order
  fixed, flag mask swept; must solve 256/256).
- enum_d5: per-stabilizer capped enumeration on d=5, cap
  ENUM_CAP_EVALS = 150 (must cap-hit; a solved or stopped-guard d5
  target fails Gate 3).
- threshold: pseudo-threshold sampling on canonical + size-best at each
  size over P_GRID = (0.002, 0.005, 0.01), N_SHOTS = 20000 via
  `compile_sampler` + `compile_m2d_converter` with
  `separate_observables=True` on the convert call. The self-test
  asserts sampler output width equals num_measurements (57 at d=3
  canonical) while converter observable width equals num_observables
  (1), proving the LER path measures detectors, not raw measurements.
- Seeds SEEDS = (1, 2, 3, 4, 5); d=3 salts (11, 13, 17, 19) reproduce
  the certified RNG streams exactly; d=5 salts (21, 23, 27, 29) and
  d=7 salts (31, 33, 37, 39) are fresh.
- Soundness: determinism check (canonical evaluated twice, must match);
  eval-shape check; layout-counts and commute checks at all sizes in
  `self_tests`; anchor check (canonical 120/16, exact best 72,
  greedy 72-hits >= 4, exact total 256) folds into selftest_ok and FAILS
  the payload if the d=3 numbers do not reproduce.

Frozen symbols (byte-identical brief<->code):
SEEDS = (1, 2, 3, 4, 5)
P_NOISE = 0.005
ROUNDS = 3
P_GRID = (0.002, 0.005, 0.010)
N_SHOTS = 20000
D_SIZES = (3, 5, 7)
N_RANDOM_SEED_D3 = 60
N_RANDOM_SEED_D5 = 20
N_RANDOM_SEED_D7 = 8
GREEDY_ITERS_D3 = 60
GREEDY_ITERS_D5 = 20
GREEDY_ITERS_D7 = 10
SA_ITERS_D3 = 50
SA_ITERS_D5 = 20
SA_ITERS_D7 = 10
SA_T0 = 1.0
SA_ALPHA = 0.97
ENUM_CAP_EVALS = 150
WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0
SALT_D3_RANDOM = 11
SALT_D3_GREEDY = 13
SALT_D3_SA = 17
SALT_D3_SA_NP = 19
SALT_D5_RANDOM = 21
SALT_D5_GREEDY = 23
SALT_D5_SA = 27
SALT_D5_SA_NP = 29
SALT_D7_RANDOM = 31
SALT_D7_GREEDY = 33
SALT_D7_SA = 37
SALT_D7_SA_NP = 39
ANCHOR_CANON3_CNOTS = 120
ANCHOR_CANON3_ANC = 16
ANCHOR_BEST3_CNOTS = 72
ANCHOR_GREEDY3_HITS = 4
EXACT_TOTAL_D3 = 256

Controls (gates computed from serialized cells in work/results.json):
- Gate 1: canon_valid at d=3 AND d=5 AND d=7 (canonical ok with
  d_eff == d) AND exact_valid (exact best d_eff == 3) AND random valid
  fraction at d=3 < 1.0 (search space discriminative) AND anchor_ok
  (canonical 120/16, exact total 256 solved with best 72 at d_eff 3,
  greedy 72-hits >= 4). Coded exactly as
  `all-canon-valid && exact_valid && rand_frac_d3 < 1.0 && anchor_ok`.
- Gate 2: gradient-only — LER strictly increasing over the p grid on
  the canonical rows at d=3 AND d=5 AND d=7. Every recorded threshold
  row (canonical + best per size) carries its own strictly-increasing
  flag. Coded exactly as `grad d3 canonical && grad d5 canonical &&
  grad d7 canonical`.
- Gate 3: exact solved (256/256 evaluated on d=3) AND enum_d5 status is
  exactly "cap-hit" (150/150, limit-expiry). A solved or stopped-guard
  d5 target fails Gate 3. Coded exactly as
  `exact solved && enum_d5 cap-hit only`.
- Gate 4: complete (all serialized cells present with full counts:
  d3 random/greedy/SA, d5 random/greedy/SA, d7 random/greedy/SA,
  exact solved, enum_d5 cap-full, all six threshold rows length 3) AND
  payload wall < WALL_LIMIT_S = 500 s AND zero skip records. Coded
  exactly as `complete && wall < 500 && zero skips`.

Budgets: wall 900 s, cpu 5400 s (reservation basis; same generous
staging as screens 19/20). Payload keeps wall ~150-250 s (d3 anchor
~72 s + d5/d7 search + threshold) via ordering (self-test, layout,
fixed canon/transfer, d3 random/greedy/SA, exact, d5
random/greedy/SA, enum, d7 random/greedy/SA, thresholds) plus a
WALL_GUARD_S = 300 s elapsed guard checked before every seed batch,
every mutation iteration, every exact mask, every enum_d5 step, and
every threshold point. EVERY guard exit appends an explicit skip record
with iters_done/n_evaluated (points done/total on threshold rows,
configured totals on entry-guard failures) and stopped=True, including
exact entry-guard ("exact-remaining") and enum guard exits
("enum-d5-remaining") and per-seed batch entry guards, so a
guard-truncated run cannot pass G4 clean. results.json is written at
normal completion; witnesses/selftest.json is written after the
self-test and witnesses/checkpoint-<tag>.json after layout, fixed,
each size-arm phase, exact, enum, and each threshold, so a supervisor
stop still leaves classifiable evidence. Every skip path publishes
(guarded lookups, default-empty records, no unbound variables, no
variable aliasing across distinct roles in any transition function;
regression self-tests cover the greedy fallback repair path, the
better() None/tie-break controls, and input-immutability under all
three mutation operators). WALL_LIMIT_S = 500 s is the Gate-4 wall
bound.

Baseline disclosure: no MILP/SMT comparison anywhere in this screen;
the exact baseline is flag-subset enumeration on d=3 (solved 256/256
counts as optimum) and the per-stabilizer capped enumeration on d=5
(cap-hit record counts as limit-expiry, never as optimum). There is no
OLSQA/Vandaele/Lau/PhasePoly/torch implementation anywhere in this
screen.

Limitation (disclosed): the search moves are single-stabilizer (swap
two order positions or flip one flag bit) at d=3 and single+pair
(two-stabilizer joint moves) at d>=5; joint order structure beyond
pairs is unexplored. d=7 is transfer-plus-short-refinement only (no
d=7 exact enumeration — 2^48 masks are intractable, recorded as the
reason Gate 3 stays d=5-class).

Acceptance (exact coded conditions): PURSUE d=3-bounded iff some d=3
arm jointly wins (valid d_eff == 3 schedule with strictly fewer CNOTs
than canonical) AND g1 AND g2 AND g3 AND g4 AND selftest_ok (anchor
included). Extension to d=7 iff pursue_d3 AND some d=7 arm jointly
wins (transfer counts). REJECT iff complete AND canon_valid at all
sizes AND no d=3 joint win. Else UNRESOLVED + next experiment.
Pursue/reject classification is coordinator-side; the payload reports
numbers + gate evidence and its verdict field is always
unresolved-with-reason. Deterministic given seeds.
NEXT_EXPERIMENT: scale to d=9 with depth-regularized joint order+flag search under hardware-calibrated noise, with exact-synthesis timeout probes at d=9.
