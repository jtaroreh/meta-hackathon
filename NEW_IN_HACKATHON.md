# What is new in the hackathon window

Build window: Oct 26 to Nov 2, 2026. Everything below landed in that window.

## New: `pursuit/05/`

The PufferLib program is new: the exact-evaluation harness, the abort env, the exact static and history optima, the BC plus PPO trainer, the Muse Spark demo loop, the held-out results, the submission video, and the tests. It arrived in five parts: harness, env, train, demo, ship. The dated record is [pursuit/05/BUILD_LOG.md](pursuit/05/BUILD_LOG.md). Also new at the root: `README.md`, this file, and `.audit/pursuit-05.tsv`, the committed decision trail.

## Imported in-window: `screens/05/src/run05.py`

The certified screen 05 search landed in-window and the program imports it without editing it:

- `cd83fd0` (2026-10-30): stage screen 05 magic-state cultivation schedules.
- `08446bb` (2026-10-30): per-arm pursue counting plus exact-guard skip records.

One module imports it: `pursuit/05/pursuit05/screen.py` re-exports the certified functions (`build_cell`, `drop_one`, `precompute`, `eval_policy`, the `run_*` arms) and nothing else touches `run05` directly.

## Excluded

- `screens/**`: imported, never edited. `git diff main -- screens/` is empty on every pursuit branch.
- `tools/**`, `tests/**`, `overnight-*`: untouched by this program.
- `verify-evidence/`: review captures from the program's own verification; not part of the submission.
- Checkpoints and receipts under `pursuit/05/runs/` are committed build outputs of the new code above, so the offline demo and the eval checks run on a fresh clone.

Built by `muse-spark-1.3-contributor`; the build log names the model on every row.
