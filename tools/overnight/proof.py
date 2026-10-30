"""Practical tiny proof where the source allows.

Builds the shared lib from the writable execution copy, imports the
frozen native bridge, runs native_checks.py, and runs tiny baseline
API checks including GraySynth. Records unresolved blockers instead
of claiming nonexistent tests. Path 18 pilot use is infrastructure
and control validation only, never a pursue verdict.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

MISSING_BASELINES = (
    "Vandaele 2407.08695: no local implementation in frozen closure",
    "Lau et al. 2508.04092: no local implementation in frozen closure",
    "PhasePoly 2506.20624: no local implementation in frozen closure",
    "torch MinGRU policy for native_search neural path: not installed",
)

TINY_CHECK_SNIPPET = r"""
import sys
sys.path.insert(0, PYTHON_DIR_LITERAL)
import compiler_baselines as b
import circuits as c

terms = ((0b011, 1), (0b101, 1), (0b110, 7))
gates = b.graysynth(3, terms)
phase, g = c.phase_and_linear(gates, 3)
assert phase == c.normalize_terms(terms), phase
assert g == (1, 2, 4), g
print("graysynth tiny ok: %d gates" % len(gates))

rows = (0b10, 0b01)
pmh_gates = b.pmh(rows)
print("pmh tiny ok: %d gates" % len(pmh_gates))

import pyzx as zx
circ = zx.Circuit(2)
circ.add_gate("CNOT", 0, 1)
circ.add_gate("T", 0)
circ.add_gate("CNOT", 0, 1)
graph = circ.to_graph()
zx.simplify.full_reduce(graph)
back = zx.extract_circuit(graph.copy())
assert back.qubits >= 2
print("pyzx tiny ok")
"""


def run(cmd: list, cwd: str, env_extra: dict | None = None,
        timeout: int = 600) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout)


def tiny_proof(exec_dir: str, python_bin: str) -> dict:
    """Run the tiny proof. Returns a structured receipt."""
    exec_dir = os.path.abspath(exec_dir)
    python_bin = os.path.abspath(python_bin)
    receipt = {"steps": {}, "blockers_unresolved": list(MISSING_BASELINES),
               "pilot_scope": "infrastructure and control validation only"}
    build = run(["make", "shared"], cwd=exec_dir)
    receipt["steps"]["make_shared"] = {
        "ok": build.returncode == 0, "tail": "see supervised stdout.log"}
    if build.returncode != 0:
        receipt["ok"] = False
        return receipt
    python_dir = os.path.join(exec_dir, "python")
    loaded = run([python_bin, "-B", "-c", "import native; native.load()"],
                 cwd=exec_dir, env_extra={"PYTHONPATH": python_dir})
    receipt["steps"]["native_load"] = {"ok": loaded.returncode == 0}
    native_checks = os.path.join(exec_dir, "tests", "native_checks.py")
    checks = run([python_bin, "-B", native_checks], cwd=exec_dir)
    receipt["steps"]["native_checks"] = {
        "ok": checks.returncode == 0,
        "tail": "see supervised stdout.log"}
    snippet = TINY_CHECK_SNIPPET.replace("PYTHON_DIR_LITERAL", repr(python_dir))
    tiny = run([python_bin, "-B", "-c", snippet], cwd=exec_dir)
    receipt["steps"]["tiny_baselines"] = {
        "ok": tiny.returncode == 0,
        "tail": "see supervised stdout.log"}
    receipt["ok"] = all(s["ok"] for s in receipt["steps"].values())
    return receipt


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: proof.py <exec_dir> <python_bin>")
        return 2
    receipt = tiny_proof(sys.argv[1], sys.argv[2])
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
