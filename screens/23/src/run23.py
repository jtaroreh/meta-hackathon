"""Screen 23 payload: adaptive QPE under T2 dephasing, fixed time/shots budget.

Screen-authored adaptive phase-estimation simulator (stdlib + numpy only):
unknown phase phi in [0, 2pi); each shot picks an evolution multiplier k and
a feedback angle theta; outcome 0/1 from P = (1 + C(k) cos(k(phi-theta)))/2
with T2 contrast C(k) = exp(-k*TAU/T2_VAL); the posterior is tracked on a
frozen N_PART particle grid. Arms: M myopic one-step expected-resultant
maximizer (the decomposed adaptive baseline), R seeded random control, G
depth-2 lookahead (shortlisted two-step search, receding horizon), A
simulated annealing over closed-loop (k-schedule + feedback-offset) policies
(cost = mean 1-cos(err) over N_ROLL seeded rollouts). Metric: Holevo
variance of the final estimator at fixed shots AND fixed time budget, plus
mean posterior concentration (no-regress secondary) and a
posterior-normalization estimator-validity audit (any invalid rep flags its
cell and blocks pursue). A bounded-exact level-order branch-and-bound over
setting sequences solves the tiny instance (optimum by construction) and
cap-hits at target scale (limit-expiry). Writes ALL output under cwd (the
attempt work dir): results.json + witnesses/. Deterministic given seeds.
Verdict is always unresolved-with-reason; classification is coordinator-side.
"""

import argparse
import json
import math
import os
import time

import numpy as np

SIZES = (2, 4, 6)
SEEDS = (1, 2, 3, 4, 5)
ARMS = ("M", "R", "G", "A")
N_SHOTS = 12
TIME_BUDGET = 16
TAU = 1.0
T2_VAL = 8.0
N_THETA = 6
N_PART = 64
LOOK_B = 6
ANNEAL_ITERS = 40
ANNEAL_T0 = 0.05
ANNEAL_ALPHA = 0.96
N_ROLL = 3
N_INST = 24
WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0
EXACT_CAP = 50000
TINY_KMAX = 1
TINY_SHOTS = 1
TINY_PHI = 0.0
TINY_OPT_V = 0.0
TINY_NCOMBOS = 6
TINY_C = 1.0
SCORE_TOL = 1e-12
VALID_TOL = 1e-9
VALID_SHARP_MIN = 1e-12
TARGET = {"size_idx": 2, "seed": 1, "rep": 0}
NEXT_EXPERIMENT = "depth-3 sparse lookahead with learned rollout policy plus closed-loop annealed feedback-gain retest under stronger T2 dephasing"

P_GRID = np.arange(N_PART, dtype=float) * (2.0 * math.pi / N_PART)
E_VEC = np.exp(1j * P_GRID)
TH_GRID = np.arange(N_THETA, dtype=float) * (2.0 * math.pi / N_THETA)

LIKE_CACHE = {}
TINY_LIKE = None


def seed_rng(size_idx, seed_v, rep_v, salt_v):
    return np.random.default_rng(
        (int(size_idx * 100003 + seed_v * 10007 + rep_v * 101
             + salt_v * 1000003) % (2 ** 63 - 1)))


def contrast_of(mult_k):
    return math.exp(-float(mult_k) * TAU / T2_VAL)


def get_like(size_idx):
    if size_idx not in LIKE_CACHE:
        kmax_v = SIZES[size_idx]
        tab_m = np.zeros((kmax_v + 1, N_THETA, N_PART))
        for mult_k in range(1, kmax_v + 1):
            cont_v = contrast_of(mult_k)
            for th_i in range(N_THETA):
                tab_m[mult_k, th_i, :] = 0.5 * (
                    1.0 + cont_v * np.cos(
                        mult_k * (P_GRID - TH_GRID[th_i])))
        LIKE_CACHE[size_idx] = tab_m
    return LIKE_CACHE[size_idx]


def get_tiny_like():
    global TINY_LIKE
    if TINY_LIKE is None:
        tab_m = np.zeros((TINY_KMAX + 1, N_THETA, N_PART))
        for th_i in range(N_THETA):
            tab_m[TINY_KMAX, th_i, :] = 0.5 * (
                1.0 + TINY_C * np.cos(
                    TINY_KMAX * (P_GRID - TH_GRID[th_i])))
        TINY_LIKE = tab_m
    return TINY_LIKE


def wrap_err(val_v):
    return (float(val_v) + math.pi) % (2.0 * math.pi) - math.pi


def filter_step(w_in, mult_k, th_idx, outcome_bv, like_tab):
    like_vec = like_tab[int(mult_k), int(th_idx)]
    if int(outcome_bv) == 1:
        like_vec = 1.0 - like_vec
    post_unnorm = w_in * like_vec
    norm_sum = float(np.sum(post_unnorm))
    post_new = post_unnorm / norm_sum
    return post_new


def predict_p0(w_in, mult_k, th_idx, like_tab):
    return float(np.dot(w_in, like_tab[int(mult_k), int(th_idx)]))


def resultant_of(w_in):
    z_val = complex(np.sum(w_in * E_VEC))
    return abs(z_val), math.atan2(z_val.imag, z_val.real)


def audit_weights(w_in):
    sum_v = float(np.sum(w_in))
    sharp_v, _ = resultant_of(w_in)
    return {"norm_ok": abs(sum_v - 1.0) <= VALID_TOL,
            "finite_ok": bool(np.all(np.isfinite(w_in))),
            "sharp_ok": bool(sharp_v > VALID_SHARP_MIN)}


def true_p0(phase_v, mult_k, th_idx, cont_v):
    return 0.5 * (1.0 + cont_v * math.cos(
        mult_k * (float(phase_v) - float(TH_GRID[int(th_idx)]))))


def feasible_kmax(budget_rem, shots_left, k_cap):
    avail_v = int(budget_rem) - (int(shots_left) - 1)
    maxk_v = int(k_cap)
    if avail_v < maxk_v:
        maxk_v = avail_v
    if maxk_v < 1:
        maxk_v = 1
    return maxk_v


def snap_idx(theta_v):
    return int(math.floor(float(theta_v) / (2.0 * math.pi)
                          * N_THETA + 0.5)) % N_THETA


def scored_candidates(w_in, budget_rem, shots_left, k_cap, like_tab):
    score_list = []
    feas_v = feasible_kmax(budget_rem, shots_left, k_cap)
    for mult_k in range(1, feas_v + 1):
        for th_idx in range(N_THETA):
            prob0_v = predict_p0(w_in, mult_k, th_idx, like_tab)
            w_post0 = filter_step(w_in, mult_k, th_idx, 0, like_tab)
            res0_v, _ = resultant_of(w_post0)
            w_post1 = filter_step(w_in, mult_k, th_idx, 1, like_tab)
            res1_v, _ = resultant_of(w_post1)
            score_v = prob0_v * res0_v + (1.0 - prob0_v) * res1_v
            score_list.append((score_v, mult_k, th_idx))
    return score_list


def myopic_choice(w_in, budget_rem, shots_left, k_cap, like_tab):
    best_score = -1.0
    best_k = 1
    best_th = 0
    for score_v, mult_k, th_idx in scored_candidates(
            w_in, budget_rem, shots_left, k_cap, like_tab):
        if score_v > best_score + SCORE_TOL:
            best_score = score_v
            best_k = mult_k
            best_th = th_idx
    return best_k, best_th, best_score


def two_step_value(w_in, first_k, first_th, budget_rem, shots_left,
                   k_cap, like_tab):
    prob0_v = predict_p0(w_in, first_k, first_th, like_tab)
    w_post0 = filter_step(w_in, first_k, first_th, 0, like_tab)
    _, _, sec0_v = myopic_choice(
        w_post0, budget_rem - first_k, shots_left - 1, k_cap, like_tab)
    w_post1 = filter_step(w_in, first_k, first_th, 1, like_tab)
    _, _, sec1_v = myopic_choice(
        w_post1, budget_rem - first_k, shots_left - 1, k_cap, like_tab)
    return prob0_v * sec0_v + (1.0 - prob0_v) * sec1_v


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


def decode_combo(flat_d, k_cap):
    flat_i = int(flat_d) % (int(k_cap) * N_THETA)
    return flat_i // N_THETA + 1, flat_i % N_THETA


def enforce_budget(flat_seq, k_cap, budget_v, pick_rng):
    work_seq = list(flat_seq)
    for _ in range(4096):
        mult_list = [decode_combo(d_v, k_cap)[0] for d_v in work_seq]
        if sum(mult_list) <= int(budget_v):
            break
        flex_idx = [i_v for i_v, m_v in enumerate(mult_list) if m_v > 1]
        if not flex_idx:
            break
        pick_i = flex_idx[int(pick_rng.integers(len(flex_idx)))]
        old_k, old_th = decode_combo(work_seq[pick_i], k_cap)
        work_seq[pick_i] = (old_k - 2) * N_THETA + old_th
    return work_seq


def gen_phase(size_idx, seed_v, rep_v):
    phase_rng = seed_rng(size_idx, seed_v, rep_v, 11)
    return float(phase_rng.uniform(0.0, 2.0 * math.pi))


def gen_draws(size_idx, seed_v, rep_v, n_shots):
    draw_rng = seed_rng(size_idx, seed_v, rep_v, 12)
    return [float(v_v) for v_v in draw_rng.uniform(size=n_shots)]


def gen_eval_sets(size_idx, seed_v, rep_v):
    phi_rng = seed_rng(size_idx, seed_v, rep_v, 775)
    uni_rng = seed_rng(size_idx, seed_v, rep_v, 774)
    eval_phases = [float(v_v) for v_v in
                   phi_rng.uniform(0.0, 2.0 * math.pi, size=N_ROLL)]
    eval_draws = [[float(v_v) for v_v in row_v] for row_v in
                  uni_rng.uniform(size=(N_ROLL, N_SHOTS))]
    return eval_phases, eval_draws


def run_m(phase_true, outcome_draws, k_cap, like_tab, budget_v, stop_fn):
    """Myopic one-step adaptive baseline: each shot maximizes the expected
    posterior resultant over feasible (k, theta); ties keep the first
    (smallest k, smallest theta) via SCORE_TOL. Never mutates inputs."""
    post_w = np.full(N_PART, 1.0 / N_PART)
    spend_used = 0
    budget_rem = int(budget_v)
    n_shots = len(outcome_draws)
    cont_tab = {m_k: (math.exp(-float(m_k) * TAU / T2_VAL)
                      if like_tab is not TINY_LIKE else TINY_C)
                for m_k in range(1, int(k_cap) + 1)}
    for shot_t in range(n_shots):
        if shot_t % 4 == 0 and stop_fn is not None and stop_fn():
            return {"err": None, "conc": None, "spend": None,
                    "audit": None, "stopped": True}
        shots_left = n_shots - shot_t
        pick_k, pick_th, _ = myopic_choice(
            post_w, budget_rem, shots_left, k_cap, like_tab)
        prob0_v = true_p0(phase_true, pick_k, pick_th,
                          cont_tab[pick_k])
        bit_v = 0 if float(outcome_draws[shot_t]) < prob0_v else 1
        post_w = filter_step(post_w, pick_k, pick_th, bit_v, like_tab)
        budget_rem -= pick_k
        spend_used += pick_k
    sharp_v, mean_v = resultant_of(post_w)
    return {"err": wrap_err(mean_v - float(phase_true)), "conc": sharp_v,
            "spend": spend_used, "audit": audit_weights(post_w),
            "stopped": False}


def run_r(phase_true, outcome_draws, k_cap, like_tab, budget_v,
          choice_rng, stop_fn):
    """Random control: seeded uniform (k, theta) among feasible settings;
    same outcome-draw coupling as the other arms. Never mutates inputs."""
    post_w = np.full(N_PART, 1.0 / N_PART)
    spend_used = 0
    budget_rem = int(budget_v)
    n_shots = len(outcome_draws)
    cont_tab = {m_k: (math.exp(-float(m_k) * TAU / T2_VAL)
                      if like_tab is not TINY_LIKE else TINY_C)
                for m_k in range(1, int(k_cap) + 1)}
    for shot_t in range(n_shots):
        if shot_t % 4 == 0 and stop_fn is not None and stop_fn():
            return {"err": None, "conc": None, "spend": None,
                    "audit": None, "stopped": True}
        shots_left = n_shots - shot_t
        feas_v = feasible_kmax(budget_rem, shots_left, k_cap)
        pick_k = int(choice_rng.integers(1, feas_v + 1))
        pick_th = int(choice_rng.integers(N_THETA))
        prob0_v = true_p0(phase_true, pick_k, pick_th,
                          cont_tab[pick_k])
        bit_v = 0 if float(outcome_draws[shot_t]) < prob0_v else 1
        post_w = filter_step(post_w, pick_k, pick_th, bit_v, like_tab)
        budget_rem -= pick_k
        spend_used += pick_k
    sharp_v, mean_v = resultant_of(post_w)
    return {"err": wrap_err(mean_v - float(phase_true)), "conc": sharp_v,
            "spend": spend_used, "audit": audit_weights(post_w),
            "stopped": False}


def run_g(phase_true, outcome_draws, k_cap, like_tab, budget_v, stop_fn):
    """Depth-2 lookahead: every shot scores all feasible first settings by
    expected two-step resultant (top LOOK_B by myopic score get the full
    nested rollout; the rest carry their myopic score as proxy), picks the
    argmax with SCORE_TOL ties-to-first, then replans. Never mutates inputs.
    """
    post_w = np.full(N_PART, 1.0 / N_PART)
    spend_used = 0
    budget_rem = int(budget_v)
    n_shots = len(outcome_draws)
    cont_tab = {m_k: (math.exp(-float(m_k) * TAU / T2_VAL)
                      if like_tab is not TINY_LIKE else TINY_C)
                for m_k in range(1, int(k_cap) + 1)}
    for shot_t in range(n_shots):
        if stop_fn is not None and stop_fn():
            return {"err": None, "conc": None, "spend": None,
                    "audit": None, "stopped": True}
        shots_left = n_shots - shot_t
        if shots_left < 2:
            pick_k, pick_th, _ = myopic_choice(
                post_w, budget_rem, shots_left, k_cap, like_tab)
        else:
            cand_scores = scored_candidates(
                post_w, budget_rem, shots_left, k_cap, like_tab)
            order_idx = sorted(range(len(cand_scores)),
                               key=lambda i_v: -cand_scores[i_v][0])
            short_set = set(order_idx[:min(LOOK_B, len(order_idx))])
            best_val = -1.0
            pick_k, pick_th = cand_scores[0][1], cand_scores[0][2]
            for cand_i, (score_v, mult_k, th_idx) in enumerate(
                    cand_scores):
                if cand_i in short_set:
                    val_v = two_step_value(
                        post_w, mult_k, th_idx, budget_rem, shots_left,
                        k_cap, like_tab)
                else:
                    val_v = score_v
                if val_v > best_val + SCORE_TOL:
                    best_val = val_v
                    pick_k, pick_th = mult_k, th_idx
        prob0_v = true_p0(phase_true, pick_k, pick_th,
                          cont_tab[pick_k])
        bit_v = 0 if float(outcome_draws[shot_t]) < prob0_v else 1
        post_w = filter_step(post_w, pick_k, pick_th, bit_v, like_tab)
        budget_rem -= pick_k
        spend_used += pick_k
    sharp_v, mean_v = resultant_of(post_w)
    return {"err": wrap_err(mean_v - float(phase_true)), "conc": sharp_v,
            "spend": spend_used, "audit": audit_weights(post_w),
            "stopped": False}


def rollout_policy(flat_seq, off_val, phase_true, outcome_draws, k_cap,
                   like_tab, budget_v):
    """Closed-loop rollout of an annealed (k-schedule + feedback-offset)
    policy: shot t uses k_t (clipped to feasible) and theta snapped from
    posterior mean + off_val. Returns per-rep proxy cost 1-cos(err)."""
    post_w = np.full(N_PART, 1.0 / N_PART)
    budget_rem = int(budget_v)
    n_shots = len(outcome_draws)
    cont_tab = {m_k: (math.exp(-float(m_k) * TAU / T2_VAL)
                      if like_tab is not TINY_LIKE else TINY_C)
                for m_k in range(1, int(k_cap) + 1)}
    for shot_t in range(n_shots):
        shots_left = n_shots - shot_t
        feas_v = feasible_kmax(budget_rem, shots_left, k_cap)
        raw_k, _ = decode_combo(flat_seq[shot_t], k_cap)
        use_k = raw_k if raw_k <= feas_v else feas_v
        _, mean_v = resultant_of(post_w)
        use_th = snap_idx(mean_v + float(off_val))
        prob0_v = true_p0(phase_true, use_k, use_th, cont_tab[use_k])
        bit_v = 0 if float(outcome_draws[shot_t]) < prob0_v else 1
        post_w = filter_step(post_w, use_k, use_th, bit_v, like_tab)
        budget_rem -= use_k
    _, final_v = resultant_of(post_w)
    return 1.0 - math.cos(wrap_err(final_v - float(phase_true)))


def eval_policy(flat_seq, off_val, eval_phases, eval_draws, k_cap,
                like_tab, budget_v):
    cost_list = [rollout_policy(flat_seq, off_val, eval_phases[r_r],
                                eval_draws[r_r], k_cap, like_tab,
                                budget_v)
                 for r_r in range(len(eval_phases))]
    return sum(cost_list) / len(cost_list)


def run_a(eval_phases, eval_draws, real_phase, real_draws, k_cap,
          like_tab, budget_v, n_iters, prop_rng, stop_fn):
    """Annealed closed-loop policy search over flat (k, theta) schedules
    plus a feedback offset: proposals mutate one slot or the offset,
    budget-repaired; cost = mean 1-cos(err) over N_ROLL seeded rollouts;
    best tracked with strict improvement so the start is never regressed
    past. Inputs are copied, never mutated."""
    n_shots = len(real_draws)
    n_combos = int(k_cap) * N_THETA
    anneal_seq = enforce_budget(
        repair_seq([0] * n_shots, n_shots, n_combos), k_cap, budget_v,
        prop_rng)
    anneal_off = 0.0
    anneal_cost = eval_policy(anneal_seq, anneal_off, eval_phases,
                              eval_draws, k_cap, like_tab, budget_v)
    best_seq = list(anneal_seq)
    best_off = float(anneal_off)
    best_cost = float(anneal_cost)
    anneal_temp = ANNEAL_T0
    for iter_i in range(int(n_iters)):
        if iter_i % 8 == 0 and stop_fn is not None and stop_fn():
            return {"err": None, "conc": None, "spend": None,
                    "audit": None, "stopped": True}
        if float(prop_rng.random()) < 0.7:
            slot_pick = int(prop_rng.integers(n_shots))
            raw_seq = list(anneal_seq)
            raw_seq[slot_pick] = int(prop_rng.integers(n_combos))
            prop_seq = enforce_budget(
                repair_seq(raw_seq, n_shots, n_combos), k_cap,
                budget_v, prop_rng)
            prop_off = float(anneal_off)
        else:
            prop_seq = list(anneal_seq)
            prop_off = float(anneal_off
                             + float(prop_rng.normal(0.0, 0.5)))
        prop_cost = eval_policy(prop_seq, prop_off, eval_phases,
                                eval_draws, k_cap, like_tab, budget_v)
        accept_draw = float(prop_rng.random())
        if prop_cost < anneal_cost or bool(
                accept_draw < math.exp(-(prop_cost - anneal_cost)
                                       / anneal_temp)):
            anneal_seq = prop_seq
            anneal_off = prop_off
            anneal_cost = prop_cost
            if prop_cost < best_cost:
                best_seq = list(prop_seq)
                best_off = float(prop_off)
                best_cost = float(prop_cost)
        anneal_temp *= ANNEAL_ALPHA
    post_w = np.full(N_PART, 1.0 / N_PART)
    budget_rem = int(budget_v)
    spend_used = 0
    for shot_t in range(n_shots):
        shots_left = n_shots - shot_t
        feas_v = feasible_kmax(budget_rem, shots_left, k_cap)
        raw_k, _ = decode_combo(best_seq[shot_t], k_cap)
        use_k = raw_k if raw_k <= feas_v else feas_v
        _, mean_v = resultant_of(post_w)
        use_th = snap_idx(mean_v + best_off)
        cont_v = (math.exp(-float(use_k) * TAU / T2_VAL)
                  if like_tab is not TINY_LIKE else TINY_C)
        prob0_v = true_p0(real_phase, use_k, use_th, cont_v)
        bit_v = 0 if float(real_draws[shot_t]) < prob0_v else 1
        post_w = filter_step(post_w, use_k, use_th, bit_v, like_tab)
        budget_rem -= use_k
        spend_used += use_k
    sharp_v, final_v = resultant_of(post_w)
    return {"err": wrap_err(final_v - float(real_phase)),
            "conc": sharp_v, "spend": spend_used,
            "audit": audit_weights(post_w), "stopped": False}


def exact_opt(n_combos, depth_v, leaf_infid, base_infid, cap, stop):
    """Bounded-exact level-order branch-and-bound over flat setting
    sequences, minimizing realized proxy cost with an admissible zero
    lower bound (bounding comes from the node budget, never from
    data-dependent pruning, so node counts are deterministic).
    Level-order enumeration counts every partial schedule; leaves are
    evaluated only when reached. Statuses: solved / cap-hit /
    stopped-guard."""
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


def tiny_leaf_cost(flat_seq, tiny_like):
    use_k, use_th = decode_combo(flat_seq[0], TINY_KMAX)
    tiny_draw = float(seed_rng(9, 9, 9, 31).uniform())
    prob0_v = 0.5 * (1.0 + TINY_C * math.cos(
        use_k * (TINY_PHI - float(TH_GRID[use_th]))))
    bit_v = 0 if tiny_draw < prob0_v else 1
    post_w = np.full(N_PART, 1.0 / N_PART)
    post_w = filter_step(post_w, use_k, use_th, bit_v, tiny_like)
    _, mean_v = resultant_of(post_w)
    return 1.0 - math.cos(wrap_err(mean_v - TINY_PHI))


def run_tiny_arm(arm_k, tiny_like, n_iters):
    tiny_draws = [0.0]
    if arm_k == "M":
        return run_m(TINY_PHI, tiny_draws, TINY_KMAX, tiny_like,
                     TIME_BUDGET, None)
    if arm_k == "R":
        return run_r(TINY_PHI, tiny_draws, TINY_KMAX, tiny_like,
                     TIME_BUDGET, seed_rng(0, 7, 7, 999), None)
    if arm_k == "G":
        return run_g(TINY_PHI, tiny_draws, TINY_KMAX, tiny_like,
                     TIME_BUDGET, None)
    tiny_phases = [TINY_PHI] * N_ROLL
    tiny_drawsets = [[0.0] for _ in range(N_ROLL)]
    return run_a(tiny_phases, tiny_drawsets, TINY_PHI, tiny_draws,
                 TINY_KMAX, tiny_like, TIME_BUDGET, n_iters,
                 seed_rng(0, 7, 7, 777), None)


def self_tests():
    out = {"ran": True, "failed": [], "gradient_probe": []}
    try:
        if TINY_NCOMBOS != TINY_KMAX * N_THETA:
            out["failed"].append("tiny-ncombos-mismatch")
        if not (0 <= TARGET["size_idx"] < len(SIZES)):
            out["failed"].append("target-size-range")
        if TARGET["seed"] not in SEEDS:
            out["failed"].append("target-seed-range")
        size0_like = get_like(0)
        if size0_like.shape != (SIZES[0] + 1, N_THETA, N_PART):
            out["failed"].append("like-shape")
        if not bool(np.all(size0_like[1:] > 0.0)) or not bool(
                np.all(size0_like[1:] < 1.0)):
            out["failed"].append("like-prob-range")
        if abs(contrast_of(1) - math.exp(-TAU / T2_VAL)) > 1e-15:
            out["failed"].append("contrast-formula")
        if len(P_GRID) != N_PART or len(TH_GRID) != N_THETA:
            out["failed"].append("grid-shape")
        probe_phase = gen_phase(0, 1, 0)
        if not 0.0 <= probe_phase < 2.0 * math.pi:
            out["failed"].append("phase-range")
        probe_draws = gen_draws(0, 1, 0, N_SHOTS)
        if len(probe_draws) != N_SHOTS or not all(
                0.0 <= d_v < 1.0 for d_v in probe_draws):
            out["failed"].append("draws-range")
        uni_w = np.full(N_PART, 1.0 / N_PART)
        uni_audit = audit_weights(uni_w)
        if not uni_audit["norm_ok"] or not uni_audit["finite_ok"]:
            out["failed"].append("audit-uniform-pass")
        zero_w = np.zeros(N_PART)
        if audit_weights(zero_w)["norm_ok"]:
            out["failed"].append("audit-zero-norm")
        nan_w = uni_w.copy()
        nan_w[3] = float("nan")
        if audit_weights(nan_w)["finite_ok"]:
            out["failed"].append("audit-nan-finite")
        spike_w = np.zeros(N_PART)
        spike_w[0] = 1.0
        if not audit_weights(spike_w)["sharp_ok"]:
            out["failed"].append("audit-spike-sharp")
        cancel_w = np.zeros(N_PART)
        cancel_w[0] = 0.5
        cancel_w[N_PART // 2] = 0.5
        if audit_weights(cancel_w)["sharp_ok"]:
            out["failed"].append("audit-cancel-sharp")
        tiny_like = get_tiny_like()
        tiny_results = {}
        for arm_k in ("M", "R", "G", "A"):
            tiny_results[arm_k] = run_tiny_arm(arm_k, tiny_like, 50)
        for arm_k in ("M", "G", "A"):
            arm_out = tiny_results[arm_k]
            if arm_out.get("stopped"):
                out["failed"].append("tiny-%s-stopped" % arm_k)
            elif abs(float(arm_out["err"])) > 1e-9:
                out["failed"].append("tiny-%s-hand" % arm_k)
        if tiny_results["R"].get("stopped"):
            out["failed"].append("tiny-R-stopped")
        tiny_base = 1.0 - math.cos(
            float(tiny_results["M"]["err"]))
        tiny_ex = exact_opt(TINY_NCOMBOS, TINY_SHOTS,
                            lambda s_q: tiny_leaf_cost(s_q, tiny_like),
                            tiny_base, EXACT_CAP, None)
        if tiny_ex["status"] != "solved" or abs(
                tiny_ex["opt_infid"] - TINY_OPT_V) > 1e-9:
            out["failed"].append("tiny-exact-opt")
        if tiny_ex["nodes"] != 1 + TINY_NCOMBOS:
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
        budget_probe = enforce_budget(
            [35] * N_SHOTS, SIZES[2], TIME_BUDGET,
            seed_rng(0, 1, 0, 5))
        budget_ks = [decode_combo(d_v, SIZES[2])[0]
                     for d_v in budget_probe]
        if sum(budget_ks) > TIME_BUDGET or any(
                m_v < 1 for m_v in budget_ks):
            out["failed"].append("budget-repair")
        budget_in = [35] * N_SHOTS
        enforce_budget(budget_in, SIZES[2], TIME_BUDGET,
                       seed_rng(0, 1, 0, 5))
        if budget_in != [35] * N_SHOTS:
            out["failed"].append("alias-mutate-budget")
        probe_all_tied = True
        probe_gm_tied = True
        for probe_rep in range(4):
            probe_phase = gen_phase(0, 1, probe_rep)
            probe_draws = gen_draws(0, 1, probe_rep, N_SHOTS)
            probe_like = get_like(0)
            eval_ph, eval_dr = gen_eval_sets(0, 1, probe_rep)
            probe_m = run_m(probe_phase, probe_draws, SIZES[0],
                            probe_like, TIME_BUDGET, None)
            probe_r = run_r(probe_phase, probe_draws, SIZES[0],
                            probe_like, TIME_BUDGET,
                            seed_rng(0, 1, probe_rep, 999), None)
            probe_g = run_g(probe_phase, probe_draws, SIZES[0],
                            probe_like, TIME_BUDGET, None)
            probe_a = run_a(eval_ph, eval_dr, probe_phase,
                            probe_draws, SIZES[0], probe_like,
                            TIME_BUDGET, 20,
                            seed_rng(0, 1, probe_rep, 777), None)
            probe_vals = (probe_m["err"], probe_r["err"],
                          probe_g["err"], probe_a["err"])
            out["gradient_probe"].append(
                {"rep": probe_rep,
                 "err": list(probe_vals),
                 "conc": [probe_m["conc"], probe_r["conc"],
                          probe_g["conc"], probe_a["conc"]]})
            for arm_out in (probe_m, probe_r, probe_g, probe_a):
                if arm_out.get("stopped"):
                    out["failed"].append("probe-stopped")
                arm_audit = arm_out.get("audit") or {}
                if not (arm_audit.get("norm_ok")
                        and arm_audit.get("finite_ok")
                        and arm_audit.get("sharp_ok")):
                    out["failed"].append("probe-validity")
                if arm_out["spend"] is None or \
                        arm_out["spend"] > TIME_BUDGET:
                    out["failed"].append("probe-budget")
            if not (probe_vals[0] == probe_vals[1] == probe_vals[2]
                    == probe_vals[3]):
                probe_all_tied = False
            if probe_vals[2] != probe_vals[0]:
                probe_gm_tied = False
            if probe_g["audit"] is None:
                out["failed"].append("probe-audit-missing")
        if probe_all_tied:
            out["failed"].append("gradient-degenerate")
        if probe_gm_tied:
            out["failed"].append("gradient-gm-tied")
        alias_w = np.full(N_PART, 1.0 / N_PART)
        alias_snap = alias_w.copy()
        filter_step(alias_w, 1, 0, 0, size0_like)
        if not np.array_equal(alias_w, alias_snap):
            out["failed"].append("alias-mutate-filter")
        choice_w = np.full(N_PART, 1.0 / N_PART)
        choice_snap = choice_w.copy()
        myopic_choice(choice_w, TIME_BUDGET, N_SHOTS, SIZES[0],
                      size0_like)
        if not np.array_equal(choice_w, choice_snap):
            out["failed"].append("alias-mutate-myopic")
        eval_ph, eval_dr = gen_eval_sets(0, 1, 0)
        eval_ph_snap = [v_v for v_v in eval_ph]
        eval_dr_snap = [[v_v for v_v in row_v] for row_v in eval_dr]
        real_draws = gen_draws(0, 1, 0, N_SHOTS)
        real_snap = [v_v for v_v in real_draws]
        run_a(eval_ph, eval_dr, gen_phase(0, 1, 0), real_draws,
              SIZES[0], size0_like, TIME_BUDGET, 10,
              seed_rng(0, 1, 0, 777), None)
        if eval_ph != eval_ph_snap or eval_dr != eval_dr_snap \
                or real_draws != real_snap:
            out["failed"].append("alias-mutate-anneal")
        det_g1 = run_g(probe_phase, probe_draws, SIZES[0],
                       probe_like, TIME_BUDGET, None)
        det_g2 = run_g(probe_phase, probe_draws, SIZES[0],
                       probe_like, TIME_BUDGET, None)
        if (det_g1["err"], det_g1["conc"]) != (det_g2["err"],
                                               det_g2["conc"]):
            out["failed"].append("determinism-lookahead")
        det_r1 = run_r(probe_phase, probe_draws, SIZES[0],
                       probe_like, TIME_BUDGET,
                       seed_rng(0, 1, 0, 999), None)
        det_r2 = run_r(probe_phase, probe_draws, SIZES[0],
                       probe_like, TIME_BUDGET,
                       seed_rng(0, 1, 0, 999), None)
        if (det_r1["err"], det_r1["conc"]) != (det_r2["err"],
                                               det_r2["conc"]):
            out["failed"].append("determinism-random")
        det_a1 = run_a(eval_ph, eval_dr, probe_phase, probe_draws,
                       SIZES[0], probe_like, TIME_BUDGET, 10,
                       seed_rng(0, 1, 0, 777), None)
        det_a2 = run_a(eval_ph, eval_dr, probe_phase, probe_draws,
                       SIZES[0], probe_like, TIME_BUDGET, 10,
                       seed_rng(0, 1, 0, 777), None)
        if (det_a1["err"], det_a1["conc"]) != (det_a2["err"],
                                               det_a2["conc"]):
            out["failed"].append("determinism-anneal")
    except Exception as ex:
        out["failed"].append("raise: %r" % ex)
    return out


def run_arm(size_idx, seed_v, rep_v, arm, n_iters, stop):
    like_tab = get_like(size_idx)
    k_cap = SIZES[size_idx]
    phase_v = gen_phase(size_idx, seed_v, rep_v)
    draw_list = gen_draws(size_idx, seed_v, rep_v, N_SHOTS)
    if arm == "M":
        return run_m(phase_v, draw_list, k_cap, like_tab,
                     TIME_BUDGET, stop)
    if arm == "R":
        return run_r(phase_v, draw_list, k_cap, like_tab,
                     TIME_BUDGET,
                     seed_rng(size_idx, seed_v, rep_v, 999), stop)
    if arm == "G":
        return run_g(phase_v, draw_list, k_cap, like_tab,
                     TIME_BUDGET, stop)
    eval_ph, eval_dr = gen_eval_sets(size_idx, seed_v, rep_v)
    return run_a(eval_ph, eval_dr, phase_v, draw_list, k_cap,
                 like_tab, TIME_BUDGET, n_iters,
                 seed_rng(size_idx, seed_v, rep_v, 777), stop)


def holevo_of(err_list):
    if not err_list:
        return None
    evec_m = np.exp(1j * np.asarray(err_list, dtype=float))
    mean_v = complex(np.mean(evec_m))
    sharp_v = abs(mean_v)
    if sharp_v <= VALID_SHARP_MIN:
        return None
    return 1.0 / (sharp_v * sharp_v) - 1.0


def bias_of(err_list):
    evec_m = np.exp(1j * np.asarray(err_list, dtype=float))
    mean_v = complex(np.mean(evec_m))
    return abs(math.atan2(mean_v.imag, mean_v.real))


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

    cellrecs = []
    skipped = []
    invalid_cells = []
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
                           "n_cells": len(cellrecs),
                           "gate3tiny": gate3tiny,
                           "gate3targets": gate3targets,
                           "n_skipped": len(skipped),
                           "n_invalid_cells": len(invalid_cells),
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
        tiny_like = get_tiny_like()
        tiny_m = run_tiny_arm("M", tiny_like, n_iters)
        tiny_base = 1.0 - math.cos(float(tiny_m["err"]))

        def tiny_leaf(leaf_seq):
            return tiny_leaf_cost(leaf_seq, tiny_like)

        ex = exact_opt(TINY_NCOMBOS, TINY_SHOTS, tiny_leaf,
                       tiny_base, EXACT_CAP, over)
        gate3tiny["arms"]["tiny"] = ex
        gate3tiny["total"] += 1
        if ex["status"] == "solved" and abs(
                ex["opt_infid"] - TINY_OPT_V) <= 1e-9:
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
        t_like = get_like(TARGET["size_idx"])
        t_kmax = SIZES[TARGET["size_idx"]]
        t_phase = gen_phase(TARGET["size_idx"], TARGET["seed"],
                            TARGET["rep"])
        t_draws = gen_draws(TARGET["size_idx"], TARGET["seed"],
                            TARGET["rep"], N_SHOTS)
        t_base_out = run_m(t_phase, t_draws, t_kmax, t_like,
                           TIME_BUDGET, over)
        if t_base_out.get("stopped"):
            gate3targets.append({"status": "stopped-guard",
                                 "nodes": 0})
            skipped.append({"what": "target-exact",
                            "reason": "stopped-guard",
                            "iters_done": 0,
                            "n_evaluated": EXACT_CAP})
        else:
            t_base = 1.0 - math.cos(float(t_base_out["err"]))

            def target_leaf(leaf_seq):
                return rollout_policy(list(leaf_seq), 0.0, t_phase,
                                      t_draws, t_kmax, t_like,
                                      TIME_BUDGET)

            tex = exact_opt(t_kmax * N_THETA, N_SHOTS, target_leaf,
                            t_base, EXACT_CAP, over)
            gate3targets.append(dict(tex, size=t_kmax,
                                     kmax=t_kmax))
            if tex["status"] == "stopped-guard":
                skipped.append({"what": "target-exact",
                                "reason": "stopped-guard",
                                "iters_done": tex.get("nodes", 0),
                                "n_evaluated": EXACT_CAP})
    with open(os.path.join(witdir, "gate3_targets.json"), "w") as f:
        json.dump(gate3targets, f, indent=1, default=str)
    checkpoint("targets")

    def run_cellrec(si, seed_v, arm):
        rec = {"size": SIZES[si], "seed": seed_v, "arm": arm,
               "errs": [], "concs": [], "spends": [], "n_valid": 0,
               "blocked": None, "iters_done": 0,
               "n_evaluated": n_inst}
        if over():
            rec["blocked"] = "wall-guard"
            rec["iters_done"] = 0
            return rec
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
            rec["errs"].append(float(arm_out["err"]))
            rec["concs"].append(float(arm_out["conc"]))
            rec["spends"].append(int(arm_out["spend"]))
            arm_audit = arm_out.get("audit") or {}
            if bool(arm_audit.get("norm_ok")) and bool(
                    arm_audit.get("finite_ok")) and bool(
                    arm_audit.get("sharp_ok")):
                rec["n_valid"] += 1
        if nstop:
            rec["blocked"] = "stopped-guard"
            rec["iters_done"] = len(rec["errs"])
            return rec
        rec["iters_done"] = len(rec["errs"])
        return rec

    def record_cellrec(rec):
        if rec.get("blocked") is None and len(rec["errs"]) == n_inst:
            cellrecs.append(rec)
            return True
        skipped.append({"what": "cell %d/%d/%s" % (
            rec["size"], rec["seed"], rec["arm"]),
            "reason": rec.get("blocked", "arm-incomplete"),
            "iters_done": rec.get("iters_done", 0),
            "n_evaluated": n_inst})
        return False

    for si, kmax_v in enumerate(SIZES):
        siz_cells = [(si, seed_v) for seed_v in SEEDS]
        if over():
            for (s2, sd2) in siz_cells:
                for arm in ARMS:
                    skipped.append({"what": "cell %d/%d/%s" % (
                        SIZES[s2], sd2, arm), "reason": "wall-guard",
                        "iters_done": 0, "n_evaluated": n_inst})
        else:
            for (s2, sd2) in siz_cells:
                if over():
                    for arm in ARMS:
                        skipped.append({"what": "cell %d/%d/%s" % (
                            SIZES[s2], sd2, arm),
                            "reason": "wall-guard",
                            "iters_done": 0, "n_evaluated": n_inst})
                    continue
                for arm in ARMS:
                    rec = run_cellrec(s2, sd2, arm)
                    record_cellrec(rec)
        with open(os.path.join(witdir, "cells.json"), "w") as f:
            json.dump(cellrecs, f, indent=1, default=str)
        checkpoint("size%d" % kmax_v)
    with open(os.path.join(witdir, "cells.json"), "w") as f:
        json.dump(cellrecs, f, indent=1, default=str)
    checkpoint("corpus")

    with open(os.path.join(witdir, "cells.json")) as f:
        loaded_recs = json.load(f)

    summaries = {}
    for rec in loaded_recs:
        key = "%d/%d/%s" % (rec["size"], rec["seed"], rec["arm"])
        holevo_v = holevo_of(rec.get("errs", []))
        conc_m = float(np.mean(rec.get("concs", [float("nan")])))
        bias_v = bias_of(rec.get("errs", [])) \
            if rec.get("errs") else None
        spend_m = float(np.mean(rec.get("spends", [0])))
        valid_v = bool(rec.get("n_valid", 0) == n_inst
                       and holevo_v is not None)
        summaries[key] = {"n": len(rec.get("errs", [])),
                          "holevo": holevo_v, "conc": conc_m,
                          "bias": bias_v, "spend": spend_m,
                          "valid": valid_v}
        if not valid_v:
            invalid_cells.append(key)

    def cell_holevo(size_v, seed_v, arm):
        return summaries.get(
            "%d/%d/%s" % (size_v, seed_v, arm), {}).get("holevo")

    def cell_conc(size_v, seed_v, arm):
        return summaries.get(
            "%d/%d/%s" % (size_v, seed_v, arm), {}).get("conc")

    def pool_vals(size_v, arm, field):
        vals = []
        for seed_v in SEEDS:
            entry = summaries.get("%d/%d/%s" % (size_v, seed_v, arm))
            if entry is not None and entry.get(field) is not None:
                vals.append(entry[field])
        return pooled_stats(vals), len(vals) == len(SEEDS)

    det_g = run_arm(0, 1, 0, "G", n_iters, None)
    det_gb = run_arm(0, 1, 0, "G", n_iters, None)
    det_r = run_arm(0, 1, 0, "R", n_iters, None)
    det_rb = run_arm(0, 1, 0, "R", n_iters, None)
    det_a = run_arm(0, 1, 0, "A", n_iters, None)
    det_ab = run_arm(0, 1, 0, "A", n_iters, None)
    determinism_ok = bool(
        (det_g["err"], det_g["conc"]) == (det_gb["err"],
                                          det_gb["conc"])
        and (det_r["err"], det_r["conc"]) == (det_rb["err"],
                                              det_rb["conc"])
        and (det_a["err"], det_a["conc"]) == (det_ab["err"],
                                              det_ab["conc"]))

    g1_cells, g1_beats = [], True
    for size_v in SIZES:
        for seed_v in SEEDS:
            hg = cell_holevo(size_v, seed_v, "G")
            hr = cell_holevo(size_v, seed_v, "R")
            ok = (hg is not None and hr is not None and hg < hr)
            g1_cells.append({"cell": "%d/%d" % (size_v, seed_v),
                             "mean_G": hg, "mean_R": hr,
                             "pass": bool(ok)})
            if not ok:
                g1_beats = False
    g1_ok = bool(g1_beats and tiny_ok and determinism_ok)

    g2_fams, g2_n = [], 0
    g2s_fams, g2s_n = [], 0
    win_fams = []
    win_counts = {"G": 0, "A": 0}
    for size_v in SIZES:
        pools, pok = {}, True
        for arm in ("M", "G", "A"):
            pools[arm], oka = pool_vals(size_v, arm, "holevo")
            pok = pok and oka
        se_v, spread_v, gp = spread_win(pools, pok)
        g2_fams.append({"size": size_v, "pools": pools, "SE": se_v,
                        "spread": spread_v, "pass": bool(gp)})
        if gp:
            g2_n += 1
        spools, spok = {}, True
        for arm in ("M", "G", "A"):
            spools[arm], oka = pool_vals(size_v, arm, "conc")
            spok = spok and oka
        sse, sspread, sgp = spread_win(spools, spok)
        g2s_fams.append({"size": size_v, "pools": spools,
                         "SE": sse, "spread": sspread,
                         "pass": bool(sgp)})
        if sgp:
            g2s_n += 1
        joint = {}
        if pok and spok and all(
                pools[a]["se"] is not None and
                pools[a]["mean"] is not None for a in ("M", "G", "A")):
            sse2 = math.sqrt(sum(pools[a]["se"] ** 2
                                 for a in ("M", "G", "A")) / 3.0)
            for a in ("G", "A"):
                iwin = pools[a]["mean"] < pools["M"]["mean"] \
                    - 2.0 * sse2
                lok = spools[a]["mean"] >= spools["M"]["mean"]
                joint[a] = bool(iwin and lok)
        else:
            joint = {"G": False, "A": False}
        for a in ("G", "A"):
            if joint[a]:
                win_counts[a] += 1
        if pok and all(pools[a]["mean"] is not None
                       for a in ("M", "G", "A")):
            spass = (pools["G"]["mean"] < pools["M"]["mean"] or
                     pools["A"]["mean"] < pools["M"]["mean"])
        else:
            spass = False
        win_fams.append({"size": size_v, "strict_win": bool(spass),
                         "pools_ok": bool(pok),
                         "joint": dict(joint)})
    g2_ok = g2_n >= 2

    tiny_solved = (gate3tiny["total"] == 1 and gate3tiny["solved"] == 1)
    target_cap = (len(gate3targets) == 1 and
                  gate3targets[0].get("status") == "cap-hit" and
                  gate3targets[0].get("nodes") == EXACT_CAP + 1)
    g3pass = bool(tiny_solved and target_cap)

    complete = all(
        summaries.get("%d/%d/%s" % (size_v, seed_v, arm),
                      {}).get("n") == n_inst
        for size_v in SIZES for seed_v in SEEDS for arm in ARMS)
    tiny_attempted = gate3tiny["total"] == 1
    targets_attempted = len(gate3targets) == 1
    wall = elapsed()
    clean = len(skipped) == 0
    g4_ok = bool(complete and tiny_attempted and targets_attempted and
                 wall < WALL_LIMIT_S and clean)

    selftest_ok = bool(tiny_ok)
    valid_free = len(invalid_cells) == 0
    n_win = max(win_counts["G"], win_counts["A"])
    strict_n = sum(1 for wrec in win_fams if wrec.get("strict_win"))
    pools_all = all(wrec.get("pools_ok") for wrec in win_fams)
    pursue = (n_win >= 2 and g1_ok and g2_ok and g3pass and g4_ok and
              selftest_ok and valid_free)
    reject = (complete and tiny_solved and g1_ok and
              pools_all and strict_n == 0)
    if pursue:
        reason = ("PURSUE-condition holds (joint Holevo win "
                  "+ concentration no-regress on the SAME arm at >=2 "
                  "sizes + gates 1,2,3,4 + self-tests ok + zero "
                  "invalid-estimator cells); payload verdict stays "
                  "unresolved-with-reason, classification is "
                  "coordinator-side. Next experiment: "
                  + NEXT_EXPERIMENT + ".")
    elif reject:
        reason = ("REJECT-condition holds (complete cells, tiny "
                  "solved, Gate-1 controls pass, no strict pooled "
                  "Holevo win at any size); payload verdict "
                  "stays unresolved-with-reason, classification is "
                  "coordinator-side. Next experiment: "
                  + NEXT_EXPERIMENT + ".")
    else:
        reason = ("UNRESOLVED + next experiment (joint wins G=%d/3, "
                  "A=%d/3, strict wins=%d/3, g1=%s g2=%s "
                  "g2s(conc-spread)=%s g3=%s (tiny solved=%s, target "
                  "cap-hit=%s) selftest=%s g4=%s complete=%s "
                  "skipped=%d invalid=%d; "
                  "next: %s)." % (
                      win_counts["G"], win_counts["A"], strict_n,
                      g1_ok, g2_ok, g2s_n >= 2, g3pass, tiny_solved,
                      target_cap, selftest_ok, g4_ok, complete,
                      len(skipped), len(invalid_cells),
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
                       "invalid_cells": list(invalid_cells),
                       "valid_free": bool(valid_free),
                       "reason": reason},
    }

    results = {
        "screen": "23",
        "verdict": "unresolved-with-reason: payload reports numbers "
                   "and gate evidence; classification is "
                   "coordinator-side.",
        "design": {
            "model": "screen-authored adaptive QPE simulator under T2 "
                     "dephasing (stdlib + numpy only; no external libs)",
            "sizes": list(SIZES),
            "kmax_per_size": {str(v_v): v_v for v_v in SIZES},
            "t2": T2_VAL,
            "tau": TAU,
            "shots": N_SHOTS,
            "time_budget": TIME_BUDGET,
            "theta_grid": N_THETA,
            "particles": N_PART,
            "lookahead": {"depth": 2, "shortlist": LOOK_B},
            "anneal": {"iters": n_iters, "t0": ANNEAL_T0,
                       "alpha": ANNEAL_ALPHA, "rollouts": N_ROLL},
            "seeds": list(SEEDS),
            "reps_per_cell_arm": n_inst,
            "arms": {"M": "myopic one-step expected-resultant "
                          "maximizer baseline",
                     "R": "random control",
                     "G": "depth-2 lookahead search over future "
                          "measurement settings",
                     "A": "simulated annealing over closed-loop "
                          "policies (mean 1-cos(err) + strict-best "
                          "tracking)"},
            "metrics": "Holevo variance of the final estimator at "
                       "fixed shots and time (primary) + mean "
                       "posterior concentration (secondary, higher "
                       "is better) + posterior-normalization "
                       "estimator-validity audit",
            "pareto": "PURSUE needs a Holevo win + concentration "
                      "no-regress on the SAME arm; a Holevo-only win "
                      "with lower concentration is NOT a joint win; "
                      "joint wins counted PER ARM, bar max(G,A) >= 2; "
                      "any invalid-estimator cell blocks pursue",
            "exact": "bounded-exact level-order branch-and-bound "
                     "over setting sequences on tiny (must solve, "
                     "optimum %.1f, exactly %d nodes) + target-scale "
                     "instance (size-%d family, node cap %d, must "
                     "cap-hit at exactly %d nodes)" % (
                         TINY_OPT_V, 1 + TINY_NCOMBOS,
                         SIZES[TARGET["size_idx"]], EXACT_CAP,
                         EXACT_CAP + 1),
        },
        "timing": {"wall_s": wall, "guards": {"wall_guard_s": WALL_GUARD_S,
                                              "limit_s": WALL_LIMIT_S}},
        "cells": summaries,
        "gates": verdict_bits,
        "skipped": skipped,
    }
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)


if __name__ == "__main__":
    main()
