# HANDOFF — overnight screening loop (run a0268985, AC restored)

Snapshot at handoff: AC attached (battery 80%), envelope `a0268985` parked
clean (recover exit 0, 0 attempts, 0 CPU), ~7.9 h left on deadline 1793337603
(≈22:20 PDT; no-launch cutoff ≈22:05 PDT). Tool `e10ce85a…`, config `3290f84f…`.

## What is already done in this run

- pytest 62/62; capabilities PASS (live call done — do NOT call
  orchestrator_capabilities again this run); tooling PASS rebound on identical
  bytes. Production checks green. Receipts in
  `overnight-data/a0268985f0e5456b9384ea8e4e609ee0/receipts/`.
- Screen-06 fix staged: `loc_candidates` traversal timing, dead helper
  deleted, timeout-reason language tightened. screen_files `f5b0f75d…`.
- Screen-01 precedent (prior run): ran clean, UNRESOLVED — no MILP binary in
  supervised env. Fix ready: `brew install cbc` (bottled 2.10.13 confirmed),
  then re-run Gate-3 arm under fresh review in a later cycle.

## Resume sequence (in order, one step at a time)

1. `run_one status` + production preflight (must show AC).
2. `brew install cbc` (also serves screen-01 retry; does not touch tool_hash).
3. `run_one prepare` → pilot 18 (`OVERNIGHT_PYTHON=$PY sh screens/18/run.sh`).
4. Postpilot review: one delegate_task role=review to
   codex-pstack/gpt-6.1-sol high/default, read-only, no sub-delegation,
   deadline-bound, max 2 attempts, no fallback. File postpilot-review.json
   ONLY on PASS; verify via receipts.check_review.
5. `run_one select 06` (starts 9000 s screen clock).
6. Screen-06 review: same delegate pattern (attempt count restarts: max 2).
   File screen-06-review.json ONLY on PASS with artifacts
   {preparation, pilot, screen_files=f5b0f75d…}.
7. `sh screens/06/run.sh`, read work/results.json, classify per frozen
   brief (pursue/reject/unresolved + next experiment). Record in
   `overnight-data/a0268985…/results/verdicts.md`.
8. Continue queue in order: 10 (BLOCKED until OLSQA figures sourced — do not
   select), 15 (stageable; pyzx has gflow), 20 (needs from-scratch sim),
   then 02, 04, 07, 12, 19, 24, 03, 05, 08, 09, 11, 13, 14, 16, 17, 21, 22,
   23. Per screen: select → stage → review (max 2) → run → classify.
   One screen at a time; one writer or one review task active at a time.

## Hard constraints (never override)

- No editing frozen tooling mid-run (tools/, tests/, screens/18, docs,
  OVERNIGHT_LAUNCH.md). No commits/pushes/installs-into-run/cloud/GPU.
- REVISE → one bounded correction + fresh review. Second REVISE, TAKEOVER,
  unavailable reviewer, failed gate, or unconfirmed cancel → stop safely,
  archive envelope to verify-evidence/<run-id>/ (never delete), report.
- Reviewer/advisor/takeover is ALWAYS codex-pstack/gpt-6.1-sol high/default;
  workhorse is muse/muse-spark-1.3-contributor xhigh. No substitutions,
  no fallbacks. Reviews are read-only, no sub-delegation, deadline-bound.
- Budgets: 28800 global CPU-capacity s; 7200 CPU + 9000 wall per screen;
  120 wall/1800 CPU prep/pilot. Final-15-min no-launch cutoff. Preflight AC,
  ≥4GiB mem, 8GiB start / 6GiB stop disk.
- Finish every run with recover + status and per-path
  pursue/reject/unresolved + next-experiment in <output>/results/verdicts.md.
  Never promise all 24 paths.

## Key records

- Ledger: verify-evidence/a0268985f0e5456b9384ea8e4e609ee0/RUN_RECORD.md
- Verdicts: overnight-data/a0268985f0e5456b9384ea8e4e609ee0/results/verdicts.md
- Prior runs (archived, intact): verify-evidence/9135f7bc…,
  verify-evidence/54a977c2…, verify-evidence/6589952c… (+ overnight-data trees)
- Screen-01 evidence: prior run attempt 01-3d08f8e5…/work/results.json
  (pheno B-fractions ≤0; circuit B1-serial +70–80% gap; Gate 3 missing-solver)

## Paste-ready prompt for the new thread

```text
/jtaroreh-mode continue the overnight screening loop in checkout
/Users/joeltaroreh/projects/challenges/meta-hackathon
(interpreter .venv/bin/python). Read OVERNIGHT_LAUNCH.md,
docs/overnight-contract.md, docs/cloud-swarm-readiness-plan.md,
.agents/skills/verify-overnight/SKILL.md, and the HANDOFF + RUN_RECORD at
verify-evidence/a0268985f0e5456b9384ea8e4e609ee0/ first. Workhorse
muse/muse-spark-1.3-contributor xhigh; advisor/takeover
codex-pstack/gpt-6.1-sol high/default; no substitutions. Run a0268985 is
parked clean (0 attempts, 0 CPU) with gate receipts filed; AC is restored.
Execute the resume sequence in HANDOFF (preflight, brew install cbc,
prepare, pilot 18, postpilot review, select 06, screen-06 review, run,
classify, then the queue), obeying all hard constraints. Loop screens until
cutoff/budget/stop; finish with recover+status and results/verdicts.md.
```
