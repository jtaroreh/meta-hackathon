"""Screen 01 payload: qLDPC BP-guiding (phenomenological + circuit noise).

Self-contained: stdlib + numpy + ldpc + stim + pulp only.
Writes ALL output under cwd (the attempt work dir): results.json + witnesses/.
Deterministic given seeds. Never claims pursue/reject: verdict is always
unresolved-with-reason; classification is coordinator-side.
"""

import argparse
import hashlib
import json
import os
import time

import numpy as np

PHENO_D = (3, 5, 7)
PHENO_P = 0.06
PHENO_N = 300
SEEDS = (1, 2, 3, 4, 5)
CIRCUIT_D = (3, 5)
CIRCUIT_P = 0.005
CIRCUIT_N = 300
MAX_ITER = 30
LAT_CAP_US = 5000.0
MLD_D3_LIMIT = 30
MLD_D7_LIMIT = 10
MLD_D7_COUNT = 20
# Guard must fire before the supervisor's admitted deadline, not the
# nominal wall allowance: admission grants min(wall - screen_wall_used,
# run-remaining, cpu_remaining / capacity), minus 8.5 s handshake /
# termination / finalization overhead. With staged wall/cpu 900/5400 on
# 10-capacity, a prompt select->launch (~350 s of review) still admits
# ~540 s, so the 300 s guard fires with ample finalization reserve;
# checkpoints below preserve evidence regardless.
WALL_GUARD_S = 300.0

ARMS = ("A", "B1", "B2", "B3", "C", "R")
BP_CONF = {
    "A": ("parallel", 1.0),
    "B1": ("serial", 1.0),
    "B2": ("parallel", 0.625),
    "B3": ("serial", 0.625),
}


def rep_pc(d):
    H = np.zeros((d - 1, d), dtype=int)
    for i in range(d - 1):
        H[i, i] = 1
        H[i, i + 1] = 1
    return H


def hgp_mats(d):
    H = rep_pc(d)
    n, r = d, d - 1
    In, Ir = np.eye(n, dtype=int), np.eye(r, dtype=int)
    Hx = np.block([np.kron(H, In), np.kron(Ir, H.T)])
    Hz = np.block([np.kron(In, H), np.kron(H.T, Ir)])
    return H, Hx % 2, Hz % 2


def gf2_rank(M):
    A = (np.asarray(M, dtype=int) % 2).copy()
    m, n = A.shape
    rk = 0
    for c in range(n):
        piv = -1
        for i in range(rk, m):
            if A[i, c]:
                piv = i
                break
        if piv < 0:
            continue
        A[[rk, piv]] = A[[piv, rk]]
        for i in range(m):
            if i != rk and A[i, c]:
                A[i] ^= A[rk]
        rk += 1
    return rk


def self_tests():
    for d in (3, 5, 7):
        H, Hx, Hz = hgp_mats(d)
        n, r = d, d - 1
        N1, N2 = n * n, r * r
        assert Hx.shape == (r * n, N1 + N2)
        assert Hz.shape == (n * r, N1 + N2)
        assert np.array_equal((Hx @ Hz.T) % 2, np.zeros_like(Hx @ Hz.T))
        L = np.concatenate([np.ones(N1, dtype=int), np.zeros(N2, dtype=int)])
        assert np.array_equal((Hx @ L) % 2, np.zeros(Hx.shape[0], dtype=int))
        assert np.array_equal((Hz @ L) % 2, np.zeros(Hz.shape[0], dtype=int))
        ones = np.ones(n, dtype=int)
        assert gf2_rank(np.vstack([H, ones])) == gf2_rank(H) + 1
    rng = np.random.default_rng(1000 * 1 + 3)
    _, _, Hz3 = hgp_mats(3)
    e1 = (rng.random(Hz3.shape[1]) < PHENO_P).astype(int)
    e2 = (rng.random(Hz3.shape[1]) < PHENO_P).astype(int)
    s1, s2 = (Hz3 @ e1) % 2, (Hz3 @ e2) % 2
    assert np.array_equal((Hz3 @ ((e1 + e2) % 2)) % 2, (s1 + s2) % 2)
    return {"HxHz_orth": True, "logical_kernel": True, "logical_nontrivial": True,
            "syndrome_linearity": True}


def make_bp(H, error_rate, schedule, ms_scale, channel=None):
    import ldpc
    n = H.shape[1]
    kw = {"max_iter": MAX_ITER, "bp_method": "ms", "ms_scaling_factor": ms_scale}
    if channel is not None:
        if len(channel) != n:
            raise RuntimeError("channel_probs length %d != n %d" % (len(channel), n))
        kw["channel_probs"] = [float(v) for v in channel]
    else:
        kw["error_rate"] = error_rate
    try:
        dec = ldpc.bp_decoder(H, **kw)
    except TypeError:
        if channel is not None:
            raise
        dec = ldpc.bp_decoder(H, error_rate, MAX_ITER, "ms", ms_scale)
    dec.schedule = schedule
    if getattr(dec, "schedule", schedule) != schedule:
        raise RuntimeError("schedule %r not honored (got %r)" % (schedule, getattr(dec, "schedule", None)))
    return dec


def make_bposd(H, error_rate, channel=None):
    import ldpc
    n = H.shape[1]
    kw = {"max_iter": MAX_ITER, "bp_method": "ms", "osd_method": "osd_cs", "osd_order": 2}
    if channel is not None:
        if len(channel) != n:
            raise RuntimeError("channel_probs length %d != n %d" % (len(channel), n))
        kw["channel_probs"] = [float(v) for v in channel]
    else:
        kw["error_rate"] = error_rate
    try:
        return ldpc.bposd_decoder(H, **kw)
    except TypeError:
        if channel is not None:
            raise
        return ldpc.bposd_decoder(H, error_rate=error_rate, max_iter=MAX_ITER,
                                  bp_method="ms", osd_order=2)


def decode_with(dec, H, syndrome):
    est = dec.decode(np.asarray(syndrome, dtype=int))
    e = (np.asarray(est).round().astype(int) % 2).reshape(-1)
    if e.shape[0] != H.shape[1]:
        return None
    if not np.array_equal((H @ e) % 2, np.asarray(syndrome, dtype=int) % 2):
        return None
    return e


def run_arm_pheno(Hz, syndromes, errors, N1, arm, error_rate, channel=None):
    n = syndromes.shape[0]
    fails = conv = exc = 0
    times = []
    if arm == "R":
        for s, e in zip(syndromes, errors):
            t0 = time.perf_counter()
            est = np.zeros(Hz.shape[1], dtype=int)
            dt = time.perf_counter() - t0
            times.append(dt)
            if not np.array_equal((Hz @ est) % 2, s):
                conv += 1
                fails += 1
            elif int(np.sum(((e + est) % 2)[:N1]) % 2) == 1:
                fails += 1
    else:
        if arm == "C":
            dec = make_bposd(Hz, error_rate, channel)
        else:
            sched, scale = BP_CONF[arm]
            dec = make_bp(Hz, error_rate, sched, scale, channel)
        for s, e in zip(syndromes, errors):
            t0 = time.perf_counter()
            try:
                est = decode_with(dec, Hz, s)
            except Exception:
                est = None
                exc += 1
            dt = time.perf_counter() - t0
            times.append(dt)
            if est is None:
                conv += 1
                fails += 1
            elif int(np.sum(((e + est) % 2)[:N1]) % 2) == 1:
                fails += 1
    tus = [t * 1e6 for t in times]
    return {"n": n, "logical_fails": fails, "converge_fails": conv,
            "decode_exceptions": exc, "mean_us": float(sum(tus) / len(tus)),
            "max_us": float(max(tus))}


def parse_dem(circuit):
    dem = circuit.detector_error_model(decompose_errors=True).flattened()
    nd, no = dem.num_detectors, dem.num_observables
    hcols, lcols, priors = [], [], []
    dropped = 0
    for instr in dem:
        if instr.type != "error":
            continue
        p = float(instr.args_copy()[0])
        if not (0.0 < p < 1.0):
            continue
        det_set, obs_set = set(), set()
        for t in instr.targets_copy():
            if t.is_relative_detector_id():
                if t.val in det_set:
                    det_set.remove(t.val)
                else:
                    det_set.add(t.val)
            elif t.is_logical_observable_id():
                if t.val in obs_set:
                    obs_set.remove(t.val)
                else:
                    obs_set.add(t.val)
        dets = sorted(v for v in det_set if 0 <= v < nd)
        obss = sorted(v for v in obs_set if 0 <= v < max(no, 1))
        if len(dets) != len(det_set) or len(obss) != len(obs_set):
            dropped += 1
            continue
        hc = np.zeros(nd, dtype=int)
        hc[dets] = 1
        lc = np.zeros(max(no, 1), dtype=int)
        lc[obss] = 1
        hcols.append(hc)
        lcols.append(lc)
        priors.append(p)
    if nd == 0 or not hcols:
        raise RuntimeError("empty DEM parse (nd=%d, mechs=%d, dropped=%d)"
                           % (nd, len(hcols), dropped))
    return (np.stack(hcols, axis=1) % 2), (np.stack(lcols, axis=1) % 2), priors, nd, no, dropped


def run_arm_circuit(Hd, Lo, dets, obs_true, arm, error_rate, channel=None):
    n = dets.shape[0]
    fails = conv = exc = 0
    times = []
    if arm == "R":
        for i in range(n):
            t0 = time.perf_counter()
            est = np.zeros(Hd.shape[1], dtype=int)
            dt = time.perf_counter() - t0
            times.append(dt)
            if not np.array_equal((Hd @ est) % 2, dets[i] % 2):
                conv += 1
                fails += 1
            elif not np.array_equal((Lo @ est) % 2, obs_true[i] % 2):
                fails += 1
    else:
        if arm == "C":
            dec = make_bposd(Hd, error_rate, channel)
        else:
            sched, scale = BP_CONF[arm]
            dec = make_bp(Hd, error_rate, sched, scale, channel)
        for i in range(n):
            t0 = time.perf_counter()
            try:
                est = decode_with(dec, Hd, dets[i])
            except Exception:
                est = None
                exc += 1
            dt = time.perf_counter() - t0
            times.append(dt)
            if est is None:
                conv += 1
                fails += 1
            elif not np.array_equal((Lo @ est) % 2, obs_true[i] % 2):
                fails += 1
    tus = [t * 1e6 for t in times]
    return {"n": n, "logical_fails": fails, "converge_fails": conv,
            "decode_exceptions": exc, "mean_us": float(sum(tus) / len(tus)),
            "max_us": float(max(tus))}


def mld_decode(H, syndrome, time_limit):
    import pulp
    m, nn = H.shape
    s = (np.asarray(syndrome, dtype=int) % 2).tolist()
    t0 = time.perf_counter()
    try:
        prob = pulp.LpProblem("mld", pulp.LpMinimize)
        r = [prob.add_variable("r%d" % j, cat="Binary") for j in range(nn)]
        prob.setObjective(pulp.lpSum(r))
        for i in range(m):
            cols = [j for j in range(nn) if H[i, j]]
            w = len(cols)
            t = prob.add_variable("t%d" % i, lowBound=0, upBound=w // 2, cat="Integer")
            prob.addConstraint(pulp.lpSum([r[j] for j in cols]) - 2 * t == s[i])
        solver = pulp.COIN_CMD(msg=0, threads=1, timeLimit=time_limit)
        stats = prob.solve(solver)
        dt = time.perf_counter() - t0
        sname = getattr(stats.status, "name", None) or str(stats.status_str)
        sname = str(sname).split(".")[-1]
        return {"status": sname, "time_s": dt,
                "objective": stats.objective, "has_solution": bool(stats.has_solution),
                "solver": "COIN_CMD"}
    except Exception as ex:
        return {"status": "BUILD_ERROR: %s: %s" % (type(ex).__name__, ex),
                "time_s": time.perf_counter() - t0, "objective": None,
                "has_solution": False, "solver": "COIN_CMD"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--attempt", required=True)
    ap.add_argument("--data", required=True)
    args = ap.parse_args()
    t_start = time.perf_counter()
    outdir = os.getcwd()
    os.makedirs(os.path.join(outdir, "witnesses"), exist_ok=True)

    corpus_spec = {
        "pheno": {"d": list(PHENO_D), "p": PHENO_P, "n_per_cell": PHENO_N, "seeds": list(SEEDS),
                  "code": "HGP(rep(d),rep(d))", "error": "X", "matrix": "Hz"},
        "circuit": {"circuit": "surface_code:rotated_memory_x", "d": list(CIRCUIT_D),
                    "rounds": "d", "p": CIRCUIT_P, "shots_per_cell": CIRCUIT_N,
                    "seeds": list(SEEDS)},
        "arms": list(ARMS), "max_iter": MAX_ITER,
        "bp": {"A": ["parallel", "ms", 1.0], "B1": ["serial", "ms", 1.0],
               "B2": ["parallel", "ms", 0.625], "B3": ["serial", "ms", 0.625],
               "C": ["bposd", "osd_cs", 2]},
        "priors": "per-bit channel_probs everywhere (uniform-p list pheno; "
                  "DEM mechanism priors circuit; mean-prior list fallback recorded)",
    }
    corpus_sha = hashlib.sha256(json.dumps(corpus_spec, sort_keys=True).encode()).hexdigest()
    with open(os.path.join(outdir, "witnesses", "corpus_sha.txt"), "w") as f:
        f.write(corpus_sha + "\n" + json.dumps(corpus_spec, sort_keys=True) + "\n")

    st = self_tests()
    with open(os.path.join(outdir, "witnesses", "selftest.json"), "w") as f:
        json.dump(st, f, indent=1)

    cells = []
    pheno_syn = {}
    gate3 = {"d3": None, "d7": [], "skipped": []}
    circuit_blocker = None
    circuit_meta = {}

    def elapsed():
        return time.perf_counter() - t_start

    def skipped_tally(code, noise, seed, arm, reason):
        return {"code": code, "noise": noise, "seed": seed, "arm": arm, "n": 0,
                "logical_fails": 0, "converge_fails": 0, "decode_exceptions": 0,
                "mean_us": 0.0, "max_us": 0.0, "skipped": reason}

    def checkpoint(tag):
        """Best-effort partial evidence so a supervisor stop still leaves
        the accumulated tallies (final results.json is written only at
        normal completion). Coordinator-side classification can apply the
        same gate rules to a checkpoint's cells."""
        try:
            with open(os.path.join(outdir, "witnesses",
                                   "checkpoint-%s.json" % tag), "w") as f:
                json.dump({"tag": tag, "wall_s": elapsed(), "cells": cells,
                           "gate3": gate3,
                           "circuit_blocked": circuit_blocker,
                           "verdict": "unresolved-with-reason: partial "
                                      "checkpoint (supervisor stop may have "
                                      "preempted final results.json)"},
                          f, indent=1, default=str)
        except Exception:
            pass

    for d in PHENO_D:
        _, _, Hz = hgp_mats(d)
        N1 = d * d
        chan_pheno = [PHENO_P] * Hz.shape[1]
        for seed in SEEDS:
            if elapsed() > WALL_GUARD_S:
                for arm in ARMS:
                    cells.append(skipped_tally("hgp_d%d" % d, "pheno_p0.06", seed, arm,
                                               "wall-guard"))
                continue
            rng = np.random.default_rng(1000 * seed + d)
            errors = (rng.random((PHENO_N, Hz.shape[1])) < PHENO_P).astype(int)
            syndromes = (errors @ Hz.T) % 2
            pheno_syn[(d, seed)] = syndromes
            for arm in ARMS:
                if elapsed() > WALL_GUARD_S:
                    cells.append(skipped_tally("hgp_d%d" % d, "pheno_p0.06", seed, arm,
                                               "wall-guard"))
                    continue
                tally = run_arm_pheno(Hz, syndromes, errors, N1, arm, PHENO_P, chan_pheno)
                tally.update({"code": "hgp_d%d" % d, "noise": "pheno_p0.06",
                              "seed": seed, "arm": arm})
                cells.append(tally)

    det_check = {}
    for d in PHENO_D:
        _, _, Hz = hgp_mats(d)
        chan_det = [PHENO_P] * Hz.shape[1]
        if (d, 1) not in pheno_syn:
            det_check["d%d" % d] = "skipped-no-corpus"
            continue
        s = pheno_syn[(d, 1)][0]
        e1 = decode_with(make_bp(Hz, PHENO_P, "parallel", 1.0, chan_det), Hz, s)
        e2 = decode_with(make_bp(Hz, PHENO_P, "parallel", 1.0, chan_det), Hz, s)
        det_check["d%d" % d] = (e1 is None and e2 is None) or (
            e1 is not None and e2 is not None and bool(np.array_equal(e1, e2)))
    with open(os.path.join(outdir, "witnesses", "determinism.json"), "w") as f:
        json.dump(det_check, f, indent=1)
    checkpoint("pheno")

    for d in CIRCUIT_D:
        if circuit_blocker is None:
            try:
                import stim
                circ = stim.Circuit.generated(
                    "surface_code:rotated_memory_x", distance=d, rounds=d,
                    after_clifford_depolarization=CIRCUIT_P)
                Hd, Lo, priors, nd, no, dropped = parse_dem(circ)
                circuit_meta["d%d" % d] = {"num_detectors": nd, "num_observables": no,
                                           "num_mechanisms": len(priors),
                                           "dropped_mechanisms": dropped}
                for seed in SEEDS:
                    sampler = circ.compile_detector_sampler(seed=seed)
                    dets, obs = sampler.sample(shots=CIRCUIT_N, separate_observables=True)
                    dets = (np.asarray(dets, dtype=int) % 2)
                    obs = (np.asarray(obs, dtype=int) % 2).reshape(CIRCUIT_N, -1)
                    Lo_use = Lo
                    if Lo.shape[0] != obs.shape[1]:
                        raise RuntimeError("observable dim mismatch dem=%d sampler=%d"
                                           % (Lo.shape[0], obs.shape[1]))
                    erate = float(sum(priors) / len(priors))
                    if len(priors) == Hd.shape[1]:
                        chan = [float(v) for v in priors]
                        chan_kind = "per-mechanism-priors"
                    else:
                        chan = [erate] * Hd.shape[1]
                        chan_kind = "mean-prior-fallback"
                    circuit_meta["d%d" % d]["error_rate"] = chan_kind
                    order = ["A", "B1", "B2", "B3", "R", "C"]
                    for arm in order:
                        if elapsed() > WALL_GUARD_S:
                            cells.append({"code": "rotmemx_d%d" % d, "noise": "circuit_p0.005",
                                          "seed": seed, "arm": arm, "n": 0, "logical_fails": 0,
                                          "converge_fails": 0, "decode_exceptions": 0,
                                          "mean_us": 0.0, "max_us": 0.0, "skipped": "wall-guard"})
                            continue
                        tally = run_arm_circuit(Hd, Lo_use, dets, obs, arm, erate, chan)
                        tally.update({"code": "rotmemx_d%d" % d, "noise": "circuit_p0.005",
                                      "seed": seed, "arm": arm})
                        cells.append(tally)
            except Exception as ex:
                circuit_blocker = "%s: %s" % (type(ex).__name__, ex)
                for seed in SEEDS:
                    for arm in ARMS:
                        cells.append({"code": "rotmemx_d%d" % d, "noise": "circuit_p0.005",
                                      "seed": seed, "arm": arm, "n": 0, "logical_fails": 0,
                                      "converge_fails": 0, "decode_exceptions": 0,
                                      "mean_us": 0.0, "max_us": 0.0, "blocked": circuit_blocker})
        else:
            for seed in SEEDS:
                for arm in ARMS:
                    cells.append({"code": "rotmemx_d%d" % d, "noise": "circuit_p0.005",
                                  "seed": seed, "arm": arm, "n": 0, "logical_fails": 0,
                                  "converge_fails": 0, "decode_exceptions": 0,
                                  "mean_us": 0.0, "max_us": 0.0, "blocked": circuit_blocker})

    checkpoint("circuit")

    _, _, Hz3 = hgp_mats(3)
    syn3 = pheno_syn[(3, 1)][0] if (3, 1) in pheno_syn else None
    syn7 = pheno_syn.get((7, 1))
    if elapsed() > WALL_GUARD_S or syn3 is None:
        g3 = {"status": "SKIPPED_WALL_GUARD", "d": 3, "time_s": 0.0,
              "objective": None, "has_solution": False, "solver": "COIN_CMD"}
        gate3["d3"] = g3
        gate3["skipped"].append("d3")
    else:
        g3 = mld_decode(Hz3, syn3, MLD_D3_LIMIT)
        g3["d"] = 3
        gate3["d3"] = g3
    with open(os.path.join(outdir, "witnesses", "gate3_d3.json"), "w") as f:
        json.dump({"syndrome": None if syn3 is None else syn3.tolist(),
                   "result": gate3["d3"]}, f, indent=1)
    checkpoint("gate3-d3")
    _, _, Hz7 = hgp_mats(7)
    for k in range(MLD_D7_COUNT):
        if elapsed() > WALL_GUARD_S or syn7 is None:
            gate3["skipped"].append(k)
            continue
        r = mld_decode(Hz7, syn7[k], MLD_D7_LIMIT)
        r["d"] = 7
        gate3["d7"].append(r)
    with open(os.path.join(outdir, "witnesses", "gate3_d7.json"), "w") as f:
        json.dump(gate3["d7"], f, indent=1)
    checkpoint("gate3-d7")

    def lookup(code, noise, seed, arm):
        for c in cells:
            if (c["code"], c["noise"], c["seed"], c["arm"]) == (code, noise, seed, arm):
                return c
        return None

    gaps = []
    for d in PHENO_D:
        code = "hgp_d%d" % d
        for seed in SEEDS:
            a = lookup(code, "pheno_p0.06", seed, "A")
            c = lookup(code, "pheno_p0.06", seed, "C")
            row = {"code": code, "noise": "pheno_p0.06", "seed": seed}
            if a["n"] and c["n"]:
                fa, fc = a["logical_fails"] / a["n"], c["logical_fails"] / c["n"]
                row.update({"fail_A": fa, "fail_C": fc, "gap": fa - fc})
                best, bestf = None, None
                for b in ("B1", "B2", "B3"):
                    bb = lookup(code, "pheno_p0.06", seed, b)
                    if not bb["n"]:
                        row[b] = {"fail": None, "recovered_frac": None,
                                  "mean_us": 0.0, "skipped": True}
                        continue
                    fb = bb["logical_fails"] / bb["n"]
                    frac = ((fa - fb) / (fa - fc)) if (fa - fc) > 0 else None
                    row[b] = {"fail": fb, "recovered_frac": frac, "mean_us": bb["mean_us"]}
                    if best is None or (fb, bb["mean_us"]) < bestf:
                        best, bestf = b, (fb, bb["mean_us"])
                row["best_B"] = best
            gaps.append(row)
    for d in CIRCUIT_D:
        code = "rotmemx_d%d" % d
        for seed in SEEDS:
            a = lookup(code, "circuit_p0.005", seed, "A")
            c = lookup(code, "circuit_p0.005", seed, "C")
            row = {"code": code, "noise": "circuit_p0.005", "seed": seed}
            if a.get("blocked") or c.get("blocked") or not a["n"] or not c["n"]:
                row["unavailable"] = a.get("blocked") or c.get("blocked") or "missing-tally"
            else:
                fa, fc = a["logical_fails"] / a["n"], c["logical_fails"] / c["n"]
                row.update({"fail_A": fa, "fail_C": fc, "gap": fa - fc})
            gaps.append(row)

    g1 = all(lookup("hgp_d%d" % d, "pheno_p0.06", s, "A")["logical_fails"]
             < lookup("hgp_d%d" % d, "pheno_p0.06", s, "R")["logical_fails"]
             for d in PHENO_D for s in SEEDS)
    g2 = bool(det_check) and all(v is True for v in det_check.values()) and bool(corpus_sha)
    nonflat = 0
    for d in PHENO_D:
        code = "hgp_d%d" % d
        rates = []
        for arm in ("A", "B1", "B2", "B3", "C"):
            F = sum(lookup(code, "pheno_p0.06", s, arm)["logical_fails"] for s in SEEDS)
            Nn = sum(lookup(code, "pheno_p0.06", s, arm)["n"] for s in SEEDS)
            rates.append(F / Nn if Nn else 0.0)
        Nn = sum(lookup(code, "pheno_p0.06", s, "A")["n"] for s in SEEDS)
        se = (max(rates) * (1 - max(rates)) / Nn) ** 0.5 if Nn else 0.0
        if Nn and (max(rates) - min(rates)) > 2 * se + 1e-12:
            nonflat += 1
    g3pass = ((gate3["d3"] or {}).get("status") == "Optimal"
              and any(r.get("status") == "TimeLimit" for r in gate3["d7"]))
    planned = len(PHENO_D) * len(SEEDS) * len(ARMS) + len(CIRCUIT_D) * len(SEEDS) * len(ARMS)
    g4 = (len([c for c in cells if c["n"] == (PHENO_N if "hgp" in c["code"] else CIRCUIT_N)
               and not c.get("blocked") and not c.get("skipped")]) == planned
          and elapsed() < 500.0)
    gates = {
        "gate1_bp_beats_null": {"pass": bool(g1), "evidence": ["cells: arm A vs R logical_fails, all pheno cells"]},
        "gate2_nonflat": {"pass": bool(nonflat >= 2),
                          "evidence": ["gaps tallies pooled per size; sizes_passed=%d" % nonflat]},
        "control_determinism": {"pass": bool(g2), "evidence": ["witnesses/selftest.json",
                                "witnesses/determinism.json", "witnesses/corpus_sha.txt"]},
        "gate3_mld": {"pass": bool(g3pass), "evidence": ["witnesses/gate3_d3.json",
                       "witnesses/gate3_d7.json"]},
        "gate4_completeness": {"pass": bool(g4), "evidence": ["cells tallies n=300 + timing"]},
    }

    wall = elapsed()
    results = {
        "screen": "01", "attempt": args.attempt, "data": args.data,
        "corpus": dict(corpus_spec, sha=corpus_sha),
        "cells": cells, "gaps": gaps, "gates": gates, "gate3": gate3,
        "circuit": {"meta": circuit_meta, "blocked": circuit_blocker},
        "acceptance": {"rule": "PURSUE iff best-B recovers >=25% of (fail_A-fail_C) at >=2 pheno sizes "
                       "with mean latency <=5000us AND gap>0 at >=1 circuit size AND gates 1,2,4 pass "
                       "AND gate-3 CBC expiry at d=7",
                       "latency_cap_us": LAT_CAP_US, "inputs": "see gaps + cells mean_us"},
        "timing": {"wall_s": wall},
        "verdict": ("unresolved-with-reason: payload reports measurements and gate evidence only; "
                    "scientific pursue/reject classification is coordinator-side"),
    }
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump(results, f, indent=1)


if __name__ == "__main__":
    main()


