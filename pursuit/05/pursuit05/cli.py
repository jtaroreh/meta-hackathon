from __future__ import annotations

import argparse
import json
import math
import os
import sys
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
    return cmd_baselines(args)
