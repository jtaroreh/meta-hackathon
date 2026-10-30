"""Small live lifecycle controls. No unbounded output generators."""
import json
import os
from pathlib import Path
import sys
import time

import psutil
import pytest

from tools.overnight import supervisor as sup
from tools.overnight.envelope import EnvelopeError, EnvelopeStore
from tests.fixture_support import FixtureProbes, fast_settings


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    fast_settings(monkeypatch)


@pytest.fixture
def store(tmp_path):
    keeper = EnvelopeStore(tmp_path / "envelope.json")
    keeper.create("run", 3600, 7200, "cfg", output_root=tmp_path / "data")
    Path(keeper.envelope.output_root).mkdir()
    yield keeper
    keeper.close()


def run(store, code, *, wall=2, cpu=100, screen="01", probes=None, limits=None, caffeinate=False):
    root = Path(store.envelope.output_root)
    path = root / "attempts" / str(len(store.envelope.attempts))
    return sup.run_screen(store, screen, [sys.executable, "-B", "-c", code], str(root), str(path),
                          wall, cpu, probes=probes or FixtureProbes(),
                          caffeinate=caffeinate, limits=limits)


def no_live(pid):
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


def test_wait4_charges_nonzero_cpu_and_forces_threads(store, monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "16")
    result = run(store, "import os,time; assert os.environ['OMP_NUM_THREADS']=='2'; "
                       "end=time.monotonic()+0.12\nwhile time.monotonic()<end: pass")
    assert result.execution_status == "finished", result.execution_reason
    assert result.cpu_seconds > 0.03
    assert store.envelope.cpu_used_sec == result.cpu_reserved_sec
    assert result.cleanup_verified
    assert no_live(result.pid)


def test_global_deadline_crossing(store):
    store.envelope.cutoff_sec = 0
    store.envelope.original_deadline = time.time() + 1.2
    store.save()
    started = time.monotonic()
    result = run(store, "import time; time.sleep(10)", wall=10, cpu=600)
    assert result.execution_status == "deadline_killed", result.execution_reason
    assert time.monotonic() - started < 2
    assert result.cleanup_verified


def test_zero_budget_and_cumulative_retry_limit(store):
    result = run(store, "print('ok')", wall=2, cpu=20)
    assert result.execution_status == "finished"
    with pytest.raises(EnvelopeError, match="exhausted"):
        run(store, "print('must not launch')", wall=2, cpu=20)
    store.envelope.global_cpu_budget_sec = store.envelope.cpu_used_sec
    with pytest.raises(EnvelopeError, match="exhausted"):
        run(store, "print('must not launch')", screen="02")
    assert len(store.envelope.attempts) == 1


def test_term_resistant_descendant_removed_after_normal_wrapper_exit(store):
    child_code = ("import signal,time; from pathlib import Path; "
                  "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                  "Path('child-ready').write_text('ready'); time.sleep(10)")
    code = ("import subprocess,sys,json,time; from pathlib import Path\n"
            "p=subprocess.Popen([sys.executable,'-c'," + repr(child_code) + "])\n"
            "end=time.monotonic()+1\n"
            "while not Path('child-ready').exists() and time.monotonic()<end: time.sleep(.005)\n"
            "assert Path('child-ready').exists()\n"
            "Path('../descendant.json').write_text(json.dumps({'pid':p.pid}))\n"
            "print('wrapper finished')")
    result = run(store, code)
    path = Path(store.envelope.attempts[0].evidence_path)
    child = json.loads((path / "descendant.json").read_text())["pid"]
    assert result.execution_status == "crashed", result.execution_reason
    assert "live descendants" in result.execution_reason
    assert result.cleanup_verified
    assert no_live(child)


def test_caffeinate_spawn_exception_cleans_ownership(store, monkeypatch):
    def fail(*args):
        raise OSError("synthetic caffeinate failure")
    monkeypatch.setattr(sup, "_own_caffeinate", fail)
    result = run(store, "print('must not start')", caffeinate=True)
    assert result.execution_status == "resource_killed"
    assert "caffeinate failure" in result.execution_reason
    assert result.cleanup_verified
    path = Path(store.envelope.attempts[0].evidence_path)
    assert not (path / "payload.json").exists()
    assert no_live(result.pid)


def test_live_pipe_limit_is_exact_and_finite(store):
    limits = {"rss_bytes": 256 * 1024 ** 2, "attempt_bytes": 1024 ** 2,
              "global_bytes": 2 * 1024 ** 2, "log_bytes": 32768}
    result = run(store, "import os,time\nfor i in range(128): os.write(1,b'x'*4096)\ntime.sleep(1)",
                 limits=limits)
    log = Path(store.envelope.attempts[0].evidence_path, "stdout.log")
    assert log.stat().st_size == 32768
    assert result.execution_status == "resource_killed"
    assert result.execution_reason == "stdout byte limit"
    assert result.cleanup_verified


@pytest.mark.parametrize("probe", ["power", "disk", "memory"])
def test_continuous_host_checks(store, probe):
    probes = FixtureProbes()
    count = [0]
    if probe == "power":
        def measure():
            count[0] += 1
            return "ac" if count[0] == 1 else "battery"
        probes.power_source = measure
    elif probe == "disk":
        def measure(_):
            count[0] += 1
            return (100 if count[0] == 1 else 1) * 1024 ** 3
        probes.disk_free_bytes = measure
    else:
        def measure():
            count[0] += 1
            return (8 if count[0] == 1 else 1) * 1024 ** 3
        probes.mem_available_bytes = measure
    result = run(store, "import time; time.sleep(5)", probes=probes)
    assert result.execution_status == "resource_killed"
    assert result.cleanup_verified


def test_sampled_descendant_rss(store):
    limits = {"rss_bytes": 90 * 1024 ** 2, "attempt_bytes": 1024 ** 2,
              "global_bytes": 2 * 1024 ** 2, "log_bytes": 32768}
    code = ("import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',"
            "'import time; a=bytearray(100*1024**2); time.sleep(4)']); time.sleep(4)")
    result = run(store, code, limits=limits)
    assert result.execution_status == "resource_killed", result.execution_reason
    assert "RSS" in result.execution_reason
    assert result.cleanup_verified


@pytest.mark.parametrize("global_limit", [False, True])
def test_sampled_output_scope_includes_tmp_and_global(store, global_limit):
    limits = {"rss_bytes": 256 * 1024 ** 2, "attempt_bytes": 1024 ** 2 if global_limit else 65536,
              "global_bytes": 65536 if global_limit else 2 * 1024 ** 2, "log_bytes": 32768}
    result = run(store, "import os,time; open(os.path.join(os.environ['TMPDIR'],'out'),'wb').write(b'x'*100000); time.sleep(3)",
                 limits=limits)
    assert result.execution_status == "resource_killed", result.execution_reason
    assert ("global" if global_limit else "attempt") in result.execution_reason
    assert result.cleanup_verified


def test_identity_mismatch_and_permission_are_not_gone(monkeypatch):
    import signal
    pid = os.getpid()
    assert not sup._same_process(pid, psutil.Process(pid).create_time() - 100)
    monkeypatch.setattr(os, "kill", lambda *args: (_ for _ in ()).throw(PermissionError("denied")))
    with pytest.raises(sup.SupervisionError, match="permission"):
        sup._signal_identity((pid, psutil.Process(pid).create_time()), signal.SIGTERM)


def test_unknown_wait4_accounting_blocks_future_launch(store, monkeypatch):
    parent_pid = os.getpid()
    original = os.wait4
    def unknown(pid, options):
        if os.getpid() != parent_pid:
            raise ChildProcessError("synthetic lost usage")
        return original(pid, options)
    monkeypatch.setattr(os, "wait4", unknown)
    result = run(store, "import time; time.sleep(1)")
    assert result.cpu_seconds is None
    assert store.envelope.blocked_reason
    with pytest.raises(EnvelopeError, match="uncertain"):
        run(store, "print('must not launch')", screen="02")


def test_caffeinate_release_exception_still_cleans_payload(store, monkeypatch):
    import subprocess
    monkeypatch.setattr(sup, "_own_caffeinate", lambda *args: subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    def release_failure(proc):
        raise OSError("synthetic release failure")
    monkeypatch.setattr(sup, "_release_caffeinate", release_failure)
    result = run(store, "print('ok')", caffeinate=True)
    assert result.cleanup_verified
    assert no_live(result.pid)
    assert "release failure" in result.execution_reason


def test_new_pgid_child_rss_enforced(store):
    limits = {"rss_bytes": 90 * 1024 ** 2, "attempt_bytes": 1024 ** 2,
              "global_bytes": 2 * 1024 ** 2, "log_bytes": 32768}
    code = ("import subprocess,sys,time,os; subprocess.Popen([sys.executable,'-c',"
            "'import time; a=bytearray(100*1024**2); time.sleep(4)'], preexec_fn=os.setpgrp); time.sleep(4)")
    result = run(store, code, limits=limits)
    assert result.execution_status == "resource_killed", result.execution_reason
    assert "RSS" in result.execution_reason
    assert result.cleanup_verified


def test_new_pgid_wrapper_exit_detected(store):
    child_code = ("import signal,time; from pathlib import Path; "
                  "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                  "Path('child-ready').write_text('ready'); time.sleep(10)")
    code = ("import subprocess,sys,json,time,os; from pathlib import Path\n"
            "p=subprocess.Popen([sys.executable,'-c'," + repr(child_code) + "], preexec_fn=os.setpgrp)\n"
            "assert os.getpgid(p.pid) != os.getpgid(0)\n"
            "assert os.getsid(p.pid) == os.getsid(0)\n"
            "end=time.monotonic()+1\n"
            "while not Path('child-ready').exists() and time.monotonic()<end: time.sleep(.005)\n"
            "assert Path('child-ready').exists()\n"
            "Path('../descendant.json').write_text(json.dumps({'pid':p.pid}))\n"
            "print('wrapper finished')")
    result = run(store, code)
    path = Path(store.envelope.attempts[0].evidence_path)
    child = json.loads((path / "descendant.json").read_text())["pid"]
    assert result.execution_status == "crashed", result.execution_reason
    assert "live descendants" in result.execution_reason
    assert result.cleanup_verified
    assert no_live(child)


def test_new_pgid_timeout_kills_session(store):
    child_code = "import time; time.sleep(10)"
    code = ("import subprocess,sys,json,time,os; from pathlib import Path\n"
            "p=subprocess.Popen([sys.executable,'-c'," + repr(child_code) + "], preexec_fn=os.setpgrp)\n"
            "assert os.getpgid(p.pid) != os.getpgid(0)\n"
            "assert os.getsid(p.pid) == os.getsid(0)\n"
            "Path('../descendant.json').write_text(json.dumps({'pid':p.pid}))\n"
            "time.sleep(10)")
    result = run(store, code, wall=1.5)
    path = Path(store.envelope.attempts[0].evidence_path)
    child = json.loads((path / "descendant.json").read_text())["pid"]
    assert result.execution_status == "deadline_killed", result.execution_reason
    assert result.cleanup_verified
    assert no_live(child)


def test_reconcile_cleans_new_pgid_session(tmp_path):
    import signal
    import subprocess
    from types import SimpleNamespace
    evidence = tmp_path / "rec-evidence"
    evidence.mkdir()
    leader_code = ("import subprocess,sys,os,time; "
                   "p=subprocess.Popen([sys.executable,'-B','-c','import time; time.sleep(10)'],"
                   " preexec_fn=os.setpgrp); print(p.pid, flush=True); time.sleep(10)")
    proc = subprocess.Popen([sys.executable, "-B", "-c", leader_code],
                            start_new_session=True, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, bufsize=1)
    grandchild_pid = None
    try:
        grandchild_pid = int(proc.stdout.readline().strip())
        end = time.monotonic() + 5
        while True:
            try:
                same_sid = os.getsid(grandchild_pid) == os.getsid(proc.pid)
                diff_pgid = os.getpgid(grandchild_pid) != os.getpgid(proc.pid)
            except ProcessLookupError:
                same_sid, diff_pgid = False, False
            if same_sid and diff_pgid:
                break
            assert time.monotonic() < end, "grandchild never entered expected session/pgid"
            time.sleep(0.005)
        owner_time = psutil.Process(proc.pid).create_time()
        (evidence / "owner.json").write_text(json.dumps({"pid": proc.pid, "create_time": owner_time}))
        attempt = SimpleNamespace(evidence_path=str(evidence), pid=proc.pid,
                                  pid_create_time=owner_time)
        result = sup.reconcile(attempt)
        assert result["cleanup_verified"]
        deadline = time.monotonic() + 5
        while not (no_live(proc.pid) and no_live(grandchild_pid)):
            assert time.monotonic() < deadline, "reconcile left session members alive"
            time.sleep(0.01)
    finally:
        for pid in ([grandchild_pid] if grandchild_pid else []):
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        try:
            proc.kill()
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
        if proc.stdout:
            proc.stdout.close()


def test_preparation_wait_cannot_launch_payload_after_deadline(store, monkeypatch):
    def delayed(*args):
        time.sleep(1.1)
        return None
    monkeypatch.setattr(sup, "_own_caffeinate", delayed)
    result = run(store, "print('must not start')", wall=1.3, caffeinate=True)
    assert result.execution_status == "deadline_killed", result.execution_reason
    assert not Path(store.envelope.attempts[0].evidence_path, "payload.json").exists()
    assert result.cleanup_verified
