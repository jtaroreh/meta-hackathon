# Init envelope

Init envelope lets an operator create one overnight envelope from the repo root, get a run-id data dir, and start the 8h deadline that later prepare and run steps depend on.

## Sub-features

- `init-create` creates `overnight-envelope.json` plus `overnight-data/<run-id>/`.
- `init-deadline` starts the 8h deadline recorded in the envelope.
- `init-idempotent-refuse` refuses a second envelope while one is held.
- `init-status` shows the new envelope through a `status` call (with recovery reconciliation).

## How to get to it (user POV)

- Run `$PY -B -m tools.overnight.run_one init` from the repo root with `PY=.venv/bin/python`.
- Run `$PY -B -m tools.overnight.run_one status` to inspect the envelope.

## Driving it with PTY

Preconditions:

- No `overnight-envelope.json` is held by another session and the `EnvelopeStore` lock is free.
- Prior-clean state only: with no envelope file, `status` exits 3 with a `blocked` message (`open_existing` fails on the missing file), so a fresh-init start is an exit-3 `status`, not an exit-0 one.
- `init` performs no resource preflight. `prepare`, `select`, and `run` require AC power, at least 4 GiB available memory, and at least 8 GiB free disk. Running work stops below 6 GiB free disk. A run that would fail a gate still creates a valid deadline-anchored envelope here and blocks later.

- **Create envelope.** Start the run. Run `$PY -B -m tools.overnight.run_one init` in an isolated PTY. Exit code `0` and stdout name the run id, and `overnight-envelope.json` plus `overnight-data/<run-id>/` exist.
- **Confirm deadline.** Inspect the envelope. Run `$PY -B -m tools.overnight.run_one status` in the same PTY. The output (or `execution.json`) shows the 8h deadline anchored at init time.
- **Confirm refusal.** Attempt a second init. Run `$PY -B -m tools.overnight.run_one init` again. It refuses (nonzero exit or explicit refusal) and does not create a second envelope.
- **Proof.** Capture the created state. Copy `overnight-envelope.json`, the `status` transcript, and the `overnight-data/<run-id>/` listing to `verify-evidence/<run-id>/init-envelope/`. The artifacts show the run id and deadline.

## Gotchas

- Single-envelope refusal: a second `init` while the lock is held must refuse. Never force it, never hand-edit the envelope, never kill by process name.
- 8h deadline: every later step runs against the init-anchored deadline. Re-init resets it, so do not re-init mid-verification.
- Launch gates are not suggestions, but `init` never checks them. A run below a gate still exits `init` with code 0 and a valid envelope, then blocks at the first launch.
- No pre-window claims: the envelope counts only after `overnight-envelope.json` and the run-id dir both exist on disk.
- Cleanup removes scratch attempt dirs but never `overnight-envelope.json` receipts kept as proof under `verify-evidence/<run-id>/`.
