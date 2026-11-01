import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import torch

from pursuit05 import bc as bc_mod
from pursuit05 import dp, exact, screen, train
from pursuit05.cells import CellRegistry
from pursuit05.policy import (
    CultivationPolicy,
    decision_table,
    fit_final_threshold,
    table_decider,
)

PURSUIT05_DIR = Path(__file__).resolve().parents[1]
STRICT_ACCEPT_FTH = 0


def test_bc_reproduces_table():
    reg = CellRegistry()
    cells = [reg.find(f"6/0.001/{s}") for s in (1, 2, 3)]
    inputs = []
    for cell in cells:
        pre = reg.pre(cell)
        f = screen.run_F(pre, cell.p)
        h = dp.best_history(pre, cell.p, f["inf"])
        inputs.append(
            bc_mod.BCTable(
                pre, h.table, h.fth, cell.p, cell.stage_idx, cell.rate_idx
            )
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
    tiny_input = bc_mod.BCTable(pre, h.table, h.fth, 0.001, 0, 0)
    tiny_policy, tiny_stats = bc_mod.clone_from_tables([tiny_input], seed=0)
    assert tiny_stats["agreement"] == 1.0
    obs, tgt = bc_mod.bc_dataset([tiny_input])
    with torch.no_grad():
        got = tiny_policy.forward_eval(obs)[0].argmax(dim=-1)
    assert bool((got == tgt).all())


def _small_point(tmp_path):
    out = train.train_cell(
        "6/0.001/1",
        ["6/0.001/4"],
        lam=5000,
        total_timesteps=4096,
        seed=0,
        agents_per_env=64,
        beta=1.0,
        run_dir=tmp_path,
        log=lambda msg: None,
    )
    reg = CellRegistry()
    return reg, [reg.find("6/0.001/1")], [reg.find("6/0.001/4")], out["point"]


def test_pick_kept_prefers_feasible():
    got = train._pick_kept([("a", 5.0, 0.1), ("b", 50.0, 0.01)], 0.05)
    assert got == "b"


def test_pick_kept_min_w_among_feasible():
    got = train._pick_kept([("a", 5.0, 0.01), ("b", 3.0, 0.02)], 0.05)
    assert got == "b"


def test_pick_kept_tie_goes_first():
    got = train._pick_kept([("a", 5.0, 0.01), ("b", 5.0, 0.01)], 0.05)
    assert got == "a"


def test_pick_kept_none_feasible_picks_min_w():
    got = train._pick_kept([("a", 5.0, 0.1), ("b", 3.0, 0.2)], 0.05)
    assert got == "b"


def test_regime_ids():
    assert train.regime_id([6], [0.001]) == "6-0.001"
    assert train.regime_id([6, 9], [0.001, 0.002, 0.005]) == "transfer-6-9"
    assert train.regime_id([9, 6], [0.001, 0.002, 0.005]) == "transfer-6-9"
    assert train.regime_id([6, 9], [0.001]) == "transfer-6-9-r0.001"
    assert train.regime_id([6], [0.001, 0.002]) == "transfer-6-r0.001-0.002"


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
    reg = CellRegistry()
    cell = reg.find("6/0.001/1")
    out = train.train_cell(
        "6/0.001/1",
        ["6/0.001/4"],
        lam=5000,
        total_timesteps=4096,
        scratch_timesteps=200000,
        seed=0,
        agents_per_env=256,
        beta=1.0,
        do_scratch=True,
        run_dir=tmp_path,
        log=lambda msg: None,
    )
    policy = CultivationPolicy()
    policy.load_state_dict(out["scratch"]["state_dict"])
    policy.eval()
    got = train.evaluate_policy(policy, [cell], reg)
    pre = reg.pre(cell)
    keys = decision_table(
        CultivationPolicy(), pre, stage_id=cell.stage_idx, rate_id=cell.rate_idx
    )
    rng = np.random.default_rng(0)
    rand = {k: bool(rng.random() < 0.5) for k in keys if k[0] < pre["T"] - 1}
    strict = exact.eval_exact(
        table_decider(rand, fth=STRICT_ACCEPT_FTH), pre, cell.p
    )
    assert got["mean_W"] < strict["W"]
    full = {k: bool(rng.random() < 0.5) for k in keys}
    fitted = exact.eval_exact(
        table_decider(full, fth=fit_final_threshold(full, pre, cell.p)),
        pre,
        cell.p,
    )
    scratch_cost = got["mean_W"] + screen.LAMBDA * got["mean_inf"]
    random_cost = fitted["W"] + screen.LAMBDA * fitted["inf"]
    assert scratch_cost < random_cost


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
