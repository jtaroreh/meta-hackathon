# Bounded takeover verification

Status is pending fresh independent review. This report is an implementation handoff, not a launch approval. The implementation ran in-thread as Codex GPT 6.1 Sol at high reasoning. No subagents were started, as required by the bounded takeover brief. The coordinator owns the next fresh independent review.

Checkout is `/Users/joeltaroreh/.t3/worktrees/meta-hackathon/t3-aaca8270`. Base HEAD remains `4735c977361f72137d2234727e7011ae8f9e10f0`. No commit, push, global settings edit, overnight research launch or real research pilot occurred. Only tiny native/environment controls and synthetic lifecycle fixtures ran.

## What changed

The original direct command reproduced `ImportError: attempted relative import with no known parent package`. The shell entry reproduced a missing checkout-local `.venv/bin/python`. The replacement supports the direct CLI, documented module commands, an explicit absolute interpreter and a shell entry that works from another cwd. `init` creates the envelope before any preparation or provider waiting. Supervised preparation executes freeze, writable exec and blocking proof in order; the pilot uses its own fresh writable exec copy.

One session worker now owns the local workload. It writes identity before launch acknowledgement, monitors coordinator identity and deadlines, and cleans foreground descendants after normal wrapper exit, exceptions, timeout and caffeinate failure. A wrapper that leaves descendants running is an execution failure. A persisted payload identity can anchor cleanup after worker death. Unknown ownership or CPU accounting blocks further execution. Recovery and interrupted receipt publication stop the run instead of silently relaunching.

CPU admission uses nonrefundable machine-capacity reservations. It combines global remaining CPU, cumulative screen CPU, the persisted screen clock and original absolute deadline. Research selection starts the clock before feasibility, model waits and review. Zero and exhausted budgets, final-15-minute launch attempts and stale hashes fail closed. On this 10-core machine, 7,200 CPU-capacity seconds permit at most 720 reserved wall seconds including shutdown. The total 28,800-second CPU-capacity allowance permits at most 48 minutes of reserved local attempt lifetime across the run. This is deliberately more conservative than the original exact aggregate-CPU promise.

The supervisor writes stdout through an exact byte cap, counts foreground session RSS, samples available memory, AC and disk, and includes temporary files, writable builds and logs in the output scope. Numerical thread variables override inherited values. The global allowance includes generated screen sources. Production has no AC override environment variable.

Capability receipts are explicit coordinator attestations bound to run, config, tools and raw evidence. The coordinator must inspect live T3 capability output; the local CLI does not validate a remote provider. Independent tooling review precedes preparation. Postpilot review and a separately bound screen review precede broader research. Tooling hashes include the receipt contract, scientific plan, literal launch prompt, tests and staged pilot. Input hashes and evidence artifacts are rechecked before launch.

Model the Domain changed the design to durable attempts, reservations and selection clocks. Prove It Works changed verification to real CLI subprocesses, measured wait4 usage and live survivor checks. These are the two principle leaves read and applied in this takeover.

## Actual checks

The final command was:

```sh
/Users/joeltaroreh/projects/challenges/meta-hackathon/.venv/bin/python -B -m pytest tests -q --junitxml=docs/overnight-tests.xml -o junit_logging=all -o junit_log_passing_tests=true
```

Result was **58 passed, 0 failed, 0 errors, 0 skipped**. The earlier claim of 38 verified passes is removed from the current plan. [JUnit evidence](overnight-tests.xml) includes the real copied native build and its output. That proof reported `PASS: 45 checks, 0 failures`, loaded the native bridge, replayed tiny GraySynth and PMH controls and exercised pyzx extraction.

[The six environment smoke controls](overnight-smoke.txt) passed using the supplied interpreter with numerical thread clamps and checkout-local temporary paths. They cover tiny MILP, SMT, ZX, BP-OSD, Qiskit and Stim operations. They are environment controls, not a research pilot or a solver hardness claim.

`sh -n screens/18/run.sh` and `git diff --check` passed. The unmodified documented shell entry also ran through an explicit fixture interpreter from another cwd. Its synthetic launch chain completed preparation, pilot, postpilot review gating and one broader screen. Production probes were never bypassed for a research pilot.

[Collected receipts](overnight-receipts.json) preserve attempt state, CPU measurements, nonrefundable reservations, cleanup results, receipt hashes and absolute evidence paths. The collection is explicitly marked synthetic. Cases include CLI death, worker death, a crash before go acknowledgement, finite streaming output observed while live, normal-wrapper orphan cleanup, caffeinate exceptions, missing usage, sampled RSS and output limits, changing AC/disk/memory, zero budgets, cumulative retries, global deadline crossing, selected-screen waiting, receipt publication cuts and all required review gates. No live test worker with a matching recorded identity remained after the final suite.

Rebuild the summary from the latest suite without launching research:

```sh
/Users/joeltaroreh/projects/challenges/meta-hackathon/.venv/bin/python -B env/record_overnight_checks.py
```

## Current real launch prerequisites

The [host observation](overnight-host.json) was recorded at `2026-10-29T09:09:59.512722+00:00`. It reports `battery`, 3,228,680,192 available memory bytes and 9,895,141,376 free disk bytes. The host currently fails the real AC and 4 GiB available-memory gates. Disk exceeds the 8 GiB start threshold. The expected distributions and cc, make and caffeinate were found. This does not certify all screen formulations or literature baselines.

No production capability attestation or fresh independent takeover PASS was created. Those gates remain closed. The intended overnight coordinator must validate the exact Muse xhigh and Codex high/default targets, save real evidence, satisfy host gates, and follow [the literal T3 prompt](../OVERNIGHT_LAUNCH.md).

## Limits and remaining work

- This is cooperative foreground session supervision, not a filesystem sandbox or a malicious-daemonization defense. Detached sessions are unsupported. If ownership cannot be established safely, the run blocks rather than signalling unrelated processes. A matching owner or payload is required to anchor cleanup.
- RSS, disk and non-log output are sampled and can overshoot before observation. Shutdown can overrun; the extra conservative debit is recorded and the run stops. The exact write cap applies to supervisor stdout only.
- wait4 usage is payload evidence and can omit descendants it did not wait for. The capacity reservation bounds admission without claiming exact tree measurement. CPU reservations cover owned local attempts, including native preparation and watchdog work, not unrelated OS activity, the T3 app or the coordinator's lightweight text editing and probes. Provider waits consume the global and selected-screen wall clocks.
- Reservations are not refunded and interrupted runs do not retry automatically. This intentionally reduces throughput. No all-24 completion guarantee is made.
- Local safety does not depend on a remote callback. Provider and agent lifecycle bounds are instructions to the coordinator, not an API interceptor. An unavailable bounded provider lifecycle or unconfirmed cancellation is a blocker. Caffeinate is owned per local attempt; no run-wide wake guarantee is claimed for idle provider waiting.
- Only infrastructure pilot 18 is staged. The full scientific path-18 experiment remains unresolved, and the broader research screens are not built. This run uses ID 18 for the staged pilot; a full scientific path-18 experiment needs a separately staged and reviewed follow-up rather than treating pilot completion as science.
- Missing Vandaele, Lau et al., PhasePoly and torch policy implementations remain named blockers. Infrastructure failure stays unresolved. A controlled real solver limit and formulation evidence are necessary for a scientific timeout. The 136-to-140 CNOT case still fails Pareto. A pilot cannot establish a four-gate PASS or an RL recommendation.
- Early diagnostic pytest calls used the OS default temporary directory before `pytest.ini` was added. Final fixtures and evidence are under this isolated checkout. External source checkouts were read only throughout, and no venv was copied.

The remaining gate is a fresh independent review of the complete scoped source, conservative policy, literal prompt and these receipts. Self-review and tests do not satisfy that gate. No architecture, comment-review or audit-trail agent was spawned because the takeover brief explicitly prohibited delegation.

## Exact changed files

The manifest [overnight-changes.json](overnight-changes.json) lists every changed or added delivery file with its SHA256 and comparison against the prior completed worktree. The base contained only README.md and .gitignore, so copied prerequisites are also new files in this checkout. Temporary fixtures, bytecode and caches are excluded.

The exact relative paths are:

- `.audit/overnight-takeover.tsv`.
- `.gitignore`.
- `OVERNIGHT_LAUNCH.md`.
- `docs/cloud-swarm-readiness-plan.md`.
- `docs/local-readiness-review-20261027.md`.
- `docs/overnight-changes.json`.
- `docs/overnight-contract.md`.
- `docs/overnight-host.json`.
- `docs/overnight-receipts.json`.
- `docs/overnight-smoke.txt`.
- `docs/overnight-tests.xml`.
- `docs/overnight-verification.md`.
- `env/record_overnight_checks.py`.
- `env/requirements.local`.
- `env/smoke.py`.
- `overnight-config.json`.
- `pytest.ini`.
- `screens/18/brief.md`.
- `screens/18/command.json`.
- `screens/18/run.sh`.
- `tests/__init__.py`.
- `tests/fixture_cli.py`.
- `tests/fixture_interpreter.py`.
- `tests/fixture_payload.py`.
- `tests/fixture_support.py`.
- `tests/test_envelope.py`.
- `tests/test_freeze.py`.
- `tests/test_gates.py`.
- `tests/test_preflight.py`.
- `tests/test_proof.py`.
- `tests/test_stage_run.py`.
- `tests/test_supervisor.py`.
- `tools/__init__.py`.
- `tools/overnight/__init__.py`.
- `tools/overnight/envelope.py`.
- `tools/overnight/freeze.py`.
- `tools/overnight/gates.py`.
- `tools/overnight/pilot_18.py`.
- `tools/overnight/preflight.py`.
- `tools/overnight/prepare.py`.
- `tools/overnight/proof.py`.
- `tools/overnight/receipts.py`.
- `tools/overnight/run_one.py`.
- `tools/overnight/stage.py`.
- `tools/overnight/supervisor.py`.
