"""Exact scoring of any decider with the screen's binomial accounting.

Data shape: pre from precompute is the frozen world. cw1 and cw2 hold
cumulative detector weights per checkpoint, fw1 and fw2 final weights,
nt2 the logical flag for pairs, spent the volume at each abort point,
Vf the full volume. A decider maps a prefix (k, cw[0..k]) to abort or
continue; final accept is an fw threshold in {0, 1, 2}. The all-zero
prefix always continues and is never presented to the decider.
"""

from __future__ import annotations

import time
from typing import NamedTuple, Protocol

import numpy as np

from pursuit05 import screen

_INDEX_KEY = "_pursuit05_prefix_index"


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
    return StaticDecider(tuple(ath), int(fth))


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
        abort = np.zeros(len(uniq), dtype=bool)
        for u, row in enumerate(uniq):
            if row.any():
                abort[u] = bool(decide(k, tuple(int(v) for v in row)))
        hit = abort[inv] & alive
        at[hit] = k
        alive[hit] = False
    return at


def eval_exact(decide, pre: dict, p: float) -> dict:
    fth = getattr(decide, "fth", None)
    if fth not in (0, 1, 2):
        raise ValueError(f"decider final threshold must be 0, 1, or 2, got {fth!r}")
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
    assert best is not None
    W, inf, pacc, ath, fth = best
    return StaticBest(
        ath=ath,
        fth=fth,
        result=ArmResult("S", W, inf, pacc, n, cost),
    )
