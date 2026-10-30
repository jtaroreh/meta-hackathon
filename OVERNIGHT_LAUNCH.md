# Prepare and run bounded local screens

Status: the takeover implementation and its fresh independent review are complete. The 45 reviewed files are integrated into this checkout and byte-verified, and the full test suite here passes 58/58. Local probes on this machine confirmed AC power, 9 GiB free disk, and a working preflight, which correctly blocked launch on one live host condition: keep available memory above 4 GiB at launch time (close heavy applications). These instructions prepare an autonomous run. They do not authorize starting research during this implementation task.

Use the checkout containing this file. Its `overnight-config.json` fixes the queue and exact model targets. Keep the phasepoly and audit source checkouts read-only. No cloud compute, GPU training, PufferLib setup, commits, pushes, or global setting changes belong to this run.

## Create the envelope before preparation

Choose an absolute interpreter path. In this isolated checkout the available interpreter is `/Users/joeltaroreh/projects/challenges/meta-hackathon/.venv/bin/python`. The shell entry accepts that path through `OVERNIGHT_PYTHON`. It defaults to this checkout's `.venv/bin/python` when no override is set.

Run these commands from the checkout root:

```sh
PY=/Users/joeltaroreh/projects/challenges/meta-hackathon/.venv/bin/python
"$PY" -B -m pytest tests -q
"$PY" -B -m tools.overnight.run_one init
```

`init` creates `overnight-envelope.json` and a unique `overnight-data/<run-id>/` directory. It starts the absolute eight-hour deadline. Provider waits, source preparation, reviews, and reporting all consume that deadline. Do not remove the envelope or create another one to extend a run.

The coordinator must now produce matching capability and independent tooling-review receipts in the run's `receipts/` directory. The exact fields and evidence requirements are in [the receipt contract](docs/overnight-contract.md). A caller-supplied `available=true` is not capability validation. The local CLI never contacts T3 or a model API.

Connect AC power, keep the lid open and T3 running, and satisfy the local gates. Then run:

```sh
"$PY" -B -m tools.overnight.run_one prepare
OVERNIGHT_PYTHON="$PY" sh screens/18/run.sh
```

`prepare` executes the freeze, writable exec copy, and blocking proof in that order, inside one supervised attempt. Proof builds `make shared`, loads the native bridge, runs `native_checks.py`, and runs tiny GraySynth, PMH, and pyzx controls. The pilot uses a fresh writable exec copy in its own attempt. It repeats proof and runs the small algebra control with a five-second solver limit and a 60-second outer control timeout. An outer timeout is infrastructure failure.

A receipt path is printed for every completed launch. Inspect the corresponding `stdout.log`, `execution.json`, `worker-result.json`, and proof or pilot artifact. The pilot is infrastructure only. It never recommends pursue or clears Gate 3.

After a matching independent postpilot PASS, the coordinator selects the next queued path itself. Before feasibility or model preparation, run `"$PY" -B -m tools.overnight.run_one select 01` for that selected ID. This starts its durable cumulative screen clock; repeating selection never resets it. Each broader screen also needs its own independent PASS bound to its frozen brief, command, and source files. Stage those files under `screens/<id>/`, then use:

```sh
"$PY" -B -m tools.overnight.run_one run 01
```

The example selects 01. The coordinator selects subsequent IDs in the ordered queue without another human prompt. There is one local screen at a time. Missing or stale evidence blocks launch. No claim is made that all 24 paths fit.

## Apply the envelope

The run has eight absolute hours and no new launch in its final 15 minutes. Default total CPU allowance is 28,800 CPU-capacity seconds. Each research screen has at most 7,200 CPU-capacity seconds and 9,000 cumulative wall seconds, including feasibility, model waits, review and local execution after selection. Preparation and pilot each request at most 120 wall seconds and 1,800 CPU-capacity seconds.

Admission reserves the full allocated lifetime multiplied by the machine's logical CPU count. Reservations are charged before spawn, persist across resume, and are never refunded. On a 10-core M4 a 7,200-second screen budget permits at most 720 seconds of reserved lifetime, including shutdown time. This deliberately replaces the earlier promise of exact sampled aggregate CPU accounting. Short runs can consume their full reservation. Fewer retries and screens fit. The eight-hour wall allowance is not eight hours of continuous experimental compute.

`wait4` usage is recorded once for the payload and descendants it waited for. It is evidence, not a complete tree meter. An unavailable usage receipt or uncertain cleanup blocks further launch. Actual lifetime overruns add a conservative CPU debit and stop the run. Watchdog checks and shutdown can overshoot a limit. This is a sampled watchdog, not a kernel aggregate CPU quota.

The sampled session RSS threshold is 4 GiB, including foreground descendants. Available system memory must remain at least 4 GiB. Start with at least 8 GiB free disk; stop active work below 6 GiB. Each attempt, including writable exec, temporary files, caches, and logs, has a sampled 100 MiB allowance. The run has a sampled 2 GiB allowance, including generated screen sources. The supervisor caps its combined stdout log at 5 MiB during writes. Other file output and RSS can overshoot between samples. Numerical thread variables are forced to two even when the parent requested sixteen.

Workloads must keep their descendants in the owned foreground session and write into the attempt directory. `TMPDIR`, `TMP`, `TEMP`, and common cache paths point there. This is cooperative process supervision, not a filesystem sandbox. Provider tasks are bounded separately by the coordinator instructions below.

## Recover without duplicate launches

```sh
"$PY" -B -m tools.overnight.run_one recover
"$PY" -B -m tools.overnight.run_one status
```

Every CLI open reconciles a stale running attempt before any new launch. The worker identity is persisted before it receives permission to start the payload. A crash before acknowledgement cannot start the payload. The worker also watches its coordinator's identity and absolute deadline. Cleanup checks process identities, sends TERM then KILL as needed, and verifies survivors. Ordinary wrapper exit also triggers descendant cleanup.

Recovery preserves the deadline, reservations, and evidence. An interrupted run stops autonomous execution after reconciliation. There is no automatic retry after a supervisor crash or local execution failure. An operator can inspect it later. Re-running a command never resets the envelope, clears a blocker, or overwrites an attempt.

## Literal autonomous T3 overnight prompt

Paste the following block only when an actual overnight run is authorized and the reviewed files are present in the intended checkout.

```text
Run the prepared local screening plan autonomously in /jtaroreh-mode.
Work only in the checkout containing OVERNIGHT_LAUNCH.md. Read that file,
docs/overnight-contract.md, docs/cloud-swarm-readiness-plan.md, and the
source scientific contracts first. External source checkouts are read-only.

Use session-local role overrides only. Workhorse is
muse/muse-spark-1.3-contributor with reasoningEffort=xhigh. Advisor and
bounded takeover are codex-pstack/gpt-6.1-sol with reasoningEffort=high
and serviceTier=default. Do not change global model settings. Do not
substitute another provider, model, or unsupported option. An unavailable
target stops this run with a named blocker.

Create the run envelope with the documented init command BEFORE provider
validation, preparation, or model work. Reuse an existing envelope if it
exists. Never reset it. Record its immutable deadline and output directory.
Call orchestrator_capabilities once as required by T3. Validate the exact
three targets and advertised options against its real response. Save the
raw response and write a run-bound capability attestation per the contract.
Obtain or bind a matching independent tooling PASS covering this exact
supervisor, config, tests, launch prompt and staged pilot. Save the raw
review evidence. Do not fabricate either receipt. A historical PASS on
other bytes is insufficient. Missing, REVISE, or failed tooling review
stops launch rather than editing frozen tooling inside this run.

Check AC, disk, available memory, interpreter and tools with the production
local gates. Never fake host probes or use tests.fixture_cli for research.
The lid stays open and T3 stays running. If a real gate fails, record the
blocker and stop. Run documented supervised prepare. Only after its proof
passes, run the staged infrastructure pilot 18. The local supervisor owns
all experimental commands, builds, descendants, logs and temporary output.
Do not run a solver, build, benchmark, or pilot as an unmonitored shell
command, and do not leave background local work between screens.

Request a fresh independent advisor review of the pilot, complete raw
receipts, native proof and resource evidence. Only a matching PASS creates
the postpilot receipt. The pilot cannot recommend pursue or satisfy the
four scientific gates. On a failed pilot, missing review, TAKEOVER or an
unrecoverable infrastructure error, stop safely and report the blocker.

After pilot plus independent PASS, autonomously select the first eligible
queued path from overnight-config.json, then the next, without asking the
human between screens. The order is 01, 06, 10, 15, 20, 02, 04, 07, 12,
19, 24, 03, 05, 08, 09, 11, 13, 14, 16, 17, 21, 22, 23. The completed
infrastructure pilot 18 is not a completed scientific screen. Do not build
all screens upfront. For each selected path, first call run_one select <id> to persist its screen
clock BEFORE feasibility, model work or code preparation. Repeating select
never extends that clock. Use the returned deadline for every agent task.
Then freeze the hypothesis,
corpus, controls, three sizes where feasible, seeds 1 through 5, acceptance
rule, complete source_files closure, and rerunnable command in its screen
dir. Use Pareto or weights fixed before the experiment. Stop feasibility
at 45 minutes or sooner on a failed premise or missing baseline. Named
missing baselines yield unresolved and the exact next experiment, then
continue to the next eligible path if no global blocker exists. Keep
reports and provider evidence inside the run output tree. Generated source
files under screens are counted in the global allowance.

Before each broader local launch obtain a matching independent screen PASS
covering the current brief, command, source files, input hash, preparation
and pilot evidence. A screen REVISE permits one bounded correction within
its existing allowance, then fresh review. Track that count across resume.
A second REVISE, TAKEOVER, unavailable reviewer or review without PASS
stops this run. Do not silently promote workhorse self-review to PASS.
Run the screen only through run_one run <id>. Import its evidence and move
to the next eligible path yourself. No new human prompt is required.

All provider and agent activity consumes the same absolute eight hours.
Give every delegate the run deadline, output scope, no independent research
launch authority, and no further delegation authority. Keep at most one
writing workhorse or one review task active at a time. Allow at most two
provider attempts total for an operation, no model fallback, and a combined
provider-start/retry wait allowance of 120 seconds, always inside the
remaining run and screen deadline. Follow each delegate's T3 next action.
Do not poll it with sleep or task_status. A delegate must return or be
cancelled at its assigned deadline. If the provider cannot supply a bounded
terminal lifecycle under these constraints, do not start it. Cancel tasks
you replace or no longer need with task_cancel and obtain terminal evidence
before continuing. A cancellation that cannot be confirmed is a global
blocker. Keep all local process safety in the local supervisor; it must
not depend on an API callback or the agent successfully cancelling a task.
At the final-15-minute cutoff stop dispatching both model work and local
screens. Cancel any outstanding provider task before final reporting.

Respect nonrefundable CPU-capacity reservations, cumulative screen limits,
4 GiB sampled session RSS, 100 MiB sampled attempt output, 2 GiB sampled
global output, start 8 GiB free and stop 6 GiB, and forced numerical threads.
Do not extend a budget after a negative or remove the envelope to retry.
Keep one local screen active. No cloud compute, GPU training, installs,
commits, pushes, deployments, source checkout edits or global settings.

An infrastructure deadline, memory, disk, power, missing solver, provider
or process failure is unresolved, never a scientific exact-solver timeout.
Gate 3 needs a real solver formulation, tiny solved controls, evidence that
the solver started, and its own controlled limit expiry on the same hardware.
T-count decoding timeout does not establish joint CNOT/depth hardness.
The known 136-to-140 CNOT tradeoff with depth 5-to-4 fails Pareto. Missing
Vandaele, Lau et al., PhasePoly and torch policy implementations remain
named blockers. Never recommend RL training unless all four gates pass on
physical end-to-end metrics with independent checkable evidence at two sizes.

Finish by cancelling or reconciling owned work, reading final status, and
writing the per-path pursue, reject or unresolved record with exact evidence
and the next experiment that changes the verdict. Report what fit, what
remains queued, resource debits and blockers. Do not promise all 24 paths
finish. Stop safely on any unrecoverable error or unconfirmed ownership.
```
