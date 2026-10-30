# Screen 14 — Distributed multi-QPU optical interconnect & teleportation scheduling

Design: screen-authored deterministic multi-QPU teledata/telegate
scheduling model (stdlib + numpy only; no external physics, solver,
or policy libraries). N_QPU = 3 modular QPUs share all-to-all
optical links with finite per-slot EPR generation rates, finite
link buffers, and a link buffer coherence cutoff. Each cell replays
frozen remote two-qubit op lists under one seeded channel
realization per rep (precomputed success table shared by every arm
and every lookahead trial, so arm equivalence holds by
construction). Probabilistic links are modeled ONLY via seeded
deterministic draws, never unseeded randomness. No MILP, SMT,
OLSQA, Vandaele, Lau et al., PhasePoly, or torch code exists
anywhere in this screen (named blockers, same as all screens).

Hypothesis: dynamically partitioning teledata (qubit teleportation)
vs telegate (remote CNOT) operations across modular QPUs linked by
slow, probabilistic EPR channels beats static min-cut graph
partitioning. Continue only if joint teledata/telegate lookahead
beats static min-cut-style placement across multiple EPR rates.

Model (screen-authored):
- QPUs: N_QPU = 3 fixed (of the 2-4 range); frozen round-robin
  qubit placement (qubit q on QPU q % N_QPU); the static arm never
  moves it (min-cut-style frozen cut, all-telegate FIFO).
- Benchmarks BENCHMARKS = (ghz14, qft12, vqe12); BENCH_QUBITS =
  (14, 12, 12); N_REMOTE_OPS = (10, 12, 10). ghz14 is a seeded star
  around qubit 0, qft12 a seeded-offset chain, vqe12 seeded random
  remote pairs; every listed op is remote under placement.
- Rates EPR_RATES = (0.2, 0.5, 0.8) per-pair per-slot success.
  Links: LINK_BUF = 2 buffered pairs, COH_CUTOFF = 6 slots (older
  pairs expire), GATE_OVERHEAD = 1 slot telegate classical round,
  MAX_SLOTS = 400. Teledata relocates the moving qubit to the
  anchor QPU (later ops may go local and cost nothing).
- Metric: frozen cost = W_STALL x total link wait + W_EXP x buffer
  expiries past cutoff + W_TD/W_TG per remote teledata/telegate
  (W_STALL = 1.0, W_EXP = 3.0, W_TD = 1.0, W_TG = 2.0) + schedule
  validity (dep order, EPR balance, relocation consistency).
- Arms (code truth):
- M: static min-cut-style baseline — frozen placement, all
  telegate, program-order FIFO link consumption.
- R: random control — seeded random teledata/telegate partition +
  seeded random consumption priority.
- G: greedy lookahead scheduler — left-to-right partition search,
  each candidate scored by a window rollout of that op plus the
  next LOOKAHEAD = 3 ops (prefix-closed, telegate default beyond
  fixed modes) on the shared seeded channel; ties go telegate.
- A: annealing over partition + consumption order (ANNEAL_ITERS =
  150, A_T0 = 1.0, A_ALPHA = 0.99) from the G start, best tracked,
  so A never regresses G.
- Seeds SEEDS = (1, 2, 3, 4, 5); N_INST = 40 reps per cell
  (45 cell-arms per rate, 180 cell-arms, 7200 arm evaluations over
  1800 circuits). Seeds are replicates.
- Soundness: tiny 2-QPU hand-check [CNOT(0,1) x2, always-generate
  channel] with known costs M = 4.0 / G = 1.0 by construction
  (teledata co-locates, second op goes local). M/G match; A
  invariant (>= G means cost <= G); R recorded but random by design
  (not hand-gated) + exact-opt optimum 1.0 on tiny + determinism
  (same seed repeated gives identical G and R).
- Frozen symbols (code identifiers match exactly): N_QPU,
  BENCHMARKS, BENCH_QUBITS, N_REMOTE_OPS, EPR_RATES, SEEDS, ARMS,
  W_STALL, W_EXP, W_TD, W_TG, LINK_BUF, COH_CUTOFF, GATE_OVERHEAD,
  MAX_SLOTS, LOOKAHEAD, ANNEAL_ITERS, A_T0, A_ALPHA, N_INST,
  EXACT_CAP, WALL_GUARD_S, WALL_LIMIT_S, TINY_N_QPU, TINY_PLACE,
  TINY_OPS, TINY_P, TINY_EXP_COST_M, TINY_EXP_COST_G, TARGET,
  NEXT_EXPERIMENT.

Controls:
- Gate 1: mean cost(G) strictly below mean cost(R) in every one of
  the 45 (benchmark, rate, seed) cells (pipeline discriminative)
  AND tiny hand-check (M/G exact, A invariant) AND determinism
  repeat identical. Coded exactly as
  `beats_all_45 && tiny_ok && determinism_ok`.
- Gate 2: pooled cost spread across {M,G,A} > 2*SE at >= 2 EPR
  rates (pools = 15 cell means per rate per arm). Coded exactly as
  `n_rates_spread_pass >= 2`.
- Gate 3: bounded-exact scheduling search solves the tiny instance
  (status solved, optimum cost == 1.0 hand value) AND the target
  instance (vqe12 bench, rate 0.5, seed 1 rep 0, node cap 50000)
  reports exactly "cap-hit" (probed 50001 nodes). Only cap-hit
  counts as limit-expiry; a solved, stopped-guard, or skipped-guard
  target fails Gate 3. A wall-kill or missing baseline never
  counts. If exact search cannot reach limit-expiry at these
  scales, Gate 3 CANNOT pass and the screen caps at UNRESOLVED.
  Coded exactly as `tiny_solved && target_caphit_only`.
- Gate 4: complete (all 45 cells x 4 arms with n == N_INST; tiny +
  target records present) AND payload wall < WALL_LIMIT_S = 500 s
  AND zero skip records. Coded exactly as
  `complete && wall < 500 && zero skips`.

Budgets: wall 900 s, cpu 5400 s (reservation basis; same generous
staging as screens 19/13). Payload keeps wall to ~1 min via a
compact corpus (<= 12 remote ops per rep) plus a WALL_GUARD_S =
300 s elapsed guard checked before every rate, every cell, every
arm loop, every 32 reps, every 32 annealing proposals, and every
512 exact-solver nodes. Each batch publishes its completed count,
and EVERY guard exit appends an explicit skip record with
iters_done/n_evaluated, including tiny/target entry-guard failures
("tiny-exact", "target-exact"), tiny/target stopped-guard returns,
and per-cell / per-rate guard exits, so a guard-truncated run
cannot pass G4 clean. All arms propagate stopped=True on a mid-arm
guard trip. results.json is written at normal completion;
witnesses/selftest.json after the self-test,
witnesses/gate3_tiny.json + gate3_targets.json after the exact
phases, witnesses/cells.json after each rate, and
witnesses/checkpoint-<tag>.json after tiny, targets, each rate,
and the corpus, so a supervisor stop still leaves classifiable
evidence. Every skip path publishes (guarded lookups,
default-empty records, no unbound variables). WALL_LIMIT_S = 500 s
is the Gate-4 wall bound. The payload accepts test-only --n-inst /
--anneal-iters overrides for dry-run calibration; the supervised
command line passes neither, so frozen N_INST = 40 and
ANNEAL_ITERS = 150 govern.

Baseline disclosure: no MILP/SMT comparison anywhere in this
screen; the exact baseline is the bounded-exact scheduling search
over partition + consumption order (own solved record on tiny
counts as optimum for the tiny instance; own cap-hit record at
target scale counts as limit-expiry, never as optimum). There is no
OLSQA/Vandaele/Lau/PhasePoly/torch implementation anywhere in
this screen.

Limitation (disclosed): modeled QPUs only (round-robin placement,
Bernoulli link model, no device maps), synthetic remote-op lists,
frozen scalar cost weights (no full fidelity model), no hardware
claim; wins come from teledata/telegate + order choices only.
Next experiment: adaptive EPR buffering with
entanglement-distillation retries + cross-benchmark transfer
retest.

Acceptance (exact coded conditions): PURSUE iff some arm in {G,A}
jointly wins at >= 2 EPR rates, where arm X jointly wins a rate iff
pooled mean cost(X) beats M by > 2*SE over {M,G,A} AND pooled mean
validity(X) >= pooled mean validity(M) — both on the SAME arm; a
cost-only win with degraded validity is NOT a joint win. Joint
wins are counted PER ARM, bar is max(G,A) >= 2, never a
per-instance any-winner count. Also required: Gates 1, 2, 3, 4
pass AND self-tests ok. REJECT iff complete AND tiny solved AND
Gate-1 controls pass AND no strict pooled cost win (G or A mean <
M mean) at any rate. Else UNRESOLVED + next experiment (adaptive
EPR buffering with entanglement-distillation retries +
cross-benchmark transfer retest). Pursue/reject classification is
coordinator-side; the payload reports numbers + gate evidence and
its verdict field is always unresolved-with-reason. Deterministic
given seeds.
