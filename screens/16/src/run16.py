"""Screen 16 payload: Pauli-propagation and surrogate expectation-value
truncation (adaptive lookahead path-importance pruning).

Screen-authored bitwise Heisenberg-picture Pauli back-propagation
(stdlib + numpy only; no external physics, solver, or policy
libraries). Observables are back-propagated as X/Z-mask dicts
(Python ints) through Clifford layers (H/S/CNOT with exact sign
rules) plus non-Clifford Rz rotation layers (each branching doubles
strings) under per-layer depolarizing damping. Every arm replays the
SAME frozen seeded circuit per rep under a matched tracked-string
budget, so arm equivalence holds by construction. Metric is
mean-squared observable error vs a converged large-budget reference
at the matched string budget plus budget-validity verification
(tracked strings never exceed the cap). Arms: W static Pauli-weight
cutoff baseline, R random truncation control, G greedy
magnitude-cutoff scheduling, A adaptive lookahead path-importance
pruning. A bounded-exact Pauli-path search validates the tiny
instance (solved, optimum by enumeration) and cap-hits at target
scale (limit-expiry). Writes ALL output under cwd (the attempt work
dir): results.json plus witnesses/. Deterministic given seeds.
Verdict is always unresolved-with-reason; classification is
coordinator-side.
"""

import argparse
import json
import math
import os
import time

import numpy as np

N_QUBITS = 14
DEPTHS = (6, 12, 18)
SEEDS = (1, 2, 3, 4, 5)
ARMS = ("W", "R", "G", "A")
K_BUDGET = 64
K_REF = 8192
DEPOL_P = 0.01
N_INST = 16
LOOKAHEAD = 1
OBS_Q = 0
EXACT_CAP = 50000
WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0
TINY_N = 2
TINY_THETA = math.pi / 3.0
TINY_EXP = 0.5
TARGET = {"di": 2, "seed": 1, "rep": 0}
NEXT_EXPERIMENT = ("weight-aware damping reweighting + multi-observable "
                   "transfer retest")


def seed_rng(di, seed, rep, salt):
    return np.random.default_rng(
        (int(di * 100003 + seed * 10007 + rep * 101
             + salt * 1000003) % (2 ** 63 - 1)))


def gen_circuit(di, seed, rep):
    """Frozen seeded utility circuit: DEPTHS[di] layers, each a random
    Clifford sublayer (H/S/CNOT) plus a rotation sublayer (Rz angles,
    None means no rotation) followed by depolarizing noise.
    Deterministic given inputs; the same circuit object is replayed
    by the reference and every arm, so arm equivalence holds by
    construction."""
    depth = DEPTHS[di]
    rng = seed_rng(di, seed, rep, 21)
    nq = N_QUBITS
    layers = []
    for _li in range(depth):
        hqs = tuple(q for q in range(nq) if bool(rng.random() < 0.30))
        sqs = tuple(q for q in range(nq) if bool(rng.random() < 0.20))
        cnots = []
        for q in range(nq - 1):
            if bool(rng.random() < 0.40):
                cnots.append((q, q + 1))
        rots = []
        for _q in range(nq):
            if bool(rng.random() < 0.80):
                rots.append(float(rng.uniform(-math.pi, math.pi)))
            else:
                rots.append(None)
        layers.append({"h": hqs, "s": sqs, "cnot": tuple(cnots),
                       "rots": tuple(rots), "noise": True})
    return tuple(layers)


def tiny_setup():
    """Hand-checkable instance: 2 qubits, [H0, Rz0(pi/3), H0], no
    noise, observable Z0. Back-prop: Z0 ->H-> X0 ->Rz-> cos X0 +
    sin Y0 ->H-> cos Z0 - sin Y0, so exact expectation in |00> is
    cos(pi/3) = 0.5 by construction."""
    return ({"h": (0,), "s": (), "cnot": (),
             "rots": (None,) * TINY_N, "noise": False},
            {"h": (), "s": (), "cnot": (),
             "rots": (TINY_THETA,) + (None,) * (TINY_N - 1),
             "noise": False},
            {"h": (0,), "s": (), "cnot": (),
             "rots": (None,) * TINY_N, "noise": False})


def target_setup():
    return gen_circuit(TARGET["di"], TARGET["seed"], TARGET["rep"])


def wt_of(x_mask, z_mask):
    return bin(x_mask | z_mask).count("1")


def apply_h_step(in_x, in_z, in_sign, hq):
    """Single-H transition: logical roles use separate names (in_*
    input vs out_* result); never reuses one name for two roles."""
    bit = 1 << hq
    in_xq = bool(in_x & bit)
    in_zq = bool(in_z & bit)
    out_sign = -in_sign if (in_xq and in_zq) else in_sign
    if in_xq != in_zq:
        out_x = in_x ^ bit
        out_z = in_z ^ bit
    else:
        out_x = in_x
        out_z = in_z
    return out_x, out_z, out_sign


def apply_s_step(in_x, in_z, in_sign, sq):
    bit = 1 << sq
    in_xq = bool(in_x & bit)
    in_zq = bool(in_z & bit)
    out_sign = -in_sign if (in_xq and in_zq) else in_sign
    out_x = in_x
    out_z = in_z ^ bit if in_xq else in_z
    return out_x, out_z, out_sign


def apply_cnot_step(in_x, in_z, in_sign, cq, tq):
    cbit = 1 << cq
    tbit = 1 << tq
    ctrl_x = bool(in_x & cbit)
    ctrl_z = bool(in_z & cbit)
    targ_x = bool(in_x & tbit)
    targ_z = bool(in_z & tbit)
    flip = ctrl_x and targ_z and ((targ_x ^ ctrl_z) ^ 1)
    out_sign = -in_sign if flip else in_sign
    out_x = in_x ^ tbit if ctrl_x else in_x
    out_z = in_z ^ cbit if targ_z else in_z
    return out_x, out_z, out_sign


def apply_clifford_layer(dist, layer):
    """Clifford transition over a whole distribution: src_* names
    the read side, dst_* names the merged write side."""
    dst_accum = {}
    for src_key, src_coeff in dist.items():
        src_x, src_z = src_key
        run_x, run_z, run_sign = src_x, src_z, 1
        for hq in layer["h"]:
            run_x, run_z, run_sign = apply_h_step(run_x, run_z,
                                                  run_sign, hq)
        for sq in layer["s"]:
            run_x, run_z, run_sign = apply_s_step(run_x, run_z,
                                                  run_sign, sq)
        for cq, tq in layer["cnot"]:
            run_x, run_z, run_sign = apply_cnot_step(run_x, run_z,
                                                     run_sign, cq, tq)
        dst_key = (run_x, run_z)
        dst_accum[dst_key] = (dst_accum.get(dst_key, 0.0)
                              + run_sign * src_coeff)
    return dst_accum


def apply_rotation_layer(dist, rots):
    """Rz branching transition: keep_* names the cos child that
    preserves masks, fork_* names the sin child with the flipped
    Z bit; each is accumulated into its own entry, never reusing
    the input coefficient name for a child role."""
    dst_accum = {}
    for src_key, src_coeff in dist.items():
        src_x, src_z = src_key
        pending = [(src_x, src_z, src_coeff)]
        for rq, ang in enumerate(rots):
            if ang is None:
                continue
            bit = 1 << rq
            if not (src_x & bit):
                continue
            cos_w = math.cos(ang)
            sin_w = math.sin(ang)
            if sin_w == 0.0:
                if cos_w != 1.0:
                    pending = [(px, pz, pc * cos_w)
                               for px, pz, pc in pending]
                continue
            next_pending = []
            for pend_x, pend_z, pend_c in pending:
                if pend_x & bit:
                    keep_c = pend_c * cos_w
                    if keep_c != 0.0:
                        next_pending.append((pend_x, pend_z, keep_c))
                    fork_z = pend_z ^ bit
                    fork_c = (pend_c * sin_w
                              if not (pend_z & bit)
                              else -pend_c * sin_w)
                    if fork_c != 0.0:
                        next_pending.append((pend_x, fork_z, fork_c))
                else:
                    next_pending.append((pend_x, pend_z, pend_c))
            pending = next_pending
        for pend_x, pend_z, pend_c in pending:
            if pend_c == 0.0:
                continue
            dst_key = (pend_x, pend_z)
            dst_accum[dst_key] = dst_accum.get(dst_key, 0.0) + pend_c
    return dst_accum


def apply_noise_layer(dist, prob):
    """Depolarizing damping transition: undamped_* names the read
    coefficient, damped_* names the written coefficient."""
    if prob == 0.0:
        return dict(dist)
    dst_damped = {}
    for dst_key, undamped_c in dist.items():
        str_w = wt_of(*dst_key)
        damped_c = undamped_c * ((1.0 - prob) ** str_w)
        if damped_c != 0.0:
            dst_damped[dst_key] = damped_c
    return dst_damped


def expectation_of(dist):
    """Expectation of the back-propagated observable in |0...0>:
    only diagonal (x_mask == 0) strings contribute, each +coeff."""
    total = 0.0
    for (ex_x, _ex_z), ex_c in dist.items():
        if ex_x == 0:
            total += ex_c
    return total


def _select_topk(dist, prim_of, cap):
    """Shared top-K selection: one pass builds the primary key
    (lower wins) plus mask arrays, then a single lexsort orders by
    (primary, x_mask, z_mask) — O(n log n) only in C, fully
    deterministic including ties. Repair path: n <= cap keeps
    everything."""
    n_all = len(dist)
    if n_all <= cap:
        return dict(dist)
    sel_x = np.empty(n_all, dtype=np.int64)
    sel_z = np.empty(n_all, dtype=np.int64)
    sel_p = np.empty(n_all, dtype=np.float64)
    sel_v = [None] * n_all
    for i, (sel_k, sel_c) in enumerate(dist.items()):
        sel_x[i] = sel_k[0]
        sel_z[i] = sel_k[1]
        sel_p[i] = prim_of(sel_k, sel_c)
        sel_v[i] = sel_c
    take = np.lexsort((sel_z, sel_x, sel_p))[:cap]
    return {(int(sel_x[i]), int(sel_z[i])): sel_v[i] for i in take}


def trunc_weight(dist, cap, _ctx):
    """W static baseline: keep the lowest Pauli-weight strings;
    ties broken by mask order (deterministic, magnitude-blind)."""
    return _select_topk(dist, lambda wk, _wv: float(wt_of(*wk)),
                        cap)


def trunc_random(dist, cap, ctx):
    """R random control: seeded random keep-set under the matched
    string budget (repair path: cap >= n keeps everything)."""
    if len(dist) <= cap:
        return dict(dist)
    pick_rng = ctx["rng"]
    keys = list(dist.keys())
    take = pick_rng.choice(len(keys), size=cap, replace=False)
    return {keys[int(i)]: dist[keys[int(i)]] for i in take}


def trunc_magnitude(dist, cap, _ctx):
    """G greedy magnitude scheduling: keep the largest-|coeff|
    strings; ties broken by mask order (deterministic)."""
    return _select_topk(dist, lambda _gk, gv: -abs(gv), cap)


def lookahead_score(sco_x, sco_z, sco_c, next_rots, prob):
    """One-step path-importance score: |coeff| times the damped
    next-layer branch mass (product of |cos|+|sin| over rotated
    X-bearing qubits), peeking LOOKAHEAD layers ahead."""
    str_w = wt_of(sco_x, sco_z)
    damp_f = (1.0 - prob) ** str_w
    mass_f = 1.0
    for lq, lang in enumerate(next_rots):
        if lang is None or not (sco_x & (1 << lq)):
            continue
        mass_f *= abs(math.cos(lang)) + abs(math.sin(lang))
    return abs(sco_c) * damp_f * mass_f


def trunc_lookahead(dist, cap, ctx):
    """A adaptive lookahead path-importance pruning: score every
    string by its damped next-layer branch mass and keep the top
    scorers; carries the original strings forward (never the
    scored children), so selection adapts to upcoming rotations
    while the propagated state stays exact pre-truncation."""
    next_rots = ctx["next_rots"]
    prob = ctx["prob"]

    def prim_of(lk, lv):
        return -lookahead_score(lk[0], lk[1], lv, next_rots,
                                prob)

    return _select_topk(dist, prim_of, cap)


def empty_stats(stopped):
    return {"est": None, "mse": None, "stopped": bool(stopped),
            "max_tracked": 0, "valid": False, "n_dropped": 0}


def propagate(layers, cap, policy, ctx, stop, nq):
    """Back-propagate Z on OBS_Q from the final layer to the
    initial state. Stage roles use separate names: work_dist is
    the live distribution, layer_out the post-gate result,
    kept_dist the post-truncation result; the truncation cursor
    track_peak records the pre-truncation size (budget check uses
    the kept size). Returns est + stopped + max_tracked."""
    work_dist = {(0, 1 << OBS_Q): 1.0}
    peak_kept = len(work_dist)
    total_dropped = 0
    n_layers = len(layers)
    for li in range(n_layers - 1, -1, -1):
        if stop is not None and stop():
            return {"est": None, "mse": None, "stopped": True,
                    "max_tracked": peak_kept, "valid": False,
                    "n_dropped": total_dropped}
        layer = layers[li]
        layer_out = apply_clifford_layer(work_dist, layer)
        layer_out = apply_rotation_layer(layer_out, layer["rots"])
        if layer.get("noise"):
            layer_out = apply_noise_layer(layer_out, DEPOL_P)
        if len(layer_out) > cap:
            total_dropped += len(layer_out) - cap
            if li > 0:
                peek_rots = layers[li - LOOKAHEAD]["rots"]
            else:
                peek_rots = tuple(None for _q in range(nq))
            kept_dist = policy(layer_out, cap,
                               {"rng": ctx.get("rng"),
                                "next_rots": peek_rots,
                                "prob": (DEPOL_P if layers[li - 1].get(
                                    "noise") and li > 0 else 0.0)})
        else:
            kept_dist = layer_out
        if len(kept_dist) > peak_kept:
            peak_kept = len(kept_dist)
        work_dist = kept_dist
    return {"est": expectation_of(work_dist), "mse": None,
            "stopped": False, "max_tracked": peak_kept,
            "valid": peak_kept <= cap, "n_dropped": total_dropped}


POLICIES = {"W": trunc_weight, "R": trunc_random,
            "G": trunc_magnitude, "A": trunc_lookahead}


def run_arm(di, seed, rep, arm, circuit, stop):
    """One arm evaluation on one frozen circuit under the matched
    string budget K_BUDGET. The policy context rng is reseeded per
    rep (R only consumes it), so arm equivalence holds."""
    ctx = {"rng": seed_rng(di, seed, rep, 901)}
    return propagate(circuit, K_BUDGET, POLICIES[arm], ctx, stop,
                     N_QUBITS)


def run_ref(di, seed, rep, circuit, stop):
    """Converged large-budget reference: magnitude-kept
    propagation at K_REF (no matched-budget truncation). Records
    n_dropped as the convergence witness (zero means the reference
    never truncated, hence exact)."""
    ctx = {"rng": seed_rng(di, seed, rep, 901)}
    out = propagate(circuit, K_REF, trunc_magnitude, ctx, stop,
                    N_QUBITS)
    return out


def run_tiny_arm(arm, circuit, stop):
    ctx = {"rng": seed_rng(0, 7, 7, 901)}
    return propagate(circuit, K_BUDGET, POLICIES[arm], ctx, stop,
                     TINY_N)


def exact_opt(layers, nq, cap, stop):
    """Bounded-exact Pauli-path search: exhaustive DFS over
    Rz-branch children (Cliffords carry the single path forward),
    accumulating the exact |0> expectation over leaf paths.
    Parent vs child roles use separate names (path_* vs
    child_*); every visit counts one node until the cap.
    Statuses solved / cap-hit / stopped-guard."""
    nodes = [0]
    capped = [False]
    stopped = [False]
    total = [0.0]

    def rec(li, path_x, path_z, path_c):
        if capped[0] or stopped[0]:
            return
        nodes[0] += 1
        if nodes[0] > cap:
            capped[0] = True
            return
        if nodes[0] % 512 == 0 and stop is not None and stop():
            stopped[0] = True
            return
        if li < 0:
            if path_x == 0:
                total[0] += path_c
            return
        layer = layers[li]
        run_x, run_z, run_sign = path_x, path_z, 1
        for hq in layer["h"]:
            run_x, run_z, run_sign = apply_h_step(run_x, run_z,
                                                  run_sign, hq)
        for sq in layer["s"]:
            run_x, run_z, run_sign = apply_s_step(run_x, run_z,
                                                  run_sign, sq)
        for cq, tq in layer["cnot"]:
            run_x, run_z, run_sign = apply_cnot_step(run_x, run_z,
                                                     run_sign, cq,
                                                     tq)
        mid_c = path_c * run_sign
        branch_rots = [(rq, ang) for rq, ang in
                       enumerate(layer["rots"])
                       if ang is not None and (run_x & (1 << rq))]
        stack = [(run_x, run_z, mid_c)]
        for branch_q, branch_ang in branch_rots:
            branch_cos = math.cos(branch_ang)
            branch_sin = math.sin(branch_ang)
            if branch_sin == 0.0:
                stack = [(st_x, st_z, st_c * branch_cos)
                         for st_x, st_z, st_c in stack]
                continue
            grown = []
            for st_x, st_z, st_c in stack:
                grown.append((st_x, st_z, st_c * branch_cos))
                fork_z = st_z ^ (1 << branch_q)
                fork_c = (st_c * branch_sin
                          if not (st_z & (1 << branch_q))
                          else -st_c * branch_sin)
                grown.append((st_x, fork_z, fork_c))
            stack = grown
        for child_x, child_z, child_c in stack:
            if child_c == 0.0:
                continue
            rec(li - 1, child_x, child_z, child_c)
            if capped[0] or stopped[0]:
                return

    rec(len(layers) - 1, 0, 1 << OBS_Q, 1.0)
    if stopped[0]:
        return {"status": "stopped-guard", "nodes": nodes[0],
                "opt": total[0], "cap": cap, "started": True}
    if capped[0]:
        return {"status": "cap-hit", "nodes": nodes[0],
                "opt": total[0], "cap": cap, "started": True}
    return {"status": "solved", "nodes": nodes[0],
            "opt": total[0], "cap": cap, "started": True}


def audit_gen(di, seed, rep):
    circ = gen_circuit(di, seed, rep)
    nq = N_QUBITS
    ok = (len(circ) == DEPTHS[di]
          and all(set(lay.keys()) == {"h", "s", "cnot", "rots",
                                      "noise"} for lay in circ))
    if not ok:
        return False, circ
    for lay in circ:
        if not (all(0 <= q < nq for q in lay["h"])
                and all(0 <= q < nq for q in lay["s"])
                and all(0 <= c < nq and 0 <= t < nq and c != t
                        for c, t in lay["cnot"])
                and len(lay["rots"]) == nq
                and all(a is None or -math.pi <= a <= math.pi
                        for a in lay["rots"])):
            return False, circ
    return True, circ


def self_tests():
    out = {"ran": True, "failed": []}
    try:
        for di in range(len(DEPTHS)):
            for rep in (0, 1):
                ok, _c = audit_gen(di, 1, rep)
                if not ok:
                    out["failed"].append("gen-%d-%d" % (di, rep))
        _ok, g1 = audit_gen(0, 1, 0)
        _ok, g1b = audit_gen(0, 1, 0)
        if g1 != g1b:
            out["failed"].append("gen-determinism")
        tiny_circ = tiny_setup()
        if len(tiny_circ) != 3 or TINY_N != 2:
            out["failed"].append("tiny-fixture")
        for arm in ARMS:
            tm = run_tiny_arm(arm, tiny_circ, None)
            if (tm["stopped"] or not tm["valid"]
                    or tm["est"] is None
                    or abs(tm["est"] - TINY_EXP) > 1e-9):
                out["failed"].append("tiny-hand-%s: %r" % (arm, tm))
        tref = propagate(tiny_circ, K_REF, trunc_magnitude,
                         {"rng": seed_rng(0, 7, 7, 901)}, None,
                         TINY_N)
        if (tref["stopped"] or tref["n_dropped"] != 0
                or abs(tref["est"] - TINY_EXP) > 1e-9):
            out["failed"].append("tiny-ref-exact: %r" % (tref,))
        tex = exact_opt(tiny_circ, TINY_N, EXACT_CAP, None)
        if (tex["status"] != "solved"
                or abs(tex["opt"] - TINY_EXP) > 1e-9):
            out["failed"].append("tiny-exact-opt: %r" % (tex,))
        hx, hz, hs = apply_h_step(0, 1, 1, 0)
        if (hx, hz, hs) != (1, 0, 1):
            out["failed"].append("clifford-H-Z: %r" % ((hx, hz, hs),))
        yx, yz, ys = apply_h_step(1, 1, 1, 0)
        if (yx, yz, ys) != (1, 1, -1):
            out["failed"].append("clifford-H-Y: %r" % ((yx, yz, ys),))
        sx, sz, ss = apply_s_step(1, 0, 1, 0)
        if (sx, sz, ss) != (1, 1, 1):
            out["failed"].append("clifford-S-X: %r" % ((sx, sz, ss),))
        syx, syz, sys = apply_s_step(1, 1, 1, 0)
        if (syx, syz, sys) != (1, 0, -1):
            out["failed"].append("clifford-S-Y: %r"
                                 % ((syx, syz, sys),))
        cxx, cxz, cxs = apply_cnot_step(1, 0, 1, 0, 1)
        if (cxx, cxz, cxs) != (3, 0, 1):
            out["failed"].append("clifford-CNOT-XI: %r"
                                 % ((cxx, cxz, cxs),))
        rz_out = apply_rotation_layer(
            {(1, 0): 1.0}, (TINY_THETA,) + (None,) * (TINY_N - 1))
        if (len(rz_out) != 2
                or abs(rz_out.get((1, 0), 0.0)
                       - math.cos(TINY_THETA)) > 1e-12
                or abs(rz_out.get((1, 1), 0.0)
                       - math.sin(TINY_THETA)) > 1e-12):
            out["failed"].append("rz-branch: %r" % (rz_out,))
        damp_out = apply_noise_layer({(3, 0): 1.0}, 0.10)
        if abs(damp_out.get((3, 0), 0.0) - 0.9 ** 2) > 1e-12:
            out["failed"].append("damping-w2: %r" % (damp_out,))
        fix_ctx = {"rng": seed_rng(0, 0, 0, 901),
                   "next_rots": (None,) * N_QUBITS, "prob": 0.0}
        for pname, pfn in (("W", trunc_weight), ("R", trunc_random),
                           ("G", trunc_magnitude),
                           ("A", trunc_lookahead)):
            if pfn({}, 4, dict(fix_ctx)) != {}:
                out["failed"].append("trunc-empty-%s" % pname)
        small = {(1, 0): 0.5, (0, 2): -0.25}
        for pname, pfn in (("W", trunc_weight), ("R", trunc_random),
                           ("G", trunc_magnitude),
                           ("A", trunc_lookahead)):
            if pfn(dict(small), 8, dict(fix_ctx)) != small:
                out["failed"].append("trunc-nocap-%s" % pname)
        skew = {(7, 0): 100.0, (1, 0): 0.01}
        if set(trunc_weight(dict(skew), 1, dict(fix_ctx))) != {
                (1, 0)}:
            out["failed"].append("trunc-W-blind: %r"
                                 % (trunc_weight(dict(skew), 1,
                                                 dict(fix_ctx)),))
        if set(trunc_magnitude(dict(skew), 1, dict(fix_ctx))) != {
                (7, 0)}:
            out["failed"].append("trunc-G-mag")
        big = {(x, 0): float(x + 1) for x in range(20)}
        for pname, pfn in (("W", trunc_weight), ("R", trunc_random),
                           ("G", trunc_magnitude),
                           ("A", trunc_lookahead)):
            kept = pfn(dict(big), 5, dict(fix_ctx))
            if len(kept) != 5 or not set(kept) <= set(big):
                out["failed"].append("trunc-cap-%s: %r" % (pname,
                                                           kept))
        r1 = trunc_random(dict(big), 5, {"rng": seed_rng(0, 0, 0, 901),
                                              "next_rots": (None,) * 14,
                                              "prob": 0.0})
        r2 = trunc_random(dict(big), 5, {"rng": seed_rng(0, 0, 0, 901),
                                              "next_rots": (None,) * 14,
                                              "prob": 0.0})
        if r1 != r2:
            out["failed"].append("trunc-R-determinism")
        ahead_dist = {(1, 0): 1.0, (2, 0): 1.0}
        ahead_ctx = {"rng": seed_rng(0, 0, 0, 901),
                     "next_rots": (0.0, math.pi / 4.0) + (None,) * 12,
                     "prob": 0.0}
        ahead_kept = trunc_lookahead(dict(ahead_dist), 1, ahead_ctx)
        if set(ahead_kept) != {(2, 0)}:
            out["failed"].append("trunc-A-lookahead: %r"
                                 % (ahead_kept,))
        for di, seed in ((0, 1), (2, 3)):
            _ok, dg = audit_gen(di, seed, 0)
            for arm in ARMS:
                rr = run_arm(di, seed, 0, arm, dg, None)
                if (rr["stopped"] or rr["est"] is None
                        or not rr["valid"]
                        or rr["max_tracked"] > K_BUDGET):
                    out["failed"].append(
                        "arm-valid-%s-%d-%d: %r" % (arm, di, seed,
                                                   rr))
            rf = run_ref(di, seed, 0, dg, None)
            if rf["stopped"] or rf["est"] is None:
                out["failed"].append("ref-valid-%d-%d: %r"
                                     % (di, seed, rf))
            ga = run_arm(di, seed, 0, "G", dg, None)
            ga2 = run_arm(di, seed, 0, "G", dg, None)
            if ga["est"] != ga2["est"]:
                out["failed"].append("determinism-greedy")
            ra = run_arm(di, seed, 0, "R", dg, None)
            ra2 = run_arm(di, seed, 0, "R", dg, None)
            if ra["est"] != ra2["est"]:
                out["failed"].append("determinism-random")
        _ok, dag = audit_gen(1, 1, 0)
        for arm in ARMS:
            if not run_arm(1, 1, 0, arm, dag,
                           lambda: True).get("stopped"):
                out["failed"].append("stop-propagation-%s" % arm)
        if not run_ref(1, 1, 0, dag, lambda: True).get("stopped"):
            out["failed"].append("stop-propagation-ref")
        tsize = target_setup()
        stx = exact_opt(tsize, N_QUBITS, EXACT_CAP, lambda: True)
        if stx["status"] != "stopped-guard":
            out["failed"].append("stop-propagation-exact: %r"
                                 % (stx,))
        toks = ["mi" + "lp", "sm" + "t", "ols" + "qa",
                "vand" + "aele", "l" + "au", "phasep" + "oly",
                "to" + "rch"]
        import pathlib as _pl
        src = _pl.Path(__file__).read_text().lower()
        for tok in toks:
            if tok in src:
                out["failed"].append("forbidden-lib-%s" % tok)
    except Exception as ex:
        out["failed"].append("raise: %r" % ex)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--attempt", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--n-inst", type=int, default=N_INST)
    args = ap.parse_args()
    n_inst = int(args.n_inst)
    outdir = os.getcwd()
    witdir = os.path.join(outdir, "witnesses")
    os.makedirs(witdir, exist_ok=True)
    t0 = time.perf_counter()

    def elapsed():
        return time.perf_counter() - t0

    def over():
        return elapsed() > WALL_GUARD_S

    cells = {}
    cellrecs = []
    skipped = []
    ref_exact_hits = [0, 0]
    gate3tiny = {"arms": {}, "solved": 0, "total": 0}
    gate3targets = []
    selftest = self_tests()
    with open(os.path.join(witdir, "selftest.json"), "w") as f:
        json.dump(selftest, f, indent=1, default=str)

    def checkpoint(tag):
        try:
            with open(os.path.join(witdir, "checkpoint-%s.json" % tag),
                      "w") as f:
                json.dump({"tag": tag, "wall_s": elapsed(),
                           "n_cells": len(cells),
                           "gate3tiny": gate3tiny,
                           "gate3targets": gate3targets,
                           "n_skipped": len(skipped),
                           "verdict": "unresolved-with-reason: partial "
                                      "checkpoint"}, f, indent=1,
                          default=str)
        except Exception:
            pass

    tiny_ok = bool(selftest.get("ran")) and not selftest.get("failed")

    if over():
        gate3tiny["arms"]["tiny"] = {"status": "skipped-guard"}
        skipped.append({"what": "tiny-exact", "reason": "wall-guard",
                        "iters_done": 0, "n_evaluated": EXACT_CAP})
    else:
        tiny_circ = tiny_setup()
        ex = exact_opt(tiny_circ, TINY_N, EXACT_CAP, over)
        gate3tiny["arms"]["tiny"] = ex
        gate3tiny["total"] += 1
        if ex["status"] == "solved" and abs(ex["opt"] - TINY_EXP) < 1e-9:
            gate3tiny["solved"] += 1
        if ex["status"] == "stopped-guard":
            skipped.append({"what": "tiny-exact",
                            "reason": "stopped-guard",
                            "iters_done": ex.get("nodes", 0),
                            "n_evaluated": EXACT_CAP})
    with open(os.path.join(witdir, "gate3_tiny.json"), "w") as f:
        json.dump(gate3tiny, f, indent=1, default=str)
    checkpoint("tiny")

    if over():
        gate3targets.append({"status": "skipped-guard"})
        skipped.append({"what": "target-exact", "reason": "wall-guard",
                        "iters_done": 0, "n_evaluated": EXACT_CAP})
    else:
        tsize = target_setup()
        tex = exact_opt(tsize, N_QUBITS, EXACT_CAP, over)
        gate3targets.append(dict(tex, di=TARGET["di"],
                                 seed=TARGET["seed"],
                                 rep=TARGET["rep"]))
        if tex["status"] == "stopped-guard":
            skipped.append({"what": "target-exact",
                            "reason": "stopped-guard",
                            "iters_done": tex.get("nodes", 0),
                            "n_evaluated": EXACT_CAP})
    with open(os.path.join(witdir, "gate3_targets.json"), "w") as f:
        json.dump(gate3targets, f, indent=1, default=str)
    checkpoint("targets")

    def run_cell(di, seed):
        rec = {"depth": DEPTHS[di], "seed": seed, "arms": {}}
        for arm in ARMS:
            if over():
                rec["blocked"] = "wall-guard"
                return rec
            mses, evs, peak = [], [], 0
            nstop = 0
            nvalid = 0
            for rep in range(n_inst):
                if rep % 32 == 0 and over():
                    nstop += 1
                    break
                circ = gen_circuit(di, seed, rep)
                ref = run_ref(di, seed, rep, circ, over)
                if ref.get("stopped") or ref["est"] is None:
                    nstop += 1
                    break
                if ref.get("n_dropped", 1) == 0:
                    ref_exact_hits[0] += 1
                ref_exact_hits[1] += 1
                out = run_arm(di, seed, rep, arm, circ, over)
                if out.get("stopped") or out["est"] is None:
                    nstop += 1
                    break
                mses.append((out["est"] - ref["est"]) ** 2)
                evs.append(out["est"])
                if out.get("valid"):
                    nvalid += 1
                if out.get("max_tracked", 0) > peak:
                    peak = out["max_tracked"]
            if nstop:
                rec["blocked"] = "stopped-guard"
                rec["iters_done"] = len(mses)
                rec["n_evaluated"] = n_inst
                return rec
            rec["arms"][arm] = {
                "n": len(mses),
                "mse": pooled_stats(mses),
                "est": pooled_stats(evs),
                "n_valid": int(nvalid),
                "frac_valid": (nvalid / len(mses) if mses else 0.0),
                "peak_tracked": int(peak)}
        return rec

    def record_cell(rec):
        if rec.get("blocked") is None and all(
                rec["arms"].get(a, {}).get("n") == n_inst
                for a in ARMS):
            for a in ARMS:
                key = (rec["depth"], rec["seed"], a)
                cells.setdefault(key, {"mse": [], "valid": [],
                                       "peak": []})
                cells[key]["mse"].append(
                    rec["arms"][a]["mse"]["mean"])
                cells[key]["valid"].append(
                    rec["arms"][a]["frac_valid"])
                cells[key]["peak"].append(
                    rec["arms"][a]["peak_tracked"])
            cellrecs.append(rec)
            return True
        cellrecs.append(rec)
        skipped.append({"what": "cell %s/%s" % (
            rec["depth"], rec["seed"]),
            "reason": rec.get("blocked", "arm-incomplete"),
            "iters_done": rec.get("iters_done", 0),
            "n_evaluated": n_inst})
        return False

    for di, depth in enumerate(DEPTHS):
        if over():
            for sd in SEEDS:
                skipped.append({"what": "cell %s/%s" % (depth, sd),
                                "reason": "wall-guard",
                                "iters_done": 0,
                                "n_evaluated": n_inst})
        else:
            for sd in SEEDS:
                if over():
                    skipped.append({"what": "cell %s/%s" % (depth, sd),
                                    "reason": "wall-guard",
                                    "iters_done": 0,
                                    "n_evaluated": n_inst})
                    continue
                rec = run_cell(di, sd)
                record_cell(rec)
        with open(os.path.join(witdir, "cells.json"), "w") as f:
            json.dump(cellrecs, f, indent=1, default=str)
        checkpoint("depth%d" % di)
    with open(os.path.join(witdir, "cells.json"), "w") as f:
        json.dump(cellrecs, f, indent=1, default=str)
    checkpoint("corpus")

    def cell_mean(di, seed, arm, field):
        return cells.get((DEPTHS[di], seed, arm),
                         {"mse": [], "valid": [],
                          "peak": []})[field]

    def pool(di, arm, field):
        vals = []
        for seed in SEEDS:
            vals.extend(cell_mean(di, seed, arm, field))
        return pooled_stats(vals), len(vals) == len(SEEDS)

    det_g1 = run_arm(0, 1, 0, "G", gen_circuit(0, 1, 0), None)
    det_g2 = run_arm(0, 1, 0, "G", gen_circuit(0, 1, 0), None)
    det_r1 = run_arm(0, 1, 0, "R", gen_circuit(0, 1, 0), None)
    det_r2 = run_arm(0, 1, 0, "R", gen_circuit(0, 1, 0), None)
    determinism_ok = bool(
        det_g1["est"] == det_g2["est"]
        and det_r1["est"] == det_r2["est"])

    g1_cells, g1_beats = [], True
    for di, depth in enumerate(DEPTHS):
        for seed in SEEDS:
            ms = cell_mean(di, seed, "G", "mse")
            mr = cell_mean(di, seed, "R", "mse")
            ok = (len(ms) == 1 and len(mr) == 1
                  and ms[0] is not None and mr[0] is not None
                  and ms[0] < mr[0])
            g1_cells.append({"cell": "%s/%s" % (depth, seed),
                             "mean_G": ms[0] if ms else None,
                             "mean_R": mr[0] if mr else None,
                             "pass": bool(ok)})
            if not ok:
                g1_beats = False
    g1_ok = bool(g1_beats and tiny_ok and determinism_ok)

    g2_fams, g2_n = [], 0
    win_fams = []
    n_win = {"G": 0, "A": 0}
    n_strict = 0
    pools_all = True
    for di, depth in enumerate(DEPTHS):
        pools, pok = {}, True
        for arm in ("W", "G", "A"):
            pools[arm], oka = pool(di, arm, "mse")
            pok = pok and oka
        se, spread, gp = spread_win(pools, pok)
        g2_fams.append({"depth": depth, "pools": pools, "SE": se,
                        "spread": spread, "pass": bool(gp)})
        if gp:
            g2_n += 1
        joint = {}
        if pok and all(
                pools[a]["se"] is not None and
                pools[a]["mean"] is not None for a in ("W", "G",
                                                      "A")):
            sse2 = math.sqrt(sum(pools[a]["se"] ** 2
                                 for a in ("W", "G", "A")) / 3.0)
            for a in ("G", "A"):
                mwin = pools[a]["mean"] < pools["W"]["mean"] - \
                    2.0 * sse2
                vpools = pooled_stats(
                    [v for seed in SEEDS
                     for v in cell_mean(di, seed, a, "valid")])
                vpool_w = pooled_stats(
                    [v for seed in SEEDS
                     for v in cell_mean(di, seed, "W", "valid")])
                vwin = (vpools["mean"] is not None
                        and vpool_w["mean"] is not None
                        and vpools["mean"] >= vpool_w["mean"])
                joint[a] = bool(mwin and vwin)
        else:
            joint = {"G": False, "A": False}
        for a in ("G", "A"):
            if joint[a]:
                n_win[a] += 1
        if pok and all(pools[a]["mean"] is not None
                       for a in ("W", "G", "A")):
            spass = (pools["G"]["mean"] < pools["W"]["mean"] or
                     pools["A"]["mean"] < pools["W"]["mean"])
        else:
            spass = False
            pools_all = False
        if not pok:
            pools_all = False
        if spass:
            n_strict += 1
        win_fams.append({"depth": depth, "joint": dict(joint),
                         "strict_win": bool(spass),
                         "pools_ok": bool(pok)})
    g2_ok = g2_n >= 2

    tiny_solved = (gate3tiny["total"] == 1 and gate3tiny["solved"] == 1)
    target_cap = (len(gate3targets) == 1 and
                  gate3targets[0].get("status") == "cap-hit")
    g3pass = bool(tiny_solved and target_cap)

    complete = all(
        len(cell_mean(di, seed, arm, "mse")) == 1
        for di in range(len(DEPTHS)) for seed in SEEDS
        for arm in ARMS)
    tiny_attempted = gate3tiny["total"] == 1
    targets_attempted = len(gate3targets) == 1
    wall = elapsed()
    clean = len(skipped) == 0
    g4_ok = bool(complete and tiny_attempted and targets_attempted
                 and wall < WALL_LIMIT_S and clean)

    selftest_ok = bool(tiny_ok)
    pursue = (max(n_win["G"], n_win["A"]) >= 2 and g1_ok and g2_ok
              and g3pass and g4_ok and selftest_ok)
    reject = (complete and tiny_solved and g1_ok and
              pools_all and n_strict == 0)
    if pursue:
        reason = ("PURSUE-condition holds (joint MSE win with "
                  "matched-or-better validity on the SAME arm at "
                  ">=2 depths + gates 1,2,3,4 + self-tests ok); "
                  "payload verdict stays unresolved-with-reason, "
                  "classification is coordinator-side.")
    elif reject:
        reason = ("REJECT-condition holds (complete cells, tiny "
                  "solved, Gate-1 controls pass, no strict pooled "
                  "MSE win at any depth); payload verdict stays "
                  "unresolved-with-reason, classification is "
                  "coordinator-side.")
    else:
        reason = ("UNRESOLVED + next experiment (joint wins G=%d/3, "
                  "A=%d/3, strict wins=%d/3, g1=%s g2=%s "
                  "g3=%s (tiny solved=%s, target "
                  "cap-hit=%s) selftest=%s g4=%s complete=%s skipped=%d; "
                  "next: %s)." % (
                      n_win["G"], n_win["A"], n_strict, g1_ok, g2_ok,
                      g3pass, tiny_solved, target_cap,
                      selftest_ok, g4_ok, complete, len(skipped),
                      NEXT_EXPERIMENT))
    verdict_bits = {
        "gate1": {"pass": bool(g1_ok), "beats_all_15": bool(g1_beats),
                  "tiny_ok": bool(tiny_ok),
                  "determinism_ok": bool(determinism_ok),
                  "cells": g1_cells},
        "gate2": {"pass": bool(g2_ok), "n_depths_pass": g2_n,
                  "depths": g2_fams},
        "gate3": {"pass": bool(g3pass), "tiny_solved": tiny_solved,
                  "tiny": gate3tiny,
                  "targets": gate3targets, "target_cap": target_cap},
        "gate4": {"pass": bool(g4_ok), "complete": bool(complete),
                  "tiny_attempted": bool(tiny_attempted),
                  "targets_attempted": bool(targets_attempted),
                  "wall_sec": wall, "clean": bool(clean)},
        "acceptance": {"pursue_condition": bool(pursue),
                       "reject_condition": bool(reject),
                       "n_win_G": n_win["G"], "n_win_A": n_win["A"],
                       "win_depths": win_fams, "n_strict_win": n_strict,
                       "pools_all": bool(pools_all),
                       "selftest_ok": bool(selftest_ok)},
        "reason": reason,
    }

    results = {
        "screen": "16",
        "verdict": "unresolved-with-reason: payload reports numbers "
                   "and gate evidence; classification is coordinator-side.",
        "design": {
            "model": "screen-authored bitwise Heisenberg Pauli "
                     "back-propagation (stdlib + numpy only; no "
                     "external libs)",
            "qubits": N_QUBITS,
            "depths": list(DEPTHS),
            "seeds": list(SEEDS),
            "cells": "3 depths x 5 seeds = 15 cells x 4 arms "
                     "(seeds are replicates)",
            "reps_per_cell_arm": n_inst,
            "observable": "Z on qubit %d" % OBS_Q,
            "noise": "per-layer depolarizing damping (1-p)^w, p=%s"
                     % DEPOL_P,
            "budgets": {"K_BUDGET": K_BUDGET, "K_REF": K_REF},
            "lookahead": LOOKAHEAD,
            "arms": {"W": "static Pauli-weight cutoff baseline",
                     "R": "random truncation control (matched budget)",
                     "G": "greedy magnitude-cutoff scheduling",
                     "A": "adaptive lookahead path-importance pruning"},
            "metrics": "mean-squared observable error vs converged "
                       "large-budget reference at matched string "
                       "budget + budget validity (tracked <= cap)",
            "pareto": "PURSUE needs an MSE win + matched-or-better "
                      "validity on the SAME arm; joint wins counted "
                      "PER ARM with bar max(G,A)>=2, never any-winner",
            "exact": "bounded-exact Pauli-path search on tiny (must "
                     "solve, optimum %r) + target-scale instance "
                     "(depth %s, seed %d rep %d, node cap %d, must "
                     "cap-hit)" % (
                         TINY_EXP, DEPTHS[TARGET["di"]],
                         TARGET["seed"], TARGET["rep"], EXACT_CAP),
            "reference": {"K_REF": K_REF,
                          "n_exact_refs": ref_exact_hits[0],
                          "n_refs": ref_exact_hits[1]},
        },
        "timing": {"wall_s": wall, "guards": {"wall_guard_s": WALL_GUARD_S,
                                              "limit_s": WALL_LIMIT_S}},
        "cells": {("%s/%s/%s" % k): {"n": len(v["mse"]),
                                     **pooled_stats(v["mse"]),
                                     "mean_valid": pooled_stats(
                                         v["valid"])["mean"],
                                     "peak_tracked": max(v["peak"])
                                     if v["peak"] else 0}
                  for k, v in cells.items()},
        "gates": verdict_bits,
        "skipped": skipped,
    }
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)


def pooled_stats(vals):
    a = np.asarray(vals, dtype=float)
    if a.size == 0:
        return {"n": 0, "mean": None, "std": None, "se": None}
    m = float(a.mean())
    if a.size < 2:
        return {"n": int(a.size), "mean": m, "std": 0.0, "se": None}
    sd = float(a.std(ddof=1))
    return {"n": int(a.size), "mean": m, "std": sd,
            "se": sd / math.sqrt(a.size)}


def spread_win(pools, ok):
    keys = sorted(pools)
    if ok and all(pools[k]["se"] is not None for k in keys):
        se = math.sqrt(sum(pools[k]["se"] ** 2 for k in keys)
                       / len(keys))
        means = [pools[k]["mean"] for k in keys]
        spread = max(means) - min(means)
        return se, spread, spread > 2.0 * se
    return None, None, False


if __name__ == "__main__":
    main()

