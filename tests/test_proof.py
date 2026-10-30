"""Proof test runs the real native chain from a temp exec copy.

Sources stay read only: files are copied to tmp, built there with
-O1, and verified with the root checkout .venv python. Slow but real.
"""
import os
import shutil

import pytest

from tools.overnight import proof as proof_mod
from tools.overnight.freeze import PHASEPOLY

VENV_PY = ("/Users/joeltaroreh/projects/challenges/meta-hackathon"
           "/.venv/bin/python")

NEEDED = (
    "python/exact_decode.py",
    "python/circuits.py",
    "python/compiler_baselines.py",
    "python/count_depth.py",
    "python/search.py",
    "python/reference.py",
    "python/native.py",
    "python/native_search.py",
    "python/run_algebra.py",
    "src/phase_poly.c",
    "src/verification.c",
    "src/matroid.c",
    "src/search.c",
    "include/phase_poly.h",
    "include/verification.h",
    "include/matroid.h",
    "include/search.h",
    "Makefile",
    "tests/native_checks.py",
)


@pytest.mark.skipif(not shutil.which("cc"), reason="needs cc")
def test_tiny_proof_real_chain(tmp_path, monkeypatch):
    exec_dir = str(tmp_path / "exec")
    for rel in NEEDED:
        src = os.path.join(PHASEPOLY, rel)
        dst = os.path.join(exec_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
    monkeypatch.setenv("CFLAGS", "-O1 -Wall -Wextra -std=c11 -Iinclude")
    receipt = proof_mod.tiny_proof(exec_dir, VENV_PY)
    assert receipt["steps"]["make_shared"]["ok"], \
        receipt["steps"]["make_shared"]["tail"]
    assert receipt["steps"]["native_checks"]["ok"], \
        receipt["steps"]["native_checks"]["tail"]
    assert receipt["steps"]["tiny_baselines"]["ok"], \
        receipt["steps"]["tiny_baselines"]["tail"]
    assert receipt["ok"] is True
    assert any("Vandaele" in b for b in receipt["blockers_unresolved"])
    assert receipt["pilot_scope"].startswith("infrastructure")
