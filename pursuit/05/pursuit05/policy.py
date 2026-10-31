from __future__ import annotations

from typing import NamedTuple

import numpy as np
import pufferlib.pytorch
import torch
from torch import nn

OBS_SIZE = 7
HIDDEN_SIZE = 64
NUM_ACTIONS = 2


class CultivationPolicy(nn.Module):
    """Two-layer MLP policy over the flat abort observation."""

    def __init__(
        self,
        obs_size: int = OBS_SIZE,
        hidden_size: int = HIDDEN_SIZE,
        num_actions: int = NUM_ACTIONS,
    ) -> None:
        super().__init__()
        self.hidden_size = hidden_size
        self.encoder = nn.Sequential(
            nn.Linear(obs_size, hidden_size),
            nn.GELU(),
            nn.Linear(hidden_size, hidden_size),
            nn.GELU(),
        )
        self.decoder = pufferlib.pytorch.layer_init(
            nn.Linear(hidden_size, num_actions), std=0.01
        )
        self.value = pufferlib.pytorch.layer_init(
            nn.Linear(hidden_size, 1), std=1.0
        )

    def encode_observations(self, observations, state=None):
        batch_size = observations.shape[0]
        flat = observations.view(batch_size, -1).float()
        return self.encoder(flat)

    def decode_actions(self, hidden, state=None):
        return self.decoder(hidden), self.value(hidden)

    def forward_eval(self, observations, state=None):
        hidden = self.encode_observations(observations, state=state)
        return self.decode_actions(hidden, state=state)

    def forward(self, observations, state=None):
        return self.forward_eval(observations, state)


class TableDecider(NamedTuple):
    table: dict
    fth: int

    def __call__(self, k: int, prefix: tuple[int, ...]) -> bool:
        return bool(self.table[(k, tuple(prefix))])


def _obs_row(k: int, vals: tuple, stage_id: int, rate_id: int, t: int) -> list:
    return [float(k), *[float(v) for v in vals], *[0.0] * (3 - len(vals)),
            float(stage_id), float(rate_id), float(t)]


def decision_table(
    policy: nn.Module, pre: dict, *, stage_id: int, rate_id: int
) -> dict:
    """Map every distinct non-all-zero prefix to the policy action.

    Keys are (k, prefix) with k below T-1 for abort/continue and k of
    T-1 for final accept/reject. True aborts or accepts.
    """
    t = pre["T"]
    dev = next(policy.parameters()).device
    keys: list = []
    rows: list = []
    seen: set = set()
    for k in range(t - 1):
        for cw in (pre["cw1"], pre["cw2"]):
            for row in np.unique(cw[:, : k + 1], axis=0):
                vals = tuple(int(v) for v in row)
                if any(vals) and (k, vals) not in seen:
                    seen.add((k, vals))
                    keys.append((k, vals))
                    rows.append(_obs_row(k, vals, stage_id, rate_id, t))
    for cw in (pre["cw1"], pre["cw2"]):
        for row in np.unique(cw, axis=0):
            vals = tuple(int(v) for v in row)
            if any(vals) and (t - 1, vals) not in seen:
                seen.add((t - 1, vals))
                keys.append((t - 1, vals))
                rows.append(_obs_row(t - 1, vals, stage_id, rate_id, t))
    with torch.no_grad():
        obs = torch.as_tensor(np.asarray(rows, dtype=np.float32), device=dev)
        logits, _ = policy.forward_eval(obs)
        acts = logits.argmax(dim=-1).tolist()
    return {key: bool(a) for key, a in zip(keys, acts)}


def fit_final_threshold(table: dict, pre: dict, p: float) -> int:
    """Fit the fw threshold that best matches the table final actions.

    Agreement is weighted by trajectory mass. Ties take the lower
    threshold. All-zero histories are excluded; eval_exact always
    accepts them.
    """
    t = pre["T"]
    l1 = pre["L1"]
    n2 = len(pre["fw2"])
    big_l = float(l1)
    p1 = big_l * p * (1.0 - p) ** (big_l - 1.0) if l1 else 0.0
    p2 = (
        (big_l * (big_l - 1.0) / 2.0) * p**2 * (1.0 - p) ** (big_l - 2.0)
        if l1 >= 2
        else 0.0
    )
    acc: list = []
    fw: list = []
    wt: list = []
    for cw, fw_arr, mass, n in (
        (pre["cw1"], pre["fw1"], p1, l1),
        (pre["cw2"], pre["fw2"], p2, n2),
    ):
        if not n:
            continue
        unit = mass / n
        for r in range(n):
            vals = tuple(int(v) for v in cw[r])
            if not any(vals):
                continue
            acc.append(table[(t - 1, vals)])
            fw.append(int(fw_arr[r]))
            wt.append(unit)
    acc = np.asarray(acc, dtype=bool)
    fw = np.asarray(fw)
    wt = np.asarray(wt)
    best = 0
    best_agree = -1.0
    for fth in (0, 1, 2):
        agree = float(wt[acc == (fw <= fth)].sum())
        if agree > best_agree:
            best_agree = agree
            best = fth
    return best


def table_decider(table: dict, *, fth: int) -> TableDecider:
    if fth not in (0, 1, 2):
        raise ValueError(f"final threshold must be 0, 1, or 2, got {fth!r}")
    return TableDecider(table, int(fth))


def policy_decider(
    policy: nn.Module, pre: dict, p: float, *, stage_id: int, rate_id: int
) -> TableDecider:
    table = decision_table(policy, pre, stage_id=stage_id, rate_id=rate_id)
    return table_decider(table, fth=fit_final_threshold(table, pre, p))
