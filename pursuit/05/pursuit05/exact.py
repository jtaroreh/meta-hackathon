"""Exact scoring of any decider with the screen's binomial accounting.

Data shape: pre from precompute is the frozen world. cw1 and cw2 hold
cumulative detector weights per checkpoint, fw1 and fw2 final weights,
nt2 the logical flag for pairs, spent the volume at each abort point,
Vf the full volume. A decider maps a prefix (k, cw[0..k]) to abort
(True) or continue (False); final accept is an fw threshold in
{0, 1, 2}. The all-zero prefix always continues and is never presented
to the decider, and neither is a prefix no live trajectory reaches.
A decider must be pure and deterministic in (k, prefix): rows that
share a prefix share one call. Policies that condition on the cell
close over it per cell. Static thresholds match eval_policy exactly
for non-negative integer thresholds; negatives are rejected because
the screen aborts all-zero prefixes there while this harness
continues them. Scoring memoizes a private prefix index on pre.
"""

from __future__ import annotations

import numbers
import time
from typing import NamedTuple, Protocol

import numpy as np

from pursuit05 import screen

_INDEX_KEY = object()


class ArmResult(NamedTuple):
    arm: str
    W: float
    inf: float
    pacc: float
    n_evaluated: int
    inference_cost_s: float


class Decider(Protocol):
    fth: int

    def __call__(self, k: int, prefix: tuple[int, ...]) -> bool: ...


class StaticDecider(NamedTuple):
    ath: tuple[int, ...]
    fth: int

    def __call__(self, k: int, prefix: tuple[int, ...]) -> bool:
        return prefix[k] > self.ath[k]


class StaticBest(NamedTuple):
    ath: tuple[int, ...]
    fth: int
    result: ArmResult


def static_decider(ath: list[int] | tuple[int, ...], fth: int) -> StaticDecider:
    vals = tuple(ath)
    if any(not isinstance(v, numbers.Integral) or v < 0 for v in vals):
        raise ValueError(f"abort thresholds must be non-negative ints, got {vals!r}")
    if fth not in (0, 1, 2):
        raise ValueError(f"final threshold must be 0, 1, or 2, got {fth!r}")
    return StaticDecider(tuple(int(v) for v in vals), int(fth))


def _index_rows(cw: np.ndarray) -> list:
    per_k = []
    for k in range(cw.shape[1]):
        uniq, inv = np.unique(cw[:, : k + 1], axis=0, return_inverse=True)
        per_k.append((uniq, inv))
    return per_k


def _prefix_index(pre: dict) -> tuple:
    hit = pre.get(_INDEX_KEY)
    if hit is None:
        hit = (_index_rows(pre["cw1"]), _index_rows(pre["cw2"]))
        pre[_INDEX_KEY] = hit
    return hit


def _abort_masks(indexed: list, n_rows: int, decide) -> np.ndarray:
    at = np.full(n_rows, -1)
    alive = np.ones(n_rows, dtype=bool)
    for k, (uniq, inv) in enumerate(indexed):
        if not alive.any():
            break
        present = np.bincount(inv[alive], minlength=len(uniq)) > 0
        abort = np.zeros(len(uniq), dtype=bool)
        for u, row in enumerate(uniq):
            if present[u] and row.any():
                abort[u] = bool(decide(k, tuple(int(v) for v in row)))
        hit = abort[inv] & alive
        at[hit] = k
        alive[hit] = False
    return at


def eval_exact(decide, pre: dict, p: float) -> dict:
    fth = getattr(decide, "fth", None)
    if fth not in (0, 1, 2):
        raise ValueError(f"decider final threshold must be 0, 1, or 2, got {fth!r}")
    if isinstance(decide, StaticDecider) and len(decide.ath) != pre["T"] - 1:
        raise ValueError(
            f"abort thresholds need {pre['T'] - 1} entries, got {len(decide.ath)}"
        )
    Vf = pre["Vf"]
    L1 = pre["L1"]
    idx1, idx2 = _prefix_index(pre)
    a1 = _abort_masks(idx1, pre["cw1"].shape[0], decide)
    acc1 = (a1 < 0) & (pre["fw1"] <= fth)
    sp1 = np.where(a1 >= 0, pre["spent"][np.maximum(a1, 0)], Vf)
    a2 = _abort_masks(idx2, pre["cw2"].shape[0], decide)
    acc2 = (a2 < 0) & (pre["fw2"] <= fth)
    sp2 = np.where(a2 >= 0, pre["spent"][np.maximum(a2, 0)], Vf)
    L = float(L1)
    P0 = (1.0 - p) ** L
    P1 = L * p * (1.0 - p) ** (L - 1) if L1 else 0.0
    P2 = (L * (L - 1.0) / 2.0) * p**2 * (1.0 - p) ** (L - 2.0) if L1 >= 2 else 0.0
    Pt = max(0.0, 1.0 - P0 - P1 - P2)
    a1f = float(acc1.mean()) if L1 else 1.0
    v1 = float(sp1.mean()) if L1 else Vf
    a2f = float(acc2.mean()) if len(acc2) else 1.0
    v2 = float(sp2.mean()) if len(sp2) else Vf
    l2f = float((acc2 & pre["nt2"]).mean()) if len(acc2) else 0.0
    pacc = P0 + P1 * a1f + P2 * a2f
    E = P0 * Vf + P1 * v1 + P2 * v2 + Pt * Vf
    W = E / pacc - Vf if pacc > 0 else float("inf")
    inf = (P1 * a1f + P2 * l2f) / pacc if pacc > 0 else 1.0
    return {"W": float(W), "inf": float(inf), "pacc": float(pacc), "E": float(E)}


def best_static(pre: dict, p: float, f_inf: float) -> StaticBest:
    bound = f_inf * (1.0 + screen.INF_REL) + screen.INF_ABS
    start = time.perf_counter()
    best = None
    n = 0
    for ath, fth in screen.all_threshold_policies(pre["T"]):
        out = eval_exact(static_decider(ath, fth), pre, p)
        n += 1
        if out["inf"] <= bound and (best is None or out["W"] < best[0]):
            best = (out["W"], out["inf"], out["pacc"], tuple(ath), fth)
    cost = time.perf_counter() - start
    if best is None:
        raise ValueError(f"no static policy within infidelity bound {bound}")
    W, inf, pacc, ath, fth = best
    return StaticBest(
        ath=ath,
        fth=fth,
        result=ArmResult("S", W, inf, pacc, n, cost),
    )
