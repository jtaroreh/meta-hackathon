# Run 9135f7bc8fc342978ad08e553688cf74 — fresh envelope (start-soon)

Prior expired run `d188df36...` reconciled (0 attempts, 0 CPU) and archived to
`verify-evidence/d188df3668644210b6896b1b15b3d947/overnight-envelope.json`
with its output tree intact under `overnight-data/d188df3668644210b6896b1b15b3d947/`.
This is a new run, not a reset: config and tool hashes are unchanged.

- Created: 1793304681 (≈13:11 PDT Oct 29). Deadline: 1793333481 (≈21:11 PDT Oct 29).
- No new launches after ≈20:56 PDT (final 15 min). Budgets: 28,800 CPU-capacity
  seconds global; 7,200 CPU / 9,000 wall per screen; 120 wall / 1,800 CPU for
  preparation and pilot 18.
- Verified at init: `pytest tests -q` → 58/58; preflight AC, 32 GiB disk,
  7.0 GiB available memory, all modules; `status` 0 attempts, no blocker.

## Still gated (need internet — do NOT attempt while offline)

1. `capabilities.json` attestation from live `orchestrator_capabilities`.
2. `tooling-review.json` PASS from advisor `codex-pstack/gpt-6.1-sol`
   high/default (max two provider attempts for the operation).
3. Then `prepare`, pilot 18 (`OVERNIGHT_PYTHON=$PY sh screens/18/run.sh`),
   postpilot PASS, then `select <id>` + `run <id>` in queue order.

## Execution record (full-plan attempt, same session)

- Live `orchestrator_capabilities` re-queried; all three exact targets present.
  Filed `receipts/capabilities-raw.json` (transcribed from the live tool
  response) + `receipts/capabilities.json`; production `check_capabilities`
  PASSES. Pre-existing `58/58` suite treated as historical by the reviewer.
- Tooling review delegated to `codex-pstack/gpt-6.1-sol` high/default
  (attempt 1 of 2, mode wait, completed, no timeout) → **REVISE**.
  Raw evidence preserved at
  `overnight-data/9135f7bc8fc342978ad08e553688cf74/receipts/tooling-review-attempt1.txt`.
  No binding `tooling-review.json` filed (gate requires PASS).
- `prepare` observed refusing with exit 3 and zero side effects; `status`
  confirms 0 attempts, 0.0 CPU, no blocker string (pre-launch gate stop).
- Per-path record written to
  `overnight-data/9135f7bc8fc342978ad08e553688cf74/results/verdicts.md`.
  Run stopped at the tooling gate with a named blocker. No second provider
  attempt: the verdict is substantive on unchanged bytes.

## While offline (commute steering)

Allowed: read files, `pytest`, preflight, `status`, `recover`. Keep AC, lid
open, T3 running. Forbidden: `delegate_task` or any provider call, writing
receipts, `prepare`/`select`/`run` (CLI refuses without receipts — safe by
construction). If anything looks stuck: `status`, then `recover`, then stop.
