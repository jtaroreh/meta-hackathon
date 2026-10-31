"""Command line: reproduce the screen record, then score baselines."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pursuit05.cells import Cell

RECORD_REL = Path(
    "overnight-data/cfc1d43d7de946e6988f0158b5508e28"
    "/attempts/05-3ca8e6aa423c4275a9919edb9ccb7344"
    "/work/results.json"
)
RECORD_FALLBACK_ROOT = Path("/Users/joeltaroreh/projects/challenges/meta-hackathon")

ARMS = ("F", "G", "A", "S")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_record_path() -> Path:
    cands = [repo_root() / RECORD_REL, RECORD_FALLBACK_ROOT / RECORD_REL]
    for cand in cands:
        if cand.is_file():
            return cand
    raise FileNotFoundError(
        "reproduction record not found; tried " + ", ".join(str(c) for c in cands)
    )


def record_key(n: int, p: float, seed: int, arm: str) -> str:
    return f"{n}/p{p}/{seed}/{arm}"


def run_screen_arms(screen, pre: dict, cell: Cell) -> dict:
    f = screen.run_F(pre, cell.p)
    g = screen.run_G(pre, cell.p, f["inf"], None)
    a = screen.run_arm(
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
    return {"F": f, "G": g, "A": a}


def cmd_reproduce(args) -> int:
    try:
        from pursuit05 import screen
        from pursuit05.cells import CellRegistry

        reg = CellRegistry()
        if args.cell:
            targets = [reg.find(args.cell)]
        else:
            targets = reg.all_cells()
        record = json.loads(resolve_record_path().read_text())["cells"]
    except (ImportError, FileNotFoundError, ValueError) as exc:
        print(f"pursuit05: {exc}", file=sys.stderr)
        return 1
    ok = 0
    max_dw = 0.0
    max_dinf = 0.0
    for cell in targets:
        pre = reg.pre(cell)
        outs = run_screen_arms(screen, pre, cell)
        cell_ok = True
        for arm, out in outs.items():
            rec = record.get(record_key(cell.n, cell.p, cell.seed, arm))
            if rec is None:
                print(
                    f"pursuit05: record lacks "
                    f"{record_key(cell.n, cell.p, cell.seed, arm)}",
                    file=sys.stderr,
                )
                return 1
            dw = abs(out["W"] - rec["mean"])
            dinf = abs(out["inf"] - rec["inf"]["mean"])
            max_dw = max(max_dw, dw)
            max_dinf = max(max_dinf, dinf)
            if dw > 1e-9 or dinf > 1e-9:
                cell_ok = False
            if args.cell:
                print(
                    f"{cell.cell_id} {arm} W={out['W']:.12f} "
                    f"record={rec['mean']:.12f} dW={dw:.3e} "
                    f"inf={out['inf']:.12e} dinf={dinf:.3e}"
                )
        if cell_ok:
            ok += 1
        elif not args.cell:
            print(f"{cell.cell_id} MISMATCH dW={dw:.3e} dinf={dinf:.3e}")
    print(
        f"reproduced {ok}/{len(targets)} cells, max |dW| = {max_dw:.3e}, "
        f"max |dinf| = {max_dinf:.3e}"
    )
    return 0 if ok == len(targets) else 1


def _parse_seeds(raw: str | None, all_seeds: tuple) -> tuple:
    if raw is None:
        return tuple(all_seeds)
    try:
        seeds = tuple(int(s) for s in raw.split(",") if s.strip())
    except ValueError:
        raise ValueError(f"bad --seeds {raw!r}") from None
    if not seeds or any(s not in all_seeds for s in seeds):
        raise ValueError(f"bad --seeds {raw!r}")
    return seeds


def _pooled_section(screen, table, rows, seeds, label) -> list[str]:
    head = "# pooled joint-win vs F per regime"
    lines = [f"{head} ({label} seeds {','.join(str(s) for s in seeds)})"]
    by_rate: dict[float, dict[str, list]] = {}
    for cell, vals in rows:
        if cell.seed not in seeds:
            continue
        slot = by_rate.setdefault(cell.p, {})
        for arm in ARMS:
            w, inf = vals[arm]
            lists = slot.setdefault(arm, ([], []))
            lists[0].append(w)
            lists[1].append(inf)
    wins = 0
    for p in screen.P_ERRS:
        slot = by_rate.get(p, {})
        pools_w = {a: table.pooled(slot[a][0]) for a in ARMS if a in slot}
        pools_i = {a: table.pooled(slot[a][1]) for a in ARMS if a in slot}
        lines.append(table.render_regime(p, ARMS, pools_w, pools_i))
        if table.joint_win(pools_w, pools_i, "S"):
            wins += 1
    lines.append(f"S joint-wins vs F at {wins}/3 regimes on {label} seeds")
    return lines


def cmd_baselines(args) -> int:
    try:
        from pursuit05 import exact, screen, table
        from pursuit05.cells import TEST_SEEDS, TRAIN_SEEDS, CellRegistry, split_label

        seeds = _parse_seeds(args.seeds, screen.SEEDS)
        reg = CellRegistry()
        targets = reg.select(seeds=seeds)
    except (ImportError, ValueError) as exc:
        print(f"pursuit05: {exc}", file=sys.stderr)
        return 1
    label = split_label(seeds)
    print(f"# baselines ({label} seeds {','.join(str(s) for s in seeds)})")
    rows = []
    for cell in targets:
        pre = reg.pre(cell)
        outs = run_screen_arms(screen, pre, cell)
        s = exact.best_static(pre, cell.p, outs["F"]["inf"])
        vals = {a: (outs[a]["W"], outs[a]["inf"]) for a in ("F", "G", "A")}
        vals["S"] = (s.result.W, s.result.inf)
        rows.append((cell, vals))
    print(table.render_arm_table([(cell.cell_id, vals) for cell, vals in rows], ARMS))
    if set(seeds) == set(screen.SEEDS):
        for part, part_label in ((TRAIN_SEEDS, "train"), (TEST_SEEDS, "test")):
            for line in _pooled_section(screen, table, rows, part, part_label):
                print(line)
    else:
        for line in _pooled_section(screen, table, rows, seeds, label):
            print(line)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pursuit05")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("reproduce", help="reproduce the screen record")
    rp.add_argument("--cell", default=None, help="single cell id like 12/0.005/1")
    bp = sub.add_parser("baselines", help="score F, G, A, and S")
    bp.add_argument("--seeds", default=None, help="comma seeds like 4,5")
    args = ap.parse_args(argv)
    if args.cmd == "reproduce":
        return cmd_reproduce(args)
    return cmd_baselines(args)
