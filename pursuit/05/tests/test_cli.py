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
