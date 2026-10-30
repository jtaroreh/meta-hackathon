"""Stage one screen dir. Explicit selection, no queue.

Creates screens/<id>/ with a brief template and a run.sh that wires
the envelope, the writable exec copy, and bounded logging. Refuses to
run inside the frozen tree. Staged pilot path 18 is infrastructure
and control validation only.
"""
from __future__ import annotations

import os
import stat

BRIEF_TEMPLATE = """# Screen {screen_id} brief (staged, not launched)

Scope: {scope}
Hypothesis: <one sentence>
Corpus: <frozen paths>
Controls: <classical baselines that actually exist locally>
Acceptance: <Pareto or pre frozen weights, two sizes>
Seeds: 1 2 3 4 5
Compute cap: {cpu_cap_sec} CPU-capacity-sec, {wall_cap_sec} cumulative wall-sec
Run select before feasibility or model preparation. Outputs belong to the admitted attempt.
Sizes: <three small sizes>

Pilot note: staged pilots validate infrastructure and controls only.
A pilot pass is never a pursue verdict and never clears Gate 3.
Missing baselines (Vandaele, Lau et al., PhasePoly, torch policy)
stay unresolved with named blockers.
"""

RUN_SH_TEMPLATE = """#!/bin/sh
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${{OVERNIGHT_PYTHON:-$ROOT/.venv/bin/python}}"
cd "$ROOT"
exec "$PY" -B -m tools.overnight.run_one --root "$ROOT" run "{screen_id}"
"""


def stage_screen(root: str, screen_id: str, scope: str,
                 cpu_cap_sec: float, wall_cap_sec: float) -> str:
    if "/" in screen_id or screen_id in (".", ".."):
        raise ValueError("bad screen id")
    if "frozen-source" in os.path.abspath(root):
        raise ValueError("never stage inside the frozen tree")
    screen_dir = os.path.join(root, "screens", screen_id)
    if os.path.exists(screen_dir):
        raise FileExistsError(screen_dir)
    os.makedirs(screen_dir)
    with open(os.path.join(screen_dir, "brief.md"), "w") as fh:
        fh.write(BRIEF_TEMPLATE.format(
            screen_id=screen_id, scope=scope,
            cpu_cap_sec=cpu_cap_sec, wall_cap_sec=wall_cap_sec))
    run_sh = os.path.join(screen_dir, "run.sh")
    with open(run_sh, "w") as fh:
        fh.write(RUN_SH_TEMPLATE.format(screen_id=screen_id))
    os.chmod(run_sh, os.stat(run_sh).st_mode | stat.S_IEXEC | stat.S_IXGRP)
    return screen_dir
