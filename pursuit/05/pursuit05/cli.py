from __future__ import annotations

import argparse
import json
import os
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
    override = os.environ.get("PURSUIT05_RECORD")
    if override:
        if Path(override).is_file():
            return Path(override)
        raise FileNotFoundError(f"reproduction record not found: {override}")
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


def _record_entries(record_path: Path, targets) -> dict:
    try:
        cells = json.loads(record_path.read_text())["cells"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"bad record {record_path}: {exc}") from None
    entries = {}
    for cell in targets:
        for arm in ("F", "G", "A"):
            key = record_key(cell.n, cell.p, cell.seed, arm)
            try:
                rec = cells[key]
                entries[key] = (rec["mean"], rec["inf"]["mean"])
            except (KeyError, TypeError) as exc:
                raise ValueError(f"bad record {record_path}: {key}: {exc}") from None
    return entries


def cmd_reproduce(args) -> int:
    try:
        from pursuit05 import screen
        from pursuit05.cells import CellRegistry

        reg = CellRegistry()
        if args.cell:
            targets = [reg.find(args.cell)]
        else:
            targets = reg.all_cells()
        entries = _record_entries(resolve_record_path(), targets)
    except (ImportError, OSError, ValueError) as exc:
        print(f"pursuit05: {exc}", file=sys.stderr)
        return 1
    ok = 0
    max_dw = 0.0
    max_dinf = 0.0
    for cell in targets:
        pre = reg.pre(cell)
        outs = run_screen_arms(screen, pre, cell)
        cell_ok = True
        worst = None
        for arm, out in outs.items():
            mean, infmean = entries[record_key(cell.n, cell.p, cell.seed, arm)]
            dw = abs(out["W"] - mean)
            dinf = abs(out["inf"] - infmean)
            max_dw = max(max_dw, dw)
            max_dinf = max(max_dinf, dinf)
            if dw > 1e-9 or dinf > 1e-9:
                cell_ok = False
                if worst is None or dw + dinf > worst[1] + worst[2]:
                    worst = (arm, dw, dinf)
            if args.cell:
                print(
                    f"{cell.cell_id} {arm} W={out['W']:.12f} "
                    f"record={mean:.12f} dW={dw:.3e} "
                    f"inf={out['inf']:.12e} dinf={dinf:.3e}"
                )
        if cell_ok:
            ok += 1
        elif not args.cell:
            arm, dw, dinf = worst
            print(
                f"{cell.cell_id} MISMATCH {arm} dW={dw:.3e} dinf={dinf:.3e}",
                file=sys.stderr,
            )
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
        if not slot:
            lines.append(f"p={p} n=0")
            continue
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
    if set(seeds) == set(screen.SEEDS):
        label = "all"
    else:
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


MC_EPISODES = 20000
MC_SIGMAS = 4.0


def _scripted_actions(obs, ath, fth, t):
    import numpy as np

    n = obs.shape[0]
    k = obs[:, 0].astype(np.int64)
    act = np.zeros(n, dtype=np.int64)
    mid = np.nonzero(k < t - 1)[0]
    if len(mid):
        act[mid] = (
            obs[mid][:, 1:4][np.arange(len(mid)), k[mid]]
            > np.asarray(ath)[k[mid]]
        ).astype(np.int64)
    fin = np.nonzero(k == t - 1)[0]
    if len(fin):
        act[fin] = (obs[fin][:, t - 1] <= fth).astype(np.int64)
    return act


def _mc_w(spent_list, acc_list, tail, vf):
    import numpy as np

    s = np.asarray(spent_list, dtype=float)
    a = np.asarray(acc_list, dtype=float)
    n = len(s)
    c = 1.0 - tail
    e = c * s.mean() + tail * vf
    pacc = c * a.mean()
    w = e / pacc - vf
    ds = c / pacc
    da = -c * e / pacc**2
    vs = s.var()
    va = a.var()
    cv = ((s - s.mean()) * (a - a.mean())).mean()
    se = (max(0.0, ds * ds * vs + da * da * va + 2.0 * ds * da * cv) / n) ** 0.5
    return w, se


def _tail_mass(l1: int, p: float) -> float:
    big_l = float(l1)
    p0 = (1.0 - p) ** big_l
    p1 = big_l * p * (1.0 - p) ** (big_l - 1.0) if l1 else 0.0
    p2 = (
        (big_l * (big_l - 1.0) / 2.0) * p**2 * (1.0 - p) ** (big_l - 2.0)
        if l1 >= 2
        else 0.0
    )
    return max(0.0, 1.0 - p0 - p1 - p2)


def cmd_env_smoke(args) -> int:
    import functools
    import time

    try:
        import pufferlib.vector

        from pursuit05.cells import CellRegistry
        from pursuit05.env import CultivationAbort

        if args.agents < 1:
            raise ValueError(f"bad --agents {args.agents!r}")
        if args.steps < 1:
            raise ValueError(f"bad --steps {args.steps!r}")
        if args.workers < 0:
            raise ValueError(f"bad --workers {args.workers!r}")
        if args.workers and args.agents % args.workers:
            raise ValueError(
                f"agents {args.agents} not divisible by workers {args.workers}"
            )
        from pursuit05 import screen

        reg = CellRegistry()
        cell = reg.find(args.cell)
        pre = reg.pre(cell)
        f = screen.run_F(pre, cell.p)
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
        ath, fth = a["policy"][:-1], a["policy"][-1]
        exact_w = screen.eval_policy(pre, ath, fth, cell.p)["W"]
        per = args.agents // args.workers if args.workers else args.agents
        creator = functools.partial(
            CultivationAbort,
            pre=pre,
            p=cell.p,
            stage_id=cell.stage_idx,
            rate_id=cell.rate_idx,
            num_agents=per,
        )
        if args.workers:
            vec = pufferlib.vector.make(
                creator,
                backend=pufferlib.vector.Serial
                if args.workers == 1
                else pufferlib.vector.Multiprocessing,
                num_envs=args.workers,
                num_workers=args.workers,
            )
        else:
            vec = pufferlib.vector.make(
                creator, backend=pufferlib.vector.Serial, num_envs=1
            )
    except (ImportError, ValueError) as exc:
        print(f"pursuit05: {exc}", file=sys.stderr)
        return 1
    try:
        t = pre["T"]
        obs, _ = vec.reset(seed=args.seed)
        for i in range(min(50, obs.shape[0])):
            print(f"obs[{i}] = {' '.join(f'{v:.6g}' for v in obs[i])}")
        t0 = time.perf_counter()
        for _ in range(args.steps):
            obs, _, _, _, _ = vec.step(_scripted_actions(obs, ath, fth, t))
        wall = time.perf_counter() - t0
        rate = args.agents * args.steps / wall
        print(f"agent-steps/s = {rate:.0f}")
        obs, _ = vec.reset(seed=args.seed + 1)
        spent_list: list = []
        acc_list: list = []
        guard = 0
        while len(spent_list) < MC_EPISODES:
            obs, _, _, _, infos = vec.step(
                _scripted_actions(obs, ath, fth, t)
            )
            for info in infos:
                if "spent" in info:
                    spent_list.append(info["spent"])
                    acc_list.append(1.0 if info["accepted"] else 0.0)
            guard += 1
            if guard * args.agents > 10_000_000:
                raise RuntimeError("mc rollout exceeded step guard")
        mc_w, se = _mc_w(spent_list, acc_list, _tail_mass(pre["L1"], cell.p),
                         pre["Vf"])
        ok = abs(mc_w - exact_w) <= MC_SIGMAS * se if se else abs(
            mc_w - exact_w
        ) <= 1e-9
        print(
            f"scripted A thresholds via env rollouts: W = {mc_w:.10g} "
            f"+- {se:.3g} (exact {exact_w:.10g}), "
            f"{'within MC error' if ok else 'MISMATCH'}"
        )
        return 0 if ok else 1
    finally:
        vec.close()


def cmd_optimum(args) -> int:
    try:
        from pursuit05 import dp, exact, screen, table
        from pursuit05.cells import TEST_SEEDS, CellRegistry, split_label

        seeds = _parse_seeds(args.seeds, screen.SEEDS)
        reg = CellRegistry()
        targets = reg.select(seeds=seeds)
    except (ImportError, ValueError) as exc:
        print(f"pursuit05: {exc}", file=sys.stderr)
        return 1
    if set(seeds) == set(screen.SEEDS):
        label = "all"
    else:
        label = split_label(seeds)
    print(f"# optimum ({label} seeds {','.join(str(s) for s in seeds)})")
    rows = []
    for cell in targets:
        pre = reg.pre(cell)
        f = screen.run_F(pre, cell.p)
        bound = f["inf"] * (1.0 + screen.INF_REL) + screen.INF_ABS
        s = exact.best_static(pre, cell.p, f["inf"])
        h = dp.best_history(pre, cell.p, f["inf"])
        rows.append((cell, s, h, bound, _tail_mass(pre["L1"], cell.p)))
    body = table.render_arm_table(
        [
            (cell.cell_id, {"S": (s.result.W, s.result.inf),
                            "H": (h.result.W, h.result.inf)})
            for cell, s, h, _, _ in rows
        ],
        ("S", "H"),
    )
    lines = body.splitlines()
    print(lines[0] + " " + "tail".rjust(16))
    for line, (_, _, h, _, tail) in zip(lines[1:], rows):
        mark = " FALLBACK" if h.fallback else ""
        print(f"{line} {tail:16.10g}{mark}")
    nfb = sum(1 for _, _, h, _, _ in rows if h.fallback)
    if nfb:
        print(f"H fallback in {nfb}/{len(rows)} cells")
    if set(TEST_SEEDS) <= set(seeds):
        wins = 0
        for n in screen.SIZES:
            for p in screen.P_ERRS:
                if p > 0.002:
                    continue
                sub = [(s, h, b) for c, s, h, b, _ in rows
                       if c.n == n and c.p == p and c.seed in TEST_SEEDS]
                mw_h = sum(h.result.W for _, h, _ in sub) / len(sub)
                mw_s = sum(s.result.W for s, _, _ in sub) / len(sub)
                mi_h = sum(h.result.inf for _, h, _ in sub) / len(sub)
                mi_s = sum(s.result.inf for s, _, _ in sub) / len(sub)
                mb = sum(b for _, _, b in sub) / len(sub)
                if mw_h <= 0.9 * mw_s and mi_h <= mb and mi_s <= mb:
                    wins += 1
        print(
            "on test seeds, H's W is at least 10% below S's W, both "
            f"within the F-anchored bound, in {wins}/6 (stage, rate) "
            "cells at p <= 0.002"
        )
    else:
        print("D1 census skipped: select test seeds 4,5")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pursuit05")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("reproduce", help="reproduce the screen record")
    rp.add_argument("--cell", default=None, help="single cell id like 12/0.005/1")
    bp = sub.add_parser("baselines", help="score F, G, A, and S")
    bp.add_argument("--seeds", default=None, help="comma seeds like 4,5")
    ep = sub.add_parser("env-smoke", help="smoke the abort env")
    ep.add_argument("--cell", default="12/0.002/1", help="cell id")
    ep.add_argument("--agents", type=int, default=4096, help="agent count")
    ep.add_argument("--steps", type=int, default=200, help="timed steps")
    ep.add_argument("--seed", type=int, default=0, help="vec seed")
    ep.add_argument("--workers", type=int, default=0, help="mp workers")
    op = sub.add_parser("optimum", help="score exact S and H optima")
    op.add_argument("--seeds", default=None, help="comma seeds like 4,5")
    args = ap.parse_args(argv)
    if args.cmd == "reproduce":
        return cmd_reproduce(args)
    if args.cmd == "env-smoke":
        return cmd_env_smoke(args)
    if args.cmd == "optimum":
        return cmd_optimum(args)
    return cmd_baselines(args)
