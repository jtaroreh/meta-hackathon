"""Screen 22 payload: bosonic stabilization with discrete sequences.

Screen-authored truncated-Fock (N<=32) bosonic-mode simulator
(stdlib + numpy only): one bosonic mode per rep prepared in a
seeded logical superposition of frozen code words (two cat-code
families, one binomial-code family), subject to a photon-loss
channel at one of two frozen loss regimes per rep, interleaved
with a discrete L_SEQ-slot stabilization sequence (SNAP-like
diagonal phase kicks plus a two-photon-drive refill, both from
frozen discrete alphabets). Arms: S fixed SNAP-echo schedule
(the decomposed baseline), R seeded random sequence control,
G greedy first-improvement discrete-sequence search from the S
start, A simulated annealing over sequences
(cost = infidelity + LAMBDA * boundary). Metric: logical
infidelity at fixed time (primary, lower is better) plus
integrated-fidelity lifetime (secondary, higher is better) and
a truncation-artifact guard (boundary population; any cell
with an artifact rep is flagged and blocks pursue). A
bounded-exact level-order branch-and-bound over sequences
solves the tiny instance (optimum by construction) and
cap-hits at target scale (limit-expiry). Writes ALL output
under cwd (the attempt work dir): results.json + witnesses/.
Deterministic given seeds. Verdict is always
unresolved-with-reason; classification is coordinator-side.
"""

import argparse
import json
import math
import os
import time

import numpy as np

N_TRUNC = (16, 24, 32)
FAMILIES = {16: "CAT_A2", 24: "CAT_A4", 32: "BINOM_11"}
ALPHA_SQ = {16: 2.0, 24: 4.0, 32: 6.0}
SEEDS = (1, 2, 3, 4, 5)
ARMS = ("S", "R", "G", "A")
KAPPA_GRID = (0.03, 0.08)
KAPPA_PHI = (0.015, 0.04)
DT = 0.25
T_STEPS = 8
L_SEQ = 7
N_PHASE = 3
PHASE_VALS = (-1.0, 0.0, 1.0)
PHASE_SCALE = 0.3
N_PUMP = 2
REFILL_R = 0.12
N_COMBOS = 6
S_SEQ = (0, 2, 4, 2, 0, 2, 4)
IDENT_SEQ = (2, 2, 2, 2, 2, 2, 2)
GREEDY_SWEEPS = 2
ANNEAL_ITERS = 60
ANNEAL_T0 = 0.02
ANNEAL_ALPHA = 0.97
LAMBDA = 10.0
BOUND_EDGE = 4
BOUND_THRESH = 0.01
CONV_TOL = 0.05
N_INST = 8
WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0
EXACT_CAP = 50000
TINY_N = 4
TINY_ALPHA_SQ = 0.25
TINY_KAPPA = 0.0
TINY_T = 2
TINY_L = 1
TINY_PHASES = (0.0, 0.5)
TINY_OPT_INFID = 0.0
TINY_S_SEQ = (1,)
TINY_TH = 1.1
TINY_PHI = 0.4
TARGET = {"size_idx": 2, "seed": 1, "rep": 0}
NEXT_EXPERIMENT = "closed-loop per-shot adaptive SNAP-displacement sequencing with photon-number-resolved feedback plus Kerr-regularized annealing retest"


def annihilator_op(dim_n):
    low_mat = np.zeros((dim_n, dim_n))
    for lvl_k in range(1, dim_n):
        low_mat[lvl_k - 1, lvl_k] = math.sqrt(lvl_k)
    return low_mat


def snap_unitary(dim_n, sval, phase_tuple, scale_val):
    lvls = np.arange(dim_n, dtype=float)
    quad = lvls * (lvls - 1.0) / 2.0
    return np.diag(np.exp(1j * sval * scale_val * quad).astype(complex))


def jump_op(dim_n, family_name, alpha_sq):
    """Engineered-dissipation jump operator toward the code manifold.
    Cat families: (a^2 - alpha^2 I) / alpha^2, dark on the whole cat
    manifold (both parities are eigenvalue-alpha^2 eigenstates of
    a^2), so logical superpositions are preserved; scaled by the
    photon number so one frozen REFILL_R governs all families.
    Binomial family: recovery jumps mapping single-loss error
    words |3>, |1> back onto the code words |0L>, |1L>."""
    if family_name.startswith("CAT"):
        low_a = annihilator_op(dim_n)
        raw_f = low_a @ low_a - alpha_sq * np.eye(dim_n)
        return raw_f / alpha_sq
    raw_f = np.zeros((dim_n, dim_n), dtype=complex)
    if dim_n > 4:
        raw_f[0, 3] = 1.0 / math.sqrt(2.0)
        raw_f[4, 3] = 1.0 / math.sqrt(2.0)
        raw_f[2, 1] = 1.0
    return raw_f


def build_combos(dim_n, phase_tuple, scale_val):
    snap_list = [snap_unitary(dim_n, sval, phase_tuple, scale_val)
                 for sval in phase_tuple]
    combo_list = []
    for phase_i in range(len(phase_tuple)):
        for pump_j in range(N_PUMP):
            combo_list.append((phase_i, pump_j))
    return snap_list, combo_list


def loss_weights(dim_n, kappa_val, dt_val):
    """Exact photon-loss channel weights: each photon survives a
    macro-step with probability (1 - gamma) independently, so the
    (m, n) block of the output mixes only the input block
    (m + k, n + k) with amplitude B(m + k, k) * B(n + k, k),
    where B(q, k) = sqrt(C(q, k) gamma^k (1 - gamma)^(q - k)).
    Trace-preserving inside the truncation up to leakage from
    above the cutoff (negligible by the boundary guard)."""
    gamma_v = 1.0 - math.exp(-kappa_val * dt_val)
    stay_v = 1.0 - gamma_v
    amp_m = np.zeros((dim_n, dim_n))
    for jump_k in range(dim_n):
        for lvl_q in range(jump_k, dim_n):
            amp_m[lvl_q, jump_k] = math.sqrt(
                math.comb(lvl_q, jump_k) * (gamma_v ** jump_k)
                * (stay_v ** (lvl_q - jump_k)))
    wgt_t = np.zeros((dim_n, dim_n, dim_n))
    for jump_k in range(dim_n):
        blk_n = dim_n - jump_k
        col_v = amp_m[jump_k:, jump_k]
        wgt_t[jump_k, :blk_n, :blk_n] = np.outer(col_v, col_v)
    return wgt_t


def deph_matrix(dim_n, kappa_phi, dt_val):
    lvls = np.arange(dim_n, dtype=float)
    diff_m = lvls[:, None] - lvls[None, :]
    return np.exp(-kappa_phi * dt_val * diff_m * diff_m)


def loss_apply(rho_mat, wgt_t):
    dim_n = rho_mat.shape[0]
    out_m = np.zeros_like(rho_mat)
    for jump_k in range(dim_n):
        blk_n = dim_n - jump_k
        if blk_n <= 0:
            break
        out_m[:blk_n, :blk_n] += (wgt_t[jump_k, :blk_n, :blk_n]
                                  * rho_mat[jump_k:, jump_k:])
    return out_m


def coherent_vec(dim_n, alpha_val):
    raw_v = np.array([math.exp(-alpha_val * alpha_val / 2.0)
                      * (alpha_val ** lvl_k)
                      / math.sqrt(math.factorial(lvl_k))
                      for lvl_k in range(dim_n)], dtype=complex)
    return raw_v / np.linalg.norm(raw_v)


def code_words(dim_n, family_name, alpha_sq):
    if family_name.startswith("CAT"):
        alpha_v = math.sqrt(alpha_sq)
        plus_v = coherent_vec(dim_n, alpha_v)
        minus_v = coherent_vec(dim_n, -alpha_v)
        zero_v = plus_v + minus_v
        one_v = plus_v - minus_v
    else:
        zero_v = np.zeros(dim_n, dtype=complex)
        zero_v[0] = 1.0 / math.sqrt(2.0)
        zero_v[4] = 1.0 / math.sqrt(2.0)
        one_v = np.zeros(dim_n, dtype=complex)
        one_v[2] = 1.0
    return zero_v / np.linalg.norm(zero_v), one_v / np.linalg.norm(one_v)


OPS_CACHE = {}


def make_bundle(dim_n, family_name, alpha_sq, phase_tuple, scale_val):
    word_zero, word_one = code_words(dim_n, family_name, alpha_sq)
    snap_u, combo_u = build_combos(dim_n, phase_tuple, scale_val)
    jump_f = jump_op(dim_n, family_name, alpha_sq)
    jump_a = jump_f.conj().T @ jump_f
    damp_w, damp_v = np.linalg.eigh((jump_a + jump_a.conj().T) / 2.0)
    damp_m = (damp_v * np.exp(-REFILL_R * damp_w / 2.0)) @ damp_v.conj().T
    return {"n": dim_n, "family": family_name,
            "w0": word_zero, "w1": word_one,
            "snaps": snap_u, "combos": combo_u,
            "jump": jump_f, "jumpa": jump_a, "damp": damp_m}


def get_ops(size_idx):
    if size_idx not in OPS_CACHE:
        dim_n = N_TRUNC[size_idx]
        fam_n = FAMILIES[dim_n]
        bundle = make_bundle(dim_n, fam_n, ALPHA_SQ[dim_n],
                             PHASE_VALS, PHASE_SCALE)
        loss_w = {}
        deph_m = {}
        lvls = np.arange(dim_n, dtype=float)
        for kap_i, kap_v in enumerate(KAPPA_GRID):
            loss_w[kap_i] = loss_weights(dim_n, kap_v, DT)
            diff_m = lvls[:, None] - lvls[None, :]
            deph_m[kap_i] = np.exp(
                -KAPPA_PHI[kap_i] * DT * diff_m * diff_m)
        bundle["loss"] = loss_w
        bundle["deph"] = deph_m
        OPS_CACHE[size_idx] = bundle
    return OPS_CACHE[size_idx]


def tiny_bundle():
    return make_bundle(TINY_N, "CAT_TINY", TINY_ALPHA_SQ,
                       TINY_PHASES, 1.0)


def seed_rng(size_idx, seed_v, rep_v, salt_v):
    return np.random.default_rng(
        (int(size_idx * 100003 + seed_v * 10007 + rep_v * 101
             + salt_v * 1000003) % (2 ** 63 - 1)))


def kappa_of(rep_v):
    return KAPPA_GRID[rep_v % len(KAPPA_GRID)]


def gen_fock_state(size_idx, seed_v, rep_v):
    bundle = get_ops(size_idx)
    dim_n = bundle["n"]
    draw_rng = seed_rng(size_idx, seed_v, rep_v, 11)
    uni_a = float(draw_rng.random())
    uni_b = float(draw_rng.random())
    theta_v = math.acos(2.0 * uni_a - 1.0)
    phi_v = 2.0 * math.pi * uni_b
    psi_v = (math.cos(theta_v / 2.0) * bundle["w0"]
             + complex(math.cos(phi_v), math.sin(phi_v))
             * math.sin(theta_v / 2.0) * bundle["w1"])
    psi_v = psi_v / np.linalg.norm(psi_v)
    rho_m = np.outer(psi_v, psi_v.conj())
    return {"psi": psi_v, "rho": rho_m, "n": dim_n,
            "family": bundle["family"],
            "kappa": kappa_of(rep_v),
            "kappa_idx": rep_v % len(KAPPA_GRID)}


def tiny_state():
    tiny_w0, tiny_w1 = code_words(TINY_N, "CAT_A1", TINY_ALPHA_SQ)
    psi_v = (math.cos(TINY_TH / 2.0) * tiny_w0
             + complex(math.cos(TINY_PHI), math.sin(TINY_PHI))
             * math.sin(TINY_TH / 2.0) * tiny_w1)
    psi_v = psi_v / np.linalg.norm(psi_v)
    return {"psi": psi_v, "rho": np.outer(psi_v, psi_v.conj()),
            "n": TINY_N, "family": "TINY",
            "kappa": TINY_KAPPA, "kappa_idx": -1}


TINY_NCOMBOS = len(TINY_PHASES) * N_PUMP


def eval_seq(seq_list, psi_vec, rho_mat, bundle, loss_w, deph_m,
             dim_n, nsteps, edge, refill_r):
    work_rho = rho_mat.copy()
    fid_accum = 0.0
    bnd_peak = 0.0
    last_fid = 0.0
    edge_eff = min(edge, max(1, dim_n // 4))
    snap_u = bundle["snaps"]
    combo_u = bundle["combos"]
    jump_f = bundle["jump"]
    damp_m = bundle["damp"]
    for step_i in range(nsteps):
        loss_rho = loss_apply(work_rho, loss_w) * deph_m
        slot_rho = loss_rho
        for slot_k in seq_list:
            phase_i, pump_j = combo_u[int(slot_k)]
            snap_m = snap_u[phase_i]
            slot_rho = snap_m @ slot_rho @ snap_m.conj().T
            if pump_j:
                damp_rho = damp_m @ slot_rho @ damp_m.conj().T
                jump_term = jump_f @ slot_rho @ jump_f.conj().T
                slot_rho = damp_rho + refill_r * jump_term
                slot_tr = float(np.real(np.trace(slot_rho)))
                if slot_tr > 0.0:
                    slot_rho = slot_rho / slot_tr
        work_rho = slot_rho
        proj_v = work_rho @ psi_vec
        step_fid = float(np.real(np.vdot(psi_vec, proj_v)))
        fid_accum += step_fid
        last_fid = step_fid
        edge_blk = work_rho[dim_n - edge_eff:, dim_n - edge_eff:]
        step_bnd = float(np.real(np.trace(edge_blk)))
        if step_bnd > bnd_peak:
            bnd_peak = step_bnd
    return {"infid": 1.0 - last_fid, "life": fid_accum, "bnd": bnd_peak}


def repair_seq(prop_seq, seq_len, n_combos):
    fixed_seq = []
    for cand_v in list(prop_seq)[:seq_len]:
        if isinstance(cand_v, bool):
            fixed_seq.append(0)
            continue
        try:
            int_v = int(cand_v)
        except (TypeError, ValueError):
            fixed_seq.append(0)
            continue
        fixed_seq.append(int_v % n_combos)
    while len(fixed_seq) < seq_len:
        fixed_seq.append(0)
    return fixed_seq


def run_s(psi_vec, rho_mat, bundle, loss_w, deph_m,
          dim_n, nsteps, edge, refill_r):
    base_out = eval_seq(list(S_SEQ), psi_vec, rho_mat, bundle, loss_w, deph_m, dim_n, nsteps, edge,
                        refill_r)
    return {"infid": base_out["infid"], "life": base_out["life"],
            "bnd": base_out["bnd"], "stopped": False}


def run_tiny_s(psi_vec, rho_mat, tiny_bun, loss_w, deph_m, edge,
               refill_r):
    tiny_out = eval_seq(list(TINY_S_SEQ), psi_vec, rho_mat,
                        tiny_bun, loss_w, deph_m, TINY_N, TINY_T,
                        edge, refill_r)
    return {"infid": tiny_out["infid"], "life": tiny_out["life"],
            "bnd": tiny_out["bnd"], "stopped": False}


def run_r(psi_vec, rho_mat, bundle, loss_w, deph_m, dim_n,
          nsteps, edge, shuffle_rng, seq_len, n_combos, refill_r):
    rand_seq = [int(v) for v in
                shuffle_rng.integers(0, n_combos, size=seq_len)]
    rand_out = eval_seq(rand_seq, psi_vec, rho_mat, bundle, loss_w, deph_m, dim_n, nsteps, edge,
                        refill_r)
    return {"infid": rand_out["infid"], "life": rand_out["life"],
            "bnd": rand_out["bnd"], "stopped": False}


def run_g(psi_vec, rho_mat, bundle, loss_w, deph_m, dim_n,
          nsteps, edge, seq_len, n_combos, start_seq, stop,
          refill_r):
    """Greedy first-improvement discrete-sequence descent from the
    given start; strictly improving fixed-time infidelity, so the
    result never regresses past the start. Distinct names per role;
    the start list is copied, never mutated."""
    work_seq = repair_seq(list(start_seq), seq_len, n_combos)
    work_out = eval_seq(work_seq, psi_vec, rho_mat, bundle, loss_w, deph_m, dim_n, nsteps, edge,
                        refill_r)
    work_infid = work_out["infid"]
    work_life = work_out["life"]
    work_bnd = work_out["bnd"]
    guard_seq_evals = [0]

    def guard_seq_tripped():
        guard_seq_evals[0] += 1
        if guard_seq_evals[0] % 32 == 0 and stop is not None \
                and stop():
            return True
        return False

    for sweep_i in range(GREEDY_SWEEPS):
        for slot_i in range(seq_len):
            for alt_k in range(n_combos):
                if guard_seq_tripped():
                    return {"infid": None, "life": None, "bnd": None,
                            "stopped": True}
                if alt_k == work_seq[slot_i]:
                    continue
                cand_seq = list(work_seq)
                cand_seq[slot_i] = alt_k
                cand_seq = repair_seq(cand_seq, seq_len, n_combos)
                cand_out = eval_seq(cand_seq, psi_vec, rho_mat,
                                    bundle, loss_w, deph_m,
                                    dim_n, nsteps, edge, refill_r)
                if cand_out["infid"] < work_infid:
                    work_seq = cand_seq
                    work_infid = cand_out["infid"]
                    work_life = cand_out["life"]
                    work_bnd = cand_out["bnd"]
    return {"infid": float(work_infid), "life": float(work_life),
            "bnd": float(work_bnd), "stopped": False}


def run_a(psi_vec, rho_mat, bundle, loss_w, deph_m, dim_n,
          nsteps, edge, seq_len, n_combos, start_seq, prop_rng,
          n_iters, stop, refill_r):
    """Simulated annealing over discrete sequences; cost =
    infidelity + LAMBDA * boundary (frozen LAMBDA). Starts at the
    given start schedule; tracks best. Distinct names per role."""
    anneal_seq = repair_seq(list(start_seq), seq_len, n_combos)
    anneal_out = eval_seq(anneal_seq, psi_vec, rho_mat, bundle, loss_w, deph_m, dim_n, nsteps, edge,
                          refill_r)
    anneal_cost = anneal_out["infid"] + LAMBDA * anneal_out["bnd"]
    best_cost_seen = anneal_cost
    best_infid_seen = anneal_out["infid"]
    best_life_seen = anneal_out["life"]
    best_bnd_seen = anneal_out["bnd"]
    anneal_temp = ANNEAL_T0
    for iter_i in range(n_iters):
        if iter_i % 32 == 0 and stop is not None and stop():
            return {"infid": None, "life": None, "bnd": None,
                    "stopped": True}
        slot_pick = int(prop_rng.integers(seq_len))
        alt_pick = int(prop_rng.integers(n_combos))
        raw_seq = list(anneal_seq)
        raw_seq[slot_pick] = alt_pick
        prop_seq = repair_seq(raw_seq, seq_len, n_combos)
        prop_out = eval_seq(prop_seq, psi_vec, rho_mat, bundle, loss_w, deph_m, dim_n, nsteps, edge,
                            refill_r)
        prop_cost = prop_out["infid"] + LAMBDA * prop_out["bnd"]
        accept_draw = float(prop_rng.random())
        if prop_cost < anneal_cost or bool(
                accept_draw < math.exp(-(prop_cost - anneal_cost)
                                       / anneal_temp)):
            anneal_seq = prop_seq
            anneal_cost = prop_cost
            if prop_cost < best_cost_seen:
                best_cost_seen = prop_cost
                best_infid_seen = prop_out["infid"]
                best_life_seen = prop_out["life"]
                best_bnd_seen = prop_out["bnd"]
        anneal_temp *= ANNEAL_ALPHA
    return {"infid": float(best_infid_seen),
            "life": float(best_life_seen),
            "bnd": float(best_bnd_seen), "stopped": False}


def exact_opt(n_combos, depth_v, leaf_infid, base_infid, cap, stop):
    """Bounded-exact level-order branch-and-bound over discrete
    sequences, minimizing fixed-time infidelity with an admissible
    zero lower bound (bounding comes from the node budget, never
    from data-dependent pruning, so node counts are
    deterministic). Level-order enumeration counts every partial
    schedule; leaves are evaluated only when reached. Statuses:
    solved / cap-hit / stopped-guard."""
    best_val = [base_infid]
    node_total = [0]
    capped_hit = [False]
    stopped_hit = [False]
    for level_d in range(depth_v + 1):
        level_total = n_combos ** level_d
        for lex_i in range(level_total):
            node_total[0] += 1
            if node_total[0] > cap:
                capped_hit[0] = True
                return {"status": "cap-hit",
                        "nodes": node_total[0],
                        "opt_infid": best_val[0], "cap": cap,
                        "started": True}
            if node_total[0] % 512 == 0 and stop is not None \
                    and stop():
                stopped_hit[0] = True
                return {"status": "stopped-guard",
                        "nodes": node_total[0],
                        "opt_infid": best_val[0], "cap": cap,
                        "started": True}
            if level_d == depth_v:
                tmp_v = lex_i
                leaf_seq = [0] * depth_v
                for pos_d in range(depth_v - 1, -1, -1):
                    leaf_seq[pos_d] = tmp_v % n_combos
                    tmp_v //= n_combos
                leaf_val = leaf_infid(leaf_seq)
                if leaf_val < best_val[0]:
                    best_val[0] = leaf_val
    return {"status": "solved", "nodes": node_total[0],
            "opt_infid": best_val[0], "cap": cap, "started": True}


def pooled_stats(vals):
    arr_v = np.asarray(vals, dtype=float)
    if arr_v.size == 0:
        return {"n": 0, "mean": None, "std": None, "se": None}
    mean_v = float(arr_v.mean())
    if arr_v.size < 2:
        return {"n": int(arr_v.size), "mean": mean_v, "std": 0.0,
                "se": None}
    std_v = float(arr_v.std(ddof=1))
    return {"n": int(arr_v.size), "mean": mean_v, "std": std_v,
            "se": std_v / math.sqrt(arr_v.size)}


def spread_win(pools, ok):
    keys = sorted(pools)
    if ok and all(pools[ak]["se"] is not None for ak in keys):
        se_v = math.sqrt(sum(pools[ak]["se"] ** 2 for ak in keys)
                         / len(keys))
        means_v = [pools[ak]["mean"] for ak in keys]
        spread_v = max(means_v) - min(means_v)
        return se_v, spread_v, spread_v > 2.0 * se_v
    return None, None, False


def audit_state(size_idx, seed_v, rep_v):
    st = gen_fock_state(size_idx, seed_v, rep_v)
    dim_n = st["n"]
    trace_v = float(np.real(np.trace(st["rho"])))
    herm_err = float(np.max(np.abs(st["rho"] - st["rho"].conj().T)))
    bundle = get_ops(size_idx)
    ortho_err = abs(complex(np.vdot(bundle["w0"], bundle["w1"])))
    norm0 = float(np.linalg.norm(bundle["w0"]))
    norm1 = float(np.linalg.norm(bundle["w1"]))
    return {"trace_ok": abs(trace_v - 1.0) < 1e-9,
            "hermitian_ok": herm_err < 1e-12,
            "ortho_ok": ortho_err < 1e-9,
            "norm_ok": abs(norm0 - 1.0) < 1e-9
            and abs(norm1 - 1.0) < 1e-9,
            "dim_ok": dim_n == N_TRUNC[size_idx],
            "family_ok": st["family"] == FAMILIES[dim_n],
            "kappa_ok": st["kappa"] in KAPPA_GRID}


def self_tests():
    out = {"ran": True, "failed": [], "gradient_probe": []}
    try:
        for s_idx in range(len(N_TRUNC)):
            for rep_v in (0, 1):
                audit_v = audit_state(s_idx, 1, rep_v)
                for key_k in ("trace_ok", "hermitian_ok", "ortho_ok",
                              "norm_ok", "dim_ok", "family_ok",
                              "kappa_ok"):
                    if not audit_v[key_k]:
                        out["failed"].append(
                            "gen-%s-%d-%d" % (key_k, s_idx, rep_v))
        tstate = tiny_state()
        tbundle = tiny_bundle()
        tW = loss_weights(TINY_N, TINY_KAPPA, DT)
        tdeph = np.ones((TINY_N, TINY_N))
        tiny_results = {}
        tiny_results["S"] = run_tiny_s(
            tstate["psi"], tstate["rho"], tbundle, tW, tdeph,
            BOUND_EDGE, REFILL_R)
        tiny_results["G"] = run_g(
            tstate["psi"], tstate["rho"], tbundle, tW, tdeph, TINY_N,
            TINY_T, BOUND_EDGE, TINY_L, TINY_NCOMBOS,
            list(TINY_S_SEQ), None, REFILL_R)
        tiny_results["A"] = run_a(
            tstate["psi"], tstate["rho"], tbundle, tW, tdeph, TINY_N,
            TINY_T, BOUND_EDGE, TINY_L, TINY_NCOMBOS, [0],
            seed_rng(0, 7, 7, 5), 50, None, REFILL_R)
        tiny_results["R"] = run_r(
            tstate["psi"], tstate["rho"], tbundle, tW, tdeph, TINY_N,
            TINY_T, BOUND_EDGE, seed_rng(0, 7, 7, 999), TINY_L,
            TINY_NCOMBOS, REFILL_R)
        for arm_k in ("G", "A"):
            if abs(tiny_results[arm_k]["infid"] - TINY_OPT_INFID) \
                    > 1e-9:
                out["failed"].append("tiny-%s-hand" % arm_k)
        if not tiny_results["S"]["infid"] > 1e-12:
            out["failed"].append("tiny-gradient")
        if tiny_results["S"]["bnd"] > BOUND_THRESH:
            out["failed"].append("tiny-boundary")

        def tiny_leaf(leaf_seq):
            leaf_out = eval_seq(leaf_seq, tstate["psi"],
                                tstate["rho"], tbundle, tW, tdeph,
                                TINY_N, TINY_T, BOUND_EDGE, REFILL_R)
            return leaf_out["infid"]

        tiny_base = tiny_results["S"]["infid"]
        tex = exact_opt(TINY_NCOMBOS, TINY_L, tiny_leaf,
                        tiny_base, EXACT_CAP, None)
        if tex["status"] != "solved" or abs(
                tex["opt_infid"] - TINY_OPT_INFID) > 1e-9:
            out["failed"].append("tiny-exact-opt")
        if tex["nodes"] != 1 + TINY_NCOMBOS:
            out["failed"].append("tiny-node-count")
        if repair_seq([0, 0, 7, 2], 4, 6) != [0, 0, 1, 2]:
            out["failed"].append("repair-modulo")
        if repair_seq([2, 0, 1], 3, 6) != [2, 0, 1]:
            out["failed"].append("repair-identity")
        if repair_seq([], 3, 6) != [0, 0, 0]:
            out["failed"].append("repair-empty")
        if repair_seq([2, 2, 2], 3, 6) != [2, 2, 2]:
            out["failed"].append("repair-repeat")
        if repair_seq([True, -1, 2.9, "x"], 4, 6) != [0, 5, 2, 0]:
            out["failed"].append("repair-coerce")
        repaired_once = repair_seq([1, 8, 1, 9, 0], 5, 6)
        if repair_seq(repaired_once, 5, 6) != repaired_once:
            out["failed"].append("repair-idempotent")
        if any(v < 0 or v >= 6 for v in repaired_once):
            out["failed"].append("repair-range")
        probe_all_tied = True
        for probe_rep in range(4):
            probe_bundle = get_ops(0)
            probe_st = gen_fock_state(0, 1, probe_rep)
            kap_idx = probe_st["kappa_idx"]
            pW = probe_bundle["loss"][kap_idx]
            pD = probe_bundle["deph"][kap_idx]
            probe_s = run_s(probe_st["psi"], probe_st["rho"],
                            probe_bundle, pW, pD,
                            probe_bundle["n"], T_STEPS, BOUND_EDGE,
                            REFILL_R)
            probe_r = run_r(probe_st["psi"], probe_st["rho"],
                            probe_bundle, pW, pD,
                            probe_bundle["n"], T_STEPS, BOUND_EDGE,
                            seed_rng(0, 1, probe_rep, 999),
                            L_SEQ, N_COMBOS, REFILL_R)
            probe_g = run_g(probe_st["psi"], probe_st["rho"],
                            probe_bundle, pW, pD,
                            probe_bundle["n"], T_STEPS, BOUND_EDGE,
                            L_SEQ, N_COMBOS, list(S_SEQ), None,
                            REFILL_R)
            probe_a = run_a(probe_st["psi"], probe_st["rho"],
                            probe_bundle, pW, pD,
                            probe_bundle["n"], T_STEPS, BOUND_EDGE,
                            L_SEQ, N_COMBOS, list(IDENT_SEQ),
                            seed_rng(0, 1, probe_rep, 777), 20, None,
                            REFILL_R)
            probe_vals = (probe_s["infid"], probe_r["infid"],
                          probe_g["infid"], probe_a["infid"])
            out["gradient_probe"].append(
                {"rep": probe_rep, "infid": list(probe_vals)})
            if min(probe_vals) < 0.0:
                out["failed"].append("negative-infid")
            if not (probe_vals[0] == probe_vals[1] == probe_vals[2]
                    == probe_vals[3]):
                probe_all_tied = False
            if not probe_g["infid"] <= probe_s["infid"]:
                out["failed"].append("greedy-regress")
        if probe_all_tied:
            out["failed"].append("gradient-degenerate")
        alias_probe = [2, 2, 2, 2, 2, 2, 2]
        alias_snap = list(alias_probe)
        probe_bundle = get_ops(0)
        probe_st = gen_fock_state(0, 1, 0)
        pW = probe_bundle["loss"][probe_st["kappa_idx"]]
        pD = probe_bundle["deph"][probe_st["kappa_idx"]]
        eval_seq(alias_probe, probe_st["psi"], probe_st["rho"],
                 probe_bundle, pW, pD,
                 probe_bundle["n"], T_STEPS, BOUND_EDGE, REFILL_R)
        if alias_probe != alias_snap:
            out["failed"].append("alias-mutate-eval")
        start_probe = list(S_SEQ)
        run_g(probe_st["psi"], probe_st["rho"],
              probe_bundle, pW, pD, probe_bundle["n"],
              T_STEPS, BOUND_EDGE, L_SEQ, N_COMBOS, start_probe,
              None, REFILL_R)
        if start_probe != list(S_SEQ):
            out["failed"].append("alias-mutate-greedy")
        conv_full = eval_seq(list(IDENT_SEQ), probe_st["psi"],
                             probe_st["rho"], probe_bundle,
                             pW, pD, probe_bundle["n"], T_STEPS,
                             BOUND_EDGE, REFILL_R)
        narrow_n = probe_bundle["n"] - 4
        narrow_bundle = make_bundle(narrow_n, probe_bundle["family"],
                                    ALPHA_SQ[probe_bundle["n"]],
                                    PHASE_VALS, PHASE_SCALE)
        narrow_W = loss_weights(narrow_n,
                                          probe_st["kappa"], DT)
        narrow_deph = deph_matrix(narrow_n, KAPPA_PHI[
            probe_st["kappa_idx"]], DT)
        narrow_psi = probe_st["psi"][:narrow_n].copy()
        narrow_psi = narrow_psi / np.linalg.norm(narrow_psi)
        narrow_rho = np.outer(narrow_psi, narrow_psi.conj())
        conv_narrow = eval_seq(list(IDENT_SEQ), narrow_psi,
                               narrow_rho, narrow_bundle, narrow_W,
                               narrow_deph, narrow_n, T_STEPS,
                               BOUND_EDGE, REFILL_R)
        conv_denom = max(conv_full["infid"], 1e-9)
        conv_rel = abs(conv_full["infid"] - conv_narrow["infid"]) \
            / conv_denom
        out["convergence"] = {"full": conv_full["infid"],
                              "narrow": conv_narrow["infid"],
                              "rel": conv_rel}
        if not conv_rel < CONV_TOL:
            out["failed"].append("convergence")
        det_g1 = run_g(probe_st["psi"], probe_st["rho"],
                       probe_bundle, pW, pD,
                       probe_bundle["n"], T_STEPS, BOUND_EDGE,
                       L_SEQ, N_COMBOS, list(S_SEQ), None, REFILL_R)
        det_g2 = run_g(probe_st["psi"], probe_st["rho"],
                       probe_bundle, pW, pD,
                       probe_bundle["n"], T_STEPS, BOUND_EDGE,
                       L_SEQ, N_COMBOS, list(S_SEQ), None, REFILL_R)
        if (det_g1["infid"], det_g1["life"]) != (det_g2["infid"],
                                                det_g2["life"]):
            out["failed"].append("determinism-greedy")
        det_r1 = run_r(probe_st["psi"], probe_st["rho"],
                       probe_bundle, pW, pD,
                       probe_bundle["n"], T_STEPS, BOUND_EDGE,
                       seed_rng(0, 1, 0, 999), L_SEQ, N_COMBOS,
                       REFILL_R)
        det_r2 = run_r(probe_st["psi"], probe_st["rho"],
                       probe_bundle, pW, pD,
                       probe_bundle["n"], T_STEPS, BOUND_EDGE,
                       seed_rng(0, 1, 0, 999), L_SEQ, N_COMBOS,
                       REFILL_R)
        if (det_r1["infid"], det_r1["life"]) != (det_r2["infid"],
                                                det_r2["life"]):
            out["failed"].append("determinism-random")
    except Exception as ex:
        out["failed"].append("raise: %r" % ex)
    return out


def run_arm(size_idx, seed_v, rep_v, arm, n_iters, stop):
    bundle = get_ops(size_idx)
    dim_n = bundle["n"]
    fock_st = gen_fock_state(size_idx, seed_v, rep_v)
    kW = bundle["loss"][fock_st["kappa_idx"]]
    kD = bundle["deph"][fock_st["kappa_idx"]]
    if arm == "S":
        return run_s(fock_st["psi"], fock_st["rho"],
                     bundle, kW, kD, dim_n, T_STEPS,
                     BOUND_EDGE, REFILL_R)
    if arm == "R":
        return run_r(fock_st["psi"], fock_st["rho"],
                     bundle, kW, kD, dim_n, T_STEPS,
                     BOUND_EDGE,
                     seed_rng(size_idx, seed_v, rep_v, 999),
                     L_SEQ, N_COMBOS, REFILL_R)
    if arm == "G":
        return run_g(fock_st["psi"], fock_st["rho"],
                     bundle, kW, kD, dim_n, T_STEPS,
                     BOUND_EDGE, L_SEQ, N_COMBOS, list(S_SEQ),
                     stop, REFILL_R)
    return run_a(fock_st["psi"], fock_st["rho"], bundle,
                 kW, kD, dim_n, T_STEPS, BOUND_EDGE, L_SEQ,
                 N_COMBOS, list(IDENT_SEQ),
                 seed_rng(size_idx, seed_v, rep_v, 777),
                 n_iters, stop, REFILL_R)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--attempt", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--n-inst", type=int, default=N_INST)
    ap.add_argument("--anneal-iters", type=int, default=ANNEAL_ITERS)
    args = ap.parse_args()
    n_inst = int(args.n_inst)
    n_iters = int(args.anneal_iters)
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
    artifact_cells = []
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
                           "n_artifact_cells": len(artifact_cells),
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
        tstate = tiny_state()
        tbundle = tiny_bundle()
        tW = loss_weights(TINY_N, TINY_KAPPA, DT)
        tdeph = np.ones((TINY_N, TINY_N))

        def tiny_leaf(leaf_seq):
            leaf_out = eval_seq(leaf_seq, tstate["psi"],
                                tstate["rho"], tbundle, tW, tdeph,
                                TINY_N, TINY_T, BOUND_EDGE, REFILL_R)
            return leaf_out["infid"]

        tiny_snap = run_tiny_s(tstate["psi"], tstate["rho"], tbundle,
                               tW, tdeph, BOUND_EDGE, REFILL_R)
        ex = exact_opt(TINY_NCOMBOS, TINY_L, tiny_leaf,
                       tiny_snap["infid"], EXACT_CAP, over)
        gate3tiny["arms"]["tiny"] = ex
        gate3tiny["total"] += 1
        if ex["status"] == "solved" and abs(
                ex["opt_infid"] - TINY_OPT_INFID) <= 1e-9:
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
        t_bundle = get_ops(TARGET["size_idx"])
        t_fock = gen_fock_state(TARGET["size_idx"], TARGET["seed"],
                                TARGET["rep"])
        tW = t_bundle["loss"][t_fock["kappa_idx"]]
        tdeph = t_bundle["deph"][t_fock["kappa_idx"]]
        t_base = run_s(t_fock["psi"], t_fock["rho"],
                       t_bundle, tW, tdeph,
                       t_bundle["n"], T_STEPS, BOUND_EDGE, REFILL_R)

        def target_leaf(leaf_seq):
            leaf_out = eval_seq(leaf_seq, t_fock["psi"],
                                t_fock["rho"], t_bundle,
                                tW, tdeph, t_bundle["n"], T_STEPS,
                                BOUND_EDGE, REFILL_R)
            return leaf_out["infid"]

        tex = exact_opt(N_COMBOS, L_SEQ, target_leaf,
                        t_base["infid"], EXACT_CAP, over)
        gate3targets.append(dict(tex, size=t_bundle["n"],
                                 kappa=t_fock["kappa"]))
        if tex["status"] == "stopped-guard":
            skipped.append({"what": "target-exact",
                            "reason": "stopped-guard",
                            "iters_done": tex.get("nodes", 0),
                            "n_evaluated": EXACT_CAP})
    with open(os.path.join(witdir, "gate3_targets.json"), "w") as f:
        json.dump(gate3targets, f, indent=1, default=str)
    checkpoint("targets")

    def run_cell(si, seed_v):
        dim_n = N_TRUNC[si]
        rec = {"size": dim_n, "seed": seed_v, "arms": {},
               "family": FAMILIES[dim_n], "artifact": False,
               "regimes": {}}
        for arm in ARMS:
            if over():
                rec["blocked"] = "wall-guard"
                rec["iters_done"] = 0
                rec["n_evaluated"] = n_inst
                return rec
            inf_list, life_list, bnd_list = [], [], []
            reg_inf = {0: [], 1: []}
            nstop = 0
            for rep_v in range(n_inst):
                if rep_v % 32 == 0 and over():
                    nstop += 1
                    break
                arm_out = run_arm(si, seed_v, rep_v, arm, n_iters,
                                  over)
                if arm_out.get("stopped"):
                    nstop += 1
                    break
                inf_list.append(arm_out["infid"])
                life_list.append(arm_out["life"])
                bnd_list.append(arm_out["bnd"])
                reg_inf[rep_v % 2].append(arm_out["infid"])
            if nstop:
                rec["blocked"] = "stopped-guard"
                rec["iters_done"] = len(inf_list)
                rec["n_evaluated"] = n_inst
                return rec
            rec["arms"][arm] = {
                "n": len(inf_list),
                "infid": pooled_stats(inf_list),
                "life": pooled_stats(life_list),
                "bnds": list(bnd_list),
                "bnd_max": max(bnd_list) if bnd_list else None}
            for reg_k in (0, 1):
                rec["regimes"].setdefault(str(reg_k), {})[arm] = \
                    pooled_stats(reg_inf[reg_k])
        rep_peaks = [0.0] * n_inst
        for arm in ARMS:
            for rep_i, bnd_v in enumerate(
                    rec["arms"][arm].get("bnds", [])):
                if bnd_v > rep_peaks[rep_i]:
                    rep_peaks[rep_i] = bnd_v
        for peak_v in rep_peaks:
            if peak_v > BOUND_THRESH:
                rec["artifact"] = True
                break
        return rec

    def record_cell(rec):
        if rec.get("blocked") is None and all(
                rec["arms"].get(a, {}).get("n") == n_inst
                for a in ARMS):
            for a in ARMS:
                key = (rec["size"], rec["seed"], a)
                cells.setdefault(key, {"infid": [], "life": []})
                cells[key]["infid"].append(
                    rec["arms"][a]["infid"]["mean"])
                cells[key]["life"].append(
                    rec["arms"][a]["life"]["mean"])
            if rec.get("artifact"):
                artifact_cells.append("%d/%d" % (rec["size"],
                                                rec["seed"]))
            return True
        skipped.append({"what": "cell %d/%d" % (
            rec["size"], rec["seed"]),
            "reason": rec.get("blocked", "arm-incomplete"),
            "iters_done": rec.get("iters_done", 0),
            "n_evaluated": n_inst})
        return False

    for si, dim_n in enumerate(N_TRUNC):
        siz_cells = [(si, seed_v) for seed_v in SEEDS]
        if over():
            for (s2, sd2) in siz_cells:
                skipped.append({"what": "cell %d/%d" % (
                    N_TRUNC[s2], sd2), "reason": "wall-guard",
                    "iters_done": 0, "n_evaluated": n_inst})
        else:
            for (s2, sd2) in siz_cells:
                if over():
                    skipped.append({"what": "cell %d/%d" % (
                        N_TRUNC[s2], sd2), "reason": "wall-guard",
                        "iters_done": 0, "n_evaluated": n_inst})
                    continue
                rec = run_cell(s2, sd2)
                cellrecs.append(rec)
                record_cell(rec)
        with open(os.path.join(witdir, "cells.json"), "w") as f:
            json.dump(cellrecs, f, indent=1, default=str)
        checkpoint("size%d" % dim_n)
    with open(os.path.join(witdir, "cells.json"), "w") as f:
        json.dump(cellrecs, f, indent=1, default=str)
    checkpoint("corpus")

    def cell_mean(dim_n, seed_v, arm, field):
        return cells.get((dim_n, seed_v, arm),
                         {"infid": [], "life": []})[field]

    def pool(dim_n, arm, field):
        vals = []
        for seed_v in SEEDS:
            vals.extend(cell_mean(dim_n, seed_v, arm, field))
        return pooled_stats(vals), len(vals) == len(SEEDS)

    det_g = run_arm(0, 1, 0, "G", n_iters, None)
    det_gb = run_arm(0, 1, 0, "G", n_iters, None)
    det_r = run_arm(0, 1, 0, "R", n_iters, None)
    det_rb = run_arm(0, 1, 0, "R", n_iters, None)
    determinism_ok = bool(
        (det_g["infid"], det_g["life"]) == (det_gb["infid"],
                                           det_gb["life"])
        and (det_r["infid"], det_r["life"]) == (det_rb["infid"],
                                               det_rb["life"]))

    g1_cells, g1_beats = [], True
    for dim_n in N_TRUNC:
        for seed_v in SEEDS:
            mg = cell_mean(dim_n, seed_v, "G", "infid")
            mr = cell_mean(dim_n, seed_v, "R", "infid")
            ok = (len(mg) == 1 and len(mr) == 1 and mg[0] < mr[0])
            g1_cells.append({"cell": "%d/%d" % (dim_n, seed_v),
                             "mean_G": mg[0] if mg else None,
                             "mean_R": mr[0] if mr else None,
                             "pass": bool(ok)})
            if not ok:
                g1_beats = False
    g1_ok = bool(g1_beats and tiny_ok and determinism_ok)

    g2_fams, g2_n = [], 0
    g2s_fams, g2s_n = [], 0
    win_fams = []
    win_counts = {"G": 0, "A": 0}
    for dim_n in N_TRUNC:
        pools, pok = {}, True
        for arm in ("S", "G", "A"):
            pools[arm], oka = pool(dim_n, arm, "infid")
            pok = pok and oka
        se_v, spread_v, gp = spread_win(pools, pok)
        g2_fams.append({"size": dim_n, "pools": pools, "SE": se_v,
                        "spread": spread_v, "pass": bool(gp)})
        if gp:
            g2_n += 1
        spools, spok = {}, True
        for arm in ("S", "G", "A"):
            spools[arm], oka = pool(dim_n, arm, "life")
            spok = spok and oka
        sse, sspread, sgp = spread_win(spools, spok)
        g2s_fams.append({"size": dim_n, "pools": spools,
                         "SE": sse, "spread": sspread,
                         "pass": bool(sgp)})
        if sgp:
            g2s_n += 1
        joint = {}
        if pok and spok and all(
                pools[a]["se"] is not None and
                pools[a]["mean"] is not None for a in ("S", "G", "A")):
            sse2 = math.sqrt(sum(pools[a]["se"] ** 2
                                 for a in ("S", "G", "A")) / 3.0)
            for a in ("G", "A"):
                iwin = pools[a]["mean"] < pools["S"]["mean"] \
                    - 2.0 * sse2
                lok = spools[a]["mean"] >= spools["S"]["mean"]
                joint[a] = bool(iwin and lok)
        else:
            joint = {"G": False, "A": False}
        for a in ("G", "A"):
            if joint[a]:
                win_counts[a] += 1
        if pok and all(pools[a]["mean"] is not None
                       for a in ("S", "G", "A")):
            spass = (pools["G"]["mean"] < pools["S"]["mean"] or
                     pools["A"]["mean"] < pools["S"]["mean"])
        else:
            spass = False
        win_fams.append({"size": dim_n, "strict_win": bool(spass),
                         "pools_ok": bool(pok),
                         "joint": dict(joint)})
    g2_ok = g2_n >= 2

    tiny_solved = (gate3tiny["total"] == 1 and gate3tiny["solved"] == 1)
    target_cap = (len(gate3targets) == 1 and
                  gate3targets[0].get("status") == "cap-hit")
    g3pass = bool(tiny_solved and target_cap)

    complete = all(
        len(cell_mean(dim_n, seed_v, arm, "infid")) == 1
        for dim_n in N_TRUNC for seed_v in SEEDS for arm in ARMS)
    tiny_attempted = gate3tiny["total"] == 1
    targets_attempted = len(gate3targets) == 1
    wall = elapsed()
    clean = len(skipped) == 0
    g4_ok = bool(complete and tiny_attempted and targets_attempted and
                 wall < WALL_LIMIT_S and clean)

    selftest_ok = bool(tiny_ok)
    artifact_free = len(artifact_cells) == 0
    n_win = max(win_counts["G"], win_counts["A"])
    strict_n = sum(1 for wrec in win_fams if wrec.get("strict_win"))
    pools_all = all(wrec.get("pools_ok") for wrec in win_fams)
    pursue = (n_win >= 2 and g1_ok and g2_ok and g3pass and g4_ok and
              selftest_ok and artifact_free)
    reject = (complete and tiny_solved and g1_ok and
              pools_all and strict_n == 0)
    if pursue:
        reason = ("PURSUE-condition holds (joint infidelity win "
                  "+ lifetime no-regress on the SAME arm at >=2 "
                  "sizes + gates 1,2,3,4 + self-tests ok + zero "
                  "truncation artifacts); payload verdict stays "
                  "unresolved-with-reason, classification is "
                  "coordinator-side. Next experiment: "
                  + NEXT_EXPERIMENT + ".")
    elif reject:
        reason = ("REJECT-condition holds (complete cells, tiny "
                  "solved, Gate-1 controls pass, no strict pooled "
                  "infidelity win at any size); payload verdict "
                  "stays unresolved-with-reason, classification is "
                  "coordinator-side. Next experiment: "
                  + NEXT_EXPERIMENT + ".")
    else:
        reason = ("UNRESOLVED + next experiment (joint wins G=%d/3, "
                  "A=%d/3, strict wins=%d/3, g1=%s g2=%s "
                  "g2s(life-spread)=%s g3=%s (tiny solved=%s, target "
                  "cap-hit=%s) selftest=%s g4=%s complete=%s "
                  "skipped=%d artifacts=%d; "
                  "next: %s)." % (
                      win_counts["G"], win_counts["A"], strict_n,
                      g1_ok, g2_ok, g2s_n >= 2, g3pass, tiny_solved,
                      target_cap, selftest_ok, g4_ok, complete,
                      len(skipped), len(artifact_cells),
                      NEXT_EXPERIMENT))
    verdict_bits = {
        "gate1": {"pass": bool(g1_ok), "beats_all_15": bool(g1_beats),
                  "tiny_ok": bool(tiny_ok),
                  "determinism_ok": bool(determinism_ok),
                  "cells": g1_cells},
        "gate2": {"pass": bool(g2_ok), "n_sizes_pass": g2_n,
                  "sizes": g2_fams},
        "gate2_s": {"pass": bool(g2s_n >= 2), "n_sizes_pass": g2s_n,
                    "sizes": g2s_fams},
        "gate3": {"pass": bool(g3pass), "tiny_solved": tiny_solved,
                  "tiny": gate3tiny,
                  "targets": gate3targets, "target_cap": target_cap},
        "gate4": {"pass": bool(g4_ok), "complete": bool(complete),
                  "tiny_attempted": bool(tiny_attempted),
                  "targets_attempted": bool(targets_attempted),
                  "wall_sec": wall, "clean": bool(clean)},
        "acceptance": {"pursue_condition": bool(pursue),
                       "reject_condition": bool(reject),
                       "win_sizes": win_fams,
                       "win_counts": win_counts,
                       "n_win_max_arm": n_win,
                       "n_strict_win": strict_n,
                       "selftest_ok": bool(selftest_ok),
                       "artifact_cells": list(artifact_cells),
                       "artifact_free": bool(artifact_free)},
        "reason": reason,
    }

    results = {
        "screen": "22",
        "verdict": "unresolved-with-reason: payload reports numbers "
                   "and gate evidence; classification is "
                   "coordinator-side.",
        "design": {
            "model": "screen-authored truncated-Fock bosonic-mode "
                     "stabilization simulator (stdlib + numpy only; "
                     "no external libs)",
            "sizes": list(N_TRUNC),
            "families": {str(k): v for k, v in FAMILIES.items()},
            "alpha_sq": {str(k): v for k, v in ALPHA_SQ.items()},
            "kappa_grid": list(KAPPA_GRID),
            "dt": DT,
            "t_steps": T_STEPS,
            "layouts": ["kappa-low", "kappa-high"],
            "seeds": list(SEEDS),
            "reps_per_cell_arm": n_inst,
            "greedy": {"sweeps": GREEDY_SWEEPS,
                       "slots": L_SEQ, "combos": N_COMBOS},
            "anneal": {"iters": n_iters, "t0": ANNEAL_T0,
                       "alpha": ANNEAL_ALPHA, "lambda": LAMBDA},
            "slots": L_SEQ,
            "combos": N_COMBOS,
            "bound": {"edge": BOUND_EDGE, "thresh": BOUND_THRESH,
                      "conv_tol": CONV_TOL},
            "arms": {"S": "fixed SNAP-echo schedule (pump off) "
                          "baseline",
                     "R": "random sequence control",
                     "G": "greedy first-improvement discrete-sequence "
                          "search from the S start",
                     "A": "simulated annealing over sequences "
                          "(infidelity + LAMBDA*boundary)"},
            "metrics": "logical infidelity at fixed time (primary) + "
                       "integrated-fidelity lifetime (secondary) + "
                       "boundary-population artifact guard",
            "pareto": "PURSUE needs an infidelity win + lifetime "
                      "no-regress on the SAME arm; an infidelity-only "
                      "win with lower lifetime is NOT a joint win; "
                      "joint wins counted PER ARM, bar max(G,A) >= 2; "
                      "any truncation-artifact cell blocks pursue",
            "exact": "bounded-exact level-order branch-and-bound "
                     "over sequences on tiny (must solve, optimum "
                     "%.1f) + target-scale instance (%d-mode family, "
                     "node cap %d, must cap-hit)" % (
                         TINY_OPT_INFID, N_TRUNC[TARGET["size_idx"]],
                         EXACT_CAP),
        },
        "timing": {"wall_s": wall, "guards": {"wall_guard_s": WALL_GUARD_S,
                                              "limit_s": WALL_LIMIT_S}},
        "cells": {("%d/%d/%s" % k): {"n": len(v["infid"]),
                                     **pooled_stats(v["infid"]),
                                     "life": pooled_stats(
                                         v["life"])}
                  for k, v in cells.items()},
        "gates": verdict_bits,
        "skipped": skipped,
    }
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)


if __name__ == "__main__":
    main()
