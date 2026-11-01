import os
import subprocess
import sys
from pathlib import Path

PURSUIT05_DIR = Path(__file__).resolve().parents[1]


def _run(args, env_extra=None):
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("PURSUIT05_SCREEN_SRC", "PURSUIT05_RECORD")
    }
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-m", "pursuit05", *args],
        check=False,
        cwd=PURSUIT05_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _assert_one_line_error(proc, needle):
    assert proc.returncode != 0
    assert "Traceback" not in proc.stderr
    lines = [line for line in proc.stderr.strip().splitlines() if line.strip()]
    assert len(lines) == 1, proc.stderr
    assert needle in lines[0]


def test_bad_screen_src_fails_with_one_line_error():
    proc = _run(
        ["reproduce", "--cell", "6/0.001/1"],
        {"PURSUIT05_SCREEN_SRC": "/nonexistent"},
    )
    _assert_one_line_error(proc, "/nonexistent")


def test_bad_cell_fails_with_one_line_error():
    proc = _run(["reproduce", "--cell", "99/0.001/1"])
    _assert_one_line_error(proc, "unknown cell")


def test_bad_seeds_fails_with_one_line_error():
    proc = _run(["baselines", "--seeds", "7"])
    _assert_one_line_error(proc, "bad --seeds")


def test_missing_record_override_fails_with_one_line_error():
    proc = _run(
        ["reproduce", "--cell", "6/0.001/1"],
        {"PURSUIT05_RECORD": "/nonexistent/record.json"},
    )
    _assert_one_line_error(proc, "/nonexistent/record.json")


def test_corrupt_record_fails_with_one_line_error(tmp_path):
    bad = tmp_path / "results.json"
    bad.write_text('{"cells": {}}')
    proc = _run(
        ["reproduce", "--cell", "6/0.001/1"],
        {"PURSUIT05_RECORD": str(bad)},
    )
    _assert_one_line_error(proc, "bad record")


def test_env_smoke_bad_cell_fails_with_one_line_error():
    proc = _run(["env-smoke", "--cell", "99/0.001/1"])
    _assert_one_line_error(proc, "unknown cell")


def test_env_smoke_bad_args_fail_with_one_line_error():
    proc = _run(["env-smoke", "--agents", "0"])
    _assert_one_line_error(proc, "bad --agents")
    proc = _run(["env-smoke", "--seed", "-1"])
    _assert_one_line_error(proc, "bad --seed")
    proc = _run(["env-smoke", "--agents", "100", "--workers", "3"])
    _assert_one_line_error(proc, "not divisible")


def test_optimum_bad_seeds_fails_with_one_line_error():
    proc = _run(["optimum", "--seeds", "7"])
    _assert_one_line_error(proc, "bad --seeds")


def test_env_smoke_small_passes():
    proc = _run(
        ["env-smoke", "--cell", "6/0.001/1", "--agents", "32", "--steps", "2"]
    )
    assert proc.returncode == 0, proc.stderr
    assert "agent-steps/s = " in proc.stdout
    assert "within MC error" in proc.stdout


def test_parse_lams_rejects_bad_values():
    import pytest

    from pursuit05.cli import _parse_lams

    for bad in ("nan", "inf", "-inf", "0", "-5", "1000,1000", "abc", ""):
        with pytest.raises(ValueError):
            _parse_lams(bad, (1000,))
    assert _parse_lams("1000,5000", (1,)) == [1000.0, 5000.0]
    assert _parse_lams(None, (1000,)) == [1000]


def test_checked_beta_and_lam():
    import pytest

    from pursuit05.cli import _checked_beta, _checked_lam

    assert _checked_beta({"beta": 1.0}) == 1.0
    for bad in (float("nan"), float("inf"), -1.0, "abc", None):
        with pytest.raises(ValueError):
            _checked_beta({"beta": bad})
    assert _checked_lam(5000) == 5000.0
    for bad in (float("nan"), float("inf"), 0, -3, "abc", None):
        with pytest.raises(ValueError):
            _checked_lam(bad)


def test_nonneg_int_rejects_non_ints():
    import pytest

    from pursuit05.cli import _nonneg_int

    assert _nonneg_int(0, "--seed") == 0
    for bad in ("abc", None, -1):
        with pytest.raises(ValueError):
            _nonneg_int(bad, "--seed")
