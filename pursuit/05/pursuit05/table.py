from __future__ import annotations

import math

import numpy as np

from pursuit05 import screen


def pooled(vals) -> dict:
    a = np.asarray(list(vals), dtype=float)
    if a.size == 0:
        return {"n": 0, "mean": None, "std": None, "se": None}
    m = float(a.mean())
    if a.size < 2:
        return {"n": int(a.size), "mean": m, "std": 0.0, "se": None}
    sd = float(a.std(ddof=1))
    return {"n": int(a.size), "mean": m, "std": sd, "se": sd / math.sqrt(a.size)}


def joint_win(
    pools_w: dict,
    pools_inf: dict,
    arm: str,
    base: str = "F",
    sse_arms: tuple = ("F", "G", "A"),
) -> bool:
    need = {arm, base} | set(sse_arms)
    for pools in (pools_w, pools_inf):
        for name in need:
            if name not in pools:
                raise KeyError(f"arm {name!r} missing from pools")
    if any(pools_w[a]["se"] is None or pools_w[a]["mean"] is None for a in need):
        return False
    if all(pools_inf[a]["se"] is not None for a in sse_arms):
        sse = math.sqrt(sum(pools_inf[a]["se"] ** 2 for a in sse_arms) / len(sse_arms))
    else:
        sse = None
    fmean = pools_w[base]["mean"]
    wpass = (
        fmean is not None
        and fmean > screen.MEANF_FLOOR
        and pools_w[arm]["mean"] is not None
        and (fmean - pools_w[arm]["mean"]) / fmean >= screen.WIN_RED
    )
    imean = pools_inf[arm]["mean"]
    bmean = pools_inf[base]["mean"]
    if imean is None or bmean is None:
        return False
    if sse is None:
        hpass = imean <= bmean
    else:
        hpass = imean <= bmean + 2.0 * sse
    return bool(wpass and hpass)


def render_arm_table(rows: list, arms: tuple) -> str:
    width = max([len("cell")] + [len(cid) for cid, _ in rows])
    head = [f"{'cell':<{width}}"]
    for arm in arms:
        head.append(f"{arm}_W".rjust(16))
        head.append(f"{arm}_inf".rjust(16))
    lines = [" ".join(head)]
    for cid, vals in rows:
        parts = [f"{cid:<{width}}"]
        for arm in arms:
            w, inf = vals[arm]
            parts.append(f"{w:16.10g}")
            parts.append(f"{inf:16.10g}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def render_regime(
    p: float, arms: tuple, pools_w: dict, pools_inf: dict, base: str = "F"
) -> str:
    bits = []
    for arm in arms:
        if arm == base:
            continue
        w = pools_w[arm]
        i = pools_inf[arm]
        won = joint_win(pools_w, pools_inf, arm, base)
        bits.append(
            f"{arm}: W={w['mean']:.10g} inf={i['mean']:.10g} "
            f"joint={'yes' if won else 'no'}"
        )
    return f"p={p} n={pools_w[base]['n']} " + "; ".join(bits)
