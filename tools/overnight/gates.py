"""Verdict semantics. Execution reasons never become science.

An exact solver timeout counts only when formulation controls pass,
the solver actually runs, and its own limit expires. Deadline kills,
resource kills, missing solvers, and provider failures are unresolved
with distinct execution reasons. A T count decoder timeout never
certifies joint CNOT depth hardness. Pareto needs every resource.
"""
from __future__ import annotations


EXECUTION_REASONS = (
    "ok",
    "solver_timeout_exact",
    "deadline_killed",
    "resource_killed",
    "missing_solver",
    "provider_failure",
    "crashed",
    "blocked_env",
)

INFRA_REASONS = (
    "deadline_killed",
    "resource_killed",
    "missing_solver",
    "provider_failure",
    "crashed",
    "blocked_env",
)


class GateError(Exception):
    pass


def classify(execution_reason: str, controls: dict) -> dict:
    """Map an execution reason to a disposition. Infra stays unresolved.

    controls holds the formulation control receipts required for an
    exact timeout: solver_present, tiny_instance_solved, limit_honored,
    log_shows_solver_start, log_shows_limit_expiry.
    """
    if execution_reason not in EXECUTION_REASONS:
        raise GateError("unknown execution reason")
    if execution_reason in INFRA_REASONS:
        return {"disposition": "unresolved",
                "gate3_timeout_claim": False,
                "note": "infrastructure; never a scientific timeout"}
    if execution_reason == "solver_timeout_exact":
        required = ("solver_present", "tiny_instance_solved",
                    "limit_honored", "log_shows_solver_start",
                    "log_shows_limit_expiry")
        absent = [k for k in required if not controls.get(k, False)]
        if absent:
            return {"disposition": "unresolved",
                    "gate3_timeout_claim": False,
                    "note": "timeout controls missing: %s" % ",".join(absent)}
        return {"disposition": "pending",
                "gate3_timeout_claim": True,
                "note": "exact solver timed out at target scale"}
    return {"disposition": "pending",
            "gate3_timeout_claim": False,
            "note": "finished; awaits scientific verdict"}


def tcount_timeout_implies_joint(tcount_timed_out: bool) -> dict:
    """A T count decoder timeout says nothing about joint hardness."""
    return {"joint_hardness_certified": False,
            "note": "T count decoder timeout does not certify joint "
                    "CNOT depth hardness"}


def pareto_win(before: dict, after: dict,
               resources: tuple = ("cnot", "depth", "t")) -> dict:
    """Pareto win reduces one resource and increases none.

    Known counterexample. Six wire depth 5 to 4 with CNOT 136 to 140
    must fail, because CNOT regressed.
    """
    deltas = {}
    for key in resources:
        if key not in before or key not in after:
            raise GateError("resource missing: %s" % key)
        deltas[key] = after[key] - before[key]
    improved = any(v < 0 for v in deltas.values())
    regressed = [k for k, v in deltas.items() if v > 0]
    win = improved and not regressed
    return {"win": win, "deltas": deltas, "regressed": regressed}


KNOWN_COUNTEREXAMPLE = {
    "before": {"cnot": 136, "depth": 5, "t": 24},
    "after": {"cnot": 140, "depth": 4, "t": 24},
}
