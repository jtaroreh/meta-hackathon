from __future__ import annotations

from typing import NamedTuple

import numpy as np
import torch
from torch import nn

from pursuit05.env import binomial_masses
from pursuit05.policy import CultivationPolicy, PrefixTable, obs_row

BC_LR = 1e-2
BC_MAX_ITERS = 5000


class BCTable(NamedTuple):
    pre: dict
    table: PrefixTable
    fth: int
    p: float
    stage_id: int
    rate_id: int


def _majority_accept_votes(
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
    cells: list[BCTable],
) -> tuple[torch.Tensor, torch.Tensor]:
    obs: list[list[float]] = []
    tgt: list[int] = []
    for entry in cells:
        t = entry.pre["T"]
        for (k, vals), abort in entry.table.items():
            if k >= t - 1:
                continue
            obs.append(
                obs_row(k, vals, entry.stage_id, entry.rate_id, t)
            )
            tgt.append(1 if abort else 0)
        got = _majority_accept_votes(entry.pre, entry.p, entry.fth)
        for vals, accept in got.items():
            obs.append(obs_row(t - 1, vals, entry.stage_id, entry.rate_id, t))
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
    cells: list[BCTable],
    seed: int = 0,
) -> tuple[CultivationPolicy, dict]:
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
            got = policy.forward_eval(obs)[0].argmax(dim=-1)
            if bool((got == tgt).all()):
                break
    return policy, {
        "agreement": agreement(policy, obs, tgt),
        "samples": len(tgt),
        "iters": iters,
    }
