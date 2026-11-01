from __future__ import annotations

import numpy as np
import torch
from torch import nn

from pursuit05.env import CW_COLS, binomial_masses
from pursuit05.policy import CultivationPolicy, PrefixTable

BC_LR = 1e-2
BC_MAX_ITERS = 5000


def obs_row(
    k: int, vals: tuple[int, ...], stage_id: int, rate_id: int, t: int
) -> list[float]:
    return [
        float(k),
        *[float(v) for v in vals],
        *[0.0] * (CW_COLS - len(vals)),
        float(stage_id),
        float(rate_id),
        float(t),
    ]


def _final_targets(
    pre: dict, p: float, fth: int
) -> dict[tuple[int, ...], bool]:
    _, p1, p2, _ = binomial_masses(pre["L1"], p)
    n2 = len(pre["fw2"])
    q1 = p1 / pre["L1"] if pre["L1"] else 0.0
    q2 = p2 / n2 if n2 else 0.0
    votes: dict[tuple[int, ...], list[float]] = {}
    for cw, fw, q in (
        (pre["cw1"], pre["fw1"], q1),
        (pre["cw2"], pre["fw2"], q2),
    ):
        for r in range(cw.shape[0]):
            vals = tuple(int(v) for v in cw[r])
            if not any(vals):
                continue
            slot = votes.setdefault(vals, [0.0, 0.0])
            slot[0 if int(fw[r]) <= fth else 1] += q
    return {vals: acc >= rej for vals, (acc, rej) in votes.items()}


def bc_dataset(
    cells: list[tuple[dict, PrefixTable, int, float, int, int]],
) -> tuple[torch.Tensor, torch.Tensor]:
    """Stack (obs, abort-vote) rows from H tables over pooled cells.

    Each entry is (pre, table, fth, p, stage_id, rate_id). Mid
    prefixes come from the table; final-step votes are the
    mass-weighted majority accept label per full-cw prefix, since fw
    is not in the observation. Ties accept, matching the env bias
    toward accepting clean finals.
    """
    obs: list[list[float]] = []
    tgt: list[int] = []
    for pre, table, fth, p, stage_id, rate_id in cells:
        t = pre["T"]
        for (k, vals), abort in table.items():
            if k >= t - 1:
                continue
            obs.append(obs_row(k, vals, stage_id, rate_id, t))
            tgt.append(1 if abort else 0)
        for vals, accept in _final_targets(pre, p, fth).items():
            obs.append(obs_row(t - 1, vals, stage_id, rate_id, t))
            tgt.append(1 if accept else 0)
    return (
        torch.as_tensor(np.asarray(obs, dtype=np.float32)),
        torch.as_tensor(np.asarray(tgt, dtype=np.int64)),
    )


def agreement(
    policy: nn.Module,
    obs: torch.Tensor,
    tgt: torch.Tensor,
) -> float:
    with torch.no_grad():
        logits, _ = policy.forward_eval(obs)
        got = logits.argmax(dim=-1)
    return float((got == tgt).float().mean().item())


def clone_from_tables(
    cells: list[tuple[dict, PrefixTable, int, float, int, int]],
    seed: int = 0,
) -> tuple[CultivationPolicy, dict]:
    """Distill H tables into a policy; returns it with fit stats."""
    torch.manual_seed(seed)
    obs, tgt = bc_dataset(cells)
    policy = CultivationPolicy()
    opt = torch.optim.Adam(policy.parameters(), lr=BC_LR)
    loss_fn = nn.CrossEntropyLoss()
    iters = 0
    for iters in range(1, BC_MAX_ITERS + 1):
        opt.zero_grad()
        logits, _ = policy.forward_eval(obs)
        loss = loss_fn(logits, tgt)
        loss.backward()
        opt.step()
        with torch.no_grad():
            got = logits.argmax(dim=-1)
            if bool((got == tgt).all()):
                break
    return policy, {
        "agreement": agreement(policy, obs, tgt),
        "samples": len(tgt),
        "iters": iters,
    }
