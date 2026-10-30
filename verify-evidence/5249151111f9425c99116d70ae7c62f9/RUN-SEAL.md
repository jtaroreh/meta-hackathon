# Run 52491511 — seal note (stillborn, terminal infrastructure blocker)

- run_id: 5249151111f9425c99116d70ae7c62f9 (created 2026-10-30 04:23 PDT, deadline 12:23 PDT)
- config_hash: b114e0fd…a974 / tool_hash: b6b50ec6…2d9b (post-#13 + test-fix bytes)
- Bootstrap completed through: init, capabilities receipt (3/3 targets
  validated), independent tooling PASS (muse-wonder-1.0 max, attempt 1/2).
- prepare-a01: launched on a 4.17 GiB single-sample probe; worker
  resource_killed mid-run (BlockedError: available memory below 4 GiB),
  wall 1.24 s, 1200 CPU-s reserved (nonrefundable), cleanup verified.
- blocked_reason is sticky in code (run_one.py:144, nothing clears it);
  check_launchable refuses all further launches. Run is terminal with zero
  screens. Closed with recover (exit 3 = blocked, by design) + status.
- Archive: overnight-envelope-final.json + capabilities.json/raw +
  tooling-review.json/attempt1 (this directory). Attempt evidence remains
  under overnight-data/5249151111f9425c99116d70ae7c62f9/ (gitignored).
- Relay continues in a fresh envelope once host memory holds ≥4.3 GiB over
  3 consecutive probes (~5 min). Lesson: never launch on one marginal probe.
