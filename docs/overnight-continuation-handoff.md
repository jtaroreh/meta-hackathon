# Overnight Screening — Continuation Handoff (Finish the Entire Run)

> **Purpose.** Finish the 24-path portfolio started in run `f5ac1866` to a terminal
> coordinator verdict for every path, with supervised evidence only. This handoff
> is the executable continuation plan. It does not authorize skipping reviews,
> fabricating baselines, or extending budget after a negative result.
>
> **Source of truth.** `docs/overnight-run-f5ac1866-findings.md` (run `f5ac1866`,
> LOOP run 3) plus the live envelope and `results/verdicts.md`. Coordinator
> classifications come only from supervised receipts and `work/results.json`
> evidence files — never from payload self-verdicts (every payload reports
> `unresolved-with-reason` by contract).
>
> **Checkout.** `/Users/joeltaroreh/projects/challenges/meta-hackathon`
> **Interpreter.** `.venv/bin/python` (absolute:
> `/Users/joeltaroreh/projects/challenges/meta-hackathon/.venv/bin/python`)

---

## 1. Where we are (read first)

Run `f5ac1866b1794567ad299c518a43a391` is **finished and expired**. Do not try to
launch inside it.

| Item | Value |
| :--- | :--- |
| Run ID | `f5ac1866b1794567ad299c518a43a391` |
| Created | `2026-10-29 15:19 PDT` (epoch `1793312157`) |
| Deadline | `2026-10-29 23:15 PDT` (epoch `1793340957`) |
| No-launch cutoff | `~23:00 PDT` (900 s before deadline) |
| Machine | Apple M4, 16 GB, 10 logical CPUs |
| Config hash | `3290f84face5d62` |
| Tool hash | `e10ce85acffeed3` |
| Input hash (frozen SOURCES.md) | `3b3f3f765795497` |
| Preparation hash | `5beab21b5947112` |
| Pilot hash | `0d6a57ddf36c48f` |
| Global budget | `28800` CPU-capacity s (8.0 h) |
| Reserved | `24000` |
| Stranded remainder | `4800` (< `5400` minimum per screen — loop correctly stopped) |
| Supervised attempts finished | 6 (`prepare-a01`, `18-a01`, `01-a01`, `20-a01`, `02-a01`, `04-a01`), all exit 0, zero orphans |

Any `select` / `run` against this envelope now raises `ExpiredError`
(“deadline or final no-launch interval reached”). Continuation means **seal
`f5ac1866`, then relay through fresh 8 h envelopes** (Section 4). Never reuse,
hand-edit, or delete the old envelope to retry. Never reset a deadline.

### 1.1 Settled verdicts — carry verbatim, do not re-run

| Screen | Verdict | Gate vector | Decisive evidence |
| :--- | :--- | :--- | :--- |
| 18 Phase-polynomial pilot | `INFRA ONLY — ok` | G1 ✓ G2 ✓ G3 — G4 ✓ | Pilot ok, proof chain ok, postpilot `PASS`. Infrastructure only; cannot satisfy Gate 3 or recommend pursue. Never re-run inside this envelope. |
| 02 Flag-gadget schedule search | `PURSUE` | G1 ✓ G2 ✓ G3 ✓ G4 ✓ | 72 vs 120 CNOTs at `d_eff=3` (40% cut), 8 vs 16 ancillas, exact `256/256`, greedy matches optimum 4/5 seeds. Bounded to `d=3` overhead; no threshold/depth claim. |
| 20 Photonic fusion routing | `REJECT on this screen` | G1 ✓ G2 ✓ G3 ✓ G4 ✓ | Sound sim (exact 3/3 + MC within `3×SE`, cap-hit `50001/50000`). Adaptive wins `0/3` sizes; yields collapse to 0 at `N=64`. Finite non-replenished pool starves adaptive arms. |
| 04 Erasure + biased hybrid | `REJECT on this screen` | G1 ✗ G2 ✓ G3 ✓ G4 ✓ | `0/9` `2×SE` wins vs Union-Find (directional `+0.3–1.0 pt` in 8/9, never significant). HYB `0.53 ms/shot` vs MWPM `31.4 ms/shot` — speed without accuracy fails the joint rule. |

### 1.2 Open verdicts — frozen next step

| Screen | State | Why not closed | Frozen next step |
| :--- | :--- | :--- | :--- |
| 01 qLDPC BP-guiding | `UNRESOLVED` | G3 fails (CBC solves d7 MLD in `10–16 ms`, 85 vars, zero `TimeLimit`); pheno recovery negative (`-0.23` to `-1.04`) but circuit B1 recovers `+79%` (d3) / `+68%` (d5) | (a) Pheno autopsy or re-scope to circuit noise. (b) Push `d∈{9,11}` or denser noise to real CBC expiry, else record solver-sufficiency. See §6.1. |
| 06 Lattice-surgery routing | `UNRESOLVED (carried from 87b79c06)` | Makespan `3/3` strict wins, physical `0/3`; Pareto blocks pursue. Gate 1 fails `9/15` (random beats greedy A*). All Gate-3 targets solve. | Gate-1 autopsy, physical-cost-aware objective, harder exact instances. See §6.2. |
| 10 AOD vs OLSQA | `BLOCKED (never launched)` | No OLSQA figure/data files anywhere in `docs/`, `screens/`, `env/` (prose only) | Freeze published OLSQA figure tables as corpus first, or stay `BLOCKED`. Never claim a local OLSQA run. See §6.3. |
| 15 ZX + gflow | `DEFERRED to next run` | 2/2 reviews used in `f5ac1866` (`FAIL, FAIL`). Staged fix `d1970c84…` awaits fresh budget | Carry `d1970c84…` unchanged into tail relay Run N+5 (promotable per §5); fresh 2-attempt review. See §6.4. |

### 1.3 Queued — clocks untouched

Queue order (`overnight-config.json`): `18, 01, 06, 10, 15, 20, 02, 04, 07, 12, 19, 24, 03, 05, 08, 09, 11, 13, 14, 16, 17, 21, 22, 23`.

Remaining: **07, 12, 19, 24** (first wave), then **03, 05, 08, 09, 11, 13, 14, 16, 17, 21, 22, 23** (second wave, strict early-exit). These 16 never-attempted paths **execute first** (low-friction order, §5); the §1.2 retried paths execute in the tail. Real specs live in the frozen closure:
`overnight-data/f5ac1866…/attempts/prepare-…/work/frozen-source/docs/CLOUD_SWARM_RESEARCH_PATHS.md`
(read the § for a screen before staging it — do not rely on the absent external checkout).

### 1.4 Standing blockers (record on every affected screen)

1. Vandaele (`arXiv:2407.08695`), Lau et al. (`arXiv:2508.04092`), PhasePoly (`arXiv:2506.20624`), and the PyTorch MinGRU policy are **not implemented** in the frozen closure. No screen may claim them.
2. The `136→140` CNOT increase for depth `5→4` violates joint Pareto. Depth-only wins do not count.
3. No RL training recommendation without all 4 gates passing on physical end-to-end metrics at ≥2 sizes with independent checkable evidence. (No screen currently meets this; `02` is `d=3`-only.)

---

## 2. Gate and verdict contract (applies to every screen)

- **Gate 1 (Control & Soundness).** Classical/random discriminative control plus exact-soundness (tiny solved instance + MC/exact agreement where applicable).
- **Gate 2 (Sensitivity).** Non-flat gradient across noise or scaling parameters (frozen `2×SE` or strict-monotonic rule per brief).
- **Gate 3 (Hardness Frontier).** Real exact-solver limit-expiry at target scale on the same hardware — solver started, tiny controls solved, solver's own `TimeLimit` / cap-hit / `unknown(timeout)` evidence. A supervisor wall-kill, crash, outer timeout, or missing baseline **never** counts.
- **Gate 4 (Execution Integrity).** Completeness under budget with zero skips; every planned cell/seed/arm present; payload wall `< 500 s` (frozen per brief) and clean skip log.
- **Verdicts.** `PURSUE` requires every gate **plus** the screen-frozen joint Pareto/weighted rule at two sizes where demanded. Any missing baseline, seed, or solver start is `UNRESOLVED`, never a negative result. `REJECT on this screen` requires all gates evidenced and the frozen reject condition true. Payloads always self-report `unresolved-with-reason`; only the coordinator classifies, in `results/verdicts.md`, from evidence files.

Review discipline: max **2 review attempts per screen per run**. `PASS`-only receipts; `FAIL`/`REVISE` archived as `receipts/screen-<id>-review-attempt<N>.txt` + `verify-evidence/<run-id>/…`. One bounded `REVISE` correction + fresh review. A second `REVISE`, `TAKEOVER`, unavailable reviewer, failed gate, or unconfirmed cancel stops the run safely. Never promote workhorse self-review to `PASS`. Reviews are read-only, deadline-bound, one writer or one review active at a time.

Model targets (session-local only, no global changes, no substitution): workhorse `muse/muse-spark-1.3-contributor` (`reasoningEffort=xhigh`); advisor/takeover `codex-pstack/gpt-6.1-sol` (`reasoningEffort=high`, `serviceTier=default`) per `overnight-config.json`. Validate against the live `orchestrator_capabilities` response each run; save the raw response. An unavailable target is a named blocker, not a fallback.

## 3. Budgets, host gates, and safety (non-negotiable)

- **Run envelope:** 8 absolute hours, no new launch in the final 15 min (`900 s` cutoff). Global `28800` CPU-capacity s. Per-screen max `7200` CPU-s / `9000` cumulative wall s including feasibility, model waits, and review after `select`. Preparation and pilot: ≤`120` wall s / `1800` CPU-s each (staged screens use `900/5400`; `06` uses `600/3600`).
- **Reservations are nonrefundable** (`allocated lifetime × 10` capacity, charged before spawn, persist across resume). Actual payload walls in `f5ac1866` were `14–82 s` against `5400` reservations — plan **~4 screens + prepare/pilot per 8 h run** (see §5). Do not promise all 24 in one run.
- **Host preflight** (`prepare`/`select`/`run` enforce; `status` does not): AC power required; ≥`4 GiB` available memory; ≥`8 GiB` free disk at start, abort active work `<6 GiB`; sampled session RSS ≤`4 GiB`; `100 MiB` per-attempt output, `2 GiB` global; numerical threads forced to 2 (`OMP/MKL/OPENBLAS_NUM_THREADS=2`). Final `f5ac1866` launches saw `27–28 GiB` free disk, `5.9–7.3 GiB` available on AC. Never kill protected user processes (Chrome, Antigravity, T3…) to clear memory; wait or record the blocker.
- **Supervision:** one local screen at a time, foreground owned sessions only, supervisor owns all builds/solvers/logs/temp. No unmonitored solver/build/benchmark shell commands, no background work between screens, no cloud/GPU/installs/commits/pushes/deployments or frozen-tooling edits mid-run (`tools/`, `tests/`, `screens/18`, `docs/overnight-contract.md`, `OVERNIGHT_LAUNCH.md` are frozen; any change stops the run — there is no in-run amendment API).
- **Recovery:** every CLI open reconciles stale attempts first. Crash/interruption stops autonomous launch; no automatic retry, no deadline refund, no attempt overwrite. End every run with `recover` + `status` (see `verify-overnight` skill: `.agents/skills/verify-overnight/SKILL.md`).

### Evidence paths (prove by files, not exit codes)

| Artifact | Path |
| :--- | :--- |
| Verdicts (authoritative) | `overnight-data/<run-id>/results/verdicts.md` (archive: `verify-evidence/<run-id>/verdicts-final.md`) |
| Envelope | `overnight-envelope.json` (archive copy in `verify-evidence/<run-id>/`) |
| Receipts | `overnight-data/<run-id>/receipts/*.json` + `*-attempt*.txt` |
| Attempts | `overnight-data/<run-id>/attempts/<screen>-<uuid>/` (`execution.json`, `worker-result.json`, `receipt.json`, `stdout.log`, `work/results.json`) |
| Screens | `screens/<id>/brief.md`, `command.json`, `run.sh`, `src/run<id>.py` |
| Protocols | `OVERNIGHT_LAUNCH.md`, `docs/overnight-contract.md` |
| Research specs | frozen `…/frozen-source/docs/CLOUD_SWARM_RESEARCH_PATHS.md` |

Generate every cryptographic receipt programmatically. The `f5ac1866` Screen-02 slip (`input_hash …4497` vs envelope `…5497`, supervisor exit 3) must not recur: bind receipts to the live envelope hash and re-verify gates before launch.

## 4. Phase 0–1: Seal `f5ac1866`, then bootstrap each relay run

Run everything from the repo root with `PY=.venv/bin/python`. Use an isolated PTY/tmux session per drive. `status` reconciles; never call internal setters or edit the envelope by hand.

### Phase 0 — Seal (no launches)

1. `$PY -B -m pytest tests -q` and `$PY -B env/smoke.py` (exit 0). Fix the base before driving anything else.
2. `$PY -B -m tools.overnight.run_one status` → confirm no active screen, `blocked_reason` empty, 6 attempts as above. Then `$PY -B -m tools.overnight.run_one recover`. Confirm zero supervisor-owned survivors (never signal by process name; PID 0 is a kernel pseudo-process).
3. Confirm `verify-evidence/f5ac1866b1794567ad299c518a43a391/` holds `HANDOFF.md`, `overnight-envelope-final.json`, `verdicts-final.md`, and the review archives. Preserve all `execution.json` / `worker-result.json` / `receipts/*.json` — never delete proof artifacts. Remove only scratch (`/tmp/s02dry*`) if still present.
4. Commit the seal (findings + this handoff + verdict archive). Only after sealing, move `overnight-envelope.json` aside (preserve the file; do not delete) so the next `init` can create a fresh `run_id`. Record the sealed hashes from §1 as the baseline for the next run's tooling review (a PASS on other bytes is insufficient).

### Phase 1 — Bootstrap (repeat at the start of every relay run)

1. Host gates: AC connected, lid open, T3 running, memory/disk as §3. If a gate fails, record the blocker and stop — do not fake probes or use `tests/fixture_cli` for research.
2. `$PY -B -m tools.overnight.run_one init` — creates a fresh `overnight-envelope.json` + `overnight-data/<new-run-id>/` and starts the 8 h deadline. Reuse an existing fresh envelope if one was just created; never create a second to extend a run.
3. Call `orchestrator_capabilities` **once**. Validate the three frozen targets and advertised option IDs against the real response; save the unmodified raw output and write `receipts/capabilities.json` (`validated_targets` exactly equal to `tools.overnight.receipts.TARGETS`; no `available` field, no fallback).
4. Independent tooling review of the exact current bytes (supervisor, config, tests, launch prompt, staged pilot) → `receipts/tooling-review.json` (`verdict=PASS`, reviewer = configured advisor target, `tool_hash`/`config_hash` = envelope values). Missing/`REVISE`/failed tooling review stops launch; do not edit frozen tooling inside the run.
5. `$PY -B -m tools.overnight.run_one prepare` (freeze → writable exec copy → blocking proof: `make shared`, native bridge, `native_checks.py`, tiny GraySynth/PMH/PyZX controls). Inspect `stdout.log` + `execution.json` + `worker-result.json` + proof artifact — exit 0 without the receipt path is not ready.
6. `OVERNIGHT_PYTHON=$PY sh screens/18/run.sh` (fresh exec copy; repeats proof + algebra control, 5 s solver limit, 60 s outer timeout; outer timeout = infrastructure failure). Then fresh independent postpilot review → `receipts/postpilot-review.json` (bindings include `input_hash`; artifacts exactly `{preparation, pilot}` hashes). Only a matching `PASS` opens broader screens. Pilot `18` never recommends pursue and never clears Gate 3.
7. From here the coordinator selects queued IDs itself, in §5 relay order (not `overnight-config.json` queue order), without a human prompt between screens. One screen at a time. For each: stage files → independent `PASS` → `select <id>` → `run <id>` → classify (Section 5–7 pattern). `select` persists the screen clock before any feasibility/model/code work and never resets on repeat; use its returned deadline for every delegate.

## 5. Relay schedule — how the queue drains (read before launching)

**Ordering principle (low friction first).** Results have stalled on retried paths, so this handoff now leads with paths that have never been attempted. Untouched paths need greenfield staging, but they start clean — no failed premise to diagnose, no objective to reformulate, no harder instance to invent before staging can even begin. Retried paths (`01`, `06`) need an autopsy *first*, and the `02` scale-up extends an already-certified win; all three go last, where their extra diagnosis cost cannot block new coverage. Document order (§6 before §7) is preserved for reference stability only — **execution order is the relay table below**, and §6 screens execute in the tail relay, after the untouched queue in §7 has drained. The single exception is `15`: it is retried, but its staging cost is already zero (payload staged at `d1970c84…`, review + run only), so it heads the tail rather than sitting behind the autopsies, and it may be promoted into any earlier run's fourth slot if that run's staging slips. `10` stays offline until its corpus is frozen; `20`/`04` stay closed unless their regime changes (§7.4).

Promotion moves, not copies, `15`: strike it from the Run N+5 tail, the displaced fourth ID becomes the next relay's first slot, and promote only if the run's reservation still admits `15` without extending budget.

Each relay run carries **~4 research screens** after prepare/pilot. Stage one screen at a time; do not build all screens upfront. Provider waits, reviews, and reporting all consume the same absolute 8 h deadline; stop dispatching at the 15-min cutoff and cancel outstanding provider tasks before final reporting.

| Relay | Carries (in launch order) | Exit condition |
| :--- | :--- | :--- |
| Run N+1 | `07` → `12` → `19` → `24` (untouched first wave) | Each classified in that run's `verdicts.md`; `10` corpus work runs offline in parallel (no select until frozen). |
| Run N+2 | `03` → `05` → `08` → `09` (untouched second wave) | Second-wave early-exit in force; a flat-gradient/missing-baseline screen ends `UNRESOLVED` and frees the slot for the next ID in the same run only if the reservation still admits it — never by extending budget. |
| Run N+3 | `11` → `13` → `14` → `16` | Same. |
| Run N+4 | `17` → `21` → `22` → `23` (untouched queue drained: 16/16) | All never-attempted paths now have a first verdict. Proceed to the tail. |
| Run N+5 (tail) | `15` → `02` (scale-up) → `01` (follow-up) → `06` (autopsy) (+ `10` here if corpus frozen; `20`/`04` only if regime changed, else they close as `REJECT`/`BLOCKED` without a slot) | Portfolio drained; proceed to §8 synthesis. If a tail screen blocks, close the remaining IDs from existing evidence rather than opening a further relay by default. |

Reorder only for a named blocker (e.g. `10` corpus not ready, a staging slip that promotes ready `15` into the vacant slot, `15` second FAIL in the tail → stays deferred and the next tail ID advances). Never skip `select` to “save” the clock — selection before feasibility is the contract. Keep at most one writing workhorse or one review task active; ≤2 provider attempts per operation, no model fallback, combined start/retry wait ≤120 s inside the remaining deadline. Follow each delegate's T3 next action; do not poll with `sleep`/`task_status`. Cancel replaced tasks with `task_cancel` and obtain terminal evidence; an unconfirmed cancel is a global blocker. Local process safety must not depend on an API callback.

**Per-screen staging checklist** (identical for every ID below):
1. `$PY -B -m tools.overnight.run_one select <id>` first — persist the clock, capture the returned deadline.
2. Freeze in `screens/<id>/`: `brief.md` (hypothesis, corpus, controls, 3 sizes where feasible, seeds 1–5, acceptance rule with Pareto/weights fixed *before* the experiment, Gate definitions, budgets, baseline disclosure), `command.json` (`command` with `{python}/{root}/{attempt}/{data}`, `scope=research`, `cpu_limit_sec`, `wall_limit_sec`, complete `source_files` closure), `run.sh` (runs `run_one run "<id>"`), `src/run<id>.py`. Reserve the largest size for validation after the method is fixed. Feasibility stops at 45 min or sooner on a failed premise/missing baseline.
3. Dry-run in `/tmp` scratch; verify zero skips, explicit `iters_done`/`n_evaluated` on every batch, skip record on *every* guard exit (02 lesson), `None`-guard on solver timeouts with a forced-`None` probe (04 lesson). Keep payload wall ~70–120 s so the 300 s guard fires with finalization reserve (admitted window ≈ `min(wall−used, run-remaining, cpu-remaining/capacity) − 8.5 s`).
4. Compute `screen_artifacts(root, '<id>')` hash programmatically; delegate read-only review (advisor target, attempt 1 of 2, deadline-bound, no sub-delegation); file `receipts/screen-<id>-review.json` only on matching `PASS`.
5. `sh screens/<id>/run.sh` (== `run_one run <id>`). Import `execution.json`/`worker-result.json`/`work/results.json`; classify coordinator-side in `results/verdicts.md` (gate vector + verdict + exact next experiment); update resource debits. Move to the next eligible ID without a human prompt.

## 6. Tail detail — Carried / deferred / blocked (execute last, in Run N+5 tail order: `15` → `02` (§7.2) → `01` → `06`; `10` offline until corpus frozen, then conditional N+5 slot per §5)

### 6.1 Screen 01 — qLDPC BP-guiding follow-up (`UNRESOLVED` → resolve or re-scope)

Frozen design (do not rediscover): HGP(`rep(d),rep(d)`) pheno `X`-noise `p=0.06`, `d∈{3,5,7}`, 300 syndromes/cell, seeds 1–5; Stim `rotated_memory_X` circuit `p=0.005`, rounds=`d`, DEM priors. Arms A (parallel BP), B1/B2/B3 (serial/damped), C (BP-OSD-2 reference), R (random null), `max_iter=30`. Pursue bar: best-B recovers ≥25% of `(fail_A−fail_C)` at ≥2 pheno sizes, mean latency ≤`5000 µs`, gap>0 at ≥1 circuit size, Gates 1/2/4 PASS, real Gate-3 CBC expiry at `d=7`.

Observed: pheno recovery negative everywhere (B1/B2/B3 means d3 `−0.23/−0.23/−1.04`, d5 `−0.21/−0.45/−0.52`, d7 `+0.00/−0.22/−0.22`); circuit B1 recovers `+79%` (d3) / `+68%` (d5); latencies `~3–4 µs`; CBC solves all 20 d7 MLD instances in `0.012–0.016 s` (d3 `0.10 s`), zero `TimeLimit`.

Execute both frozen experiments in one re-staged screen (new `screen_files` hash, fresh review):
- **(a) Pheno autopsy.** Diagnose why serial/damped schedules hurt under pheno `X`-noise. Try one alternative perturbation family *or* freeze an explicit re-scope to circuit noise only (where B1 wins) — the re-scope, if chosen, must be frozen in the brief *before* running and the pursue rule rewritten accordingly. Do not silently keep the pheno bar while reporting circuit wins.
- **(b) Hardness frontier.** Push to `d∈{9,11}` or denser noise graphs until CBC shows its own `TimeLimit` status on ≥1 syndrome (any other non-`Optimal` status, including build errors, does not count). If CBC still demolishes the largest frozen instance, record solver-sufficiency at these scales as the Gate-3 outcome — `UNRESOLVED` with that attestation, never a fabricated timeout.
Classify: `PURSUE` only if the (possibly re-scoped) frozen bar + Gates 1/2/4 + real expiry all hold; `REJECT` only if all gates are evidenced and recovery <25% everywhere; else `UNRESOLVED` + the single next experiment that changes the verdict.

### 6.2 Screen 06 — Lattice-surgery routing autopsy (`UNRESOLVED` carried)

Frozen design: 5×5 patch grid, factories `(0,0)/(4,4)` (1 merge / 2 time units), `Q∈{10,20,30}` logical qubits, 20 gates/program, seeds 1–5, 100 programs/cell, arms A (greedy A*), B (prioritized+rotation), C (annealing, 1500 iters), R (random). Gate 1: `mean_A < mean_R` strictly in every `(size,seed)` cell (15 cells). Costs: makespan + physical (summed route lengths). Gate 3: z3 time-expanded feasibility; only `unknown` with reason exactly `timeout` counts.

Observed (run `87b79c06`, files `581cd0a6…`, 112.9 s clean): makespan `3/3` strict wins, phys `0/3`; Gate 1 fails `9/15`; all Gate-3 targets solve.

Execute: (1) Gate-1 autopsy — why random beats greedy A* in 9/15 cells (placement `patch[q]=perm[q%25]`, co-location, orientation/timing model are the suspects; verify against the feasibility checker). (2) Reformulate the objective to be physical-cost-aware so makespan and phys can win jointly (Pareto requires both). (3) Construct harder exact instances (larger horizon/scale probe) until z3 shows `unknown/timeout`. Re-stage at `600/3600`, fresh review, `select 06` → `run 06`. `PURSUE` needs joint wins at ≥2 sizes; otherwise `UNRESOLVED`/`REJECT` per the frozen rule with the autopsy finding as evidence.

### 6.3 Screen 10 — AOD shuttling vs OLSQA (`BLOCKED` — corpus first, launch last)

Do not select `10` until a corpus exists. Offline work (no envelope slot): locate the published OLSQA benchmarks (Tan et al.) for 20/40/60 qubits, extract the figure/table values into a frozen corpus file with provenance (paper, figure/table IDs, transcription method, SHA-256), and freeze it as the comparison target. Stage `10` (2D AOD grid, row/column order-preservation, min-spacing; 1000 random rollouts + greedy row-packing + annealing; score `Σ(t_move/T₂) + N_Rydberg·ε₂Q`) only after the corpus is frozen. Label every comparison “vs published OLSQA figures” — never claim a local OLSQA execution. Continue only if annealing/lookahead beats greedy on ≥2 sizes while exact SMT times out (Gate 3). If no figures can be frozen with provenance, keep `10 BLOCKED` with that named blocker and spend the slot on the next queued ID (the `f5ac1866` precedent: missing baselines resolve without launch).

### 6.4 Screen 15 — ZX spider-fusion + gflow (`DEFERRED` — fresh review of `d1970c84…`)

Carry the staged commit `d1970c84…` **unchanged** into the tail relay (Run N+5, first tail slot; promotable into any earlier vacant fourth slot — see §5). Do not re-stage. Fresh 2-attempt review budget applies in whichever run launches it. The reviewer must verify the three encoded lessons: (i) exact solving requires `optimum_twoq` (a vacuous solve does not count); (ii) bounded DFS dedupes on `(graph, depth, allowance)` with valid-move terminals and `stop()` threaded through every arm/fallback loop with a stopped-guard; (iii) brief's beam-dedupe sentence matches the code (level-synchronous beam keys on `(graph, euler-used)`). Prior FAILs to not repeat: attempt 1 (`unfuse/copy/DFS-terminal/Pareto/R/75-vs-45`), attempt 2 on `5f8ab26a…` (F1 vacuous-solve hole, F3 arm-guard overclaim, F4 beam-dedupe phrasing). Evidence: `receipts/screen-15-review-attempt2.txt` + `verify-evidence/…/screen-15-review-attempt2-FAIL.txt`.

Design reminder: Q∈{6,8,10}, 3 instances/(size,seed), seeds 1–5 (45 total); moves pivot/lcomp/`euler_expansion` (≤2/trajectory, `unfuse` dropped — `to_graph_like` fuses it back); arms F (`full_reduce` + extract, identity-fallback flagged on 17/45 gflow-breaking inputs), A (greedy proxy `spiders+4·T`), B (beam 4×6), C (annealing 100 iters), R (25× length-8 rollouts, per-rollout reasons kept). Gate 3: tiny Q=4 (depth≤4) + targets Q=8 must **solve** within caps (20k nodes / 8k extractions); the 12q depth-6 cap-hit (~20k nodes / ~125 s) is the documented next experiment, not gated. On `PASS`: `select 15` → `run 15` → classify (temporary inflation must beat `full_reduce` on extracted two-qubit count at ≥2 sizes without losing gflow). On second `FAIL`: re-defer with verbatim findings; do not burn a third attempt (there is none).

## 7. Lead detail — Untouched queue first, then scale-up and guarded reopens

For every screen below: read its § in the frozen `CLOUD_SWARM_RESEARCH_PATHS.md` first, then run the §5 staging checklist end-to-end (select → freeze → dry-run → review → run → classify). Three sizes + seeds 1–5 where feasible; reserve the largest size for validation after the method is fixed. Missing baselines/seeds = `UNRESOLVED`. Rank only certified Pareto/weighted wins at 2 sizes.

### 7.1 First wave — untouched, lead (Run N+1)

| ID | Screen (frozen §) | Frozen sizes / arms | Continue-only-if bar (pre-declared) |
| :--- | :--- | :--- | :--- |
| 07 | AutoCCZ + buffer scheduling (§07) | Deterministic 2D tile/buffer model; frozen factory:compute ratios; static FIFO vs dynamic buffer/corridor | Dynamic beats static FIFO across plausible parameter ranges. Label modeled results clearly; no hardware claim. |
| 12 | Mid-circuit reuse (§12) | 24/32/40 logical wires → 16 physical; greedy earliest-reuse vs routing-aware beam/annealing on 2D grid | Routing-aware reuse beats greedy width-minimization on routed CNOTs **and** depth at fixed width. |
| 19 | Clifford tableau, restricted topologies (§19) | `n∈{8,12,16}` grid/heavy-hex, bitwise tableau; random/greedy/annealing vs Gaussian+SWAP; exact SAT | SAT times out at `n≥12` **and** search beats routed decomposition on CNOT + depth, 5 seeds. |
| 24 | Ternary-tree fermion mapping (§24) | 12/16/20 spin-orbitals, 2D grid, full Pauli-gadget routing; random/greedy/annealing vs JW/BK/balanced trees | Tree-search mappings survive full synthesis + routing (incl. parity-reuse baselines) at 2 molecular sizes. |

### 7.2 Screen 02 scale-up (sole `PURSUE` — tail, Run N+5; win already certified at `d=3`)

Next experiment (frozen): wider commutation-order neighborhoods, weight-6+ stabilizer gadgets, and `d=7` transfer — does the overhead win survive larger distances? Keep the three load-bearing construction rules exactly: (1) layout **transcribed** from `stim.Circuit.generated("surface_code:rotated_memory_x")` via `transcribe()` (hand-tiling breaks commutation → nondeterministic detectors); (2) **full-bracket** flags (open before first data CNOT, close after last; middle brackets corrupt X syndromes); (3) LER via `compile_sampler()` + `compile_m2d_converter(separate_observables=True)` (`compile_sampler()` alone returns measurements, not detectors). Current record to beat: canonical 120 CNOTs/16 ancillas vs exact 72 CNOTs/8 ancillas at `d_eff=3` (256/256, greedy 4/5 seeds, random valid fraction 0.0067, LER tracks canonical across `p∈{0.002,0.005,0.010}`). Stage as a new screen version (new hash, fresh review) at the same `900/5400`; `PURSUE` extends beyond `d=3` only if a valid `d_eff=7` schedule preserves the overhead advantage with gradient + cap-hit evidence at `d=5`-class enumeration. If `d=7` fails, `02` stays `PURSUE (d=3-bounded)` — do not downgrade the certified win, and do not claim threshold/depth benefits that were never measured.

### 7.3 Second wave — untouched (Runs N+2–N+4, strict early-exit)

Halt each screen at the **first** flat-gradient (Gate 2) or missing-baseline signal; record `UNRESOLVED` + blocker; never extend budget after a negative. Do not let a blocked screen consume a second slot in the same run.

| ID | Screen (frozen §) | Continue-only-if bar |
| :--- | :--- | :--- |
| 03 | Floquet schedule optimization (§03) | Mutations show smooth detector-weight gradients and beat static cyclic schedules with 1–2 edges penalized/removed. |
| 05 | Magic-state cultivation (§05) | Adaptive abort cuts wasted spacetime ≥10% at matched infidelity across 2 noise regimes. |
| 08 | qLDPC transversal scheduling (§08) | Automorphism-aligned parallel schedules cut depth vs serialized addressing at 2 circuit sizes. |
| 09 | Defect-tolerant surface routing (§09) | Irregular routing beats bounding-box exclusion across 5 defect seeds (2%/4% dropouts) without degrading `d_eff`. |
| 11 | QCCD shuttling (§11) | Heating-aware schedules reduce estimated infidelity vs swap-count-only at 2 trap sizes. |
| 13 | Crosstalk coloring (§13) | Non-trivial interior optimum beats both min-depth and fully-spread extremes at 2 sizes (27–64q conflict hypergraph). |
| 14 | Multi-QPU teleportation (§14) | Joint teledata/telegate lookahead beats static min-cut across multiple EPR rates (2–4 QPUs). |
| 16 | Pauli-propagation truncation (§16) | Adaptive truncation beats static weight + magnitude cutoffs at 2 depths under matched string budgets (`K≤10⁴`). |
| 17 | Circuit-knitting cuts (§17) | Pre-cut rewrites reduce `γ²` below optimal static-DAG cuts at ≥2 sizes. |
| 21 | Sparse-state BDD prep (§21) | Reordered trees beat Gray-code multiplexers on routed CNOT + depth at ≥2 molecule sizes (`n=10,14,18`). |
| 22 | Bosonic stabilization, Fock `N≤32` (§22) | Discrete sequences improve logical lifetime over standard controls across 2 loss regimes **without** truncation-boundary artifacts. |
| 23 | Adaptive QPE (§23) | Multi-step lookahead beats myopic adaptive rules under realistic `T₂` dephasing (Holevo variance, fixed time/shots). |

### 7.4 Guarded reopens (last relay only, regime must have changed)

- **20 — reopen only with replenishment.** Add photon replenishment/multiplexing to sustain the finite pool, then retest adaptivity at ≥2 pool sizes (`N∈{16,36,64}`, loss `{5%,7.5%,10%}`, `p_fusion=0.5`). No MILP/SMT routing comparison without replenishment. Until then `20` stays `REJECT`; do not re-run the non-replenished screen.
- **04 — reopen only in a new regime.** Higher erasure rate or stronger Pauli bias (`Z:X:Y` beyond `10:1:1`, conversion beyond 95%) until hyperedge density lifts the sub-significant `~0.3–1.0 pt` edge past `2×SE` (needs ≥1/9 cells to start; pursue needs the frozen joint rule). `HYB==UF` on flag-free shots keeps the flag value isolated — preserve that invariant. Do not re-allocate budget inside the current `d∈{5,7,9}, p∈{0.002,0.005,0.010}` regime.

## 8. Phase 6 — Synthesis, funding decisions, and close

After the last queued screen classifies (or is blocked/deferred with a named blocker):

1. **Coordinator import.** For each screen, re-derive Gates 1–4 from evidence files (not summaries): Gate 1 classical/random win found, Gate 2 non-flat deltas, Gate 3 solver's own limit-expiry at target scale on the same hardware, Gate 4 physical end-to-end cost + completeness. Keep the full-engine independent-review blocker separate from screening results.
2. **Decision matrix** (one row per ID 01–24): verdict, gate vector, decisive numbers (e.g. `02: 72 vs 120 CNOTs, 256/256`), reservation vs actual debits, and the exact next experiment for every `UNRESOLVED`. Apply the standing answers unless new evidence overturns them: `02 PURSUE` (extend only via §7.2), `20/04 REJECT` (reopen only via §7.4), `01/06 HOLD` until §6 resolves, RL = `NO` unless the §1.4 bar is met at two sizes.
3. **Per-run close.** `$PY -B -m tools.overnight.run_one recover` then `status`; confirm no owned survivors; ensure `results/verdicts.md` debits match the envelope (`prepare 1200 + pilot 1200 + 5400/screen`-class reservations vs actual `wait4` CPU); archive the envelope copy to `verify-evidence/<run-id>/` (never delete proof artifacts; remove only that run's scratch attempt/work dirs). Commit per screen (`feat(screens): stage screen <id> …`, following history #5–#12); link any PR created (one link per PR, full URL, every stack layer).
4. **Final report.** What fit per run, what remains queued/deferred/blocked and why, resource debits and stranded remainders, host-gate incidents (AC/memory waits — cf. `f5ac1866` battery `80%→63%` halt and `3.8 GiB` memory block; never kill user apps), review history (attempt counts per screen), and reproduction commands (`sh screens/<id>/run.sh` requires a filed `PASS` receipt matching the exact `screen_files` SHA-256; modified sources are rejected until re-reviewed).

## 9. Troubleshooting (observed failure modes)

| Symptom | Cause / fix |
| :--- | :--- |
| `ExpiredError` on `select`/`run` | Past deadline/cutoff. Seal the run (§4 Phase 0) and `init` a fresh envelope. Never hand-edit the envelope. |
| Supervisor exit 3 on launch | Receipt hash slip (cf. `…4497` vs `…5497`). Re-bind the receipt to the live envelope hash programmatically; re-verify gates; no reviewed file changes. |
| Review `REVISE` (truncated counts) | Batches reported nominal `n` despite early exit. Record explicit `iters_done`/`n_evaluated` + a skip record on *every* guard exit, including entry-guard failures (02 fix, verified in a 75.6 s dry run). |
| `AttributeError` on solver timeout | Solver returned `None` (04: PuLP at `run04.py:1406`). Add an explicit `None` guard; verify with a forced-`None` mock probe before re-review. |
| Preflight blocks on memory/power | AC disconnected or available memory `<4 GiB` from desktop apps. Wait for clearance (it cleared to `5.9–7.3 GiB` in `f5ac1866`); `purge` needs root (refused); never kill protected processes. |
| Gate 3 “timeout” disputed | Outer wall-kill/crash/missing baseline mislabeled. Require solver-started + tiny-solved + solver's own `TimeLimit`/cap-hit/`unknown(timeout)` on the same hardware (01 CBC, 06 z3, 15 DFS caps). |
| `full_reduce` breaks gflow (15) | Expected on 17/45 dense inputs. Use the flagged deterministic identity-fallback; it is strictly weaker, so the control stays conservative. `unfuse` is a no-op under `to_graph_like` — use `euler_expansion`. |

## 10. Paste-ready prompt for the next thread

```text
/jtaroreh-mode continue the overnight screening loop in checkout
/Users/joeltaroreh/projects/challenges/meta-hackathon
(interpreter .venv/bin/python). Read OVERNIGHT_LAUNCH.md,
docs/overnight-contract.md, .agents/skills/verify-overnight/SKILL.md,
docs/overnight-run-f5ac1866-findings.md, and this handoff
(docs/overnight-continuation-handoff.md) first. Workhorse
muse/muse-spark-1.3-contributor xhigh; advisor/takeover
codex-pstack/gpt-6.1-sol high/default; no substitutions, session-local only.
Run f5ac1866 is sealed and expired (deadline 2026-10-29 23:15 PDT) — seal it
per handoff §4 Phase 0, then init a fresh 8h envelope and bootstrap per
Phase 1 (capabilities + tooling PASS + prepare + pilot 18 + postpilot PASS).
Then drain in low-friction handoff order (untouched first, retries last):
first wave 07/12/19/24 → second wave 03/05/08/09/11/13/14/16/17/21/22/23
(strict early-exit) → tail 15 (staged d1970c84…, fresh review) → 02 d=7
scale-up → 01 follow-up → 06 autopsy; guarded 20/04 reopens only if the
regime changed; 10 only after the OLSQA figure corpus is frozen. One
screen at a time via run_one select/run only,
max 2 reviews/screen/run, PASS-only receipts. Classify coordinator-side in
results/verdicts.md from evidence files. Finish each run with recover +
status and the envelope archived to verify-evidence/<run-id>/.
```

---

*Handoff generated from run `f5ac1866` findings (2026-10-29). Next operator: start at §4 Phase 0. Do not rediscover the §6 lessons — they are already paid for.*

