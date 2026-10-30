# Path 18 infrastructure pilot

This staged pilot checks preparation and controls. It does not complete the scientific path-18 screen, recommend pursue, or pass Gate 3.

Freeze the source closure listed in `tools/overnight/freeze.py`. The manifest includes source content hashes, source git state and explicit missing-file notes. The phasepoly source checkout has no AGENTS.md; the available audit-tree guidance is copied and its provenance recorded.

The pilot builds and loads the native C11 library in its own writable exec copy, runs native checks, and exercises tiny GraySynth, PMH and pyzx extraction controls. It then invokes the copied `run_algebra.py` at n=6 with a five-second solver limit and a 60-second outer timeout. It writes all output under its admitted attempt directory. The runtime envelope can impose a shorter remaining limit.

Acceptance requires successful proof and algebra control exit zero inside the current envelope. Neither success nor solver timeout is a scientific verdict here. Any outer timeout or infrastructure failure is unresolved. Corpus seeds 1 through 5 and three research sizes belong to a future full scientific screen, not this control.

The pilot requests 120 cumulative wall seconds and 1,800 cumulative CPU-capacity seconds. Admission reserves machine logical capacity for its allocated lifetime, never refunds it, and respects global remaining budgets. Limits include preparation, logs, writable copies, temporary files and shutdown. See `OVERNIGHT_LAUNCH.md` for the sampled 4 GiB RSS, 100 MiB attempt output and 2 GiB global policy.

Vandaele, Lau et al., PhasePoly and torch policy implementations are missing from the local closure and remain named blockers. The six-wire CNOT increase from 136 to 140 with depth decrease from 5 to 4 fails Pareto. A future physical-cost claim needs all four gates and independently checkable evidence at two sizes.
