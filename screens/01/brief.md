# Screen 01 — qLDPC BP-guiding follow-up (re-staged: pheno autopsy + hardness frontier)

Hypothesis: serial/damped min-sum perturbations hurt under phenomenological
X-noise because damping slows convergence inside the fixed 30-iteration
budget (non-converged syndromes count as logical fails), while serial
scheduling helps on circuit DEM noise; an over-relaxed (boosted) min-sum
family tests this mechanism from the opposite side.

Corpus (frozen):
- Phenomenological X-noise p=0.06 on HGP(rep(d),rep(d)), d in {3,5,7,9,11}.
  n=13/41/85/145/221. 300 held-out syndromes per (d,seed), seeds 1-5.
  PHENO_D=(3,5,7,9,11), PHENO_P=0.06, PHENO_N=300, SEEDS=(1,2,3,4,5).
- Circuit noise via stim `rotated_memory_x`, d in {3,5}, rounds=d, p=0.005.
  300 shots per (d,seed), seeds 1-5.
  CIRCUIT_D=(3,5), CIRCUIT_ROUNDS="d", CIRCUIT_P=0.005, CIRCUIT_N=300.
- Arms: A, B1, B2, B3, C, R. ARMS=("A","B1","B2","B3","C","R").
  MAX_ITER=30. LAT_CAP_US=5000.0.

Controls:
- R null decoder (all-zeros estimate). Gate 1: standard BP (arm A) must beat R
  everywhere (every pheno cell, strictly fewer logical fails).
- Exact MLD via pulp 4 model-owned API + COIN_CMD (threads=1). d=3 single
  syndrome limit MLD_D3_LIMIT=30 s, status must read exactly Optimal.
  Frontier: d=7 x MLD_D7_COUNT=12 syndromes, d=9 x MLD_D9_COUNT=8, d=11 x
  MLD_D11_COUNT=8, each limit MLD_FRONTIER_LIMIT=10 s. Gate 3 holds iff d=3
  is Optimal AND >=1 frontier syndrome (d7/d9/d11) shows the solver's own
  explicit TimeLimit status (any other non-Optimal status, including build
  errors, does NOT count).
- Decoders receive per-bit channel probabilities everywhere (uniform-p list
  for pheno, DEM mechanism priors for circuit, recorded mean-prior fallback).

Arms (all BP max_iter=30; C is the cap-exempt reference, reported only):
- A: parallel / min-sum / scale 1.0 (standard BP). BP_CONF A=("parallel",1.0).
- B1: serial / min-sum / scale 1.0 (frozen serial reference).
  BP_CONF B1=("serial",1.0).
- B2: parallel / min-sum / scale 1.25 (AUTOPSY FAMILY: over-relaxed/boosted).
  BP_CONF B2=("parallel",1.25).
- B3: serial / min-sum / scale 1.25 (AUTOPSY FAMILY: boosted x serial).
  BP_CONF B3=("serial",1.25).
- C: BP-OSD order 2, max_iter 30 (reference, latency-cap-exempt, reported).
  BP_CONF C=("bposd","osd_cs",2).
- R: null control.

Autopsy mechanism (frozen): prior means show converge_fails rising with
damping/serial updates (e.g. d3 seed2 converge A=17/B1=21/B2=21/B3=34) while
circuit B1 recovers +79% (d3) / +68% (d5). Frozen autopsy metrics per arm per
size: converge-fail share (converge_fails/n pooled over seeds) alongside
recovery fractions. If boosted scales converge faster and recover more, the
budget mechanism is supported; if boosted also hurts, the schedule itself
(not the rate) is indicted. No re-scope: the pheno pursue bar below is
unchanged (a circuit-only re-scope was NOT chosen).

Circuit observable mechanism (exact, no proxy): syndromes AND true observable
flips come from `circuit.compile_detector_sampler(seed=seed)` with
`separate_observables=True`. The DEM (`detector_error_model(decompose_errors=True)`)
is parsed with stim handles only (no `ldpc.ckt_noise` dependency) into a binary
check matrix H_dem, observable matrix L_obs, and per-mechanism priors. BP/BP-OSD
decode each shot's detection events on H_dem; predicted observable =
L_obs @ estimate (mod 2); logical fail = syndrome mismatch (convergence failure)
OR predicted-observable != true observable. If DEM parsing yields no usable
matrix or the sampler API fails, the payload records the circuit arm as
UNRESOLVED-blocked with the named blocker instead of fabricating a proxy metric.

Acceptance (frozen Pareto, per-arm exact counting): PURSUE iff there exists one
B arm b in {B1,B2,B3} such that at >=2 pheno sizes d, pooled over seeds,
gap_d=(fail_A-fail_C)>0 AND recovered_{b,d}=(fail_A-fail_b)/gap_d>=0.25 AND
mean latency of arm b at size d <= LAT_CAP_US=5000.0 us, AND pooled circuit
gap>0 at >=1 circuit size, AND Gates 1,2,4 pass AND Gate-3 CBC expiry holds.
Counting is per-arm (the SAME arm b at >=2 sizes; no cross-arm pooling).
REJECT iff all gates are evidenced but no B arm reaches 0.25 at any pheno
size. Else UNRESOLVED + next experiment. Pursue/reject classification is
coordinator-side; the payload reports numbers + gate evidence and its verdict
field is always unresolved-with-reason, whose reason carries NEXT_EXPERIMENT
verbatim (byte-identical).

Gates (payload-computed, evidence-linked in results.json):
- Gate 1: arm A logical fails < arm R logical fails in every pheno cell
  (25 cells). Coded exactly as `all_A_lt_R`.
- Gate 2: non-flat deltas — pooled per pheno size across {A,B1,B2,B3,C},
  max-min logical-fail rate across arms exceeds 2x binomial SE at >=2 sizes.
  Determinism self-tests + corpus sha + repeat-decode check are control
  evidence. Coded exactly as `n_sizes_spread_pass >= 2`.
- Gate 3: d=3 MLD status exactly Optimal AND >=1 frontier (d7/d9/d11) MLD
  status exactly TimeLimit. Coded exactly as `d3_optimal && frontier_timelimit`.
- Gate 4: completeness — every planned cell (210 = 150 pheno + 60 circuit)
  has n=300 tallies with timing and no skipped/blocked flag, payload wall <
  WALL_LIMIT_S=500.0 s, zero skip records. Coded exactly as
  `complete && wall < 500 && zero skips`.

Budgets: wall 900 s, cpu 5400 s (reservation basis). The supervisor admits
min(wall - screen_wall_used, run-remaining, cpu-remaining/capacity), minus
8.5 s handshake/termination/finalization overhead. WALL_GUARD_S=300.0 s
elapsed guard is checked before every size, every cell, every arm, and every
MLD solve. Tripped work is marked skipped explicitly (each skip carries
iters_done/n_evaluated) and completeness Gate 4 then fails honestly. A
`stopped` flag propagates: once any guard trips, all later phases
(tiny/target MLD callers first) skip immediately with explicit skip records.
results.json is written at normal completion; after each phase the payload
additionally writes witnesses/checkpoint-<phase>.json with the accumulated
tallies, so a supervisor stop still leaves classifiable evidence (same gate
rules apply coordinator-side). Every skip path publishes (guarded corpus
lookups, default d3 record). Solver None-results are normalized by an
explicit None-guard (a forced-None mock probe in self-tests proves it).

Baseline disclosure: no MILP/SMT/OLSQA/Vandaele/Lau/PhasePoly/torch anywhere
in this screen; the exact baseline is pulp COIN_CMD MLD (own solved record on
d3 counts as optimum; own frontier TimeLimit record counts as limit-expiry,
never as optimum). Blocker libraries are absent by construction.

NEXT_EXPERIMENT: Sweep max_iter over {30,100,300} for the winning B family at the two largest pheno sizes to separate convergence-budget effects from schedule effects, holding all other frozen symbols unchanged.
