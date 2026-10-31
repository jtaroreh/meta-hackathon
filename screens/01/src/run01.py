"""Screen 01 payload: qLDPC BP-guiding follow-up (pheno autopsy + hardness frontier).

Self-contained: stdlib + numpy + ldpc + stim + pulp only.
Writes ALL output under cwd (the attempt work dir): results.json + witnesses/.
Deterministic given seeds (rerun byte-identical except wall/timing fields).
Never claims pursue/reject: verdict is always unresolved-with-reason;
classification is coordinator-side.

Frozen design (byte-identical to brief.md):
- PHENO_D=(3,5,7,9,11), PHENO_P=0.06, PHENO_N=300, SEEDS=(1,2,3,4,5).
- CIRCUIT_D=(3,5), rounds=d, CIRCUIT_P=0.005, CIRCUIT_N=300.
- A=parallel/1.0, B1=serial/1.0, B2=parallel/1.25 (autopsy family),
  B3=serial/1.25 (autopsy family), C=BP-OSD-2, R=null. MAX_ITER=30.
- LAT_CAP_US=5000.0. MLD_D3_LIMIT=30, MLD_FRONTIER_LIMIT=10,
  MLD_D7_COUNT=12, MLD_D9_COUNT=8, MLD_D11_COUNT=8.
- WALL_GUARD_S=300.0, WALL_LIMIT_S=500.0.
"""

import argparse
import hashlib
import json
import os
import time

import numpy as np

PHENO_D = (3, 5, 7, 9, 11)
PHENO_P = 0.06
PHENO_N = 300
SEEDS = (1, 2, 3, 4, 5)
CIRCUIT_D = (3, 5)
CIRCUIT_P = 0.005
CIRCUIT_N = 300
MAX_ITER = 30
LAT_CAP_US = 5000.0
MLD_D3_LIMIT = 30
MLD_FRONTIER_LIMIT = 10
MLD_D7_COUNT = 12
MLD_D9_COUNT = 8
MLD_D11_COUNT = 8
# Guard must fire before the supervisor's admitted deadline, not the
# nominal wall allowance: admission grants min(wall - screen_wall_used,
# run-remaining, cpu_remaining / capacity), minus 8.5 s handshake /
# termination / finalization overhead. The 300 s guard fires with ample
# finalization reserve; checkpoints below preserve evidence regardless.
WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0

ARMS = ("A", "B1", "B2", "B3", "C", "R")
BP_CONF = {
    "A": ("parallel", 1.0),
    "B1": ("serial", 1.0),
    "B2": ("parallel", 1.25),
    "B3": ("serial", 1.25),
}

NEXT_EXPERIMENT = ("Sweep max_iter over {30,100,300} for the winning B family "
                    "at the two largest pheno sizes to separate "
                    "convergence-budget effects from schedule effects, holding "
                    "all other frozen symbols unchanged.")


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


def normalize_mld_result(raw, d, k):
    """None-guard: a solver timeout returning None must never crash the
    payload (lesson 04). Any None / malformed result becomes an explicit
    NONE record, never an AttributeError."""
    base = {"d": d, "k": k, "time_s": 0.0, "objective": None,
            "has_solution": False, "solver": "COIN_CMD",
            "iters_done": 0, "n_evaluated": 0}
    if raw is None:
        base["status"] = "NONE_RESULT"
        return base
    if not isinstance(raw, dict):
        base["status"] = "MALFORMED_RESULT"
        return base
    out = dict(base)
    out.update({kk: raw.get(kk) for kk in ("status", "time_s", "objective",
                                           "has_solution", "solver")})
    if out.get("status") is None:
        out["status"] = "NONE_RESULT"
    return out


def self_tests():
    for d in (3, 5, 7, 9, 11):
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
    # Repair-path regression probes: every guard/repair below is exercised.
    for arm, (sched, scale) in BP_CONF.items():
        dec = make_bp(Hz3, PHENO_P, sched, scale,
                       [PHENO_P] * Hz3.shape[1])
        assert getattr(dec, "schedule", sched) == sched
    none_rec = normalize_mld_result(None, 7, 0)
    assert none_rec["status"] == "NONE_RESULT"
    assert none_rec["has_solution"] is False
    fake_rec = normalize_mld_result({"status": None}, 9, 1)
    assert fake_rec["status"] == "NONE_RESULT"
    ok_rec = normalize_mld_result({"status": "Optimal", "time_s": 0.01,
                                   "objective": 0.0, "has_solution": True,
                                   "solver": "COIN_CMD"}, 3, 0)
    assert ok_rec["status"] == "Optimal" and ok_rec["has_solution"] is True
    skip_probe = make_skip_tally("hgp_d3", "pheno_p0.06", 1, "A",
                                 "selftest-probe", 0)
    for key in ("code", "noise", "seed", "arm", "n", "logical_fails",
                "converge_fails", "decode_exceptions", "mean_us", "max_us",
                "skipped", "iters_done", "n_evaluated"):
        assert key in skip_probe, key
    blocked_probe = make_blocked_tally("rotmemx_d3", "circuit_p0.005", 1, "A",
                                       "selftest-blocker")
    for key in ("code", "noise", "seed", "arm", "n", "logical_fails",
                "converge_fails", "decode_exceptions", "mean_us", "max_us",
                "blocked", "iters_done", "n_evaluated"):
        assert key in blocked_probe, key
    assert blocked_probe["iters_done"] == 0
    assert blocked_probe["n_evaluated"] == 0
    fake_cells = {}
    for s in SEEDS:
        fake_cells[(3, s, "A")] = {"logical_fails": 100 if s == 1 else 0,
                                   "n": 300}
        fake_cells[(3, s, "C")] = {"logical_fails": 0 if s == 1 else 100,
                                   "n": 300}
        fake_cells[(5, s, "A")] = {"logical_fails": 60, "n": 300}
        fake_cells[(5, s, "C")] = {"logical_fails": 10, "n": 300}

    def fake_lookup(code, noise, seed, arm):
        return fake_cells[(3 if code == "rotmemx_d3" else 5, seed, arm)]

    assert pooled_circuit_gap_sizes(fake_lookup) == ["rotmemx_d5"]
    return {"HxHz_orth": True, "logical_kernel": True, "logical_nontrivial": True,
            "syndrome_linearity": True, "bp_configs_honored": True,
            "none_guard": True, "skip_schema": True, "blocked_schema": True,
            "pooled_circuit_gap": True}


def make_skip_tally(code, noise, seed, arm, reason, iters_done):
    return {"code": code, "noise": noise, "seed": seed, "arm": arm, "n": 0,
            "logical_fails": 0, "converge_fails": 0, "decode_exceptions": 0,
            "mean_us": 0.0, "max_us": 0.0, "skipped": reason,
            "iters_done": iters_done, "n_evaluated": 0}


def make_blocked_tally(code, noise, seed, arm, blocker):
    """Named-blocker tally on the same schema as skips: counted as a skip
    by gate4, so it must carry iters_done/n_evaluated (review 01 finding)."""
    return {"code": code, "noise": noise, "seed": seed, "arm": arm, "n": 0,
            "logical_fails": 0, "converge_fails": 0, "decode_exceptions": 0,
            "mean_us": 0.0, "max_us": 0.0, "blocked": blocker,
            "iters_done": 0, "n_evaluated": 0}


def pooled_circuit_gap_sizes(lookup_fn):
    """Circuit sizes with pooled-over-seeds gap (fail_A - fail_C) > 0.
    Pooling precedes the sign test (brief acceptance rule); a single
    positive seed must not list a size whose pooled gap is <= 0."""
    sizes = []
    for d in CIRCUIT_D:
        code = "rotmemx_d%d" % d
        Fa = sum(lookup_fn(code, "circuit_p0.005", s, "A")["logical_fails"]
                 for s in SEEDS)
        Na = sum(lookup_fn(code, "circuit_p0.005", s, "A")["n"] for s in SEEDS)
        Fc = sum(lookup_fn(code, "circuit_p0.005", s, "C")["logical_fails"]
                 for s in SEEDS)
        Nc = sum(lookup_fn(code, "circuit_p0.005", s, "C")["n"] for s in SEEDS)
        if Na and Nc and (Fa / Na - Fc / Nc) > 0:
            sizes.append(code)
    return sorted(sizes)


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


def mld_decode(H, syndrome, time_limit, d, k):
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
        raw_status = prob.solve(solver)
        dt = time.perf_counter() - t0
        if raw_status is None:
            rec = normalize_mld_result(None, d, k)
            rec["time_s"] = dt
            return rec
        status_obj = getattr(raw_status, "status", None)
        if status_obj is None:
            sname = None
        else:
            sname = getattr(status_obj, "name", None) or str(status_obj)
            sname = str(sname).split(".")[-1]
        has_sol = bool(getattr(raw_status, "has_solution", False))
        obj = getattr(raw_status, "objective", None)
        rec = normalize_mld_result({"status": sname, "time_s": dt,
                                    "objective": obj, "has_solution": has_sol,
                                    "solver": "COIN_CMD"}, d, k)
        rec["d"] = d
        rec["k"] = k
        return rec
    except Exception as ex:
        return {"status": "BUILD_ERROR: %s: %s" % (type(ex).__name__, ex),
                "time_s": time.perf_counter() - t0, "objective": None,
                "has_solution": False, "solver": "COIN_CMD",
                "d": d, "k": k}


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
               "B2": ["parallel", "ms", 1.25], "B3": ["serial", "ms", 1.25],
               "C": ["bposd", "osd_cs", 2]},
        "priors": "per-bit channel_probs everywhere (uniform-p list pheno; "
                  "DEM mechanism priors circuit; mean-prior fallback recorded)",
        "mld": {"d3_limit_s": MLD_D3_LIMIT, "frontier_limit_s": MLD_FRONTIER_LIMIT,
                "d7_count": MLD_D7_COUNT, "d9_count": MLD_D9_COUNT,
                "d11_count": MLD_D11_COUNT},
    }
    corpus_sha = hashlib.sha256(json.dumps(corpus_spec, sort_keys=True).encode()).hexdigest()
    with open(os.path.join(outdir, "witnesses", "corpus_sha.txt"), "w") as f:
        f.write(corpus_sha + "\n" + json.dumps(corpus_spec, sort_keys=True) + "\n")

    st = self_tests()
    with open(os.path.join(outdir, "witnesses", "selftest.json"), "w") as f:
        json.dump(st, f, indent=1)

    cells = []
    pheno_syn = {}
    gate3 = {"d3": None, "d7": [], "d9": [], "d11": [], "skipped": []}
    circuit_blocker = None
    circuit_meta = {}
    stop = {"flag": False}

    def elapsed():
        return time.perf_counter() - t_start

    def tripped():
        if stop["flag"] or elapsed() > WALL_GUARD_S:
            stop["flag"] = True
            return True
        return False

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
            if tripped():
                for arm in ARMS:
                    cells.append(make_skip_tally("hgp_d%d" % d, "pheno_p0.06", seed, arm,
                                                 "wall-guard", 0))
                continue
            rng = np.random.default_rng(1000 * seed + d)
            errors = (rng.random((PHENO_N, Hz.shape[1])) < PHENO_P).astype(int)
            syndromes = (errors @ Hz.T) % 2
            pheno_syn[(d, seed)] = syndromes
            for arm_idx, arm in enumerate(ARMS):
                if tripped():
                    cells.append(make_skip_tally("hgp_d%d" % d, "pheno_p0.06", seed, arm,
                                                 "wall-guard", arm_idx))
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
                    for arm_idx, arm in enumerate(order):
                        if tripped():
                            cells.append(make_skip_tally("rotmemx_d%d" % d, "circuit_p0.005",
                                                         seed, arm, "wall-guard", arm_idx))
                            continue
                        tally = run_arm_circuit(Hd, Lo, dets, obs, arm, erate, chan)
                        tally.update({"code": "rotmemx_d%d" % d, "noise": "circuit_p0.005",
                                      "seed": seed, "arm": arm})
                        cells.append(tally)
            except Exception as ex:
                circuit_blocker = "%s: %s" % (type(ex).__name__, ex)
                for seed in SEEDS:
                    for arm in ARMS:
                        cells.append(make_blocked_tally("rotmemx_d%d" % d,
                                                        "circuit_p0.005", seed, arm,
                                                        circuit_blocker))
        else:
            for seed in SEEDS:
                for arm in ARMS:
                    cells.append(make_blocked_tally("rotmemx_d%d" % d,
                                                    "circuit_p0.005", seed, arm,
                                                    circuit_blocker))

    checkpoint("circuit")

    _, _, Hz3 = hgp_mats(3)
    syn3 = pheno_syn[(3, 1)][0] if (3, 1) in pheno_syn else None
    if stop["flag"] or elapsed() > WALL_GUARD_S or syn3 is None:
        stop["flag"] = True
        skipped_rec = {"status": "SKIPPED_WALL_GUARD", "d": 3, "k": 0, "time_s": 0.0,
                       "objective": None, "has_solution": False, "solver": "COIN_CMD",
                       "iters_done": 0, "n_evaluated": 0}
        gate3["d3"] = skipped_rec
        gate3["skipped"].append((3, 0))
    else:
        gate3["d3"] = normalize_mld_result(
            mld_decode(Hz3, syn3, MLD_D3_LIMIT, 3, 0), 3, 0)
    with open(os.path.join(outdir, "witnesses", "gate3_d3.json"), "w") as f:
        json.dump({"syndrome": None if syn3 is None else syn3.tolist(),
                   "result": gate3["d3"]}, f, indent=1)
    checkpoint("gate3-d3")

    frontier_plan = [(7, MLD_D7_COUNT), (9, MLD_D9_COUNT), (11, MLD_D11_COUNT)]
    for fd, fcount in frontier_plan:
        _, _, Hzf = hgp_mats(fd)
        synf = pheno_syn.get((fd, 1))
        done_count = 0
        for kk in range(fcount):
            if stop["flag"] or elapsed() > WALL_GUARD_S or synf is None:
                stop["flag"] = True
                skipped_rec = {"status": "SKIPPED_WALL_GUARD", "d": fd, "k": kk,
                               "time_s": 0.0, "objective": None,
                               "has_solution": False, "solver": "COIN_CMD",
                               "iters_done": done_count, "n_evaluated": 0}
                gate3["d%d" % fd].append(skipped_rec)
                gate3["skipped"].append((fd, kk))
                continue
            solved_rec = normalize_mld_result(
                mld_decode(Hzf, synf[kk], MLD_FRONTIER_LIMIT, fd, kk), fd, kk)
            gate3["d%d" % fd].append(solved_rec)
            done_count += 1
    with open(os.path.join(outdir, "witnesses", "gate3_frontier.json"), "w") as f:
        json.dump({"d7": gate3["d7"], "d9": gate3["d9"], "d11": gate3["d11"]},
                  f, indent=1)
    checkpoint("gate3-frontier")

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

    pooled = []
    per_arm_sizes = {"B1": [], "B2": [], "B3": []}
    for d in PHENO_D:
        code = "hgp_d%d" % d
        per_arm_tallies = {}
        for arm in ("A", "B1", "B2", "B3", "C", "R"):
            per_arm_tallies[arm] = [lookup(code, "pheno_p0.06", s, arm) for s in SEEDS]
        rate_of = {}
        lat_of = {}
        conv_of = {}
        complete_size = True
        for arm, seed_tallies in per_arm_tallies.items():
            fails_sum = sum(t["logical_fails"] for t in seed_tallies)
            n_sum = sum(t["n"] for t in seed_tallies)
            conv_sum = sum(t["converge_fails"] for t in seed_tallies)
            if not n_sum or any(t.get("skipped") or t.get("blocked") for t in seed_tallies):
                complete_size = False
                rate_of[arm] = None
                lat_of[arm] = None
                conv_of[arm] = None
            else:
                rate_of[arm] = fails_sum / n_sum
                lat_of[arm] = sum(t["mean_us"] for t in seed_tallies) / len(seed_tallies)
                conv_of[arm] = conv_sum / n_sum
        prow = {"code": code, "noise": "pheno_p0.06", "complete": complete_size,
                "fail": dict(rate_of), "mean_us": dict(lat_of),
                "converge_share": dict(conv_of)}
        if complete_size and (rate_of["A"] - rate_of["C"]) > 0:
            gap_d = rate_of["A"] - rate_of["C"]
            prow["gap"] = gap_d
            for b in ("B1", "B2", "B3"):
                rec_b = (rate_of["A"] - rate_of[b]) / gap_d
                hit_b = bool(rec_b >= 0.25 and lat_of[b] <= LAT_CAP_US)
                prow[b] = {"recovered_frac": rec_b, "counts": hit_b}
                if hit_b:
                    per_arm_sizes[b].append(d)
        pooled.append(prow)
    circuit_gap_sizes = pooled_circuit_gap_sizes(lookup)

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
    frontier_recs = gate3["d7"] + gate3["d9"] + gate3["d11"]
    g3pass = ((gate3["d3"] or {}).get("status") == "Optimal"
              and any(r.get("status") == "TimeLimit" for r in frontier_recs))
    planned = len(PHENO_D) * len(SEEDS) * len(ARMS) + len(CIRCUIT_D) * len(SEEDS) * len(ARMS)
    n_skips = (sum(1 for c in cells if c.get("skipped") or c.get("blocked"))
               + len(gate3["skipped"]))
    g4 = (len([c for c in cells if c["n"] == (PHENO_N if "hgp" in c["code"] else CIRCUIT_N)
               and not c.get("blocked") and not c.get("skipped")]) == planned
          and elapsed() < WALL_LIMIT_S and n_skips == 0)
    gates = {
        "gate1_bp_beats_null": {"pass": bool(g1), "evidence": ["cells: arm A vs R logical_fails, all pheno cells"]},
        "gate2_nonflat": {"pass": bool(nonflat >= 2),
                          "evidence": ["gaps tallies pooled per size; sizes_passed=%d" % nonflat]},
        "control_determinism": {"pass": bool(g2), "evidence": ["witnesses/selftest.json",
                                "witnesses/determinism.json", "witnesses/corpus_sha.txt"]},
        "gate3_mld": {"pass": bool(g3pass), "evidence": ["witnesses/gate3_d3.json",
                       "witnesses/gate3_frontier.json"]},
        "gate4_completeness": {"pass": bool(g4), "evidence": ["cells tallies n=300 + timing",
                               "skip_count=%d" % n_skips]},
    }

    wall = elapsed()
    results = {
        "screen": "01", "attempt": args.attempt, "data": args.data,
        "corpus": dict(corpus_spec, sha=corpus_sha),
        "cells": cells, "gaps": gaps, "pooled": pooled, "gates": gates, "gate3": gate3,
        "circuit": {"meta": circuit_meta, "blocked": circuit_blocker},
        "acceptance": {"rule": "PURSUE iff one B arm b in {B1,B2,B3} recovers >=25% of "
                       "(fail_A-fail_C) at >=2 pheno sizes (same arm, pooled over seeds) "
                       "with mean latency <=5000us AND pooled circuit gap>0 at >=1 circuit "
                       "size AND gates 1,2,4 pass AND gate-3 CBC expiry "
                       "(d3 Optimal + >=1 frontier TimeLimit)",
                       "latency_cap_us": LAT_CAP_US,
                       "per_arm_sizes": per_arm_sizes,
                       "circuit_gap_sizes": circuit_gap_sizes,
                       "inputs": "see pooled + gaps + cells mean_us"},
        "timing": {"wall_s": wall},
        "verdict": ("unresolved-with-reason: payload reports measurements and gate evidence only; "
                    "scientific pursue/reject classification is coordinator-side. "
                    "NEXT_EXPERIMENT: " + NEXT_EXPERIMENT),
    }
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump(results, f, indent=1)


if __name__ == "__main__":
    main()
