from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pursuit05.cells import Cell

ARMS_FULL = ("F", "G", "A")


def run_screen_arms(screen, pre: dict, cell: Cell, arms=ARMS_FULL) -> dict:
    outs = {}
    if "F" in arms:
        outs["F"] = screen.run_F(pre, cell.p)
    if "G" in arms:
        f = outs.get("F") or screen.run_F(pre, cell.p)
        outs["G"] = screen.run_G(pre, cell.p, f["inf"], None)
    if "A" in arms:
        f = outs.get("F") or screen.run_F(pre, cell.p)
        outs["A"] = screen.run_arm(
            pre,
            cell.p,
            "A",
            f["inf"],
            screen.A_ITERS,
            screen.R_SAMPLES,
            None,
            cell.stage_idx,
            cell.rate_idx,
            cell.seed,
        )
    return outs
