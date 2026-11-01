from __future__ import annotations

import configparser
import json
import math
import random
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pufferlib
import pufferlib.vector
import torch

from pursuit05 import bc as bc_mod
from pursuit05 import dp, exact, screen
from pursuit05.cells import TEST_SEEDS, TRAIN_SEEDS, Cell, CellRegistry
from pursuit05.cli import run_screen_arms
from pursuit05.env import CultivationAbort
from pursuit05.policy import (
    CultivationPolicy,
    decision_table,
    fit_final_threshold,
    table_decider,
)

NOMINAL_LAMS = (1000, 5000, 10000)
LAM_NORM = 10000.0
MONITOR_EVERY = 1_000_000

PURSUIT05_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = PURSUIT05_DIR / "runs"
CONFIG_PATH = PURSUIT05_DIR / "config" / "cultivation.ini"


def _coerce(value: str):
    text = value.strip()
    low = text.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def load_train_config(overrides: dict | None = None) -> dict:
    """PufferLib default.ini [train] with cultivation.ini overlaid."""
    default = (
        Path(pufferlib.__file__).resolve().parent / "config" / "default.ini"
    )
    base = configparser.ConfigParser()
    base.read(default)
    cfg = {k: _coerce(v) for k, v in base["train"].items()}
    local = configparser.ConfigParser()
    local.read(CONFIG_PATH)
    if "train" in local:
        cfg.update({k: _coerce(v) for k, v in local["train"].items()})
    cfg["use_rnn"] = False
    cfg["env"] = "cultivation-abort"
    if overrides:
        cfg.update(overrides)
    return cfg


def load_run_settings() -> dict:
    """Vec and env settings from cultivation.ini."""
    local = configparser.ConfigParser()
    local.read(CONFIG_PATH)
    out = {"backend": "Serial", "agents_per_env": 1024, "beta": 1.0, "lam": 5000}
    if "vec" in local:
        out.update({k: _coerce(v) for k, v in local["vec"].items()})
    if "env" in local:
        out.update({k: _coerce(v) for k, v in local["env"].items()})
    return out


def regime_id(stages: list[int], rates: list[float]) -> str:
    if len(stages) == 1 and len(rates) == 1:
        return f"{stages[0]}-{rates[0]}"
    return "transfer-" + "-".join(str(n) for n in stages)


def evaluate_policy(
    policy: torch.nn.Module, cells: list[Cell], reg: CellRegistry
) -> dict:
    """Exact scores plus decision-table key counts per cell."""
    per = {}
    for cell in cells:
        pre = reg.pre(cell)
        table = decision_table(
            policy, pre, stage_id=cell.stage_idx, rate_id=cell.rate_idx
        )
        fth = fit_final_threshold(table, pre, cell.p)
        out = exact.eval_exact(table_decider(table, fth=fth), pre, cell.p)
        per[cell.cell_id] = {
            "W": out["W"],
            "inf": out["inf"],
            "pacc": out["pacc"],
            "fth": fth,
            "keys": len(table),
        }
    ws = [v["W"] for v in per.values()]
    infs = [v["inf"] for v in per.values()]
    return {
        "cells": per,
        "mean_W": float(sum(ws) / len(ws)),
        "mean_inf": float(sum(infs) / len(infs)),
    }


def baselines_for_cells(cells: list[Cell], reg: CellRegistry) -> dict:
    per = {}
    for cell in cells:
        pre = reg.pre(cell)
        outs = run_screen_arms(screen, pre, cell)
        s = exact.best_static(pre, cell.p, outs["F"]["inf"])
        h = dp.best_history(pre, cell.p, outs["F"]["inf"])
        bound = outs["F"]["inf"] * (1.0 + screen.INF_REL) + screen.INF_ABS
        per[cell.cell_id] = {
            "F": {"W": outs["F"]["W"], "inf": outs["F"]["inf"]},
            "A": {"W": outs["A"]["W"], "inf": outs["A"]["inf"]},
            "S": {"W": s.result.W, "inf": s.result.inf},
            "H": {"W": h.result.W, "inf": h.result.inf},
            "bound": bound,
        }
    return per


def _mean_bound(cells: list[Cell], reg: CellRegistry) -> float:
    tot = 0.0
    for cell in cells:
        pre = reg.pre(cell)
        f = screen.run_F(pre, cell.p)
        tot += f["inf"] * (1.0 + screen.INF_REL) + screen.INF_ABS
    return tot / len(cells)


def _pick_kept(
    cands: list[tuple[str, float, float]], bound: float
) -> str:
    feas = [c for c in cands if c[2] <= bound]
    pool = feas if feas else cands
    return min(pool, key=lambda c: (c[1], c[2]))[0]


def make_vec(
    cells: list[Cell],
    reg: CellRegistry,
    *,
    lam_env: float,
    beta: float,
    agents_per_env: int,
):
    import functools

    creators = []
    for cell in cells:
        creators.append(
            functools.partial(
                CultivationAbort,
                pre=reg.pre(cell),
                p=cell.p,
                stage_id=cell.stage_idx,
                rate_id=cell.rate_idx,
                num_agents=agents_per_env,
                beta=beta,
                lam=lam_env,
            )
        )
    return pufferlib.vector.make(
        creators,
        env_args=[[] for _ in creators],
        env_kwargs=[{} for _ in creators],
        backend=pufferlib.vector.Serial,
        num_envs=len(creators),
    )


def run_ppo(
    policy: CultivationPolicy,
    vec,
    config: dict,
    total_timesteps: int,
    monitor=None,
    log=print,
) -> int:
    from pufferlib.pufferl import PuffeRL

    config = dict(config)
    config["total_timesteps"] = total_timesteps
    batch = config["batch_size"]
    horizon = config["bptt_horizon"]
    if batch < config["minibatch_size"]:
        mb = max(horizon, (batch // horizon) * horizon)
        log(f"minibatch_size {config['minibatch_size']} -> {mb} for batch {batch}")
        config["minibatch_size"] = mb
    pufferl = PuffeRL(config, vec, policy)
    try:
        mark = MONITOR_EVERY
        while pufferl.global_step < total_timesteps:
            pufferl.evaluate()
            pufferl.train()
            if monitor is not None and pufferl.global_step >= mark:
                monitor(pufferl.global_step)
                mark += MONITOR_EVERY
    finally:
        pufferl.utilization.stop()
    vec.close()
    pufferl.print_dashboard()
    steps = pufferl.global_step
    pufferl.save_checkpoint()
    return steps


def train_point(
    train_cells: list[Cell],
    monitor_cells: list[Cell],
    *,
    lam: float,
    total_timesteps: int,
    seed: int,
    agents_per_env: int,
    beta: float,
    bc_seed: int,
    scratch_dir: Path,
    log=print,
) -> dict:
    """BC from H then PPO fine-tuning on pooled train cells.

    lam is nominal; the env gets lam / LAM_NORM because PuffeRL
    clamps step rewards to [-1, 1] and raw lam values would collapse
    to one operating point. Reported policy keeps the better of the
    cloned start and the fine-tuned checkpoint on exact train-seed W,
    preferring bound-feasible checkpoints.
    """
    t0 = time.perf_counter()
    torch.set_num_threads(2)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    reg = CellRegistry()
    lam_env = lam / LAM_NORM
    log(f"train_point lam={lam} (env {lam_env}) seed={seed} steps={total_timesteps}")
    h_inputs = []
    for cell in train_cells:
        pre = reg.pre(cell)
        f = screen.run_F(pre, cell.p)
        h = dp.best_history(pre, cell.p, f["inf"])
        h_inputs.append(
            (pre, h.table, h.fth, cell.p, cell.stage_idx, cell.rate_idx)
        )
    bc_policy, bc_stats = bc_mod.clone_from_tables(h_inputs, seed=bc_seed)
    log(
        f"bc agreement={bc_stats['agreement']:.4f} "
        f"samples={bc_stats['samples']} iters={bc_stats['iters']}"
    )
    bound = _mean_bound(train_cells, reg)
    bc_train = evaluate_policy(bc_policy, train_cells, reg)
    log(
        f"bc exact train W={bc_train['mean_W']:.10g} "
        f"inf={bc_train['mean_inf']:.10g} bound={bound:.10g}"
    )
    vec = make_vec(
        train_cells,
        reg,
        lam_env=lam_env,
        beta=beta,
        agents_per_env=agents_per_env,
    )
    config = load_train_config(
        {"seed": seed, "data_dir": str(scratch_dir)}
    )
    total_agents = vec.num_agents
    config["batch_size"] = total_agents * config["bptt_horizon"]

    def monitor(steps: int) -> None:
        got = evaluate_policy(ft_policy, monitor_cells, reg)
        log(
            f"[{steps}] exact test W={got['mean_W']:.10g} "
            f"inf={got['mean_inf']:.10g}"
        )

    ft_policy = CultivationPolicy()
    ft_policy.load_state_dict(bc_policy.state_dict())
    steps = run_ppo(ft_policy, vec, config, total_timesteps, monitor, log)
    ft_train = evaluate_policy(ft_policy, train_cells, reg)
    log(
        f"finetuned exact train W={ft_train['mean_W']:.10g} "
        f"inf={ft_train['mean_inf']:.10g}"
    )
    kept_from = _pick_kept(
        [
            ("bc", bc_train["mean_W"], bc_train["mean_inf"]),
            ("finetune", ft_train["mean_W"], ft_train["mean_inf"]),
        ],
        bound,
    )
    kept = bc_policy if kept_from == "bc" else ft_policy
    log(f"kept {kept_from} on exact train-seed W")
    return {
        "lam": lam,
        "lam_env": lam_env,
        "kept_from": kept_from,
        "bc_train_W": bc_train["mean_W"],
        "bc_train_inf": bc_train["mean_inf"],
        "ft_train_W": ft_train["mean_W"],
        "ft_train_inf": ft_train["mean_inf"],
        "train_bound": bound,
        "bc_agreement": bc_stats["agreement"],
        "bc_samples": bc_stats["samples"],
        "steps": steps,
        "wall_s": time.perf_counter() - t0,
        "state_dict": kept.state_dict(),
    }


def train_scratch(
    train_cells: list[Cell],
    monitor_cells: list[Cell],
    *,
    lam: float,
    total_timesteps: int,
    seed: int,
    agents_per_env: int,
    beta: float,
    scratch_dir: Path,
    log=print,
) -> dict:
    t0 = time.perf_counter()
    torch.set_num_threads(2)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    reg = CellRegistry()
    lam_env = lam / LAM_NORM
    log(f"train_scratch lam={lam} (env {lam_env}) seed={seed}")
    vec = make_vec(
        train_cells,
        reg,
        lam_env=lam_env,
        beta=beta,
        agents_per_env=agents_per_env,
    )
    config = load_train_config(
        {"seed": seed, "data_dir": str(scratch_dir)}
    )
    config["batch_size"] = vec.num_agents * config["bptt_horizon"]
    policy = CultivationPolicy()

    def monitor(steps: int) -> None:
        got = evaluate_policy(policy, monitor_cells, reg)
        log(
            f"[scratch {steps}] exact test W={got['mean_W']:.10g} "
            f"inf={got['mean_inf']:.10g}"
        )

    steps = run_ppo(policy, vec, config, total_timesteps, monitor, log)
    return {
        "steps": steps,
        "wall_s": time.perf_counter() - t0,
        "state_dict": policy.state_dict(),
    }


def train_cell(
    cell_id: str,
    monitor_ids: list[str],
    *,
    lam: float = 5000,
    total_timesteps: int = 20000,
    scratch_timesteps: int | None = None,
    seed: int = 0,
    agents_per_env: int = 256,
    beta: float = 1.0,
    do_scratch: bool = False,
    run_dir: Path | None = None,
    log=print,
) -> dict:
    """Train on one cell; small wrapper over train_point for tests."""
    reg = CellRegistry()
    train_cells = [reg.find(cell_id)]
    monitor_cells = [reg.find(cid) for cid in monitor_ids]
    scratch_dir = Path(run_dir) / "scratch-tmp" if run_dir else Path("scratch-tmp")
    scratch_dir.mkdir(parents=True, exist_ok=True)
    point = train_point(
        train_cells,
        monitor_cells,
        lam=lam,
        total_timesteps=total_timesteps,
        seed=seed,
        agents_per_env=agents_per_env,
        beta=beta,
        bc_seed=seed,
        scratch_dir=scratch_dir,
        log=log,
    )
    out = {"point": point}
    if do_scratch:
        out["scratch"] = train_scratch(
            train_cells,
            monitor_cells,
            lam=lam,
            total_timesteps=scratch_timesteps or total_timesteps,
            seed=seed + 1000,
            agents_per_env=agents_per_env,
            beta=beta,
            scratch_dir=scratch_dir,
            log=log,
        )
    return out


def _point_worker(spec: dict) -> dict:
    log_lines: list[str] = []

    def log(msg) -> None:
        log_lines.append(str(msg))

    reg = CellRegistry()
    train_cells = [reg.find(cid) for cid in spec["train"]]
    monitor_cells = [reg.find(cid) for cid in spec["monitor"]]
    scratch_dir = Path(spec["scratch_dir"])
    scratch_dir.mkdir(parents=True, exist_ok=True)
    if spec["kind"] == "scratch":
        res = train_scratch(
            train_cells,
            monitor_cells,
            lam=spec["lam"],
            total_timesteps=spec["total_timesteps"],
            seed=spec["seed"],
            agents_per_env=spec["agents_per_env"],
            beta=spec["beta"],
            scratch_dir=scratch_dir,
            log=log,
        )
    else:
        res = train_point(
            train_cells,
            monitor_cells,
            lam=spec["lam"],
            total_timesteps=spec["total_timesteps"],
            seed=spec["seed"],
            agents_per_env=spec["agents_per_env"],
            beta=spec["beta"],
            bc_seed=spec["seed"],
            scratch_dir=scratch_dir,
            log=log,
        )
    res["log_lines"] = log_lines
    return res


def _policy_from_state(state) -> CultivationPolicy:
    policy = CultivationPolicy()
    policy.load_state_dict(state)
    policy.eval()
    return policy


def _versions() -> dict:
    import pufferlib as _pl

    return {
        "pufferlib": str(getattr(_pl, "__version__", "unknown")),
        "torch": torch.__version__,
        "numpy": np.__version__,
    }


def assemble_receipt(
    run_dir: Path,
    run_id: str,
    kind: str,
    train_cells: list[Cell],
    eval_cells: list[Cell],
    points: list[dict],
    scratch: dict | None,
    total_timesteps: int,
    seed: int,
    agents_per_env: int,
    beta: float,
) -> dict:
    """Score kept policies on test cells and write receipt.json.

    The receipt holds test-seed scores only. Train-seed scores stay
    in train.log, which records the keep-better selection evidence.
    """
    reg = CellRegistry()
    run_dir.mkdir(parents=True, exist_ok=True)
    outs = []
    for pt in points:
        policy = _policy_from_state(pt["state_dict"])
        torch.save(policy.state_dict(), run_dir / f"policy-lam{pt['lam']:g}.pt")
        ev = evaluate_policy(policy, eval_cells, reg)
        outs.append((pt, ev))
    bound = _mean_bound(train_cells, reg)
    cands = [
        (
            str(i),
            pt["ft_train_W"] if pt["kept_from"] == "finetune" else pt["bc_train_W"],
            pt["ft_train_inf"] if pt["kept_from"] == "finetune" else pt["bc_train_inf"],
        )
        for i, pt in enumerate(points)
    ]
    sel = int(_pick_kept(cands, bound))
    sel_pt = outs[sel][0]
    sel_policy = _policy_from_state(sel_pt["state_dict"])
    torch.save(sel_policy.state_dict(), run_dir / "policy.pt")
    tables = {}
    for cell in eval_cells:
        pre = reg.pre(cell)
        table = decision_table(
            sel_policy, pre, stage_id=cell.stage_idx, rate_id=cell.rate_idx
        )
        fth = fit_final_threshold(table, pre, cell.p)
        tables[cell.cell_id] = {
            "fth": fth,
            "prefixes": [
                [k, list(vals), bool(abort)]
                for (k, vals), abort in sorted(
                    table.items(), key=lambda kv: (kv[0][0], kv[0][1])
                )
            ],
        }
    scratch_out = None
    if scratch is not None:
        policy = _policy_from_state(scratch["state_dict"])
        torch.save(policy.state_dict(), run_dir / "policy-scratch.pt")
        ev = evaluate_policy(policy, eval_cells, reg)
        scratch_out = {
            "mean_W": ev["mean_W"],
            "mean_inf": ev["mean_inf"],
            "steps": scratch["steps"],
            "cells": ev["cells"],
        }
    receipt = {
        "id": run_id,
        "kind": kind,
        "trained_on": {
            "stages": sorted({c.n for c in train_cells}),
            "rates": sorted({c.p for c in train_cells}),
            "seeds": sorted({c.seed for c in train_cells}),
        },
        "seeds_eval": sorted({c.seed for c in eval_cells}),
        "config": {
            "lams": [pt["lam"] for pt in points],
            "lam_norm": LAM_NORM,
            "total_timesteps": total_timesteps,
            "seed": seed,
            "agents_per_env": agents_per_env,
            "beta": beta,
        },
        "versions": _versions(),
        "wall_s": sum(pt["wall_s"] for pt in points)
        + (scratch["wall_s"] if scratch else 0.0),
        "points": [
            {
                "lam": pt["lam"],
                "lam_env": pt["lam_env"],
                "kept_from": pt["kept_from"],
                "mean_W": ev["mean_W"],
                "mean_inf": ev["mean_inf"],
                "bc_agreement": pt["bc_agreement"],
                "steps": pt["steps"],
                "cells": ev["cells"],
            }
            for pt, ev in outs
        ],
        "selected_lam": sel_pt["lam"],
        "tables": tables,
        "scratch": scratch_out,
    }
    (run_dir / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def regime_cells(
    reg: CellRegistry, stages: list[int], rates: list[float]
) -> tuple[list[Cell], list[Cell]]:
    train = [
        c
        for c in reg.all_cells()
        if c.n in stages and c.p in rates and c.seed in TRAIN_SEEDS
    ]
    test = [
        c
        for c in reg.all_cells()
        if c.n in stages and c.p in rates and c.seed in TEST_SEEDS
    ]
    return train, test


def sweep_lambda(
    stages: list[int],
    rates: list[float],
    lams: list[float],
    *,
    total_timesteps: int,
    seed: int,
    agents_per_env: int,
    beta: float,
    jobs: int = 2,
    do_scratch: bool = True,
    log=print,
) -> dict:
    """Train one pooled policy per (regime, lam); write receipts."""
    reg = CellRegistry()
    regimes = [
        ([n], [p]) for n in stages for p in rates
    ]
    specs = []
    for ri, (nstages, nrates) in enumerate(regimes):
        train, test = regime_cells(reg, nstages, nrates)
        rid = regime_id(nstages, nrates)
        for li, lam in enumerate(lams):
            specs.append(
                {
                    "regime": rid,
                    "kind": "point",
                    "lam": lam,
                    "train": [c.cell_id for c in train],
                    "monitor": [c.cell_id for c in test],
                    "total_timesteps": total_timesteps,
                    "seed": seed + ri * 100 + li,
                    "agents_per_env": agents_per_env,
                    "beta": beta,
                    "scratch_dir": str(
                        RUNS_DIR / "scratch" / f"{rid}-lam{lam:g}"
                    ),
                }
            )
        if do_scratch:
            specs.append(
                {
                    "regime": rid,
                    "kind": "scratch",
                    "lam": lams[len(lams) // 2],
                    "train": [c.cell_id for c in train],
                    "monitor": [c.cell_id for c in test],
                    "total_timesteps": total_timesteps,
                    "seed": seed + ri * 100 + 50,
                    "agents_per_env": agents_per_env,
                    "beta": beta,
                    "scratch_dir": str(RUNS_DIR / "scratch" / f"{rid}-scratch"),
                }
            )
    results: dict[str, dict[str, list]] = {}
    logs: dict[str, list[str]] = {}

    def collect(spec, res) -> None:
        for line in res.pop("log_lines"):
            tagged = f"[{spec['regime']} {spec['kind']}] {line}"
            log(tagged)
            logs.setdefault(spec["regime"], []).append(tagged)

    if jobs < 2:
        for spec in specs:
            res = _point_worker(spec)
            collect(spec, res)
            results.setdefault(spec["regime"], {}).setdefault(
                spec["kind"], []
            ).append(res)
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            futs = [(spec, pool.submit(_point_worker, spec)) for spec in specs]
            for spec, fut in futs:
                res = fut.result()
                collect(spec, res)
                results.setdefault(spec["regime"], {}).setdefault(
                    spec["kind"], []
                ).append(res)
    receipts = {}
    for nstages, nrates in regimes:
        rid = regime_id(nstages, nrates)
        train, test = regime_cells(reg, nstages, nrates)
        (RUNS_DIR / rid).mkdir(parents=True, exist_ok=True)
        (RUNS_DIR / rid / "train.log").write_text(
            "\n".join(logs.get(rid, [])) + "\n"
        )
        got = results[rid]
        points = sorted(got.get("point", []), key=lambda r: r["lam"])
        scratch = got.get("scratch", [None])[0]
        receipts[rid] = assemble_receipt(
            RUNS_DIR / rid,
            rid,
            "regime",
            train,
            test,
            points,
            scratch,
            total_timesteps,
            seed,
            agents_per_env,
            beta,
        )
        log(f"receipt {rid}: selected lam {receipts[rid]['selected_lam']}")
    return receipts


def write_frontier(receipts: dict, log=print) -> dict:
    """Frontier JSON plus PNG from regime receipts on test seeds."""
    reg = CellRegistry()
    points = []
    arms: dict[str, dict] = {}
    for rid, receipt in sorted(receipts.items()):
        for pt in receipt["points"]:
            points.append(
                {
                    "regime": rid,
                    "lam": pt["lam"],
                    "mean_W": pt["mean_W"],
                    "mean_inf": pt["mean_inf"],
                    "kept_from": pt["kept_from"],
                }
            )
        eval_cells = [
            reg.find(cid) for cid in receipt["tables"]
        ]
        base = baselines_for_cells(eval_cells, reg)
        pooled = {}
        for arm in ("F", "A", "S", "H"):
            ws = [base[cid][arm]["W"] for cid in base]
            infs = [base[cid][arm]["inf"] for cid in base]
            pooled[arm] = {
                "mean_W": sum(ws) / len(ws),
                "mean_inf": sum(infs) / len(infs),
            }
        arms[rid] = pooled
    frontier = {
        "seeds_eval": [4, 5],
        "points": points,
        "arms": arms,
        "note": (
            "P points are kept BC/PPO policies per nominal lam on "
            "held-out cells; lam_env = lam / 10000 in the env."
        ),
    }
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / "frontier.json").write_text(
        json.dumps(frontier, indent=2) + "\n"
    )
    _render_frontier_png(frontier)
    log(f"frontier: {len(points)} P points over {len(arms)} regimes")
    return frontier


def _render_frontier_png(frontier: dict) -> None:
    from PIL import Image, ImageDraw

    w, h = 960, 640
    margin = 70
    img = Image.new("RGB", (w, h), "white")
    dr = ImageDraw.Draw(img)
    xs = [p["mean_inf"] for p in frontier["points"]]
    ys = [p["mean_W"] for p in frontier["points"]]
    for pooled in frontier["arms"].values():
        for arm in ("F", "A", "S", "H"):
            xs.append(pooled[arm]["mean_inf"])
            ys.append(pooled[arm]["mean_W"])
    finite_ys = [y for y in ys if math.isfinite(y)]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(finite_ys), max(finite_ys)
    if x1 == x0:
        x0, x1 = x0 * 0.9, x0 * 1.1 + 1e-12
    if y1 == y0:
        y0, y1 = y0 * 0.9, y0 * 1.1 + 1e-12
    px = lambda x: margin + (x - x0) / (x1 - x0) * (w - 2 * margin)
    py = lambda y: h - margin - (y - y0) / (y1 - y0) * (h - 2 * margin)
    dr.rectangle([margin, margin, w - margin, h - margin], outline="black")
    for i in range(6):
        xv = x0 + (x1 - x0) * i / 5
        yv = y0 + (y1 - y0) * i / 5
        dr.text((px(xv) - 20, h - margin + 6), f"{xv:.2g}", fill="black")
        dr.text((4, py(yv) - 6), f"{yv:.2g}", fill="black")
    dr.text((w // 2 - 60, h - 24), "mean inf (test seeds)", fill="black")
    colors = {"F": "gray", "A": "blue", "S": "green", "H": "black", "P": "red"}
    for pooled in frontier["arms"].values():
        for arm, draw in (
            ("F", lambda x, y: dr.rectangle([x - 4, y - 4, x + 4, y + 4], fill=colors["F"])),
            ("A", lambda x, y: dr.ellipse([x - 4, y - 4, x + 4, y + 4], fill=colors["A"])),
            ("S", lambda x, y: dr.polygon([(x, y - 5), (x + 5, y + 4), (x - 5, y + 4)], fill=colors["S"])),
            ("H", lambda x, y: dr.polygon([(x, y - 5), (x + 5, y), (x, y + 5), (x - 5, y)], fill=colors["H"])),
        ):
            draw(px(pooled[arm]["mean_inf"]), py(pooled[arm]["mean_W"]))
    for pt in frontier["points"]:
        x, y = px(pt["mean_inf"]), py(pt["mean_W"])
        dr.ellipse([x - 5, y - 5, x + 5, y + 5], outline=colors["P"], width=2)
    lx = w - margin - 130
    for i, arm in enumerate(("F", "A", "S", "H", "P")):
        dr.text((lx, margin + 6 + i * 18), arm, fill=colors[arm])
    dr.text((margin, 12), "learned volume-vs-infidelity frontier (test means)", fill="black")
    img.save(RUNS_DIR / "frontier.png")
