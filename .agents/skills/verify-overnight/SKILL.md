---
name: verify-overnight
description: Drive the overnight supervisor CLI (tools.overnight.run_one) the way an operator does — use to launch, doctor, drive, and prove init, prepare, and screen-18 runs with file evidence.
---

# Verify Overnight

Drive the overnight supervisor CLI as an operator would. Local CLI only. No web UI, no API, no browser.

Primary surface: `tools.overnight.run_one` subcommands (`init`, `prepare`, `select <id>`, `run <id>`, `recover`, `status`), plus `.venv/bin/python -B -m pytest tests -q` and `sh screens/18/run.sh` with `OVERNIGHT_PYTHON`. Evidence lives in files, never in a live server response.

## Launch

Run everything from the repo root with `PY=.venv/bin/python`.

Build once (short-lived CLI, no server to keep alive):

```sh
PY=.venv/bin/python
$PY -B -m pytest tests -q
```

Start each drive in its own isolated PTY or tmux session. Exact drive commands:

```sh
$PY -B -m tools.overnight.run_one init
$PY -B -m tools.overnight.run_one prepare
$PY -B -m tools.overnight.run_one select <id>
$PY -B -m tools.overnight.run_one run <id>
$PY -B -m tools.overnight.run_one recover
$PY -B -m tools.overnight.run_one status
OVERNIGHT_PYTHON=$PY sh screens/18/run.sh
```

`init` creates `overnight-envelope.json` plus `overnight-data/<run-id>/` and starts the 8h deadline. `prepare` runs the freeze plus exec copy plus proof. Pilot 18 repeats the proof plus the algebra control.

Ready means usable, not just exit code 0: a usable prompt or receipt path exists (`overnight-envelope.json`, `overnight-data/<run-id>/`, `receipts/*.json`) plus a proof or pilot artifact (`execution.json`, `worker-result.json`, or `screens/18` output). A bare exit code without the receipt path is not ready.

Teardown: run `status`, then `recover` for anything this run started, then remove scratch attempt and work dirs. Never delete proof artifacts. See Cleanup.

## Doctor

Run first whenever anything looks off. `status` performs recovery reconciliation and can update the envelope or clean up interrupted processes. Never use internal setters.

```sh
$PY -B -m tools.overnight.run_one status
```

Checks:

- `overnight-envelope.json` exists and parses.
- Exactly one envelope and one lock holder: the `EnvelopeStore` exclusive OS lock is held by this run. A second holder or second envelope means refuse to drive.
- `init` performs no resource preflight. `prepare`, `select`, and `run` require AC power, at least 4 GiB available memory, and at least 8 GiB free disk. Running work stops below 6 GiB free disk. `status` does not check these resource gates.
- Port owned by us: N/A. Local CLI only, no ports.
- Version and build: pytest and `env/smoke.py` report the expected tree (`.venv/bin/python -B env/smoke.py` exits 0).

If any check fails, stop and fix the base before driving.

## Drive

Shell plus one isolated PTY or tmux session per drive. Existing harness first: `tests/fixture_cli.py` plus pytest. No browser.

PTY recipe:

1. Open a fresh isolated PTY or tmux session owned by this run.
2. From the repo root, run one subcommand: `$PY -B -m tools.overnight.run_one status` for state, or `init`, `prepare`, `select <id>`, `run <id>`, `recover` for action.
3. For pilot 18: `OVERNIGHT_PYTHON=$PY sh screens/18/run.sh` in its own PTY.
4. Prefer `$PY -B -m tools.overnight.run_one status` for state. Never call internal setters or edit the envelope by hand.

Stable handles are subcommand names plus receipt paths (`execution.json`, `worker-result.json`, `receipts/*.json`). No coordinates, no tab order, no screen scraping.

## Evidence

Capture the action and the resulting state, not just the final line.

- Terminal transcript including the exact command, stdout, stderr, and exit code. `stdout.log` has a 5MiB cap.
- Resulting state files: `execution.json`, `worker-result.json`, `receipts/*.json`.
- Side files: `screens/18/brief.md`, `screens/18/command.json`, `screens/18/run.sh` output, plus attempt and work dirs and envelope files changed by the run.
- Side effects: verify attempt and work dirs, envelope files, and receipts alongside the transcript. A passing exit code without the receipt is not proof.
- Mocks only at a production boundary the harness already isolates. No ad-hoc mocks.
- When the safe path is a dry run or test mode, verify what it actually skips by observing files and git refs, never by trusting its name.

Proof artifacts survive cleanup at the location the feature file names (see `features/`).

## Cleanup

Kill only what this run started, via the supervisor. Never kill by process name, only owned session members.

```sh
$PY -B -m tools.overnight.run_one status
$PY -B -m tools.overnight.run_one recover
```

Then remove scratch attempt and work dirs created by this run. NEVER delete proof artifacts (`execution.json`, `worker-result.json`, `receipts/*.json`, pilot 18 output, captured transcripts). Evidence path: `verify-evidence/<run-id>/` under the repo root (create per run, keep after teardown).

Run cleanup after every failed iteration too, so broken attempts do not strand sessions or the envelope lock.

## Helpers

No shipped helpers. Every command above runs directly from the repo root with `PY=.venv/bin/python`. The existing harness (`tests/fixture_cli.py` plus pytest) is invoked as shown in Launch and Drive.
