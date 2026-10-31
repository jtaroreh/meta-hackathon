from pursuit05 import exact, screen
from pursuit05.cells import CellRegistry


def test_eval_exact_equals_eval_policy_for_every_static_policy():
    reg = CellRegistry()
    cell = reg.find("12/0.001/1")
    pre = reg.pre(cell)
    policies = screen.all_threshold_policies(pre["T"])
    assert len(policies) == 375
    for ath, fth in policies:
        want = screen.eval_policy(pre, ath, fth, cell.p)
        got = exact.eval_exact(exact.static_decider(ath, fth), pre, cell.p)
        assert abs(got["W"] - want["W"]) <= 1e-12, (ath, fth)
        assert abs(got["inf"] - want["inf"]) <= 1e-12, (ath, fth)


def test_best_static_never_above_annealing():
    reg = CellRegistry()
    checked = 0
    for cell in reg.all_cells():
        pre = reg.pre(cell)
        f = screen.run_F(pre, cell.p)
        bound = f["inf"] * (1.0 + screen.INF_REL) + screen.INF_ABS
        a = screen.run_arm(
            pre,
            cell.p,
            "A",
            f["inf"],
            screen.A_ITERS,
            screen.R_SAMPLES,
            None,
            cell.stage_idx,
            cell.rate_idx,
            cell.seed,
        )
        if a["inf"] <= bound:
            s = exact.best_static(pre, cell.p, f["inf"])
            assert s.result.W <= a["W"] + 1e-12, cell.cell_id
            assert s.result.n_evaluated == (75 if pre["T"] == 3 else 375)
            checked += 1
    assert checked > 0


def _brute_force_always_abort(pre, p):
    Vf = pre["Vf"]
    L1 = pre["L1"]
    T = pre["T"]
    acc1 = 0
    v1 = 0.0
    for r in range(L1):
        k = next((k for k in range(T - 1) if any(pre["cw1"][r, : k + 1])), -1)
        v1 += pre["spent"][k] if k >= 0 else Vf
        acc1 += k < 0 and pre["fw1"][r] <= 0
    n2 = len(pre["fw2"])
    acc2 = 0
    log2 = 0
    v2 = 0.0
    for r in range(n2):
        k = next((k for k in range(T - 1) if any(pre["cw2"][r, : k + 1])), -1)
        v2 += pre["spent"][k] if k >= 0 else Vf
        if k < 0 and pre["fw2"][r] <= 0:
            acc2 += 1
            log2 += bool(pre["nt2"][r])
    L = float(L1)
    P0 = (1.0 - p) ** L
    P1 = L * p * (1.0 - p) ** (L - 1)
    P2 = (L * (L - 1.0) / 2.0) * p**2 * (1.0 - p) ** (L - 2.0)
    Pt = max(0.0, 1.0 - P0 - P1 - P2)
    a1f = acc1 / L1
    a2f = acc2 / n2
    pacc = P0 + P1 * a1f + P2 * a2f
    E = P0 * Vf + P1 * v1 / L1 + P2 * v2 / n2 + Pt * Vf
    return {"W": E / pacc - Vf, "inf": (P1 * a1f + P2 * log2 / n2) / pacc}


def test_zero_prefix_forced_continue():
    reg = CellRegistry()
    cell = reg.find("6/0.001/1")
    pre = reg.pre(cell)
    seen = []

    class AlwaysAbort:
        fth = 0

        def __call__(self, k, prefix):
            seen.append(prefix)
            return True

    got = exact.eval_exact(AlwaysAbort(), pre, cell.p)
    assert seen
    assert all(any(v != 0 for v in prefix) for prefix in seen)
    want = _brute_force_always_abort(pre, cell.p)
    assert abs(got["W"] - want["W"]) <= 1e-12
    assert abs(got["inf"] - want["inf"]) <= 1e-12
