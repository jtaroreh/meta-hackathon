# Screen 01 — qLDPC BP-guiding (re-staged in run 87b79c06198749628ea3f77e7f16c3cb; host cbc 2.10.13 on PATH, brief unchanged otherwise)

Hypothesis: normalized/serial min-sum perturbations recover part of the BP-to-BP-OSD
gap on held-out syndromes within a fixed per-syndrome latency cap.

Corpus (frozen):
- Phenomenological X-noise p=0.06 on HGP(rep(d),rep(d)), d in {3,5,7}
  (n=13/41/85, k=1). 300 held-out syndromes per (d,seed), seeds 1-5.
- Circuit noise via stim `rotated_memory_x`, d in {3,5}, rounds=d, p=0.005.
  300 shots per (d,seed), seeds 1-5.

Controls:
- R null decoder (all-zeros estimate). Gate 1: standard BP (arm A) must beat R
  everywhere (every pheno cell, strictly fewer logical fails).
- Exact MLD via pulp 4 model-owned API + COIN_CMD (threads=1). Gate 3: d=3
  single syndrome status Optimal (timeLimit 30 s); d=7 per-syndrome 10 s limit
  must show the solver's explicit TimeLimit status on at least one syndrome
  (any other non-Optimal status, including build errors, does NOT count).
- Decoders receive per-bit channel probabilities everywhere (uniform-p list for
  pheno, DEM mechanism priors for circuit, recorded mean-prior fallback).

Arms (all BP max_iter=30; C is the cap-exempt reference, reported only):
- A: parallel / min-sum / scale 1.0 (standard BP).
- B1: serial / min-sum / scale 1.0.
- B2: parallel / min-sum / scale 0.625.
- B3: serial / min-sum / scale 0.625.
- C: BP-OSD order 2, max_iter 30 (reference, latency-cap-exempt, reported).

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

Acceptance (frozen Pareto): PURSUE iff best B recovers >=25% of the
(fail_A - fail_C) gap at >=2 pheno sizes with mean latency <=5000 us AND gap>0
at >=1 circuit size AND Gates 1,2,4 pass AND Gate-3 CBC expiry at d=7.
REJECT iff all gates evidenced but gap<25% everywhere. Else UNRESOLVED + next
experiment. Pursue/reject classification is coordinator-side; the payload
reports numbers + gate evidence and its verdict field is always
unresolved-with-reason.

Gates (payload-computed, evidence-linked in results.json):
- Gate 1: arm A logical fails < arm R logical fails in every pheno cell.
- Gate 2: non-flat deltas — pooled per pheno size across seeds, max-min
  logical-fail rate across {A,B1,B2,B3,C} exceeds 2x binomial SE at >=2 sizes.
  Determinism self-tests + corpus sha + repeat-decode check are control evidence.
- Gate 3: d=3 MLD status Optimal AND >=1 d=7 MLD status shows solver limit-expiry.
- Gate 4: completeness — every planned (code,noise,seed,arm) cell has n=300
  tallies with timing, and payload wall time <500 s.

Budgets: wall 900 s, cpu 5400 s (reservation basis; raised from 600/3600
after 01-review-attempt2 showed review burn shrinking the admitted window
below a 300 s guard under 600/3600 staging). The supervisor admits
min(wall - screen_wall_used, run-remaining, cpu-remaining/capacity), minus
8.5 s handshake/termination/finalization overhead: with 900/5400 on
10-capacity, a prompt select->launch (~350 s of review) still admits
~540 s, so the 300 s elapsed guard (checked at every cell and before each
MLD solve) fires with ample finalization reserve. Ordering: pheno,
circuit, MLD d=3, MLD d=7. Tripped work is marked skipped explicitly and
completeness Gate 4 then fails honestly. results.json is written at normal
completion; after each phase the payload additionally writes
witnesses/checkpoint-<phase>.json with the accumulated tallies, so a
supervisor stop still leaves classifiable evidence (same gate rules apply
coordinator-side). Every skip path publishes (guarded corpus lookups,
default d3 record).
