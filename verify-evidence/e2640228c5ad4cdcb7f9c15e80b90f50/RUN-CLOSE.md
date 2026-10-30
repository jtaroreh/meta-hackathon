# Run e2640228 — close note (relay Run N+1, closed clean)

- run_id: e2640228c5ad4cdcb7f9c15e80b90f50 (init 2026-10-30 ~05:06 PDT,
  closed same day; no blocker, recover exit 0, 3/3 attempts finished).
- Bootstrap: capabilities (3/3 targets) + tooling PASS (Wonder, 1/2) +
  prepare-a01 finished 1.5 s + pilot 18-a01 finished 5.2 s +
  postpilot PASS (Wonder, 1/2).
- Screen 07: staged (workhorse spark xhigh, 6 min) → integrated
  byte-identical → review PASS (Wonder, 1/2) → run 07-a01 finished
  86.9 s wall, reservation 2744.9 CPU-s → coordinator verdict PURSUE
  (G1✓ G2✓ G3✓ G4✓, joint B wins 3/3 regimes). Committed.
- Screen 12: staged + integrated byte-identical (workhorse spark xhigh,
  dry-run 74.4 s zero skips). No review filed, never launched — first
  launch refused (`cumulative screen or run budget exhausted`) because
  the select→review-ready gap (~1017 s) exceeded the ~891 s admission
  window: launch admits only
  min(900 − screen_wall_used, …) > 8.5 s with screen_wall_used including
  the live select clock (envelope.py:170-175); repeat select never resets
  (run_one.py:202 setdefault). Verdict UNRESOLVED + named blocker; files
  carried to the next relay run (precedent: screen 15 staging carried
  across relays). Flagged as a candidate between-run tooling amendment
  (891 s first-launch window vs 45-min feasibility / 9000 s cumulative
  language). Lesson: sprint staging + review inside ~890 s of select;
  pre-stage nothing (contract), but reuse staged files across relays.
- Debits: 5144.86 / 28800 CPU-s (prepare 1200 + pilot 1200 + 07 2744.86).
  Stranded remainder by design at close.
- Screen 10 stays BLOCKED (offline OLSQ-DPQA corpus evaluation recorded
  in task note; no freezable 20/40/60 tables in-metric).
