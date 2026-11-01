from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import UTC
from pathlib import Path

import numpy as np

from pursuit05.arms import run_screen_arms

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


def _mc_w(spent_list, acc_list, tail, vf):
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


def _mc_inf_ok(log_list, acc_list, exact_inf, pacc, tail):
    n = len(log_list)
    count = int(sum(log_list))
    ma = sum(acc_list) / n
    mc = (count / n) / ma if ma else 0.0
    c = 1.0 - tail
    exp = n * exact_inf * pacc / c if c > 0 else 0.0
    ok = abs(count - exp) <= MC_SIGMAS * exp**0.5 if exp > 0 else count == 0
    return mc, count, ok


def cmd_env_smoke(args) -> int:
    import functools
    import time

    try:
        import pufferlib.vector

        from pursuit05.cells import CellRegistry
        from pursuit05.env import (
            CultivationAbort,
            binomial_masses,
            draw_trajectories,
            rollout_loaded,
            scripted_actions,
        )

        if args.agents < 1:
            raise ValueError(f"bad --agents {args.agents!r}")
        if args.steps < 1:
            raise ValueError(f"bad --steps {args.steps!r}")
        if args.seed < 0:
            raise ValueError(f"bad --seed {args.seed!r}")
        if args.workers < 0:
            raise ValueError(f"bad --workers {args.workers!r}")
        if args.workers and args.agents % args.workers:
            raise ValueError(
                f"agents {args.agents} not divisible by workers {args.workers}"
            )
        from pursuit05 import exact, screen

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
        ref = exact.eval_exact(exact.static_decider(ath, fth), pre, cell.p)
        exact_w, exact_inf, exact_pacc = ref["W"], ref["inf"], ref["pacc"]
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
            obs, _, _, _, _ = vec.step(scripted_actions(obs, ath, fth, t))
        wall = time.perf_counter() - t0
        rate = args.agents * args.steps / wall
        print(f"agent-steps/s = {rate:.0f}")
        mc_env = CultivationAbort(
            pre,
            cell.p,
            stage_id=cell.stage_idx,
            rate_id=cell.rate_idx,
            num_agents=args.agents,
        )
        w_all, rows_all = draw_trajectories(
            pre, cell.p, MC_EPISODES, np.random.default_rng(args.seed + 1)
        )
        outs = rollout_loaded(
            mc_env,
            w_all,
            rows_all,
            lambda obs, s, w, rows: scripted_actions(obs, ath, fth, t),
        )
        spent_list = [o[0] for o in outs]
        acc_list = [1.0 if o[1] else 0.0 for o in outs]
        log_list = [1.0 if o[2] else 0.0 for o in outs]
        tail = binomial_masses(pre["L1"], cell.p)[3]
        mc_w, se_w = _mc_w(spent_list, acc_list, tail, pre["Vf"])
        mc_inf, count, ok_inf = _mc_inf_ok(
            log_list, acc_list, exact_inf, exact_pacc, tail
        )
        ok_w = abs(mc_w - exact_w) <= MC_SIGMAS * se_w if se_w else abs(
            mc_w - exact_w
        ) <= 1e-9
        ok = ok_w and ok_inf
        print(
            f"scripted A thresholds via env rollouts: W = {mc_w:.10g} "
            f"+- {se_w:.3g} (exact {exact_w:.10g}), inf = {mc_inf:.10g} "
            f"(exact {exact_inf:.10g}, {count}/{len(log_list)} logicals), "
            f"{'within MC error' if ok else 'MISMATCH'}"
        )
        return 0 if ok else 1
    finally:
        vec.close()


def cmd_optimum(args) -> int:
    try:
        from pursuit05 import exact, screen, table
        from pursuit05.cells import TEST_SEEDS, CellRegistry, split_label

        seeds = _parse_seeds(args.seeds, screen.SEEDS)
        reg = CellRegistry()
        targets = reg.select(seeds=seeds)
        from pursuit05 import dp
        from pursuit05.env import binomial_masses
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
        rows.append((cell, s, h, bound, binomial_masses(pre["L1"], cell.p)[3]))
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


def _parse_int_list(raw: str | None, allowed: tuple, name: str) -> list[int]:
    if raw is None:
        return list(allowed)
    try:
        vals = [int(s) for s in raw.split(",") if s.strip()]
    except ValueError:
        raise ValueError(f"bad {name} {raw!r}") from None
    if not vals or any(v not in allowed for v in vals):
        raise ValueError(f"bad {name} {raw!r}")
    return vals


def _parse_float_list(raw: str | None, allowed: tuple, name: str) -> list[float]:
    if raw is None:
        return list(allowed)
    try:
        vals = [float(s) for s in raw.split(",") if s.strip()]
    except ValueError:
        raise ValueError(f"bad {name} {raw!r}") from None
    if not vals or any(v not in allowed for v in vals):
        raise ValueError(f"bad {name} {raw!r}")
    return vals


def _parse_lams(raw: str | None, default: tuple) -> list[float]:
    if raw is None:
        return list(default)
    try:
        vals = [float(s) for s in raw.split(",") if s.strip()]
    except ValueError:
        raise ValueError(f"bad --lams {raw!r}") from None
    if (
        not vals
        or any(not math.isfinite(v) or v <= 0 for v in vals)
        or len(set(vals)) != len(vals)
    ):
        raise ValueError(f"bad --lams {raw!r}")
    return vals


def _nonneg_int(raw, name: str) -> int:
    if raw is None:
        raise ValueError(f"bad {name} {raw!r}")
    try:
        bad = raw < 0
    except TypeError:
        raise ValueError(f"bad {name} {raw!r}") from None
    if bad:
        raise ValueError(f"bad {name} {raw!r}")
    return raw


def _checked_beta(settings: dict) -> float:
    try:
        beta = float(settings["beta"])
    except (TypeError, ValueError):
        raise ValueError(f"bad beta {settings.get('beta')!r}") from None
    if not math.isfinite(beta) or beta < 0:
        raise ValueError(f"bad beta {beta!r}")
    return beta


def _checked_lam(raw) -> float:
    try:
        lam = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"bad --lam {raw!r}") from None
    if not math.isfinite(lam) or lam <= 0:
        raise ValueError(f"bad --lam {raw!r}")
    return lam


def cmd_train(args) -> int:
    try:
        from pursuit05 import screen, train
        from pursuit05.cells import CellRegistry

        if args.stage is not None and args.stages is not None:
            raise ValueError("pass only one of --stage and --stages")
        if args.rate is not None and args.rates is not None:
            raise ValueError("pass only one of --rate and --rates")
        if (
            args.stage is None
            and args.stages is None
            and args.rate is None
            and args.rates is None
        ):
            raise ValueError("pass --stage/--rate or --stages/--rates")
        stages = (
            _parse_int_list(args.stages, screen.SIZES, "--stages")
            if args.stages is not None
            else _parse_int_list(
                str(args.stage) if args.stage is not None else None,
                screen.SIZES,
                "--stage",
            )
        )
        rates = (
            _parse_float_list(args.rates, screen.P_ERRS, "--rates")
            if args.rates is not None
            else _parse_float_list(
                str(args.rate) if args.rate is not None else None,
                screen.P_ERRS,
                "--rate",
            )
        )
        settings = train.load_run_settings()
        lam = _checked_lam(args.lam if args.lam is not None else settings["lam"])
        cfg = train.load_train_config()
        total = args.total_timesteps if args.total_timesteps is not None else cfg["total_timesteps"]
        total = _nonneg_int(total, "--total-timesteps")
        if total < 1:
            raise ValueError(f"bad --total-timesteps {total!r}")
        seed = args.seed if args.seed is not None else cfg["seed"]
        seed = _nonneg_int(seed, "--seed")
        agents = args.agents if args.agents is not None else settings["agents_per_env"]
        agents = _nonneg_int(agents, "--agents")
        if agents < 1:
            raise ValueError(f"bad --agents {agents!r}")
        beta = _checked_beta(settings)
        reg = CellRegistry()
        train_cells, test_cells = train.regime_cells(reg, stages, rates)
        rid = train.regime_id(stages, rates)
        run_dir = train.RUNS_DIR / rid
        run_dir.mkdir(parents=True, exist_ok=True)
    except (ImportError, ValueError) as exc:
        print(f"pursuit05: {exc}", file=sys.stderr)
        return 1
    kind = "regime" if len(stages) == 1 and len(rates) == 1 else "transfer"
    lines: list[str] = []

    def log(msg) -> None:
        print(msg)
        lines.append(str(msg))

    try:
        log(
            f"train {rid} kind={kind} lam={lam:g} steps={total} seed={seed} "
            f"bptt={cfg['bptt_horizon']} mb={cfg['minibatch_size']} "
            f"gamma={cfg['gamma']} lr={cfg['learning_rate']}"
        )
        scratch_dir = train.RUNS_DIR / "scratch" / f"{rid}-lam{lam:g}"
        scratch_dir.mkdir(parents=True, exist_ok=True)
        point = train.train_point(
            train_cells,
            test_cells,
            lam=lam,
            total_timesteps=total,
            seed=seed,
            agents_per_env=agents,
            beta=beta,
            bc_seed=seed,
            scratch_dir=scratch_dir,
            log=log,
        )
        scratch = None
        if not args.no_scratch:
            sdir = train.RUNS_DIR / "scratch" / f"{rid}-scratch"
            sdir.mkdir(parents=True, exist_ok=True)
            scratch = train.train_scratch(
                train_cells,
                test_cells,
                lam=lam,
                total_timesteps=total,
                seed=seed + 1000,
                agents_per_env=agents,
                beta=beta,
                scratch_dir=sdir,
                log=log,
            )
        receipt = train.assemble_receipt(
            run_dir,
            rid,
            kind,
            train_cells,
            test_cells,
            [point],
            scratch,
            total,
            seed,
            agents,
            beta,
        )
        base = train.baselines_for_cells(test_cells, reg)
        pt = receipt["points"][0]
        pw, pinf = pt["mean_W"], pt["mean_inf"]
        sw = sum(base[c]["S"]["W"] for c in base) / len(base)
        hw = sum(base[c]["H"]["W"] for c in base) / len(base)
        aw = sum(base[c]["A"]["W"] for c in base) / len(base)
        for cell in test_cells:
            keys = pt["cells"][cell.cell_id]["keys"]
            log(f"decision-table keys {cell.cell_id}: {keys}")
        line = (
            f"exact test W = {pw:.10g}, inf = {pinf:.10g}; "
            f"S = {sw:.10g}; H = {hw:.10g}; A = {aw:.10g}"
        )
        if pw > sw:
            line += " SHORTFALL vs S"
        log(line)
        return 0
    finally:
        (run_dir / "train.log").write_text("\n".join(lines) + "\n")


def cmd_sweep(args) -> int:
    try:
        from pursuit05 import screen, train

        stages = _parse_int_list(args.stages, screen.SIZES, "--stages")
        rates = _parse_float_list(args.rates, screen.P_ERRS, "--rates")
        lams = _parse_lams(args.lams, train.NOMINAL_LAMS)
        settings = train.load_run_settings()
        cfg = train.load_train_config()
        total = args.total_timesteps if args.total_timesteps is not None else cfg["total_timesteps"]
        total = _nonneg_int(total, "--total-timesteps")
        if total < 1:
            raise ValueError(f"bad --total-timesteps {total!r}")
        seed = args.seed if args.seed is not None else cfg["seed"]
        seed = _nonneg_int(seed, "--seed")
        agents = args.agents if args.agents is not None else settings["agents_per_env"]
        agents = _nonneg_int(agents, "--agents")
        if agents < 1:
            raise ValueError(f"bad --agents {agents!r}")
        jobs = _nonneg_int(args.jobs, "--jobs")
        if jobs < 1 or jobs > 2:
            raise ValueError(f"bad --jobs {args.jobs!r}: at most 2 concurrent trainings")
        beta = _checked_beta(settings)
    except (ImportError, ValueError) as exc:
        print(f"pursuit05: {exc}", file=sys.stderr)
        return 1
    receipts = train.sweep_lambda(
        stages,
        rates,
        lams,
        total_timesteps=total,
        seed=seed,
        agents_per_env=agents,
        beta=beta,
        jobs=jobs,
        do_scratch=not args.no_scratch,
    )
    train.write_frontier(receipts)
    return 0


def _eval_rows(screen, table, train, reg, stages, rates, seeds, policy_path):
    rows = []
    trained_on = None
    for n in stages:
        for p in rates:
            rid = train.regime_id([n], [p])
            run_dir = train.RUNS_DIR / rid
            receipt_path = run_dir / "receipt.json"
            if policy_path is None and not receipt_path.is_file():
                raise ValueError(f"missing receipt for {rid}: run train or sweep first")
            cells = [
                c
                for c in reg.all_cells()
                if c.n == n and c.p == p and c.seed in seeds
            ]
            base = train.baselines_for_cells(cells, reg)
            import torch

            from pursuit05.policy import CultivationPolicy

            weights_path = (
                Path(policy_path) if policy_path is not None else run_dir / "policy.pt"
            )
            try:
                weights = torch.load(
                    weights_path, map_location="cpu", weights_only=True
                )
            except (OSError, RuntimeError) as exc:
                raise ValueError(
                    f"cannot load weights {weights_path}: {exc}"
                ) from None
            try:
                policy = CultivationPolicy()
                policy.load_state_dict(weights)
            except RuntimeError as exc:
                raise ValueError(
                    f"bad weights {weights_path}: {exc}"
                ) from None
            policy.eval()
            if policy_path is not None:
                side = weights_path.parent / "receipt.json"
                if side.is_file():
                    try:
                        trained_on = json.loads(side.read_text())["trained_on"]
                    except (KeyError, ValueError) as exc:
                        raise ValueError(
                            f"bad sidecar receipt {side}: {exc}"
                        ) from None
                    if not isinstance(trained_on, dict):
                        raise ValueError(f"bad sidecar receipt {side}")
                else:
                    trained_on = "unknown (no sidecar receipt)"
            ev = train.evaluate_policy(policy, cells, reg)
            vals = {}
            for arm in ("F", "A", "S", "H"):
                ws = [base[c.cell_id][arm]["W"] for c in cells]
                infs = [base[c.cell_id][arm]["inf"] for c in cells]
                vals[arm] = (sum(ws) / len(ws), sum(infs) / len(infs))
            vals["P"] = (ev["mean_W"], ev["mean_inf"])
            bounds = [base[c.cell_id]["bound"] for c in cells]
            rows.append((f"{n}/{p}", vals, sum(bounds) / len(bounds)))
    return rows, trained_on


def cmd_eval(args) -> int:
    try:
        from pursuit05 import screen, table, train
        from pursuit05.cells import TEST_SEEDS, TRAIN_SEEDS, CellRegistry

        seeds = _parse_seeds(args.seeds, screen.SEEDS)
        if any(s in TRAIN_SEEDS for s in seeds):
            print("train seeds are not reportable", file=sys.stderr)
            return 2
        stages = _parse_int_list(args.stages, screen.SIZES, "--stages")
        rates = _parse_float_list(args.rates, screen.P_ERRS, "--rates")
        if args.policy is not None and not Path(args.policy).is_file():
            raise ValueError(f"policy not found: {args.policy}")
        reg = CellRegistry()
        rows, trained_on = _eval_rows(
            screen, table, train, reg, stages, rates, seeds, args.policy
        )
    except (ImportError, ValueError) as exc:
        print(f"pursuit05: {exc}", file=sys.stderr)
        return 1
    full = stages == list(screen.SIZES) and rates == list(screen.P_ERRS)
    label = "all" if full else "selected"
    print(f"# eval P vs F, A, S, H ({label} regimes, test seeds {','.join(str(s) for s in seeds)})")
    print(table.render_arm_table([(cid, vals) for cid, vals, _ in rows], ("F", "A", "S", "H", "P")))
    if trained_on is not None:
        if isinstance(trained_on, dict):
            print(f"trained_on = {trained_on.get('stages')}")
            print(f"trained_rates = {trained_on.get('rates')}")
            print(f"trained_seeds = {trained_on.get('seeds')}")
        else:
            print(f"trained_on = {trained_on}")
    census = [(cid, vals, b) for cid, vals, b in rows if float(cid.split("/")[1]) <= 0.002]
    if len(census) == 6 and set(seeds) == set(TEST_SEEDS):
        beats_s = beats_a = near_h = 0
        for _, vals, bound in census:
            pw, pinf = vals["P"]
            p_ok = pinf <= bound
            for arm, slot in (("S", "s"), ("A", "a")):
                ow, oinf = vals[arm]
                if pw <= 0.9 * ow and p_ok and oinf <= bound:
                    if slot == "s":
                        beats_s += 1
                    else:
                        beats_a += 1
            hw, _ = vals["H"]
            if pw <= 1.02 * hw and p_ok:
                near_h += 1
        print(
            f"P beats S in {beats_s}/6, beats A in {beats_a}/6, "
            f"and reaches H within 2% in {near_h}/6 at p <= 0.002"
        )
    else:
        print("D2 census skipped: select all p <= 0.002 regimes on test seeds")
    return 0


DEMO_ARMS = ("F", "A", "S", "H", "L", "P")
REPLAY_TOL = 1e-9


def _pursuit05_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _parse_regime(raw: str):
    from pursuit05 import screen

    try:
        n_s, p_s = raw.split("/")
        n, p = int(n_s), float(p_s)
        if n not in screen.SIZES or p not in screen.P_ERRS:
            raise ValueError(raw)
    except (ValueError, AttributeError):
        raise ValueError(f"bad --regime {raw!r}, want n/p like 9/0.002") from None
    return n, p


def _load_demo_tables() -> dict:
    path = _pursuit05_dir() / "pursuit05" / "fixtures" / "demo_tables.json"
    if not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return obj if isinstance(obj, dict) else {}


def _cell_summary(cell, pre) -> str:
    return (
        f"A {cell.n}-qubit magic-state cultivation stage runs {cell.T} syndrome "
        f"rounds with {pre['L1']} checks at physical error rate {cell.p}. "
        f"After each of the first {cell.T - 1} rounds you may abort if the "
        "cumulative syndrome weight exceeds a threshold (99 means never abort). "
        "At the end you accept if the final weight is at or below a final threshold."
    )


def _collect_versions() -> dict:
    import importlib.metadata
    import platform

    versions = {"python": platform.python_version()}
    for dist in ("pufferlib", "torch", "numpy"):
        try:
            versions[dist] = importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError:
            versions[dist] = "unknown"
    try:
        import subprocess

        proc = subprocess.run(
            ["muse", "--version"], capture_output=True, text=True, timeout=15,
            check=False,
        )
        versions["muse"] = (
            proc.stdout.strip().splitlines()[0] if proc.returncode == 0
            else "unknown"
        )
    except (OSError, subprocess.SubprocessError, IndexError):
        versions["muse"] = "unknown"
    return versions


def _find_policy_checkpoint(n: int, p: float):
    runs = _pursuit05_dir() / "runs"
    if not runs.is_dir():
        return None
    for receipt_path in sorted(runs.glob("*/receipt.json")):
        try:
            obj = json.loads(receipt_path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        rn = obj.get("stage", obj.get("n"))
        rp = obj.get("rate", obj.get("p"))
        if rn == n and rp == p:
            policy_path = receipt_path.parent / "policy.pt"
            if policy_path.is_file():
                return policy_path
    return None


def _score_policy_checkpoint(policy_path: Path, reg, cells):
    import torch

    from pursuit05 import exact
    from pursuit05.policy import (
        CultivationPolicy,
        decision_table,
        fit_final_threshold,
        table_decider,
    )
    from pursuit05.witness import encode_table

    policy = CultivationPolicy()
    policy.load_state_dict(
        torch.load(policy_path, map_location="cpu", weights_only=True)
    )
    policy.eval()
    out = {}
    for cell in cells:
        pre = reg.pre(cell)
        tbl = decision_table(
            policy, pre, stage_id=cell.stage_idx, rate_id=cell.rate_idx
        )
        fth = fit_final_threshold(tbl, pre, cell.p)
        res = exact.eval_exact(table_decider(tbl, fth=fth), pre, cell.p)
        out[cell.cell_id] = (res, {"table": encode_table(tbl), "fth": fth})
    return out


def _offline_explanation(goal, table_text, rules_text, s_text) -> dict:
    diffs = [line for line in rules_text.splitlines() if line.endswith("*differs from S*")]
    if diffs:
        shown = "; ".join(diffs[:3])
        expl = (
            f"Offline read of the exact table for goal {goal!r}: the learned "
            f"policy differs from the best static policy on {len(diffs)} prefixes, "
            f"including {shown}."
        )
    else:
        expl = (
            f"Offline read of the exact table for goal {goal!r}: the learned "
            "policy matches the best static policy on every listed prefix, so "
            "history buys nothing on these cells within the pinned decider class."
        )
    return {
        "explanation": expl,
        "next_experiment": (
            "Sweep the PPO penalty weight and re-score exactly on the held-out "
            "cells to trace the learned volume-versus-infidelity frontier."
        ),
    }


def cmd_demo(args) -> int:
    import uuid
    from datetime import datetime

    from pursuit05 import exact, screen, table
    from pursuit05.cells import TEST_SEEDS, CellRegistry
    from pursuit05.proposer import (
        EXPECTED_PROVIDER,
        MODEL_ID,
        CallOverBudget,
        ExecFailed,
        ProposalError,
        SpendGuard,
        SpendRefused,
        build_explainer_prompt,
        dominance_reason,
        fixture_proposal,
        load_fixture,
        make_workdir,
        render_table_rules,
        run_explainer,
        run_proposal_loop,
    )
    from pursuit05.witness import Witness, decode_table

    try:
        n, p = _parse_regime(args.regime)
        reg = CellRegistry()
        cells = sorted(
            (c for c in reg.all_cells()
             if c.n == n and c.p == p and c.seed in TEST_SEEDS),
            key=lambda c: c.seed,
        )
        if not cells:
            raise ValueError(f"no test cells for regime {args.regime!r}")
    except (ImportError, ValueError) as exc:
        print(f"pursuit05: {exc}", file=sys.stderr)
        return 1
    started = datetime.now(UTC).isoformat()
    guard = SpendGuard()
    in_tok = 0
    out_tok = 0
    stored = _load_demo_tables()
    arms: dict[str, dict] = {}
    fails: dict[str, str] = {}
    h_tables: dict[str, dict] = {}
    s_bests: dict[str, tuple] = {}
    for cell in cells:
        pre = reg.pre(cell)
        f = screen.run_F(pre, cell.p)
        a = screen.run_arm(
            pre, cell.p, "A", f["inf"], screen.A_ITERS, screen.R_SAMPLES,
            None, cell.stage_idx, cell.rate_idx, cell.seed,
        )
        slot = arms.setdefault(cell.cell_id, {})
        slot["F"] = {"W": f["W"], "inf": f["inf"], "pacc": f.get("pacc", 0.0),
                     "n_evaluated": 1, "inference_cost_s": 0.0}
        slot["A"] = {"W": a["W"], "inf": a["inf"], "pacc": a.get("pacc", 0.0),
                     "n_evaluated": 1, "inference_cost_s": 0.0}
        hit = stored.get(cell.cell_id)
        if hit:
            slot["S"] = hit["S"]
            slot["H"] = {k: v for k, v in hit["H"].items() if k != "table"}
            h_tables[cell.cell_id] = decode_table(hit["H"]["table"])
            s_bests[cell.cell_id] = (tuple(hit["S"]["policy"]["ath"]),
                                     hit["S"]["policy"]["fth"])
        else:
            print(f"computed S/H live for {cell.cell_id}")
            from pursuit05 import dp

            s = exact.best_static(pre, cell.p, f["inf"])
            h = dp.best_history(pre, cell.p, f["inf"])
            slot["S"] = {"W": s.result.W, "inf": s.result.inf,
                         "pacc": s.result.pacc,
                         "n_evaluated": s.result.n_evaluated,
                         "inference_cost_s": s.result.inference_cost_s,
                         "policy": {"ath": list(s.ath), "fth": s.fth}}
            slot["H"] = {"W": h.result.W, "inf": h.result.inf,
                         "pacc": h.result.pacc,
                         "n_evaluated": h.result.n_evaluated,
                         "inference_cost_s": h.result.inference_cost_s,
                         "lam": h.lam}
            h_tables[cell.cell_id] = dict(h.table)
            s_bests[cell.cell_id] = (s.ath, s.fth)
    proposals: dict = {}
    provider_id: str | None = None
    model_id: str | None = None
    source = "live"
    if args.offline:
        source = "fixture"
        try:
            fixture = load_fixture()
            entries = fixture["entries"]
            if len(entries) < len(cells):
                raise ValueError(
                    f"fixture holds {len(entries)} entries for {len(cells)} cells"
                )
        except (OSError, ValueError) as exc:
            print(f"pursuit05: {exc}", file=sys.stderr)
            return 1
        for cell, entry in zip(cells, entries):
            pre = reg.pre(cell)
            t = pre["T"]
            try:
                prop, usage = fixture_proposal(entry, t)
            except ValueError as exc:
                print(f"pursuit05: fixture entry bad: {exc}", file=sys.stderr)
                return 1
            f = screen.run_F(pre, cell.p)
            res = exact.eval_exact(exact.static_decider(prop.ath, prop.fth),
                                   pre, cell.p)
            dom = dominance_reason(res["W"], res["inf"], f["W"], f["inf"])
            if dom is not None:
                fails[cell.cell_id] = dom
            arms[cell.cell_id]["L"] = {
                "W": res["W"], "inf": res["inf"], "pacc": res["pacc"],
                "n_evaluated": 1, "inference_cost_s": 0.0,
                "policy": {"ath": list(prop.ath), "fth": prop.fth},
            }
            in_tok += usage.get("input_tokens", 0)
            out_tok += usage.get("output_tokens", 0)
            provider_id = EXPECTED_PROVIDER
            model_id = MODEL_ID
            proposals[cell.cell_id] = {
                "proposal": {"ath": list(prop.ath), "fth": prop.fth,
                             "rationale": prop.rationale},
                "reason": dom or "accepted",
                "usage": usage,
            }
    else:
        workdir = make_workdir(_pursuit05_dir())
        for cell in cells:
            pre = reg.pre(cell)
            t = pre["T"]
            f = screen.run_F(pre, cell.p)
            summary = _cell_summary(cell, pre)

            def scorer(ath, fth, _pre=pre, _p=cell.p):
                r = exact.eval_exact(exact.static_decider(ath, fth), _pre, _p)
                return r["W"], r["inf"]

            try:
                loop = run_proposal_loop(
                    args.goal, summary, t, f["W"], f["inf"],
                    scorer, guard, workdir,
                    tag=f"cell-{cell.n}-{cell.p}-{cell.seed}",
                )
            except SpendRefused as exc:
                print(f"spend guard refused; table without L: {exc}")
                for slot in arms.values():
                    slot.pop("L", None)
                break
            except (ProposalError, ExecFailed, CallOverBudget) as exc:
                print(f"pursuit05: proposer failed: {exc}", file=sys.stderr)
                return 1
            for att in loop.attempts:
                in_tok += att.usage.get("input_tokens", 0)
                out_tok += att.usage.get("output_tokens", 0)
                provider_id = att.provider_id
                model_id = att.model_id
            if loop.failed:
                fails[cell.cell_id] = loop.fail_reason
            arms[cell.cell_id]["L"] = {
                "W": loop.w, "inf": loop.inf,
                "pacc": exact.eval_exact(
                    exact.static_decider(loop.best.ath, loop.best.fth),
                    pre, cell.p)["pacc"],
                "n_evaluated": len(loop.attempts), "inference_cost_s": 0.0,
                "policy": {"ath": list(loop.best.ath), "fth": loop.best.fth},
            }
            proposals[cell.cell_id] = {
                "proposal": {"ath": list(loop.best.ath), "fth": loop.best.fth,
                             "rationale": loop.best.rationale},
                "reason": loop.fail_reason or "accepted",
                "tries": len(loop.attempts),
            }
    if "L" in arms[cells[0].cell_id]:
        print(f"provider {provider_id}, model {model_id}")
        print(f"input tokens {in_tok}, output tokens {out_tok}")
        if args.offline:
            print("transcript: fixture")
    present = [a for a in DEMO_ARMS if all(a in arms[c.cell_id] for c in cells)]
    pol_path = _find_policy_checkpoint(n, p)
    if pol_path is not None:
        try:
            scored = _score_policy_checkpoint(pol_path, reg, cells)
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            print(f"policy checkpoint {pol_path} unusable: {exc}")
        else:
            for cid, (res, pol) in scored.items():
                arms[cid]["P"] = {
                    "W": res["W"], "inf": res["inf"], "pacc": res["pacc"],
                    "n_evaluated": len(pol["table"]),
                    "inference_cost_s": 0.0, "policy": pol,
                }
            present = [a for a in DEMO_ARMS if all(a in arms[c.cell_id]
                                                  for c in cells)]
    rows = [(c.cell_id, {a: (arms[c.cell_id][a]["W"], arms[c.cell_id][a]["inf"])
                         for a in present}) for c in cells]
    table_text = table.render_arm_table(rows, tuple(present))
    print(table_text)
    for cid, reason in fails.items():
        print(f"L fails joint criterion in {cid}: {reason}")
    first = cells[0]
    s_ath, s_fth = s_bests[first.cell_id]
    rules_src = h_tables[first.cell_id]
    if "P" in arms[first.cell_id]:
        rules_src = decode_table(arms[first.cell_id]["P"]["policy"]["table"])
    rules_text = render_table_rules(rules_src, s_ath, s_fth)
    s_text = (f"abort {list(s_ath)}, accept weight <= {s_fth} "
              f"(W={arms[first.cell_id]['S']['W']:.6g})")
    explanation: dict
    if args.offline:
        explanation = _offline_explanation(args.goal, table_text, rules_text,
                                           s_text)
        explanation["source"] = "offline"
        print(explanation["explanation"])
        print(f"Next experiment: {explanation['next_experiment']}")
    else:
        try:
            prompt = build_explainer_prompt(args.goal, table_text, rules_text,
                                            s_text)
            expl_obj, expl_tr = run_explainer(prompt, guard, workdir, "demo")
            in_tok += expl_tr.usage.get("input_tokens", 0)
            out_tok += expl_tr.usage.get("output_tokens", 0)
            explanation = {"explanation": expl_obj["explanation"],
                           "next_experiment": expl_obj["next_experiment"],
                           "source": "live",
                           "usage": expl_tr.usage}
            print(explanation["explanation"])
            print(f"Next experiment: {explanation['next_experiment']}")
        except (SpendRefused, ProposalError, ExecFailed, CallOverBudget) as exc:
            print(f"explainer failed ({exc}); offline text instead")
            explanation = _offline_explanation(args.goal, table_text,
                                               rules_text, s_text)
            explanation["source"] = "offline-fallback"
            print(explanation["explanation"])
            print(f"Next experiment: {explanation['next_experiment']}")
    finished = datetime.now(UTC).isoformat()
    wid = uuid.uuid4().hex[:12]
    witness_dir = Path(args.witness_dir)
    if not witness_dir.is_absolute():
        witness_dir = _pursuit05_dir() / witness_dir
    rel = f"witnesses/{wid}.json"
    witness = Witness(
        witness_id=wid, goal=args.goal, regime=args.regime,
        cell_ids=[c.cell_id for c in cells], arms=arms, proposals=proposals,
        explanation=explanation, provider_id=provider_id, model_id=model_id,
        source=source, versions=_collect_versions(), seed=args.seed,
        timestamps={"started": started, "finished": finished},
        replay_command=f"python -m pursuit05 replay {rel}",
        usage_total={"input_tokens": in_tok, "output_tokens": out_tok},
    )
    witness.write(witness_dir / f"{wid}.json")
    print(f"witness written to {rel}; replay with {witness.replay_command}")
    return 0


def cmd_replay(args) -> int:
    from pursuit05 import dp, exact, screen
    from pursuit05.cells import CellRegistry
    from pursuit05.policy import table_decider
    from pursuit05.witness import Witness, arm_names, decode_table

    try:
        witness = Witness.read(Path(args.witness))
        reg = CellRegistry()
    except (ImportError, ValueError, TypeError) as exc:
        print(f"pursuit05: {exc}", file=sys.stderr)
        return 1
    names = [a for a in DEMO_ARMS if a in arm_names(witness)]
    matched = []
    failed = []
    for arm in names:
        ok = True
        for cid in witness.cell_ids:
            try:
                cell = reg.find(cid)
            except ValueError as exc:
                print(f"pursuit05: {exc}", file=sys.stderr)
                return 1
            pre = reg.pre(cell)
            stored = witness.arms[cid][arm]
            f = screen.run_F(pre, cell.p)
            if arm == "F":
                w, inf = f["W"], f["inf"]
            elif arm == "A":
                a = screen.run_arm(
                    pre, cell.p, "A", f["inf"], screen.A_ITERS,
                    screen.R_SAMPLES, None, cell.stage_idx, cell.rate_idx,
                    cell.seed,
                )
                w, inf = a["W"], a["inf"]
            elif arm == "S":
                s = exact.best_static(pre, cell.p, f["inf"])
                w, inf = s.result.W, s.result.inf
            elif arm == "H":
                h = dp.best_history(pre, cell.p, f["inf"])
                w, inf = h.result.W, h.result.inf
            elif arm == "L":
                pol = stored["policy"]
                r = exact.eval_exact(
                    exact.static_decider(pol["ath"], pol["fth"]), pre, cell.p)
                w, inf = r["W"], r["inf"]
            elif arm == "P":
                pol = stored["policy"]
                r = exact.eval_exact(
                    table_decider(decode_table(pol["table"]), fth=pol["fth"]),
                    pre, cell.p)
                w, inf = r["W"], r["inf"]
            else:
                print(f"pursuit05: unknown arm {arm!r}", file=sys.stderr)
                return 1
            if (abs(w - stored["W"]) > REPLAY_TOL
                    or abs(inf - stored["inf"]) > REPLAY_TOL):
                print(
                    f"MISMATCH {arm} {cid}: W witness={stored['W']:.12g} "
                    f"replay={w:.12g}; inf witness={stored['inf']:.12g} "
                    f"replay={inf:.12g}"
                )
                ok = False
        (matched if ok else failed).append(arm)
    print(f"replay matches witness on {len(matched)}/{len(names)} arms")
    return 0 if not failed else 1


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
    tp = sub.add_parser("train", help="train a pooled abort policy")
    tp.add_argument("--stage", type=int, default=None, help="single stage n")
    tp.add_argument("--stages", default=None, help="comma stages like 6,9")
    tp.add_argument("--rate", type=float, default=None, help="single rate p")
    tp.add_argument("--rates", default=None, help="comma rates")
    tp.add_argument("--lam", type=float, default=None, help="nominal lam")
    tp.add_argument("--total-timesteps", type=int, default=None, help="PPO steps")
    tp.add_argument("--seed", type=int, default=None, help="train seed")
    tp.add_argument("--agents", type=int, default=None, help="agents per env")
    tp.add_argument("--no-scratch", action="store_true", help="skip scratch ablation")
    sp = sub.add_parser("sweep", help="sweep lam per regime and write frontier")
    sp.add_argument("--lams", default=None, help="comma lams like 1000,5000,10000")
    sp.add_argument("--stages", default=None, help="comma stages")
    sp.add_argument("--rates", default=None, help="comma rates")
    sp.add_argument("--total-timesteps", type=int, default=None, help="PPO steps")
    sp.add_argument("--seed", type=int, default=None, help="base seed")
    sp.add_argument("--agents", type=int, default=None, help="agents per env")
    sp.add_argument("--jobs", type=int, default=2, help="concurrent trainings, max 2")
    sp.add_argument("--no-scratch", action="store_true", help="skip scratch ablation")
    vp = sub.add_parser("eval", help="score P against F, A, S, H on test seeds")
    vp.add_argument("--all", action="store_true", help="all 9 regimes (same as defaults)")
    vp.add_argument("--stages", default=None, help="comma stages")
    vp.add_argument("--rates", default=None, help="comma rates")
    vp.add_argument("--seeds", default="4,5", help="test seeds only")
    vp.add_argument("--policy", default=None, help="override P weights path")
    dp = sub.add_parser("demo", help="run the Muse Spark demo on one regime")
    dp.add_argument("goal", help="goal string for the proposer")
    dp.add_argument("--regime", default="9/0.002", help="n/p like 9/0.002")
    dp.add_argument("--offline", action="store_true",
                    help="replay fixture transcripts, no model call")
    dp.add_argument("--seed", type=int, default=0, help="witness seed")
    dp.add_argument("--witness-dir", default="witnesses",
                    help="witness output dir")
    rp = sub.add_parser("replay", help="re-score a demo witness exactly")
    rp.add_argument("witness", help="witness json path")
    args = ap.parse_args(argv)
    if args.cmd == "reproduce":
        return cmd_reproduce(args)
    if args.cmd == "env-smoke":
        return cmd_env_smoke(args)
    if args.cmd == "optimum":
        return cmd_optimum(args)
    if args.cmd == "train":
        return cmd_train(args)
    if args.cmd == "sweep":
        return cmd_sweep(args)
    if args.cmd == "eval":
        return cmd_eval(args)
    if args.cmd == "demo":
        return cmd_demo(args)
    if args.cmd == "replay":
        return cmd_replay(args)
    return cmd_baselines(args)
