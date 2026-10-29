# Run screen 18

Run screen 18 lets an operator execute the pilot screen that repeats the proof plus the algebra control through `screens/18/run.sh`, then confirm the run from the brief, command, and receipt files.

## Sub-features

- `screen18-run` executes the pilot via `sh screens/18/run.sh` with `OVERNIGHT_PYTHON`.
- `screen18-proof` repeats the proof artifacts for the pilot run.
- `screen18-algebra` runs the algebra control alongside the proof.
- `screen18-confirm` confirms the finished state through status and receipts.

## How to get to it (user POV)

- Run `OVERNIGHT_PYTHON=$PY sh screens/18/run.sh` with `PY=.venv/bin/python` from the repo root.
- Run `$PY -B -m tools.overnight.run_one run 18` where the supervisor path requires it, and `$PY -B -m tools.overnight.run_one status` to inspect the screen. Pilot 18 takes no `select`: the CLI refuses `select 18` (`select a broader queued research path`). `select` applies only to queued research screens (see `select-run-recover.md`).

## Driving it with PTY

Preconditions:

- `prepare` has succeeded for the current envelope with a live 8h deadline.
- `screens/18/brief.md`, `screens/18/command.json`, and `screens/18/run.sh` exist and are unchanged.
- Exactly one local screen runs at a time and the `EnvelopeStore` lock is held only by this run.
- AC power and at least 4 GiB available memory are required. Each launch requires at least 8 GiB free disk. Running work stops below 6 GiB free disk.

- **Run pilot.** Execute the pilot. Run `OVERNIGHT_PYTHON=$PY sh screens/18/run.sh` in an isolated PTY. Exit code `0` and stdout name the proof plus algebra control outputs. No `select` step exists for 18: the pilot is the infrastructure gate that later `select` calls depend on, and repeating a finished pilot refuses (`pilot already complete; do not repeat`).
- **Direct run path.** `screens/18/run.sh` already execs `$PY -B -m tools.overnight.run_one run 18`; it is the same entry point, not an alternative. Exit code `0` and the attempt `execution.json` plus `worker-result.json` update for run 18. A finished pilot never repeats (`pilot already complete; do not repeat`).
- **Confirm state.** Reinspect with recovery reconciliation. Run `$PY -B -m tools.overnight.run_one status` to read the envelope `pilot_receipt` pointer, then inspect the pilot receipt at `attempts/18-<hex>/receipt.json` (`pilot_ok: true`, full artifact hash map). Files directly under `receipts/` hold only coordinator gate receipts (capabilities, tooling review), which do not name screen 18.
- **Proof.** Capture the pilot state. Copy the `run.sh` transcript and the attempt-dir artifacts (`pilot.json`, `work/control-output/`, `receipt.json`, `execution.json`, `worker-result.json`) to `verify-evidence/<run-id>/run-screen-18/`. `screens/18/` holds only `brief.md`, `command.json`, and `run.sh`; no run outputs exist there to copy. The artifacts show both the proof repeat and the algebra control.

## Gotchas

- Single-envelope refusal: a second local screen or a foreign lock holder must refuse. One envelope, one local screen at a time.
- `select 18` always refuses. The pilot runs unselected; only queued research screens take `select` (see `select-run-recover.md`).
- 8h deadline: a pilot started before expiry but finishing after it is invalid. Confirm the deadline in `status` before and after.
- AC power and at least 4 GiB available memory are required. Each launch requires at least 8 GiB free disk. Running work stops below 6 GiB free disk. Re-check when the pilot looks slow or truncated.
- No pre-window claims: `run.sh` output alone is not proof. The receipts plus `execution.json` and `worker-result.json` must all exist.
- `stdout.log` caps at 5MiB. A truncated transcript without the receipt set is an incomplete run, not a pass.
