# Handoff — overnight screening loop, run f5ac1866b1794567ad299c518a43a391

Date: Thu Oct 29 2026 ~18:35 PDT. Checkout:
`/Users/joeltaroreh/projects/challenges/meta-hackathon`
(interpreter `.venv/bin/python`). Previous thread stopped here by operator
request; background dry-run killed (was /tmp scratch only, nothing lost).

## Run state

- Active run: `f5ac1866b1794567ad299c518a43a391`
  (created ~15:19 PDT, deadline 23:15:57 PDT = epoch 1793340957,
  no-launch cutoff ~23:00 PDT). Envelope: `overnight-envelope.json`
  (root) + copy in `verify-evidence/f5ac1866…/overnight-envelope.json`.
- CPU: 7800/28800 reserved; actual spend tiny (prepare 0.6 s, pilot 4.5 s,
  screen-01 13.8 s). Capacity 10.
- Provider attempts used: postpilot review 1/2, screen-01 review 1/2,
  screen-15 reviews 2/2 (EXHAUSTED — do not re-review 15 in this run),
  screen-20 review 1/2 (PASS filed).
- Memory gate (select/run need ≥4 GiB available): BLOCKED at ~3.8 GiB
  most of the evening (user interactive apps; protected — do not kill;
  `purge` needs root, refused). **CLEARED at ~18:35 PDT (5.88 GiB).**
  Launch window likely open — verify with `status`/select and move fast.

## Do FIRST on pickup (in order)

1. `cd` checkout; `.venv/bin/python -B -m tools.overnight.run_one status`
   (confirms envelope + memory).
2. Select + run screen 20 IMMEDIATELY (review PASS already filed,
   receipt `overnight-data/f5ac1866…/receipts/screen-20-review.json`,
   screen_files `10974c30…`). Commands:
   `.venv/bin/python -B -m tools.overnight.run_one select 20`
   then `sh screens/20/run.sh` (or `run_one run 20`).
   If select still blocked on memory, wait/retry — do NOT reboot/kill apps.
3. After run 20 finishes: classify per its reason field, update
   `results/verdicts.md`.
4. Screen 02: rerun dry run to reconfirm (was killed mid-run):
   `mkdir -p /tmp/s02dry2 && cd /tmp/s02dry2 && <root>/.venv/bin/python -B
   <root>/screens/02/src/run02.py --attempt dry --data dry`
   then inspect results.json gates (expect pursue True after G2 fix).
   Then write `screens/02/brief.md`, `command.json` (wall 900/cpu 5400,
   scope research, source_files ["src/run02.py"]), `run.sh` (standard,
   runs `run_one run "02"`), compute hash via
   `tools.overnight.receipts.screen_artifacts(<absroot>, '02')`,
   select 02, delegate review (advisor codex-pstack/gpt-6.1-sol,
   high/default, READ-ONLY, attempt 1 of 2), file receipt on PASS,
   run, classify.

## Screen states

- 18: DONE (pilot). 01: DONE (ran 14.3 s, UNRESOLVED — Gate3 FALSE:
  d7 MLD ~10 ms via CBC, no timeout; Gate1 True; Gate2 True 3/3).
  06: DONE (UNRESOLVED — Gate1 fails 9/15 random beats greedy A*).
  10: BLOCKED (no OLSQA figures/data anywhere).
- 15: DEFERRED this run (2/2 reviews used: attempt1 FAIL
  unfuse/copy/DFS-terminal/Pareto/R/75-vs-45; attempt2 FAIL F1 vacuous
  solve + F3 arm-guard overclaim + F4 beam-dedupe sentence).
  Post-review staging fixes APPLIED (solved requires optimum_twoq;
  stop() threaded through all arms/fallback loops with stopped-guard;
  brief corrected). New screen_files
  `d1970c841df379f9b26ef5d4542fe08ec3e0b04400bfacf9b4c39ed4a3fd1f26`.
  Carry to NEXT run for fresh review. Evidence:
  `receipts/screen-15-review-attempt2.txt` +
  `verify-evidence/…/screen-15-review-attempt2-FAIL.txt`.
- 20: STAGED + PASS (attempt 1). Dry-run: all gates pass,
  REJECT-direction, wall ~68 s, zero skips. Receipt filed. LAUNCH FIRST.
- 02: PAYLOAD STAGED (`screens/02/src/run02.py`), dry-run validated
  once (wall ~74 s, clean, complete; G1/G3/G4 pass; best 72 CNOTs
  0 flags d_eff=3 vs canonical 120, greedy matched exact optimum
  256/256; G2 restaged gradient-only). Rerun killed pre-reconfirm.
  brief/command/run.sh NOT yet written.
- 04, 07, 12, 19, 24, 03, 05, …: QUEUED, unstaged. Real specs live in
  the FROZEN closure (not the absent external checkout):
  `overnight-data/f5ac1866…/attempts/prepare-…/work/frozen-source/docs/CLOUD_SWARM_RESEARCH_PATHS.md`
  (02 spec §68-78; 04 spec §102; read it before staging).

## Critical technical findings (do not rediscover)

- Screen 02 builder (`run02.py`): layout MUST be transcribed from
  stim's generated circuit (`transcribe()`), NOT hand-tiled (hand tiling
  broke commutation → nondeterministic detectors). Layer emission must
  follow the transcribed per-stab layer slots. Flag bracket MUST be FULL
  (open before first data CNOT, close after last) — middle brackets
  corrupt X syndromes; verified: uniform full bracket, canonical
  d_eff=3, all detectors quiet noiselessly. No-flag transcribed also
  valid (the order is hook-clean; flags are pure overhead here —
  that IS the screen's finding, not a bug).
- stim polyfill notes: `compile_sampler().sample()` returns MEASUREMENTS
  (not detectors); use `compile_m2d_converter().convert(measurements=m,
  separate_observables=True)` for detectors/LER. `compile_detector_sampler()`
  returns detectors only. `shortest_graphlike_error` validates detectors
  first (ValueError = nondeterministic = invalid schedule; catch it).
- Screen 15 lesson: bounded-exact DFS needs depth-aware dedupe
  `(graph, depth, allowance)` key + valid-move terminals + stop-hook in
  extraction loop, else false-solved/cap-blowup. Euler (not unfuse)
  survives `to_graph_like`.
- Screen 20: pool sim, euler-free; F fallback identity (full_reduce
  breaks gflow on 17/45); targets must SOLVE (8q depth-6 solves fast;
  12q too slow for wall) — cap-hit leg removed by design.

## Standing constraints

- One screen at a time; supervised `run_one` only. Max 2 attempts per
  screen-gate (15 exhausted). PASS-only receipts; FAILs archived as
  `screen-<id>-review-attempt<N>.txt` + `verify-evidence/…-FAIL.txt`.
- No substitutions: workhorse muse-spark-1.3-contributor xhigh;
  advisor/takeover codex-pstack/gpt-6.1-sol high/default.
- Reviews via `delegate_task` (role review, mode wait), READ-ONLY.
  Never edit envelope by hand; `status` reconciles.
- End of loop: `recover` + `status`, update `results/verdicts.md`,
  archive envelope copy to `verify-evidence/<run_id>/`.
- Protected: user's interactive processes (Chrome, Antigravity, T3…).
  Never kill by name; only supervisor-owned sessions.
- Attempt dirs are4305 evidence — never delete receipts/proofs.

## Unprocessed remainder of the readiness plan (this thread never got here)

Full queue order (`overnight-config.json`): 18, 01, 06, 10, 15, 20, 02,
04, 07, 12, 19, 24, 03, 05, 08, 09, 11, 13, 14, 16, 17, 21, 22, 23.
After 02, remaining first-wave (same "doc-specified comparison +
Continue only if" bar as 02; specs in the FROZEN research-paths doc,
not the absent external checkout): 04 erasure + biased hybrid (d=5,7,9),
07 AutoCCZ and buffer, 12 mid-circuit reuse (24/32/40 wires to 16
physical), 19 Clifford tableau on restricted topologies (n=8,12,16),
24 ternary-tree fermion mapping (12/16/20 spin-orbitals + full routing).

Second wave (§3, strict early exit): 03 Floquet, 05 cultivation,
08 qLDPC transversal scheduling, 09 defect-tolerant compilation,
11 QCCD shuttling, 13 crosstalk coloring, 14 multi-QPU teleportation,
16 Pauli-propagation truncation, 17 circuit-knitting cuts, 21 sparse-state
BDDs, 22 bosonic stabilization (Fock N ≤ 32 — watch truncation
artifacts), 23 adaptive QPE. Rule: STOP at first flat-gradient or
missing-baseline signal; record as unresolved with blocker, NOT a
negative-result extension. Missing baselines may resolve a path as
blocked without empirical launch (10 precedent).

End-of-loop coordinator import (§4, in this repo): import each
`screens/<id>/` into `<output-root>/results/verdicts.md`; check Gate 1
(classical/random found + win), Gate 2 (non-flat deltas), Gate 3 (exact
solver times out at target scale/latency on same hardware), Gate 4
(physical end-to-end cost) FROM EVIDENCE FILES, not summaries. Missing
baselines/seeds = unresolved. Rank ONLY certified Pareto or weighted
wins at 2 sizes. Keep the full-engine independent-review blocker
separate. Then `recover` + `status`.

Standing plan rules: every path ends pursue / reject-on-this-screen /
unresolved-with-named-blocker + exact next experiment. No guaranteed
completion of all 24 paths in one run. Never extend budget after a
negative. Reject the 136-to-140 CNOT tradeoff under Pareto even when
depth drops 5→4. Three sizes + five seeds where feasible; reserve the
largest size for validation after fixing the method.

Blockers to record explicitly per screen (plan §"Current blockers"):
Vandaele, Lau et al., PhasePoly, torch MinGRU policy are NOT implemented
in the frozen closure. Published OLSQA figures may be a frozen
comparison corpus, never a claim of a local OLSQA run.

## Standing constraints (from the a0268985 predecessor handoff, still in force)

- No editing frozen tooling mid-run (tools/, tests/, screens/18, docs,
  OVERNIGHT_LAUNCH.md). No commits/pushes/installs-into-run/cloud/GPU.
- REVISE → one bounded correction + fresh review. Second REVISE,
  TAKEOVER, unavailable reviewer, failed gate, or unconfirmed cancel →
  stop safely, archive envelope to verify-evidence/<run-id>/ (never
  delete), report. Takeover target is codex-pstack/gpt-6.1-sol
  high/default when invoked.
- Reviews are read-only, no sub-delegation, deadline-bound. One screen
  at a time; one writer or one review task active at a time.

## Paste-ready prompt for the new thread

```text
/jtaroreh-mode continue the overnight screening loop in checkout
/Users/joeltaroreh/projects/challenges/meta-hackathon
(interpreter .venv/bin/python). Read OVERNIGHT_LAUNCH.md,
docs/overnight-contract.md, docs/cloud-swarm-readiness-plan.md,
.agents/skills/verify-overnight/SKILL.md, and the HANDOFF at
verify-evidence/f5ac1866b1794567ad299c518a43a391/HANDOFF.md first.
Workhorse muse-spark-1.3-contributor xhigh; advisor/takeover
codex-pstack/gpt-6.1-sol high/default; no substitutions. Run f5ac1866
is active (deadline 23:15 PDT, cutoff ~23:00). Screen 20 is staged
with review PASS filed — select 20 and run it first, then classify.
Screen 02 payload is staged but its confirmation dry run was killed —
rerun it, then finish its brief/command/run.sh, hash, select, review,
run, classify. Screen 15 is deferred (2/2 reviews used). Obey all hard
constraints. Loop screens until cutoff/budget/stop; finish with
recover+status and results/verdicts.md.
```

## Where things live

- Payloads: `screens/<id>/src/run<id>.py`; briefs/commands/run.sh beside.
- Active results: `overnight-data/f5ac1866…/{receipts,results/verdicts.md}`.
- Verify evidence: `verify-evidence/f5ac1866…/`.
- Skill: `.agents/skills/verify-overnight/SKILL.md` (load before
  supervisor CLI work). Docs: `OVERNIGHT_LAUNCH.md`,
  `docs/overnight-contract.md`, `docs/cloud-swarm-readiness-plan.md`.
