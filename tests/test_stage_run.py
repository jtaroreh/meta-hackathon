"""Real CLI chain and gates in an isolated synthetic workspace."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from tools.overnight import stage
from tests.fixture_support import attest, load_env, make_workspace
from tests.test_supervisor import no_live


def cli(root, *args, module="tests.fixture_cli", env=None):
    return subprocess.run([sys.executable, "-B", "-m", module, "--root", str(root), *args],
                          cwd=root, capture_output=True, text=True, timeout=20, env=env)


def good(result):
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.fixture
def workspace(tmp_path):
    root = make_workspace(tmp_path / "fixture")
    good(cli(root, "init"))
    attest(root, "capabilities")
    attest(root, "tooling-review")
    return root


def prepared(root):
    result = good(cli(root, "prepare"))
    assert result["execution_status"] == "finished"
    assert load_env(root).input_hash
    return result


def piloted(root):
    prepared(root)
    result = good(cli(root, "run", "18"))
    assert result["pilot_ok"]
    assert result["scientific_disposition"] == "unresolved"
    assert result["gate3_timeout_claim"] is False
    return result


def broader(root):
    piloted(root)
    attest(root, "postpilot-review")
    attest(root, "screen-01-review")
    good(cli(root, "select", "01"))


def test_stage_layout(tmp_path):
    directory = stage.stage_screen(str(tmp_path), "01", "scope", 100, 20)
    assert Path(directory, "run.sh").is_file()
    assert "-m tools.overnight.run_one" in Path(directory, "run.sh").read_text()
    with pytest.raises(ValueError):
        stage.stage_screen(str(tmp_path), "../bad", "scope", 100, 20)


def test_documented_chain_and_shell_from_another_cwd(workspace):
    root = workspace
    before = load_env(root).original_deadline
    prep = prepared(root)
    assert prep["cpu_seconds"] > 0
    env = dict(os.environ, OVERNIGHT_PYTHON=str(root / "fixture-python"))
    result = subprocess.run(["sh", str(root / "screens" / "18" / "run.sh")],
                            cwd=root.parent, env=env, capture_output=True, text=True, timeout=20)
    receipt = good(result)
    assert receipt["pilot_ok"]
    assert load_env(root).original_deadline == before
    assert cli(root, "run", "01").returncode == 3
    attest(root, "postpilot-review")
    assert cli(root, "run", "01").returncode == 3
    attest(root, "screen-01-review")
    good(cli(root, "select", "01"))
    receipt = good(cli(root, "run", "01"))
    assert receipt["cpu_seconds"] > 0
    assert Path(receipt["receipt"]).is_file()
    assert (Path(receipt["receipt"]).parent / "tmp" / "bounded.txt").is_file()


@pytest.mark.parametrize("gate", ["capabilities", "tooling-review"])
def test_initial_gates_required(workspace, gate):
    env = load_env(workspace)
    Path(env.output_root, "receipts", gate + ".json").unlink()
    result = cli(workspace, "prepare")
    assert result.returncode == 3
    assert load_env(workspace).attempts == []


def test_boolean_availability_is_not_live_capability_receipt(workspace):
    env = load_env(workspace)
    Path(env.output_root, "receipts", "capabilities.json").write_text(
        json.dumps({"available": True, "workhorse": {"available": True}}))
    result = cli(workspace, "prepare")
    assert result.returncode == 3
    assert "binding mismatch" in result.stderr


def test_proof_and_input_and_configuration_drift_block(workspace):
    assert cli(workspace, "run", "18").returncode == 3
    prepared(workspace)
    env = load_env(workspace)
    prep = json.loads(Path(env.output_root, env.preparation).read_text())
    frozen = Path(env.output_root, prep["manifest"]).parent / "python" / "native.py"
    frozen.chmod(0o644)
    frozen.write_text("drift")
    result = cli(workspace, "run", "18")
    assert result.returncode == 3
    assert "drift" in result.stderr
    config = workspace / "overnight-config.json"
    data = json.loads(config.read_text())
    data["queue"].reverse()
    config.write_text(json.dumps(data))
    assert "changed" in cli(workspace, "run", "18").stderr


def test_postpilot_pass_is_bound_to_screen_files(workspace):
    broader(workspace)
    (workspace / "screens" / "01" / "brief.md").write_text("changed hypothesis")
    result = cli(workspace, "run", "01")
    assert result.returncode == 3
    assert "artifacts changed" in result.stderr


def test_direct_entry_and_shell_entry_import_without_venv(tmp_path):
    source = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-B", str(source / "tools/overnight/run_one.py"), "--help"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=5)
    assert result.returncode == 0
    env = dict(os.environ, OVERNIGHT_PYTHON=sys.executable)
    result = subprocess.run(["sh", str(source / "screens/18/run.sh")], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=5)
    assert result.returncode == 3
    assert "ImportError" not in result.stderr
    assert "No such file" in result.stderr


def test_live_cli_recovery_kills_descendants_before_reopen(workspace):
    root = workspace
    spec_path = root / "screens" / "01" / "command.json"
    spec = json.loads(spec_path.read_text())
    spec["command"][-1] = "sleep"
    spec_path.write_text(json.dumps(spec))
    broader(root)
    proc = subprocess.Popen([sys.executable, "-B", "-m", "tests.fixture_cli", "--root", str(root), "run", "01"],
                            cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    deadline = time.monotonic() + 5
    attempt = None
    while time.monotonic() < deadline:
        env = load_env(root)
        candidates = [a for a in env.attempts if a.screen_id == "01"]
        if candidates and Path(candidates[0].evidence_path, "descendant.json").exists():
            attempt = candidates[0]
            break
        if proc.poll() is not None:
            pytest.fail(proc.stderr.read().decode())
        time.sleep(0.02)
    assert attempt is not None
    assert attempt.pid is not None
    child = json.loads(Path(attempt.evidence_path, "descendant.json").read_text())["pid"]
    payload = json.loads(Path(attempt.evidence_path, "payload.json").read_text())["pid"]
    proc.kill()
    proc.wait(timeout=3)
    result = cli(root, "recover")
    assert result.returncode in (0, 3), result.stderr
    env = load_env(root)
    assert not any(a.execution_status == "running" for a in env.attempts)
    assert env.cpu_used_sec >= sum(a.cpu_reserved_sec for a in env.attempts)
    assert no_live(payload)
    assert no_live(child)
    assert cli(root, "run", "01").returncode == 3


def test_postpilot_raw_evidence_change_blocks(workspace):
    pilot = piloted(workspace)
    attest(workspace, "postpilot-review")
    attest(workspace, "screen-01-review")
    Path(pilot["receipt"]).parent.joinpath("stdout.log").write_text("changed")
    result = cli(workspace, "run", "01")
    assert result.returncode == 3
    assert "artifacts changed" in result.stderr


def test_live_output_stays_bounded_while_process_runs(workspace):
    spec_path = workspace / "screens" / "01" / "command.json"
    spec = json.loads(spec_path.read_text())
    spec["command"][-1] = "stream"
    spec_path.write_text(json.dumps(spec))
    broader(workspace)
    proc = subprocess.Popen([sys.executable, "-B", "-m", "tests.fixture_cli", "--root", str(workspace), "run", "01"],
                            cwd=workspace, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    observed = False
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline and proc.poll() is None:
        for log in Path(load_env(workspace).output_root, "attempts").glob("01-*/stdout.log"):
            assert log.stat().st_size <= 32768
            observed |= log.stat().st_size > 0
        time.sleep(0.002)
    out, err = proc.communicate(timeout=5)
    assert proc.returncode == 1, out + err
    assert observed
    receipt = json.loads(out)
    assert receipt["execution_status"] == "resource_killed"
    assert receipt["cleanup_verified"]


def test_crash_before_go_never_starts_payload(workspace):
    spec_path = workspace / "screens" / "01" / "command.json"
    spec = json.loads(spec_path.read_text())
    spec["command"][-1] = "sleep"
    spec_path.write_text(json.dumps(spec))
    broader(workspace)
    (workspace / ".delay-handshake").write_text("test-only")
    proc = subprocess.Popen([sys.executable, "-B", "-m", "tests.fixture_cli", "--root", str(workspace), "run", "01"],
                            cwd=workspace, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    deadline = time.monotonic() + 4
    attempt = None
    while time.monotonic() < deadline:
        candidates = [a for a in load_env(workspace).attempts if a.screen_id == "01" and a.pid]
        if candidates:
            attempt = candidates[0]
            break
        time.sleep(0.01)
    assert attempt is not None
    proc.kill()
    proc.wait(timeout=2)
    result = cli(workspace, "recover")
    assert result.returncode == 3
    assert not Path(attempt.evidence_path, "go.json").exists()
    assert not Path(attempt.evidence_path, "payload.json").exists()
    assert load_env(workspace).blocked_reason


def test_pilot_requires_successful_proof_not_just_an_exec_directory(workspace):
    (workspace / "fixture-source" / "tests" / "native_checks.py").write_text("raise SystemExit(7)")
    result = cli(workspace, "prepare")
    assert result.returncode == 1
    assert load_env(workspace).input_hash == ""
    assert cli(workspace, "run", "18").returncode == 3


def test_selection_clock_includes_model_wait_and_never_resets(workspace):
    broader(workspace)
    first = good(cli(workspace, "select", "01"))
    second = good(cli(workspace, "select", "01"))
    assert first["started_at"] == second["started_at"]
    path = workspace / "overnight-envelope.json"
    data = json.loads(path.read_text())
    data["screen_started_at"]["01"] -= 20
    path.write_text(json.dumps(data))
    result = cli(workspace, "run", "01")
    assert result.returncode == 3
    assert "exhausted" in result.stderr
    assert not any(a.screen_id == "01" for a in load_env(workspace).attempts)


def test_cli_zero_cpu_and_final_interval_refuse_preparation(workspace):
    path = workspace / "overnight-envelope.json"
    data = json.loads(path.read_text())
    original = dict(data)
    data["global_cpu_budget_sec"] = 0
    path.write_text(json.dumps(data))
    result = cli(workspace, "prepare")
    assert result.returncode == 3
    assert "CPU" in result.stderr
    original["original_deadline"] = time.time() + 899
    path.write_text(json.dumps(original))
    result = cli(workspace, "prepare")
    assert result.returncode == 3
    assert "no-launch" in result.stderr
    assert load_env(workspace).attempts == []


@pytest.mark.parametrize("change", ["verdict", "reviewer", "expiry"])
def test_matching_independent_pass_is_required(workspace, change):
    broader(workspace)
    path = Path(load_env(workspace).output_root, "receipts", "screen-01-review.json")
    receipt = json.loads(path.read_text())
    if change == "verdict":
        receipt["verdict"] = "REVISE"
    elif change == "reviewer":
        receipt["reviewer"] = {"providerInstanceId": "muse", "model": "muse-spark-1.3-contributor"}
    else:
        receipt["valid_until"] = time.time() - 1
    path.write_text(json.dumps(receipt))
    assert cli(workspace, "run", "01").returncode == 3
    assert not any(a.screen_id == "01" for a in load_env(workspace).attempts)


def test_worker_crash_uses_persisted_payload_identity_and_blocks(workspace):
    spec_path = workspace / "screens" / "01" / "command.json"
    spec = json.loads(spec_path.read_text())
    spec["command"][-1] = "sleep"
    spec_path.write_text(json.dumps(spec))
    broader(workspace)
    proc = subprocess.Popen([sys.executable, "-B", "-m", "tests.fixture_cli", "--root", str(workspace), "run", "01"],
                            cwd=workspace, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.monotonic() + 5
    attempt = None
    while time.monotonic() < deadline:
        candidates = [a for a in load_env(workspace).attempts if a.screen_id == "01"]
        if candidates and Path(candidates[0].evidence_path, "descendant.json").exists():
            attempt = candidates[0]
            break
        time.sleep(0.01)
    assert attempt is not None
    payload = json.loads(Path(attempt.evidence_path, "payload.json").read_text())["pid"]
    descendant = json.loads(Path(attempt.evidence_path, "descendant.json").read_text())["pid"]
    os.kill(attempt.pid, signal.SIGKILL)
    out, err = proc.communicate(timeout=5)
    assert proc.returncode == 1, out + err
    receipt = json.loads(out)
    assert receipt["cpu_seconds"] is None
    assert receipt["cleanup_verified"]
    assert no_live(payload)
    assert no_live(descendant)
    assert load_env(workspace).blocked_reason


@pytest.mark.parametrize("cut", ["receipt", "pointer"])
def test_interrupted_receipt_publication_cannot_repeat_preparation(workspace, cut):
    result = prepared(workspace)
    env = load_env(workspace)
    if cut == "receipt":
        Path(result["receipt"]).unlink()
    else:
        path = workspace / "overnight-envelope.json"
        data = json.loads(path.read_text())
        data["preparation"] = ""
        path.write_text(json.dumps(data))
    assert cli(workspace, "prepare").returncode == 3
    current = load_env(workspace)
    assert "publication" in current.blocked_reason
    assert current.cpu_used_sec == env.cpu_used_sec
    assert len(current.attempts) == 1
