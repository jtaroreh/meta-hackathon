# Select, run, and recover

Research screens require selection after the infrastructure pilot. Follow the configured queue order when choosing a screen. The CLI checks queue membership but does not enforce that order. Use `select <id>`, `run <id>`, `recover`, and `status` to execute and reconcile research attempts.

## Sub-features

- `select-research` starts the durable cumulative wall clock for one queued research screen.
- `run-research` executes the selected screen under the supervisor with pilot and review gates.
- `recover-status` reconciles interrupted attempts and reports the resulting envelope.

## How to get to it (user POV)

- Run `$PY -B -m tools.overnight.run_one select <id>` for a queued research id (never `18`) with `PY=.venv/bin/python` from the repo root.
- Run `$PY -B -m tools.overnight.run_one run <id>` for the selected screen.
- Run `$PY -B -m tools.overnight.run_one recover` then `$PY -B -m tools.overnight.run_one status` to reconcile and inspect.

## Driving it with PTY

Preconditions:

- `prepare` and pilot 18 both finished for the current envelope with a live 8h deadline.
- `pilot_receipt`, `postpilot` review, and the `screen-<id>` review exist; the screen `brief.md`, `command.json`, and full `source_files` closure are frozen.
- The `EnvelopeStore` lock is held only by this run and no attempt is active.
- The screen id is in the ordered `queue` and is not `18`.

- **Select screen.** Start the clock. Run `$PY -B -m tools.overnight.run_one select <id>` in an isolated PTY. Exit code `0` and stdout name the screen id with its deadline. Repeating `select` never resets the clock.
- **Confirm select gate.** A `run` without a prior `select` refuses (`select the screen before feasibility or model preparation`). `select 18` refuses (`select a broader queued research path`).
- **Run screen.** Execute the screen. Run `$PY -B -m tools.overnight.run_one run <id>` in an isolated PTY. Exit code `0` and the attempt `receipt.json` records `finished` with `bindings` for the current run id.
- **Recover and inspect.** Run `$PY -B -m tools.overnight.run_one recover` followed by `$PY -B -m tools.overnight.run_one status`. Both commands reconcile interrupted attempts and incomplete receipt publication before printing the envelope. With an existing readable envelope, exit code `0` means no stored blocker and exit code `3` means `blocked_reason` is set. Reconciliation of an interrupted attempt blocks further launches. Recovery preserves the original deadline and never refunds CPU reservations. A clean recovery does not block subsequent launches.
- **Proof.** Capture the select transcript, the run `receipt.json` plus `execution.json` and `worker-result.json`, and the closing `status` transcript under `verify-evidence/<run-id>/select-run-recover/`.

## Gotchas

- One envelope, one local screen at a time. Never drive an envelope or screen session another run started.
- The pilot gate is load-bearing: broader screens require the stored pilot receipt hash plus the `postpilot` and `screen-<id>` reviews, not just a finished pilot attempt.
- `recover` after an interruption sets a reconciled blocker and stops autonomous execution. Re-running a command never resets the envelope or clears a blocker.
- No pre-window claims: `select` output alone is not proof. The run `receipt.json` plus `execution.json` and `worker-result.json` must all exist.
