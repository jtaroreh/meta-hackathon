# Prepare proof

Prepare proof lets an operator run the freeze plus exec copy plus proof step that must succeed before any screen run, and inspect the resulting artifacts from a second view.

## Sub-features

- `prepare-freeze` freezes the envelope state for the run.
- `prepare-execcopy` stages the exec copy used by later runs.
- `prepare-proof` writes the proof artifacts (`execution.json`, `worker-result.json`, receipts).
- `prepare-status` confirms the prepared state through `status` (with recovery reconciliation).

## How to get to it (user POV)

- Run `$PY -B -m tools.overnight.run_one prepare` from the repo root with `PY=.venv/bin/python`.
- Run `$PY -B -m tools.overnight.run_one status` to confirm the prepared state.

## Driving it with PTY

Preconditions:

- `overnight-envelope.json` plus `overnight-data/<run-id>/` exist from `init` with a live 8h deadline.
- The `EnvelopeStore` lock is held only by this run.
- AC power and at least 4 GiB available memory are required. Each launch requires at least 8 GiB free disk. Running work stops below 6 GiB free disk.

- **Run prepare.** Run `$PY -B -m tools.overnight.run_one prepare` in an isolated PTY. Expect exit code `0` and a JSON execution receipt containing `receipt`, `execution_status`, `command`, `bindings`, and `artifact_hashes`. Inspect `preparation.json` for `ok`, the frozen manifest path, and the embedded proof. The writable exec copy is at `work/exec/` inside the attempt directory.
- **Confirm artifacts.** Inspect the proof from a second view. Run `$PY -B -m tools.overnight.run_one status` to read the envelope `preparation` path, then list that attempt dir: `execution.json`, `worker-result.json`, `receipt.json`, and `preparation.json` all exist. Files under `receipts/` (`capabilities.json`, `tooling-review.json`) are coordinator-written attestations the CLI checks, never writes. Run-id binding lives in `receipt.json` `bindings` plus the `evidence` hashes inside `preparation.json`, not in artifact filenames.
- **Confirm stdout bound.** Check the transcript size on disk. Confirm `stdout.log` (where present) stays under the 5MiB cap and inspect `receipt.json` for the recorded command and `execution_status`. `status` prints only the envelope dict, so it cannot show the log size or the command.
- **Proof.** Capture the prepared state. Copy the `prepare` transcript, `execution.json`, `worker-result.json`, and one receipt to `verify-evidence/<run-id>/prepare-proof/`. The artifacts show the same run id in the envelope and the proof.

## Gotchas

- Single-envelope refusal: `prepare` against a lock held by another session must refuse. Never drive a foreign envelope.
- 8h deadline: `prepare` after the deadline is invalid. Re-check `status` before claiming the proof.
- AC power and at least 4 GiB available memory are required. Each launch requires at least 8 GiB free disk. Running work stops below 6 GiB free disk.
- No pre-window claims: freeze output alone is not proof. All of `execution.json`, `worker-result.json`, and a receipt must exist.
- Dry-run skips (if used) must be verified by observing files and git refs, never by trusting the mode name. Some dry runs still write.
