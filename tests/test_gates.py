"""Gate tests: infra never becomes science; Pareto counterexample fails."""
import pytest

from tools.overnight import gates


def test_infra_stays_unresolved():
    for reason in gates.INFRA_REASONS:
        verdict = gates.classify(reason, {})
        assert verdict["disposition"] == "unresolved", reason
        assert verdict["gate3_timeout_claim"] is False, reason


def test_exact_timeout_needs_all_controls():
    full = {"solver_present": True, "tiny_instance_solved": True,
            "limit_honored": True, "log_shows_solver_start": True,
            "log_shows_limit_expiry": True}
    verdict = gates.classify("solver_timeout_exact", full)
    assert verdict["gate3_timeout_claim"] is True
    partial = dict(full)
    partial["log_shows_limit_expiry"] = False
    verdict = gates.classify("solver_timeout_exact", partial)
    assert verdict["disposition"] == "unresolved"
    assert verdict["gate3_timeout_claim"] is False


def test_unknown_reason_rejected():
    with pytest.raises(gates.GateError):
        gates.classify("solver_proved_optimal", {})


def test_known_pareto_counterexample_rejected():
    result = gates.pareto_win(gates.KNOWN_COUNTEREXAMPLE["before"],
                              gates.KNOWN_COUNTEREXAMPLE["after"])
    assert result["win"] is False
    assert "cnot" in result["regressed"]
    assert result["deltas"] == {"cnot": 4, "depth": -1, "t": 0}


def test_genuine_pareto_win_passes():
    before = {"cnot": 140, "depth": 5, "t": 24}
    after = {"cnot": 136, "depth": 4, "t": 24}
    result = gates.pareto_win(before, after)
    assert result["win"] is True
    assert result["regressed"] == []


def test_flat_tradeoff_not_win():
    before = {"cnot": 136, "depth": 5, "t": 24}
    after = {"cnot": 136, "depth": 5, "t": 24}
    assert gates.pareto_win(before, after)["win"] is False


def test_tcount_timeout_certifies_nothing():
    verdict = gates.tcount_timeout_implies_joint(True)
    assert verdict["joint_hardness_certified"] is False
