from __future__ import annotations

from typing import NamedTuple

import numpy as np
import pufferlib.pytorch
import torch
from torch import nn

from pursuit05.env import CW_COLS, OBS_SIZE, binomial_masses

HIDDEN_SIZE = 64
NUM_ACTIONS = 2

PrefixKey = tuple[int, tuple[int, ...]]
PrefixTable = dict[PrefixKey, bool]


class CultivationPolicy(nn.Module):
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
    table: PrefixTable
    fth: int

    def __call__(self, k: int, prefix: tuple[int, ...]) -> bool:
        return bool(self.table[(k, tuple(prefix))])


def _obs_row(k: int, vals: tuple, stage_id: int, rate_id: int, t: int) -> list:
    return [float(k), *[float(v) for v in vals], *[0.0] * (CW_COLS - len(vals)),
            float(stage_id), float(rate_id), float(t)]


def decision_table(
    policy: nn.Module, pre: dict, *, stage_id: int, rate_id: int
) -> PrefixTable:
    """Lower entries abort on True; T-1 entries are accept votes for fitting."""
    t = pre["T"]
    if t - 1 > CW_COLS:
        raise ValueError(f"T={t} exceeds {CW_COLS} cw columns")
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


def _survives(table: PrefixTable, cw: np.ndarray, r: int, t: int) -> bool:
    for k in range(t - 1):
        vals = tuple(int(v) for v in cw[r, : k + 1])
        if any(vals) and table[(k, vals)]:
            return False
    return True


def fit_final_threshold(table: PrefixTable, pre: dict, p: float) -> int:
    t = pre["T"]
    l1 = pre["L1"]
    n2 = len(pre["fw2"])
    _, p1, p2, _ = binomial_masses(l1, p)
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
            if not _survives(table, cw, r, t):
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


def table_decider(table: PrefixTable, *, fth: int) -> TableDecider:
    if fth not in (0, 1, 2):
        raise ValueError(f"final threshold must be 0, 1, or 2, got {fth!r}")
    return TableDecider(table, int(fth))
