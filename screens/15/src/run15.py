"""Screen 15 payload: ZX spider-fusion trajectories with gflow verification.

Re-staged v1 for run f5ac1866 (new screen). pyzx 0.10.7 + numpy + stdlib
only. Writes ALL output under cwd (the attempt work dir): results.json +
witnesses/. Deterministic given seeds. Never claims pursue/reject: verdict
is always unresolved-with-reason; classification is coordinator-side.
"""

import argparse
import json
import math
import os
import time

import numpy as np

QUBITS_LIST = (6, 8, 10)
N_INST = 3
SEEDS = (1, 2, 3, 4, 5)
GATES_PER_QUBIT = 4
R_ROLLOUTS = 25
R_SEQ_LEN = 8
SA_ITERS = 100
SA_T0 = 2.0
SA_ALPHA = 0.995
BEAM_W = 4
BEAM_DEPTH = 6
CAND_CAP = 24
INFL_CAP = 1.6
MAX_EULER = 2
GREEDY_STEP_CAP = 200
WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0
TINY_Q = 4
TINY_N = 4
TINY_DEPTH = 4
TARGET_DEPTH = 6
TARGET_LIST = [(8, 1, 0), (8, 1, 1)]
NODE_CAP = 20000
EXTR_CAP = 8000
ARMS = ("F", "A", "B", "C")
# Frozen next-experiment text (finding 3a): byte-identical to the
# NEXT_EXPERIMENT line in brief.md; interpolated verbatim into the
# UNRESOLVED reason below.
NEXT_EXPERIMENT = "12q depth-6 DFS cap-hit regime (probed 20k nodes / ~125 s on 12q seed-2, beyond this screen's 300 s wall-guard budget)"


def make_skip(what, reason, iters_done=0, n_evaluated=0):
    return {"what": what, "reason": reason,
            "iters_done": int(iters_done),
            "n_evaluated": int(n_evaluated)}


def sa_euler_next(uu, is_euler, accepted):
    if accepted and is_euler:
        return uu + 1
    return uu


def r_means(good):
    if not good:
        return (None, None, None)
    n = len(good)
    return (sum(r["twoq"] for r in good) / n,
            sum(r["t"] for r in good) / n,
            sum(r["depth"] for r in good) / n)


def zx():
    import pyzx
    return pyzx


def spider_types():
    import pyzx
    try:
        return (pyzx.VertexType.Z, pyzx.VertexType.X)
    except AttributeError:
        return None


def spiders(g, ztypes):
    out = []
    try:
        vs = list(g.vertices())
    except Exception:
        return out
    for v in vs:
        try:
            t = g.type(v)
        except Exception:
            continue
        if ztypes is None or t in ztypes:
            out.append(v)
    return out


def edge_list(g, sweep):
    seen = set()
    for u in sweep:
        try:
            nbs = list(g.neighbors(u))
        except Exception:
            continue
        for v in nbs:
            if v in sweep and u < v:
                seen.add((u, v))
    return sorted(seen)


def graph_key(g):
    try:
        vs = sorted(list(g.vertices()))
        ph = []
        for v in vs:
            try:
                ph.append((v, str(g.type(v)), str(g.phase(v))))
            except Exception:
                ph.append((v, "?", "?"))
        es = []
        for u in vs:
            try:
                nbs = list(g.neighbors(u))
            except Exception:
                continue
            for v in nbs:
                if u < v:
                    try:
                        et = str(g.edge_type((u, v)))
                    except Exception:
                        et = "?"
                    es.append((u, v, et))
        return (g.num_vertices(), tuple(ph), tuple(sorted(es)))
    except Exception:
        return None


def t_spiders(g, ztypes):
    n = 0
    for v in spiders(g, ztypes):
        try:
            ph = g.phase(v)
            if (ph * 2) % 1 != 0:
                n += 1
        except Exception:
            continue
    return n


def score_of(g, ztypes):
    try:
        return g.num_vertices() + 4 * t_spiders(g, ztypes)
    except Exception:
        return 10 ** 9


def gen_circuit(nq, seed, pi):
    pyzx = zx()
    rng = np.random.default_rng(
        (int(seed * 10007 + pi * 101 + nq * 13) % (2 ** 63 - 1)))
    c = pyzx.Circuit(nq)
    for _ in range(GATES_PER_QUBIT * nq):
        r = float(rng.random())
        if r < 0.5:
            a, b = rng.choice(nq, 2, replace=False)
            c.add_gate("CNOT", int(a), int(b))
        elif r < 0.75:
            c.add_gate("T", int(rng.integers(nq)))
        elif r < 0.9:
            c.add_gate("S", int(rng.integers(nq)))
        else:
            c.add_gate("H", int(rng.integers(nq)))
    return c


def to_graphlike(circuit):
    g = circuit.to_graph()
    zx().simplify.to_graph_like(g)
    return g


def candidates(g, ztypes, allow_euler):
    sp = spiders(g, ztypes)
    spset = set(sp)
    lc = [("lcomp", v) for v in sorted(sp)][:8]
    pv = [("pivot", u, v) for (u, v) in edge_list(g, spset)][:8]
    eu = []
    if allow_euler:
        eu = [("euler", u, v) for (u, v) in edge_list(g, spset)][:8]
    return sorted(lc + pv + eu)[:CAND_CAP]


def apply_one(g2, move):
    pyzx = zx()
    try:
        if move[0] == "lcomp":
            return bool(pyzx.simplify.lcomp(g2, move[1]))
        if move[0] == "pivot":
            return bool(pyzx.simplify.pivot(g2, move[1], move[2]))
        if move[0] == "euler":
            return bool(pyzx.simplify.euler_expansion(g2, move[1],
                                                      move[2]))
    except Exception:
        return False
    return False


def children(g, ztypes, cap_spiders, allow_euler):
    base = g.copy()
    out = []
    for mv in candidates(base, ztypes, allow_euler):
        g2 = base.copy()
        if not apply_one(g2, mv):
            continue
        try:
            zx().simplify.to_graph_like(g2)
        except Exception:
            continue
        try:
            if g2.num_vertices() > cap_spiders:
                continue
        except Exception:
            continue
        out.append((mv, g2))
    return out


def try_extract(g):
    pyzx = zx()
    try:
        work = g.copy()
    except Exception as ex:
        return (False, "copy: %r" % ex, None)
    try:
        fl = pyzx.gflow.gflow(work.copy())
    except Exception as ex:
        return (False, "gflow-raise: %r" % ex, None)
    if fl is None:
        return (False, "no-gflow", None)
    try:
        c = pyzx.extract_circuit(work.copy())
    except Exception as ex:
        return (False, "extract-raise: %r" % ex, None)
    try:
        twoq = int(c.twoqubitcount())
        depth = int(c.depth())
        t = int(c.tcount())
        cnot = sum(1 for gt in c.gates if gt.name == "CNOT")
        cz = sum(1 for gt in c.gates if gt.name == "CZ")
    except Exception as ex:
        return (False, "metric-raise: %r" % ex, None)
    return (True, None, {"twoq": twoq, "depth": depth, "t": t,
                         "cnot": int(cnot), "cz": int(cz)})


def matrix_overlap(circ_a, circ_b):
    try:
        m1 = np.asarray(circ_a.to_matrix(), dtype=complex)
        m2 = np.asarray(circ_b.to_matrix(), dtype=complex)
    except Exception:
        return None
    if m1.shape != m2.shape or m1.shape[0] == 0:
        return None
    try:
        ov = abs(np.trace(m1.conj().T @ m2)) / m1.shape[0]
        return float(ov)
    except Exception:
        return None


def run_F(g0, stop=None):
    if stop is not None and stop():
        return (False, "stopped-guard", None, g0)
    pyzx = zx()
    g = g0.copy()
    try:
        pyzx.full_reduce(g)
        pyzx.simplify.to_graph_like(g)
    except Exception:
        ok, why, m = try_extract(g0.copy())
        if ok:
            return (True, "identity-fallback:reduce-raise", m, g0)
        return (False, "reduce-raise+identity-%s" % why, None, g0)
    ok, why, m = try_extract(g)
    if ok:
        return (True, None, m, g)
    ok2, why2, m2 = try_extract(g0.copy())
    if ok2:
        return (True, "identity-fallback", m2, g0)
    return (False, why, None, g)


def run_A(g0, ztypes, stop=None):
    g = g0.copy()
    cap = max(1, int(INFL_CAP * g0.num_vertices()))
    stopped = False
    for _ in range(GREEDY_STEP_CAP):
        if stop is not None and stop():
            stopped = True
            break
        base = score_of(g, ztypes)
        best = None
        best_s = base
        for _, g2 in children(g, ztypes, cap, False):
            s = score_of(g2, ztypes)
            if s < best_s:
                best, best_s = g2, s
        if best is None:
            break
        g = best
    if stopped:
        return (False, "stopped-guard", None, g0)
    ok, why, m = try_extract(g)
    return (ok, why, m, g)


def beam_search(g0, ztypes, width, depth, stop=None):
    cap = max(1, int(INFL_CAP * g0.num_vertices()))
    beam = [(score_of(g0, ztypes), g0, 0)]
    best = (score_of(g0, ztypes), g0)
    seen = {(graph_key(g0), 0, 0)}
    for _ in range(depth):
        if stop is not None and stop():
            break
        nxt = []
        for _, g, uu in beam:
            for mv, g2 in children(g, ztypes, cap, uu < MAX_EULER):
                uu2 = uu + (1 if mv[0] == "euler" else 0)
                k = graph_key(g2)
                if k is None or (k, 0, uu2) in seen:
                    continue
                seen.add((k, 0, uu2))
                s = score_of(g2, ztypes)
                nxt.append((s, g2, uu2))
                if s < best[0]:
                    best = (s, g2)
        if not nxt:
            break
        nxt.sort(key=lambda t: t[0])
        beam = nxt[:width]
    ranked = sorted([(score_of(g, ztypes), g) for _, g, _ in beam] +
                    [best], key=lambda t: t[0])
    out = []
    seen2 = set()
    for s, g in ranked:
        k = graph_key(g)
        if k in seen2:
            continue
        seen2.add(k)
        out.append(g)
        if len(out) >= 5:
            break
    return out


def run_B(g0, ztypes, stop=None):
    finals = beam_search(g0, ztypes, BEAM_W, BEAM_DEPTH, stop)
    for i, g in enumerate(finals):
        if stop is not None and stop():
            return (False, "stopped-guard", None, g0)
        ok, why, m = try_extract(g)
        if ok:
            return (True, None if i == 0 else "fallback-%d" % i, m, g)
    return (False, "all-finals-blocked", None, g0)


def run_C(g0, ztypes, rng, stop=None):
    cap = max(1, int(INFL_CAP * g0.num_vertices()))
    cur = g0.copy()
    cur_s = score_of(cur, ztypes)
    top = [(cur_s, graph_key(cur), cur)]
    seen = {graph_key(cur)}
    uu = 0
    for it in range(SA_ITERS):
        if stop is not None and it % 16 == 0 and stop():
            break
        kids = children(cur, ztypes, cap, uu < MAX_EULER)
        if not kids:
            break
        m, g2 = kids[int(rng.integers(len(kids)))]
        is_euler = (m[0] == "euler")
        s2 = score_of(g2, ztypes)
        temp = SA_T0 * (SA_ALPHA ** it)
        accept = s2 <= cur_s or (
            temp > 0 and float(rng.random()) < math.exp(-(s2 - cur_s) / temp))
        uu = sa_euler_next(uu, is_euler, accept)
        if accept:
            cur, cur_s = g2, s2
            k = graph_key(g2)
            if k is not None and k not in seen:
                seen.add(k)
                top.append((s2, k, g2))
    top.sort(key=lambda t: t[0])
    for i, (_, _, g) in enumerate(top[:5]):
        if stop is not None and stop():
            return (False, "stopped-guard", None, g0)
        ok, why, m = try_extract(g)
        if ok:
            return (True, None if i == 0 else "fallback-%d" % i, m, g)
    return (False, "all-finals-blocked", None, g0)


def run_R(g0, ztypes, rng, n_roll, stop=None):
    cap = max(1, int(INFL_CAP * g0.num_vertices()))
    results = []
    best_g = None
    best_twoq = None
    stopped = False
    for _ in range(n_roll):
        if stop is not None and stop():
            stopped = True
            break
        g = g0.copy()
        uu = 0
        for _ in range(R_SEQ_LEN):
            kids = children(g, ztypes, cap, uu < MAX_EULER)
            if not kids:
                break
            m, g2 = kids[int(rng.integers(len(kids)))]
            if m[0] == "euler":
                uu += 1
            g = g2
        ok, why, m = try_extract(g)
        results.append({"ok": bool(ok), "why": why,
                        "twoq": m["twoq"] if (ok and m) else None,
                        "t": m["t"] if (ok and m) else None,
                        "depth": m["depth"] if (ok and m) else None})
        if ok and m is not None and (best_twoq is None or
                                     m["twoq"] < best_twoq):
            best_twoq = m["twoq"]
            best_g = g
    good = [r for r in results
            if r["ok"] and r["twoq"] is not None]
    return results, good, best_g, stopped


def dfs_exact(g0, ztypes, max_depth, tag, stop=None):
    cap = max(1, int(INFL_CAP * g0.num_vertices()))
    k0 = graph_key(g0)
    stack = [(g0, 0, 0)]
    seen = {(k0, 0, 0)} if k0 is not None else set()
    terminals = []
    nodes = 0
    completed = True
    stopped = False
    while stack:
        if nodes >= NODE_CAP:
            completed = False
            break
        if stop is not None and nodes % 64 == 0 and stop():
            completed = False
            stopped = True
            break
        g, d, uu = stack.pop()
        nodes += 1
        pushed = 0
        if d < max_depth:
            for m, g2 in children(g, ztypes, cap, uu < MAX_EULER):
                uu2 = uu + (1 if m[0] == "euler" else 0)
                k = graph_key(g2)
                if k is None or (k, d + 1, uu2) in seen:
                    continue
                seen.add((k, d + 1, uu2))
                stack.append((g2, d + 1, uu2))
                pushed += 1
        if d >= max_depth or pushed == 0:
            terminals.append(g)
            continue
    best = None
    ext = 0
    capped_extr = len(terminals) > EXTR_CAP
    for t in terminals:
        if ext >= EXTR_CAP:
            break
        if stop is not None and ext % 64 == 0 and stop():
            completed = False
            stopped = True
            break
        ext += 1
        ok, _, m = try_extract(t)
        if ok and m is not None and (best is None or
                                     m["twoq"] < best):
            best = m["twoq"]
    solved = completed and not capped_extr and best is not None
    if stopped:
        status = "stopped-guard"
    elif solved:
        status = "solved"
    else:
        status = "cap-hit"
    return {"tag": tag, "status": status,
            "nodes": nodes, "n_terminals": len(terminals),
            "n_extracted": ext, "optimum_twoq": best,
            "node_cap": NODE_CAP, "extr_cap": EXTR_CAP,
            "max_depth": max_depth}


def self_tests(ztypes):
    out = {"ran": True, "failed": []}
    try:
        c = gen_circuit(6, 1, 0)
        c2 = gen_circuit(6, 1, 0)
        if graph_key(to_graphlike(c)) != graph_key(to_graphlike(c2)):
            out["failed"].append("determinism")
        g = to_graphlike(c)
        fl = zx().gflow.gflow(g.copy())
        if fl is None:
            out["failed"].append("initial-gflow")
        sp = spiders(g, ztypes)
        if sp:
            v = sorted(sp)[0]
            r1 = zx().simplify.lcomp(g.copy(), v)
            if not isinstance(r1, bool):
                out["failed"].append("lcomp-type")
        e = edge_list(g, set(sp))
        if e:
            u, w = e[0]
            r2 = zx().simplify.pivot(g.copy(), u, w)
            if not isinstance(r2, bool):
                out["failed"].append("pivot-type")
        # Regression probes, findings 3b/3c/5/10 (forced-stop guards,
        # skip-record counts, euler allowance, R metric honesty).
        try:
            aok, awhy, am, ag = run_A(g, ztypes, stop=lambda: True)
            if (aok, awhy, am) != (False, "stopped-guard", None) or ag is not g:
                out["failed"].append("stop-A-guard")
        except Exception as ex:
            out["failed"].append("stop-A-raise: %r" % ex)
        try:
            import numpy as _np
            rr, good, _bg, rstopped = run_R(
                g, ztypes, _np.random.default_rng(0), 3,
                stop=lambda: True)
            if rstopped is not True or rr != [] or good != []:
                out["failed"].append("stop-R-guard")
        except Exception as ex:
            out["failed"].append("stop-R-raise: %r" % ex)
        try:
            fok, fwhy, fm, fg = run_F(g, stop=lambda: True)
            if (fok, fwhy, fm) != (False, "stopped-guard", None) or fg is not g:
                out["failed"].append("stop-F-guard")
        except Exception as ex:
            out["failed"].append("stop-F-raise: %r" % ex)
        try:
            bok, bwhy, _, _ = run_B(g, ztypes, stop=lambda: True)
            if (bok, bwhy) != (False, "stopped-guard"):
                out["failed"].append("stop-B-guard")
        except Exception as ex:
            out["failed"].append("stop-B-raise: %r" % ex)
        try:
            s = make_skip("probe", "wall-guard", 2, 5)
            if not (s["what"] == "probe" and s["reason"] == "wall-guard"
                    and s["iters_done"] == 2 and s["n_evaluated"] == 5):
                out["failed"].append("skip-fields")
            s0 = make_skip("probe", "wall-guard")
            if s0["iters_done"] != 0 or s0["n_evaluated"] != 0:
                out["failed"].append("skip-defaults")
        except Exception as ex:
            out["failed"].append("skip-raise: %r" % ex)
        try:
            if not (sa_euler_next(0, True, False) == 0
                    and sa_euler_next(1, True, False) == 1
                    and sa_euler_next(0, True, True) == 1
                    and sa_euler_next(1, False, True) == 1
                    and sa_euler_next(0, False, False) == 0):
                out["failed"].append("euler-allowance-rule")
        except Exception as ex:
            out["failed"].append("euler-raise: %r" % ex)
        try:
            seen = []
            real_children = children

            def stub_children(cur, zt2, cap, allow_euler):
                seen.append(bool(allow_euler))
                if len(seen) <= 2:
                    g2 = cur.copy()
                    g2.add_vertex(spider_types()[0],
                                  phase=__import__("fractions").Fraction(1, 4))
                    return [(("euler", -1, -2), g2)]
                return []

            class _FakeRng(object):
                def integers(self, n):
                    return 0

                def random(self):
                    return 0.9999999

            globals()["children"] = stub_children
            try:
                run_C(g, ztypes, _FakeRng(), stop=None)
            finally:
                globals()["children"] = real_children
            if seen != [True, True, True]:
                out["failed"].append("euler-reject-preserves: %r" % seen)
        except Exception as ex:
            try:
                globals()["children"] = real_children
            except Exception:
                pass
            out["failed"].append("euler-behavioral-raise: %r" % ex)
        try:
            import numpy as _np2
            rr2 = run_R(g, ztypes, _np2.random.default_rng(1), 3)[0]
            if len(rr2) != 3:
                out["failed"].append("R-n-roll")
            for r in rr2:
                if set(("ok", "why", "twoq", "t", "depth")) - set(r):
                    out["failed"].append("R-rollout-keys")
                    break
                if r["ok"] and not (isinstance(r["t"], int)
                                    and isinstance(r["depth"], int)):
                    out["failed"].append("R-rollout-metrics")
                    break
            m2, mt, md = r_means(
                [{"twoq": 10, "t": 3, "depth": 5},
                 {"twoq": 14, "t": 5, "depth": 7}])
            if (m2, mt, md) != (12.0, 4.0, 6.0):
                out["failed"].append("R-means")
            if r_means([]) != (None, None, None):
                out["failed"].append("R-means-empty")
            if pooled_stats([]) != {"n": 0, "mean": None, "std": None,
                                    "se": None}:
                out["failed"].append("pool-empty")
        except Exception as ex:
            out["failed"].append("R-raise: %r" % ex)
    except Exception as ex:
        out["failed"].append("raise: %r" % ex)
    return out


def extract_circuit_obj(g):
    try:
        pyzx = zx()
        if pyzx.gflow.gflow(g.copy()) is None:
            return None
        return pyzx.extract_circuit(g.copy())
    except Exception:
        return None


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


def cell_stats(vals):
    p = pooled_stats(vals)
    return {"n": p["n"], "mean": p["mean"], "std": p["std"], "se": p["se"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--attempt", required=True)
    ap.add_argument("--data", required=True)
    ap.parse_args()
    outdir = os.getcwd()
    witdir = os.path.join(outdir, "witnesses")
    os.makedirs(witdir, exist_ok=True)
    t0 = time.perf_counter()

    def elapsed():
        return time.perf_counter() - t0

    def over():
        return elapsed() > WALL_GUARD_S

    ztypes = spider_types()
    cells = {}
    instrecs = []
    matrix_checks = []
    skipped = []
    gate3tiny = {"instances": [], "solved": 0, "total": 0}
    gate3targets = []
    selftest = self_tests(ztypes)
    with open(os.path.join(witdir, "selftest.json"), "w") as f:
        json.dump(selftest, f, indent=1, default=str)

    def checkpoint(tag):
        try:
            with open(os.path.join(witdir, "checkpoint-%s.json" % tag),
                      "w") as f:
                json.dump({"tag": tag, "wall_s": elapsed(),
                           "cells": {("%d/%d/%s" % k): v
                                     for k, v in cells.items()},
                           "gate3tiny": gate3tiny,
                           "gate3targets": gate3targets,
                           "n_skipped": len(skipped),
                           "verdict": "unresolved-with-reason: partial "
                                      "checkpoint"}, f, indent=1, default=str)
        except Exception:
            pass

    def arm_rng(seed, size, pi, salt):
        return np.random.default_rng(
            (int(seed * 100003 + size * 1009 + pi * 917 + salt)
             % (2 ** 63 - 1)))

    def run_instance(size, seed, pi):
        circ = gen_circuit(size, seed, pi)
        g0 = to_graphlike(circ)
        try:
            init_gf = zx().gflow.gflow(g0.copy()) is not None
        except Exception:
            init_gf = False
        rec = {"size": size, "seed": seed, "pi": pi,
               "init_spiders": g0.num_vertices(), "init_gflow": init_gf,
               "arms": {}, "matrix": {}}
        if not init_gf:
            rec["blocked"] = "initial-no-gflow"
            return rec
        rF = run_F(g0, over)
        rec["arms"]["F"] = {"ok": rF[0], "why": rF[1], "m": rF[2]}
        rng = arm_rng(seed, size, pi, 11)
        rr, good, best_g, r_stopped = run_R(g0, ztypes, rng, R_ROLLOUTS,
                                            over)
        if r_stopped:
            rec["blocked"] = "stopped-guard"
            rec["arms"]["R"] = {"ok": False, "why": "stopped-guard",
                                "mean": None, "best_twoq": None,
                                "n_ok": len(good), "n_roll": len(rr),
                                "rollouts": rr, "stopped": True}
        elif good:
            m2, mt, md = r_means(good)
            rec["arms"]["R"] = {"ok": True, "why": None,
                                "mean": {"twoq": float(m2),
                                         "t": float(mt),
                                         "depth": float(md)},
                                "best_twoq": int(min(
                                    r["twoq"] for r in good)),
                                "n_ok": len(good), "n_roll": len(rr),
                                "rollouts": rr}
        else:
            rec["arms"]["R"] = {"ok": False, "why": "all-rollouts-blocked",
                                "mean": None, "best_twoq": None,
                                "n_ok": 0, "n_roll": len(rr),
                                "rollouts": rr}
        rA = run_A(g0, ztypes, over)
        rec["arms"]["A"] = {"ok": rA[0], "why": rA[1], "m": rA[2]}
        rB = run_B(g0, ztypes, over)
        rec["arms"]["B"] = {"ok": rB[0], "why": rB[1], "m": rB[2]}
        rng = arm_rng(seed, size, pi, 13)
        rC = run_C(g0, ztypes, rng, over)
        rec["arms"]["C"] = {"ok": rC[0], "why": rC[1], "m": rC[2]}
        finals = {"F": rF[3], "A": rA[3], "B": rB[3], "C": rC[3],
                  "Rbest": best_g}
        oks = {"F": rF[0], "A": rA[0], "B": rB[0], "C": rC[0],
               "Rbest": best_g is not None}
        if size == 6:
            for arm, gfin in finals.items():
                if not oks[arm] or gfin is None:
                    rec["matrix"][arm] = {"overlap": None,
                                          "pass": False,
                                          "note": "no-final"}
                    matrix_checks.append(
                        {"size": size, "seed": seed, "pi": pi, "arm": arm,
                         "overlap": None, "pass": False})
                    continue
                cext = extract_circuit_obj(gfin)
                if cext is None:
                    ov = None
                else:
                    ov = matrix_overlap(circ, cext)
                okm = ov is not None and ov > 1 - 1e-6
                rec["matrix"][arm] = {"overlap": ov, "pass": bool(okm)}
                matrix_checks.append(
                    {"size": size, "seed": seed, "pi": pi, "arm": arm,
                     "overlap": ov, "pass": bool(okm)})
        rec["finals_note"] = {a: ("extracted" if rec["arms"].get(a, {}).get(
            "ok") else "blocked") for a in ("F", "A", "B", "C")}
        return rec

    def record_instance(rec):
        size, seed = rec["size"], rec["seed"]
        ok_all = rec.get("blocked") is None and all(
            rec["arms"].get(a, {}).get("ok") for a in ("F", "A", "B", "C"))
        ok_r = rec.get("blocked") is None and rec["arms"].get(
            "R", {}).get("ok", False)
        if ok_all and ok_r:
            cells.setdefault((size, seed, "F"), {"twoq": [], "t": [],
                                                "depth": []})
            cells.setdefault((size, seed, "A"), {"twoq": [], "t": [],
                                                "depth": []})
            cells.setdefault((size, seed, "B"), {"twoq": [], "t": [],
                                                "depth": []})
            cells.setdefault((size, seed, "C"), {"twoq": [], "t": [],
                                                "depth": []})
            cells.setdefault((size, seed, "R"), {"twoq": [], "t": [],
                                                "depth": []})
            for a in ("F", "A", "B", "C"):
                m = rec["arms"][a]["m"]
                cells[(size, seed, a)]["twoq"].append(m["twoq"])
                cells[(size, seed, a)]["t"].append(m["t"])
                cells[(size, seed, a)]["depth"].append(m["depth"])
            # R is a control, never a winner: pooled Gate 2/2t and the
            # pursue joint-win count only pool {F,A,B,C}, so R's actual
            # rollout-extracted means below cannot affect gates. R cells
            # carry actual means (never fabricated zeros).
            rm = rec["arms"]["R"]["mean"]
            cells[(size, seed, "R")]["twoq"].append(float(rm["twoq"]))
            cells[(size, seed, "R")]["t"].append(float(rm["t"]))
            cells[(size, seed, "R")]["depth"].append(float(rm["depth"]))
            return True
        arm_whys = [rec["arms"].get(a, {}).get("why")
                    for a in ("F", "A", "B", "C", "R")]
        reason = rec.get("blocked") or (
            "stopped-guard" if "stopped-guard" in arm_whys
            else "arm-blocked")
        skipped.append(make_skip("instance %d/%d/%d" % (
            size, seed, rec.get("pi", -1)), reason, len(instrecs),
            len(plan)))
        return False

    tiny_specs = [(TINY_Q, 0, pi) for pi in range(TINY_N)]
    for (qs, sd, pi) in tiny_specs:
        if over():
            skipped.append(make_skip("tiny-%d" % pi, "wall-guard",
                                      gate3tiny["total"], TINY_N))
            gate3tiny["instances"].append({"q": qs, "pi": pi,
                                          "status": "skipped-guard"})
            continue
        circ = gen_circuit(qs, sd, pi)
        g0 = to_graphlike(circ)
        rec = dfs_exact(g0, ztypes, TINY_DEPTH, "tiny-%d" % pi,
                        stop=over)
        rec["q"] = qs
        gate3tiny["instances"].append(rec)
        if rec.get("status") == "stopped-guard":
            gate3tiny["total"] += 1
            continue
        if rec["status"] == "solved":
            gate3tiny["solved"] += 1
        gate3tiny["total"] += 1
        arms_gap = {}
        for aname, fn in (("F", lambda: run_F(g0, over)),
                          ("A", lambda: run_A(g0, ztypes, over)),
                          ("B", lambda: run_B(g0, ztypes, over)),
                          ("C", lambda: run_C(
                              g0, ztypes,
                              arm_rng(sd, qs, pi, 22), over))):
            try:
                ok, _, m, _ = fn()
            except Exception as ex:
                ok, m = False, None
                rec2 = {"arm": aname, "raise": "%r" % ex}
                arms_gap[aname] = rec2
                continue
            gap = (m["twoq"] - rec["optimum_twoq"]
                   if ok and m is not None and
                   rec["optimum_twoq"] is not None else None)
            arms_gap[aname] = {"ok": ok,
                               "twoq": m["twoq"] if m else None,
                               "gap_to_opt": gap}
        rec["arms_gap"] = arms_gap
    with open(os.path.join(witdir, "gate3_tiny.json"), "w") as f:
        json.dump(gate3tiny, f, indent=1, default=str)
    checkpoint("tiny")

    plan = [(size, seed, pi) for size in QUBITS_LIST for seed in SEEDS
            for pi in range(N_INST)]
    idx = 0
    while idx < len(plan):
        if over():
            for (s2, sd2, p2) in plan[idx:]:
                skipped.append(make_skip(
                    "instance %d/%d/%d" % (s2, sd2, p2),
                    "wall-guard", idx, len(plan)))
            break
        size, seed, pi = plan[idx]
        rec = run_instance(size, seed, pi)
        instrecs.append(rec)
        record_instance(rec)
        idx += 1
        if pi == N_INST - 1:
            checkpoint("%d-%d" % (size, seed))
    with open(os.path.join(witdir, "instances.json"), "w") as f:
        json.dump(instrecs, f, indent=1, default=str)
    checkpoint("corpus")

    for (qs, sd, pi) in TARGET_LIST:
        if over():
            skipped.append(make_skip("target-%d-%d-%d" % (qs, sd, pi),
                                      "wall-guard", len(gate3targets),
                                      len(TARGET_LIST)))
            gate3targets.append({"q": qs, "seed": sd, "pi": pi,
                                 "status": "skipped-guard"})
            continue
        circ = gen_circuit(qs, sd, pi)
        g0 = to_graphlike(circ)
        rec = dfs_exact(g0, ztypes, TARGET_DEPTH,
                        "target-%d-%d-%d" % (qs, sd, pi), stop=over)
        rec["q"] = qs
        gate3targets.append(rec)
        if rec.get("status") == "stopped-guard":
            continue
    with open(os.path.join(witdir, "gate3_targets.json"), "w") as f:
        json.dump(gate3targets, f, indent=1, default=str)
    checkpoint("targets")

    def cell_list(size, seed, arm, field):
        return cells.get((size, seed, arm), {"twoq": [],
                                             "t": [],
                                             "depth": []})[field]

    def cell_mean(size, seed, arm):
        v = cell_list(size, seed, arm, "twoq")
        if not v:
            return None
        return float(np.mean(np.asarray(v, dtype=float)))

    def pooled_for(field, size, arms):
        pools = {}
        ok = True
        for arm in arms:
            vals = []
            for seed in SEEDS:
                vals.extend(cell_list(size, seed, arm, field))
            pools[arm] = pooled_stats(vals)
            if pools[arm]["n"] != len(SEEDS) * N_INST:
                ok = False
        return pools, ok

    def spread_win(pools, ok):
        keys = sorted(pools)
        if ok and all(pools[a]["se"] is not None for a in keys):
            se = math.sqrt(sum(pools[a]["se"] ** 2 for a in keys)
                           / len(keys))
            means = [pools[a]["mean"] for a in keys]
            spread = max(means) - min(means)
            return se, spread, spread > 2.0 * se
        return None, None, False

    g1_cells, g1_ok = [], True
    for size in QUBITS_LIST:
        for seed in SEEDS:
            ma, mr = cell_mean(size, seed, "F"), cell_mean(size, seed, "R")
            ok = (ma is not None and mr is not None and ma < mr)
            g1_cells.append({"cell": "%d/%d" % (size, seed),
                             "mean_F": ma, "mean_R": mr, "pass": bool(ok)})
            if not ok:
                g1_ok = False
    matrix_ok = all(c["pass"] for c in matrix_checks)
    g1_all = bool(g1_ok and matrix_ok and matrix_checks)

    g2_sizes, g2_n = [], 0
    g2t_sizes, g2t_n = [], 0
    win_sizes, win_n = [], 0
    for size in QUBITS_LIST:
        pools, pok = pooled_for("twoq", size, ("F", "A", "B", "C"))
        se, spread, gp = spread_win(pools, pok)
        g2_sizes.append({"size": size, "pools": pools, "SE": se,
                         "spread": spread, "pass": bool(gp)})
        if gp:
            g2_n += 1
        ppool, pokt = pooled_for("t", size, ("F", "A", "B", "C"))
        tse, tspread, gpt = spread_win(ppool, pokt)
        g2t_sizes.append({"size": size, "pools": ppool, "SE": tse,
                          "spread": tspread, "pass": bool(gpt)})
        if gpt:
            g2t_n += 1
        dpools, pokd = pooled_for("depth", size, ("F", "A", "B", "C"))
        joint, tok, dok = {}, {}, {}
        if pok and pokt and pokd and all(
                pools[a]["se"] is not None for a in ("F", "B", "C")) and all(
                pools[a]["mean"] is not None for a in ("F", "B", "C")):
            sse = math.sqrt(sum(pools[a]["se"] ** 2
                                for a in ("F", "B", "C")) / 3.0)
            for a in ("B", "C"):
                qwin = pools[a]["mean"] < pools["F"]["mean"] - 2.0 * sse
                tok[a] = ppool[a]["mean"] <= ppool["F"]["mean"]
                dok[a] = dpools[a]["mean"] <= dpools["F"]["mean"]
                joint[a] = bool(qwin and tok[a] and dok[a])
        else:
            for a in ("B", "C"):
                joint[a] = False
                tok[a] = dok[a] = False
            pokd = False
        winner = ("B" if joint["B"]
                  else ("C" if joint["C"] else None))
        wpass = winner is not None
        if pok and all(pools[a]["mean"] is not None
                       for a in ("F", "B", "C")):
            spass = min(pools["B"]["mean"],
                        pools["C"]["mean"]) < pools["F"]["mean"]
        else:
            spass = False
        tpass = tok[winner] if winner else False
        dpass = dok[winner] if winner else False
        win_sizes.append({"size": size, "win": bool(wpass),
                          "strict_win": bool(spass), "pools_ok": bool(pok),
                          "joint": dict(joint), "winner": winner,
                          "t_no_regress": bool(tpass),
                          "depth_no_regress": bool(dpass)})
        if wpass and tpass and dpass:
            win_n += 1
    g2_ok = g2_n >= 2
    g2t_ok = g2t_n >= 2

    tiny_solved = (gate3tiny["total"] == TINY_N and
                   gate3tiny["solved"] == TINY_N)
    target_hits = sum(1 for r in gate3targets
                      if r.get("status") == "cap-hit")
    targets_solved = (len(gate3targets) == len(TARGET_LIST) and
                      all(r.get("status") == "solved"
                          for r in gate3targets))
    g3pass = bool(tiny_solved and targets_solved)

    complete = all(
        len(cell_list(size, seed, arm, "twoq")) == N_INST
        for size in QUBITS_LIST for seed in SEEDS
        for arm in ("F", "A", "B", "C", "R"))
    tiny_attempted = gate3tiny["total"] == TINY_N
    targets_attempted = len(gate3targets) == len(TARGET_LIST)
    wall = elapsed()
    clean = len(skipped) == 0
    g4_ok = bool(complete and tiny_attempted and targets_attempted and
                 wall < WALL_LIMIT_S and clean)

    selftest_ok = bool(selftest.get("ran")) and not selftest.get("failed")
    strict_n = sum(1 for w in win_sizes if w.get("strict_win"))
    pools_all = all(w.get("pools_ok") for w in win_sizes)
    pursue = (win_n >= 2 and g1_all and g2_ok and g2t_ok and g3pass and
              g4_ok and selftest_ok)
    reject = (complete and tiny_solved and g1_all and pools_all and
              strict_n == 0)
    if pursue:
        reason = "PURSUE-condition holds (joint CNOT win + T/depth " \
            "no-regress at >=2 sizes + tiny solved + targets solved + " \
            "gates 1,2,2t,4 + self-tests ok); payload verdict stays " \
            "unresolved-with-reason, classification is coordinator-side."
    elif reject:
        reason = "REJECT-condition holds (complete cells, tiny solved, " \
            "Gate-1 controls pass, no strict pooled CNOT win at any " \
            "size); payload verdict stays unresolved-with-reason, " \
            "classification is coordinator-side."
    else:
        reason = "UNRESOLVED + next experiment (joint wins=%d/3, strict " \
            "CNOT wins=%d/3, g1=%s g2=%s g2t=%s g3=%s (tiny %d/%d, " \
            "targets solved=%s cap-hits=%d) selftest=%s g4=%s " \
            "complete=%s skipped=%d; hardness boundary not reached " \
            "within caps — next: %s)." % (
                win_n, strict_n, g1_all, g2_ok, g2t_ok, g3pass,
                gate3tiny["solved"], gate3tiny["total"], targets_solved,
                target_hits, selftest_ok, g4_ok, complete, len(skipped),
                NEXT_EXPERIMENT)
    verdict_bits = {
        "gate1": {"pass": bool(g1_all), "cells": g1_cells,
                  "matrix_all_pass": bool(matrix_ok),
                  "n_matrix": len(matrix_checks)},
        "gate2": {"pass": bool(g2_ok), "n_sizes_pass": g2_n,
                  "sizes": g2_sizes},
        "gate2_t": {"pass": bool(g2t_ok), "n_sizes_pass": g2t_n,
                    "sizes": g2t_sizes},
        "gate3": {"pass": bool(g3pass), "tiny_solved": tiny_solved,
                  "tiny": gate3tiny, "targets": gate3targets,
                  "targets_solved": bool(targets_solved),
                  "cap_hits": target_hits},
        "gate4": {"pass": bool(g4_ok), "complete": bool(complete),
                  "tiny_attempted": bool(tiny_attempted),
                  "targets_attempted": bool(targets_attempted),
                  "wall_sec": wall, "clean": bool(clean)},
        "acceptance": {"pursue_condition": bool(pursue),
                       "reject_condition": bool(reject),
                       "win_sizes": win_sizes, "n_win": win_n,
                       "n_strict_win": strict_n,
                       "selftest_ok": bool(selftest_ok)},
        "reason": reason,
    }

    results = {
        "screen": "15",
        "verdict": "unresolved-with-reason: payload reports numbers "
                   "and gate evidence; classification is coordinator-side.",
        "design": {
            "model": "screen-authored ZX rewrite environment over pyzx "
                     "0.10.7 (no phasepoly/native code in this screen)",
            "qubits": list(QUBITS_LIST),
            "instances_per_cell": N_INST,
            "seeds": list(SEEDS),
            "moves": ["pivot", "lcomp", "euler<=2"],
            "inflation_cap": INFL_CAP,
            "proxy_score": "spiders + 4*T-spiders",
            "arms": {"F": "full_reduce baseline",
                     "A": "greedy spider reduction",
                     "B": "beam W%d D%d" % (BEAM_W, BEAM_DEPTH),
                     "C": "anneal %d iters" % SA_ITERS,
                     "R": "%d random rollouts" % R_ROLLOUTS},
            "metrics": "extracted twoqubitcount (CNOT+CZ), depth "
                       "(pyzx layer), tcount (pyzx T-gates)",
            "pareto": "PURSUE needs CNOT win + T/depth no-regress; a "
                      "CNOT-only win is not Pareto",
            "exact": "bounded-exhaustive DFS depth<=D (tiny %d, target "
                     "%d), node cap %d, extraction cap %d" % (
                         TINY_DEPTH, TARGET_DEPTH, NODE_CAP, EXTR_CAP),
        },
        "timing": {"wall_s": wall, "guards": {"wall_guard_s": WALL_GUARD_S,
                                              "limit_s": WALL_LIMIT_S}},
        "cells": {("%d/%d/%s" % k): {"n": len(v["twoq"]),
                                     **cell_stats(v["twoq"]),
                                     "t": cell_stats(v["t"]),
                                     "depth": cell_stats(v["depth"])}
                  for k, v in cells.items()},
        "gates": verdict_bits,
        "skipped": skipped,
    }
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)
    try:
        with open(os.path.join(outdir, "results.json")) as f:
            json.load(f)
    except Exception as ex:
        print("results.json re-read failed: %r" % ex)


if __name__ == "__main__":
    main()
