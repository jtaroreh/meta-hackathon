from __future__ import annotations

import os
import sys
from pathlib import Path


def _default_src() -> Path:
    return Path(__file__).resolve().parents[3] / "screens" / "05" / "src"


def _resolve_src() -> Path:
    override = os.environ.get("PURSUIT05_SCREEN_SRC")
    if override:
        return Path(override).expanduser().resolve()
    return _default_src()


SCREEN_SRC = _resolve_src()

if not (SCREEN_SRC / "run05.py").is_file():
    raise ImportError(f"screen code not found at {SCREEN_SRC}")

sys.path.insert(0, str(SCREEN_SRC))

try:
    import run05 as _run05

    build_cell = _run05.build_cell
    cell_edges = _run05.cell_edges
    drop_one = _run05.drop_one
    precompute = _run05.precompute
    eval_policy = _run05.eval_policy
    abort_idx = _run05.abort_idx
    run_F = _run05.run_F
    run_G = _run05.run_G
    run_A = _run05.run_A
    run_arm = _run05.run_arm
    seed_rng = _run05.seed_rng
    all_threshold_policies = _run05.all_threshold_policies
    SIZES = _run05.SIZES
    T_OF = _run05.T_OF
    P_ERRS = _run05.P_ERRS
    SEEDS = _run05.SEEDS
    ABORT_VALS = _run05.ABORT_VALS
    FINAL_VALS = _run05.FINAL_VALS
    LAMBDA = _run05.LAMBDA
    A_ITERS = _run05.A_ITERS
    R_SAMPLES = _run05.R_SAMPLES
    INF_REL = _run05.INF_REL
    INF_ABS = _run05.INF_ABS
    WIN_RED = _run05.WIN_RED
    MEANF_FLOOR = _run05.MEANF_FLOOR
except Exception as exc:
    if str(SCREEN_SRC) in sys.path:
        sys.path.remove(str(SCREEN_SRC))
    raise ImportError(f"cannot import screen code from {SCREEN_SRC}: {exc}") from exc

__all__ = [
    "ABORT_VALS",
    "A_ITERS",
    "FINAL_VALS",
    "INF_ABS",
    "INF_REL",
    "LAMBDA",
    "MEANF_FLOOR",
    "P_ERRS",
    "R_SAMPLES",
    "SCREEN_SRC",
    "SEEDS",
    "SIZES",
    "T_OF",
    "WIN_RED",
    "abort_idx",
    "all_threshold_policies",
    "build_cell",
    "cell_edges",
    "drop_one",
    "eval_policy",
    "precompute",
    "run_A",
    "run_F",
    "run_G",
    "run_arm",
    "seed_rng",
]
