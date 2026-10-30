# Coordinator verdicts — run e2640228 (relay Run N+1)

Run: `e2640228c5ad4cdcb7f9c15e80b90f50` (created 2026-10-30 ~05:06 PDT,
deadline ~13:06 PDT). Bootstrap: capabilities + tooling PASS (Wonder) +
prepare finished 1.5 s + pilot 18 finished 5.2 s + postpilot PASS.
Classifications below derive from supervised receipts and
`work/results.json` evidence only. Payloads self-report
`unresolved-with-reason`; only this record classifies.

## 07 AutoCCZ + buffer scheduling — PURSUE

Attempt `07-a01` (finished exit 0, cleanup verified, wall 86.9 s,
reservation 2744.9 CPU-capacity s vs 86.6 wait4 CPU s).

Gate vector: G1 ✓ G2 ✓ G3 ✓ G4 ✓.

- G1 (control/soundness): mean volume(S) strictly below mean volume(R) in
  all 15 (regime, seed) cells (gaps ~1300/580/470 volume units on
  small/base/stressed); tiny hand-check 8/8; determinism repeat identical.
- G2 (sensitivity): pooled {S,B,C} volume spread > 2×SE at 3/3 regimes
  (spreads 2928/6386/11469 vs SE 79/146/194). Stall spread also 3/3.
- G3 (hardness): bounded-exact DFS solves tiny (optimum 156 == hand value,
  11 nodes); target-scale instance (front 20, horizon 120, stressed
  rates) cap-hits at 50001/50000 nodes in 0.1 s. Solver started, tiny
  solved, solver's own cap-hit. No wall-kill.
- G4 (integrity): 60/60 cell-arms complete (400 reps each), tiny + target
  records present, wall 86.8 s < 500 s, zero skip records.
- Joint Pareto: arm B jointly wins 3/3 regimes — pooled volume beats S by
  > 2×SE (small 61437 vs 64365; base 88561 vs 94945; stressed 134936 vs
  146406) with stalls no-regress on the SAME arm (B 300/628/1196 vs S
  321/691/1318). Arm C matches B exactly at these widths (recorded
  finding, not a separate win; winner prefers B).

Decisive evidence: joint dynamic-buffer wins at 3/3 factory regimes with
all gates evidenced and exact-solver cap-hit at target scale.

Next experiment (frozen): burst-heavier fronts with larger shared
buffers, then a wider ready window / narrower corridor retest (C rollout
adds nothing at current widths).

## Carried (from sealed run f5ac1866 — not re-run here)

- 18 Phase-polynomial pilot: INFRA ONLY — ok.
- 02 Flag-gadget schedule search: PURSUE (d=3-bounded).
- 20 Photonic fusion routing: REJECT on this screen.
- 04 Erasure + biased hybrid: REJECT on this screen.
- 01 qLDPC BP-guiding: UNRESOLVED (tail follow-up).
- 06 Lattice-surgery routing: UNRESOLVED (tail autopsy).
- 10 AOD vs OLSQA: BLOCKED (offline corpus attempt 2026-10-30: no paper
  titled OLSQA exists; OLSQ-DPQA arXiv:2306.03487 has no freezable
  20/40/60 tables in the screen metric — Figs 4c/5e are figure-only).
- 15 ZX spider-fusion + gflow: DEFERRED (staged d1970c84…, tail relay).

## 12 Mid-circuit reuse — UNRESOLVED (select-to-launch window expired; carried)

Staged + integrated byte-identical (`screens/12/`, workhorse spark
xhigh, dry-run 74.4 s zero skips in `/tmp/s12dry`). No review filed, no
`run 12` launched in this run. Launch refused:
`cumulative screen or run budget exhausted`.

Root cause (verified in code): `supervisor.run_screen` admits only
`min(900 - screen_wall_used, deadline-now, remaining/10) > 8.5 s`,
where `screen_wall_used` includes the live select clock
(`envelope.py:170-175`: `max(attempts, now - screen_started_at)`).
Select 12 → review-ready took ~1017 s (workhorse bugfix + scaled
dry-runs), exceeding the ~891 s admission window. Repeat `select` never
resets the clock (`run_one.py:202` `setdefault`; hand-editing the
envelope is prohibited). Screen 07 admitted at a ~625 s gap (reservation
2744.9 CPU-s), confirming the same window. The 9000 s screen deadline
(`run_one.py:204-205`) governs cumulative screen life, but the first
launch must land within ~891 s of select — staging + independent review
must sprint inside that window. Feasibility/model work before select is
prohibited ("never skip select to save the clock"), so the sprint starts
at select, not before. Flagged as a candidate between-run tooling
amendment (whether the 891 s first-launch window is intended given the
45-minute feasibility / 9000 s cumulative language).

Exact next experiment: re-select 12 in a fresh relay envelope (clock
reset) and review + launch inside the window — the staged files carry
over unchanged (precedent: screen 15's staged commit carried across
relays). No gates evidence; never a negative result.

## Queued (clocks untouched in this run)

12 (staged, carried to next relay run), 19, 24; then 03, 05, 08, 09,
11, 13, 14, 16, 17, 21, 22, 23; tail 15, 02 scale-up, 01, 06 (+10 if
corpus frozen).
