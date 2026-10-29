# Overnight verification map

This directory is the maintained source for verifying the user-facing behavior of the overnight supervisor CLI. Read this index before driving, then use the matching feature file as the recipe.

## Baseline preconditions

- Work from the repo root with `PY=.venv/bin/python`.
- Local CLI only. No web UI, API, or browser.
- Run `$PY -B -m tools.overnight.run_one status` and require a single envelope, a single lock holder, and an empty `blocked_reason`. `init` performs no resource preflight. `prepare`, `select`, and `run` require AC power, at least 4 GiB available memory, and at least 8 GiB free disk. Running work stops below 6 GiB free disk.
- Never drive an envelope or screen session that was not started by this verification run.
- One envelope and one local screen at a time. A second holder refuses.
- Do not make pre-window claims: nothing counts as verified until its receipt and artifact exist in files.

## Driving conventions

- Start every recipe from the baseline state unless its preconditions say otherwise.
- Prefer subcommand names plus receipt paths (`execution.json`, `worker-result.json`, `receipts/*.json`) over output position or timing.
- Treat every command as literal. Keep `PY`, `-B`, subcommand names, and `OVERNIGHT_PYTHON` unchanged.
- Run state checks through `$PY -B -m tools.overnight.run_one status`, never through internal setters.
- Run pilot 18 through `OVERNIGHT_PYTHON=$PY sh screens/18/run.sh` in its own isolated PTY.
- Capture the action and the resulting state for every proof. Proof artifacts survive cleanup under `verify-evidence/<run-id>/`.

## Proof and skip reporting

- CLI proof includes the exact command, stdout, stderr, and exit code, plus the resulting receipt or artifact file.
- Mutation proof includes a second view (`status` with recovery reconciliation, `execution.json`, or receipt) of the stored value.
- Record the feature ID and entry point used with every artifact.
- Report an unreachable path with the attempted command and the unmet precondition.
- Do not report a skipped entry point as verified through a different path.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the user-visible behavior. It then uses exactly four H2 sections in this order.

1. `Sub-features` lists short IDs with one line for each behavior.
2. `How to get to it (user POV)` lists every user entry point.
3. `Driving it with PTY` starts with `Preconditions:` and uses labeled bullets that pair each user action with an exact command and observable result.
4. `Gotchas` lists traps that can waste or invalidate a verification run.

Keep implementation details out of the map. Name only user paths, stable handles, required state, commands, and observable proof.

## Features

- [Init envelope](./init-envelope.md) covers envelope creation, run-id dir, 8h deadline, and refusal of a second envelope.
- [Prepare proof](./prepare-proof.md) covers freeze, exec copy, and proof artifacts before any run.
- [Run screen 18](./run-screen-18.md) covers the pilot 18 repeat of proof plus algebra control (no `select`; the pilot runs unselected and never repeats).
- [Select, run, and recover](./select-run-recover.md) covers research-screen `select`/`run` after explicit selection plus `recover`/`status` reconciliation.
