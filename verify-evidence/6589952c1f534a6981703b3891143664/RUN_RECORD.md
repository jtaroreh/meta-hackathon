# Run 6589952c1f534a6981703b3891143664 — fresh envelope (loop continuation)

Prior stopped run `54a977c2cb03483e932a0462f33f57be` reconciled (recover exit 0:
2 attempts finished, cleanup verified, no survivors) and archived to
`verify-evidence/54a977c2cb03483e932a0462f33f57be/overnight-envelope.json`
with its output tree intact. This is a new run under standing user
authorization to fix resolved blockers and loop the plan.

- Created: 1793307462 (≈13:57 PDT Oct 29). Deadline: 1793336262 (≈21:57 PDT).
- No new launches after ≈21:42 PDT (cutoff_sec=900).
  Budgets: 28,800 global; 7,200 CPU / 9,000 wall per screen; 120/1,800 prep/pilot.
- tool_hash `e10ce85a…` recomputed at init: IDENTICAL (screen-01 guard fix
  touches screens/01 only, outside the hashed set). config_hash unchanged.

## Gates

- `pytest tests -q` → 62/62.
- `orchestrator_capabilities` (live, once this run): all three exact targets
  PRESENT. Filed receipts/capabilities-raw.json + capabilities.json;
  production check_capabilities PASSES.
- tooling-review.json: REBOUND prior PASS evidence per contract clause (prior
  raw evidence inspected these exact bytes: recomputed tool_hash matches;
  evidence bytes copied verbatim into this run's receipts/ with fresh
  run-bound attestation). Original review: codex-pstack/gpt-6.1-sol
  high/default, task tooling-review-54a977c2-attempt1, mode wait, completed.
  Production check_review PASSES. No new provider attempt spent.

## Screen-01 state

Guard-path defects from the second REVISE fixed in screens/01 (guarded corpus
lookups, default d3 record, truthy-safe determinism check, DEM dropped-count
reporting, channel_probs in determinism check). screen_files now
5282f24b… (was 17f167b1…). Fresh screen review required in this run
(attempt counting restarts: max 2 for the operation).

## Execution record

- `prepare` → finished exit 0, proof ok:true. `pilot 18` → finished exit 0,
  pilot ok:true. Postpilot review attempt 1 → PASS; all production checks green.
- Screen 01: select → staged review attempt 1 REVISE (pulp status mapping) →
  one-line fix verified → attempt 2 PASS → receipt filed → run finished
  exit 0 in ~14 s, cleanup verified. Classified UNRESOLVED (Gate 3: no CBC/
  HiGHS/GLPK binary in supervised env; pheno B-fractions ≤0, circuit B1-serial
  strongly positive — recorded). CPU 2887 reserved.
- Screen 06: select → staged by workhorse child → attempt 1 REVISE (5 groups)
  → bounded correction verified → attempt 2 REVISE (loc_candidates timing
  missed + dead helper + loose language). Defect confirmed. No receipt filed.
- RUN STOPPED per contract (second REVISE on 06). recover exit 0 (3 attempts
  finished, no survivors); status 5287 CPU, no blocker string. Verdicts in
  results/verdicts.md: 18 infra-complete; 01 unresolved; 06 unresolved
  (named defect + next experiment); 21 paths queued.
