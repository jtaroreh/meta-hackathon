import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import torch

from pursuit05 import bc as bc_mod
from pursuit05 import dp, exact, screen, train
from pursuit05.cells import CellRegistry
from pursuit05.policy import CultivationPolicy, decision_table, table_decider

PURSUIT05_DIR = Path(__file__).resolve().parents[1]


def test_bc_reproduces_table():
    reg = CellRegistry()
    cells = [reg.find(f"6/0.001/{s}") for s in (1, 2, 3)]
    inputs = []
    for cell in cells:
        pre = reg.pre(cell)
        f = screen.run_F(pre, cell.p)
        h = dp.best_history(pre, cell.p, f["inf"])
        inputs.append(
            (pre, h.table, h.fth, cell.p, cell.stage_idx, cell.rate_idx)
        )
    policy, stats = bc_mod.clone_from_tables(inputs, seed=0)
    assert stats["agreement"] >= 0.99
    for cell, single in zip(cells, inputs):
        obs, tgt = bc_mod.bc_dataset([single])
        assert bc_mod.agreement(policy, obs, tgt) >= 0.99, cell.cell_id
    tiny = screen.build_cell(6, tiny=True, drop=())
    pre = screen.precompute(tiny, list(range(tiny["C"])), 3)
    f = screen.run_F(pre, 0.001)
    h = dp.best_history(pre, 0.001, f["inf"])
    tiny_policy, tiny_stats = bc_mod.clone_from_tables(
        [(pre, h.table, h.fth, 0.001, 0, 0)], seed=0
    )
    assert tiny_stats["agreement"] == 1.0
    obs, tgt = bc_mod.bc_dataset([(pre, h.table, h.fth, 0.001, 0, 0)])
    with torch.no_grad():
        got = tiny_policy.forward_eval(obs)[0].argmax(dim=-1)
    assert bool((got == tgt).all())


def _small_point(tmp_path):
    reg = CellRegistry()
    train_cells = [reg.find("6/0.001/1")]
    monitor_cells = [reg.find("6/0.001/4")]
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    point = train.train_point(
        train_cells,
        monitor_cells,
        lam=5000,
        total_timesteps=4096,
        seed=0,
        agents_per_env=64,
        beta=1.0,
        bc_seed=0,
        scratch_dir=scratch,
        log=lambda msg: None,
    )
    return reg, train_cells, monitor_cells, point


def test_receipt_has_no_train_seed_scores(tmp_path):
    _, train_cells, monitor_cells, point = _small_point(tmp_path)
    run_dir = tmp_path / "runs" / "6-0.001"
    receipt = train.assemble_receipt(
        run_dir,
        "6-0.001",
        "regime",
        train_cells,
        monitor_cells,
        [point],
        None,
        4096,
        0,
        64,
        1.0,
    )
    assert receipt["seeds_eval"] == [4]
    assert receipt["trained_on"]["seeds"] == [1]
    text = (run_dir / "receipt.json").read_text()
    assert "6/0.001/1" not in text
    assert "train_W" not in text
    assert "bc_train" not in text
    assert "ft_train" not in text
    assert (run_dir / "policy.pt").is_file()


def test_finetune_never_worse_than_bc(tmp_path):
    _, _, _, point = _small_point(tmp_path)
    kept = (
        point["ft_train_W"]
        if point["kept_from"] == "finetune"
        else point["bc_train_W"]
    )
    assert kept <= point["bc_train_W"]
    assert point["kept_from"] in ("bc", "finetune")


def test_scratch_ppo_ablation_beats_random(tmp_path):
    """Scratch PPO beats random abort timing with strict accept (R convention)."""
    reg = CellRegistry()
    cell = reg.find("6/0.001/1")
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()
    res = train.train_scratch(
        [cell],
        [cell],
        lam=5000,
        total_timesteps=200000,
        seed=0,
        agents_per_env=256,
        beta=1.0,
        scratch_dir=scratch_dir,
        log=lambda msg: None,
    )
    policy = CultivationPolicy()
    policy.load_state_dict(res["state_dict"])
    policy.eval()
    got = train.evaluate_policy(policy, [cell], reg)
    pre = reg.pre(cell)
    keys = decision_table(
        CultivationPolicy(), pre, stage_id=cell.stage_idx, rate_id=cell.rate_idx
    )
    rng = np.random.default_rng(0)
    rand = {k: bool(rng.random() < 0.5) for k in keys if k[0] < pre["T"] - 1}
    out = exact.eval_exact(table_decider(rand, fth=0), pre, cell.p)
    assert got["mean_W"] < out["W"]


def test_eval_refuses_train_seeds():
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("PURSUIT05_SCREEN_SRC", "PURSUIT05_RECORD")
    }
    proc = subprocess.run(
        [sys.executable, "-m", "pursuit05", "eval", "--all", "--seeds", "1,2,3"],
        check=False,
        cwd=PURSUIT05_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 2
    assert "train seeds are not reportable" in proc.stderr
