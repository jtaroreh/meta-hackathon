"""One owned session, bounded pipe writes, sampled resource checks, one reap.

CPU admission reserves machine CPU capacity for the full attempt, including
cleanup. Reservations are never refunded. Measured wait4 usage is evidence,
not the aggregate admission guarantee. Workloads must keep descendants in the
owned session and write only into the run output tree. This is not a sandbox.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time
from types import SimpleNamespace

import psutil

from . import preflight as pre
from .envelope import EnvelopeError, atomic_write_json

TERM_GRACE_SEC = 0.5
WATCHDOG_INTERVAL_SEC = 0.05
HANDSHAKE_SEC = 5.0
FINALIZE_RESERVE_SEC = 3.0
LOG_MAX_BYTES = 5 * 1024 ** 2
THREAD_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
               "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS", "BLIS_NUM_THREADS",
               "GOTO_NUM_THREADS", "OMP_THREAD_LIMIT")


class SupervisionError(RuntimeError):
    pass


def child_env(extra=None):
    env = dict(os.environ)
    env.update(extra or {})
    env.update({name: "2" for name in THREAD_VARS})
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0")
    return env


def _same_process(pid, create_time):
    try:
        return abs(psutil.Process(pid).create_time() - create_time) < 0.001
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied as exc:
        raise SupervisionError("process identity inaccessible") from exc


def _members(sid):
    members = []
    for proc in psutil.process_iter():
        if proc.pid <= 0:
            continue
        try:
            if os.getsid(proc.pid) == sid and proc.status() != psutil.STATUS_ZOMBIE:
                members.append((proc.pid, proc.create_time()))
        except (psutil.NoSuchProcess, ProcessLookupError):
            continue
        except (psutil.AccessDenied, PermissionError) as exc:
            raise SupervisionError("cannot enumerate process ownership") from exc
    return members


def _signal_identity(identity, sig):
    pid, created = identity
    if _same_process(pid, created):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            raise SupervisionError("permission denied during cleanup") from exc


def cleanup_group(sid, owner_time, *, exclude_self=False, anchor=None):
    leader = _same_process(sid, owner_time)
    known = set(_members(sid))
    if not leader and known:
        if not anchor or anchor not in known or not _same_process(*anchor):
            raise SupervisionError("owner missing with survivors; identity uncertain")
    exclude = os.getpid() if exclude_self else None
    end = time.monotonic() + TERM_GRACE_SEC
    while True:
        remaining = [p for p in _members(sid) if p[0] != exclude]
        if not remaining:
            return True
        if not _same_process(sid, owner_time) and not known.intersection(remaining):
            raise SupervisionError("no surviving ownership anchor")
        known.update(remaining)
        sig = signal.SIGTERM if time.monotonic() < end else signal.SIGKILL
        for identity in remaining:
            _signal_identity(identity, sig)
        if time.monotonic() > end + 1.0:
            return not [p for p in _members(sid) if p[0] != exclude]
        time.sleep(WATCHDOG_INTERVAL_SEC)


def _dir_size(path):
    total = 0
    for root, dirs, files in os.walk(path):
        if any(Path(root, name).is_symlink() for name in dirs + files):
            raise SupervisionError("symlink in output scope")
        for name in files:
            try:
                total += Path(root, name).stat().st_size
            except FileNotFoundError:
                pass
    return total


def _resource_check(output_root, evidence, probes, limits, source_root=None):
    pre.check_power(probes)
    pre.check_disk(output_root, probes, pre.STOP_MIN_FREE_BYTES)
    pre.check_memory(probes)
    size = _dir_size(output_root)
    if source_root:
        screens = Path(source_root, "screens")
        size += _dir_size(screens)
        for path in screens.glob("*"):
            if path.is_dir() and _dir_size(path) > limits["attempt_bytes"]:
                raise SupervisionError("screen source output allowance")
    if size > limits["global_bytes"]:
        raise SupervisionError("global output allowance")
    for path in (Path(output_root) / "attempts").glob("*"):
        if _dir_size(path) > limits["attempt_bytes"]:
            raise SupervisionError("attempt output allowance")
    if _dir_size(evidence) > limits["attempt_bytes"]:
        raise SupervisionError("attempt output allowance")
    rss = 0
    for pid, created in _members(os.getsid(0)):
        if _same_process(pid, created):
            try:
                rss += psutil.Process(pid).memory_info().rss
            except psutil.NoSuchProcess:
                pass
    if rss > limits["rss_bytes"]:
        raise SupervisionError("sampled session RSS limit")
    return rss, size


def _own_caffeinate(pid, seconds):
    return subprocess.Popen(["caffeinate", "-dims", "-t", str(max(1, math.ceil(seconds))),
                             "-w", str(pid)], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def _release_caffeinate(proc):
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=1)


def _execute_owned(command, evidence, output_root, deadline, parent, probes,
                   caffeinate, extra_env, limits):
    sid = os.getsid(0)
    own_time = psutil.Process(sid).create_time()
    proc = caffeine = None
    status, reason, usage, returncode = "crashed", "not started", None, None
    peak_rss = peak_bytes = log_written = 0
    selector = selectors.DefaultSelector()
    mono_deadline = time.monotonic() + max(0, deadline - time.time())
    started = time.monotonic()
    cleanup = False
    try:
        _resource_check(output_root, evidence, probes, limits, extra_env.get("OVERNIGHT_ROOT"))
        if time.time() >= min(deadline, float(extra_env["OVERNIGHT_LAST_LAUNCH"])):
            raise SupervisionError("deadline before payload spawn")
        tmp = Path(evidence, "tmp")
        tmp.mkdir()
        work = Path(evidence, "work")
        work.mkdir()
        env = child_env({**extra_env, "TMPDIR": str(tmp), "TMP": str(tmp), "TEMP": str(tmp),
                         "XDG_CACHE_HOME": str(tmp / "cache"), "MPLCONFIGDIR": str(tmp / "mpl")})
        if caffeinate:
            caffeine = _own_caffeinate(sid, deadline - time.time())
        if (time.time() >= min(deadline, float(extra_env["OVERNIGHT_LAST_LAUNCH"])) or
                time.monotonic() >= mono_deadline):
            raise SupervisionError("deadline before payload spawn")
        proc = subprocess.Popen(command, cwd=work, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, bufsize=0)
        atomic_write_json(Path(evidence, "payload.json"),
                          {"pid": proc.pid, "create_time": psutil.Process(proc.pid).create_time()})
        os.set_blocking(proc.stdout.fileno(), False)
        selector.register(proc.stdout, selectors.EVENT_READ)
        with Path(evidence, "stdout.log").open("xb", buffering=0) as log:
            while True:
                if time.time() >= deadline or time.monotonic() >= mono_deadline:
                    status, reason = "deadline_killed", "absolute or cumulative wall deadline"
                    break
                if not _same_process(*parent):
                    status, reason = "crashed", "coordinator process disappeared"
                    break
                if caffeine is not None and caffeine.poll() is not None:
                    raise SupervisionError("caffeinate exited during payload")
                rss, size = _resource_check(output_root, evidence, probes, limits, extra_env.get("OVERNIGHT_ROOT"))
                peak_rss, peak_bytes = max(peak_rss, rss), max(peak_bytes, size)
                for key, _ in selector.select(WATCHDOG_INTERVAL_SEC):
                    data = os.read(key.fd, 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    allowed = max(0, limits["log_bytes"] - log_written)
                    log.write(data[:allowed])
                    log_written += min(len(data), allowed)
                    if len(data) > allowed:
                        status, reason = "resource_killed", "stdout byte limit"
                        break
                if status == "resource_killed":
                    break
                # Never use Popen.poll or wait for the payload. wait4 is its sole reaper.
                got, wait_status, ru = os.wait4(proc.pid, os.WNOHANG)
                if got:
                    returncode = os.waitstatus_to_exitcode(wait_status)
                    proc.returncode = returncode
                    usage = ru.ru_utime + ru.ru_stime
                    status = "finished" if returncode == 0 else "crashed"
                    reason = "exit:%d" % returncode
                    expected = {sid, caffeine.pid if caffeine is not None else None}
                    if any(pid not in expected for pid, _ in _members(sid)):
                        status, reason = "crashed", "wrapper exited with live descendants"
                    # Drain only what fits. Descendants holding the pipe are cleaned below.
                    while True:
                        try:
                            data = os.read(proc.stdout.fileno(), 65536)
                        except BlockingIOError:
                            break
                        if not data:
                            break
                        allowed = max(0, limits["log_bytes"] - log_written)
                        log.write(data[:allowed])
                        log_written += min(len(data), allowed)
                        if len(data) > allowed:
                            status, reason = "resource_killed", "stdout byte limit"
                            break
                    break
    except BaseException as exc:
        status = "deadline_killed" if (time.time() >= deadline or
                                        time.monotonic() >= mono_deadline) else "resource_killed"
        reason = "%s: %s" % (type(exc).__name__, exc)
    finally:
        selector.close()
        try:
            _release_caffeinate(caffeine)
        except BaseException as exc:
            reason += "; caffeinate release: " + str(exc)
        try:
            cleanup = cleanup_group(sid, own_time, exclude_self=True)
        except BaseException as exc:
            reason += "; cleanup uncertain: " + str(exc)
        if proc is not None:
            if proc.returncode is None and cleanup:
                try:
                    _, wait_status, ru = os.wait4(proc.pid, 0)
                    proc.returncode = os.waitstatus_to_exitcode(wait_status)
                    usage = ru.ru_utime + ru.ru_stime
                except (OSError, ChildProcessError):
                    usage = None
            if proc.stdout:
                proc.stdout.close()
        elif cleanup:
            usage = 0.0
        if not cleanup or usage is None:
            status = "crashed"
    return {"execution_status": status, "execution_reason": reason,
            "cleanup_verified": cleanup, "cpu_seconds": usage,
            "cpu_accounting": "wait4 payload and waited descendants; capacity reservation is the budget",
            "peak_sampled_session_rss": peak_rss, "peak_sampled_output_bytes": peak_bytes,
            "log_bytes": log_written, "wall_seconds": time.monotonic() - started}


def _worker(store, attempt, command, probes, caffeinate, extra_env, limits, parent):
    # Close the inherited descriptor without unlocking the parent's shared flock.
    store._lock_fh.close()
    os.setsid()
    evidence = Path(attempt.evidence_path)
    owner = {"pid": os.getpid(), "create_time": psutil.Process().create_time()}
    atomic_write_json(evidence / "owner.json", owner)
    end = time.monotonic() + HANDSHAKE_SEC
    while not (evidence / "go.json").exists():
        if not _same_process(*parent) or time.monotonic() >= end:
            os._exit(0)
        time.sleep(0.01)
    def interrupted(sig, frame):
        raise SupervisionError("worker interrupted by signal %d" % sig)
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    result = _execute_owned(command, evidence, store.envelope.output_root,
                            attempt.deadline, parent, probes, caffeinate,
                            extra_env, limits)
    atomic_write_json(evidence / "worker-result.json", result)
    os._exit(0)


def run_screen(store, screen_id, command, workdir, evidence_dir,
               wall_limit_sec, cpu_limit_sec, probes=None, caffeinate=True,
               *, extra_env=None, limits=None):
    """workdir is retained only as an admission boundary. Actual cwd is attempt/work."""
    store.check_launchable()
    env = store.envelope
    if (os.cpu_count() or 1) > env.capacity:
        raise EnvelopeError("machine CPU capacity increased; cannot reuse reservations")
    output = Path(env.output_root).resolve()
    evidence = Path(evidence_dir).resolve()
    if not evidence.is_relative_to(output / "attempts"):
        raise EnvelopeError("attempt must be inside the owned attempts tree")
    if not Path(workdir).resolve().is_relative_to(output):
        raise EnvelopeError("workdir must be inside owned output scope")
    if not all(math.isfinite(v) and v > 0 for v in (wall_limit_sec, cpu_limit_sec)):
        raise EnvelopeError("invalid screen limit")
    remaining = min(env.remaining_cpu(), cpu_limit_sec - store.screen_cpu_used(screen_id))
    # The complete launch, handshake, cleanup and reporting time fits this reservation.
    allowance = min(wall_limit_sec - store.screen_wall_used(screen_id),
                    env.original_deadline - time.time(), remaining / env.capacity)
    overhead = HANDSHAKE_SEC + TERM_GRACE_SEC + FINALIZE_RESERVE_SEC
    if allowance <= overhead:
        raise EnvelopeError("cumulative screen or run budget exhausted")
    hard_end = time.time() + allowance
    attempt = store.begin_attempt(screen_id, evidence, hard_end - TERM_GRACE_SEC - FINALIZE_RESERVE_SEC,
                                  allowance * env.capacity)
    evidence.mkdir(parents=True)
    probes = probes or pre.HostProbes()
    limits = limits or {"rss_bytes": pre.RSS_STOP_BYTES,
                        "attempt_bytes": pre.ATTEMPT_DIR_MAX_BYTES,
                        "global_bytes": pre.GLOBAL_ALLOWANCE_BYTES,
                        "log_bytes": LOG_MAX_BYTES}
    extra_env = {**(extra_env or {}),
                 "OVERNIGHT_LAST_LAUNCH": str(env.original_deadline - env.cutoff_sec)}
    parent = (os.getpid(), psutil.Process().create_time())
    pid = None
    try:
        pid = os.fork()
        if pid == 0:
            try:
                _worker(store, attempt, command, probes, caffeinate, extra_env or {}, limits, parent)
            except BaseException:
                os._exit(70)
        owner_path = evidence / "owner.json"
        until = min(hard_end, time.time() + HANDSHAKE_SEC)
        while not owner_path.exists():
            if time.time() >= until:
                raise SupervisionError("ownership handshake timed out")
            time.sleep(0.01)
        import json
        owner = json.loads(owner_path.read_text())
        if owner["pid"] != pid or not _same_process(pid, owner["create_time"]):
            raise SupervisionError("worker identity mismatch")
        attempt.pid, attempt.pid_create_time = pid, owner["create_time"]
        store.save()
        if time.time() >= env.original_deadline - env.cutoff_sec:
            raise SupervisionError("final no-launch interval reached during handshake")
        atomic_write_json(evidence / "go.json", {"pid": pid})
        while True:
            got, _, _ = os.wait4(pid, os.WNOHANG)
            if got:
                break
            if time.time() >= hard_end:
                raise SupervisionError("worker exceeded reserved lifetime")
            time.sleep(WATCHDOG_INTERVAL_SEC)
        result_path = evidence / "worker-result.json"
        if not result_path.exists():
            raise SupervisionError("worker exited without accounting receipt")
        result = json.loads(result_path.read_text())
        result["cleanup_verified"] = result["cleanup_verified"] and not _members(pid)
    except BaseException as exc:
        result = reconcile(attempt)
        result["execution_reason"] += "; supervisor: " + str(exc)
        if pid:
            try:
                os.wait4(pid, 0)
            except ChildProcessError:
                pass
    result.update(attempt_id=attempt.attempt_id, pid=attempt.pid,
                  pid_create_time=attempt.pid_create_time,
                  cpu_reserved_sec=attempt.cpu_reserved_sec, disposition="unresolved")
    atomic_write_json(evidence / "execution.json", result)
    store.finish(attempt, result)
    return SimpleNamespace(**result)


def reconcile(attempt):
    import json
    evidence = Path(attempt.evidence_path)
    owner_path = evidence / "owner.json"
    cleanup = False
    try:
        if owner_path.exists():
            owner = json.loads(owner_path.read_text())
            if attempt.pid is not None and (attempt.pid != owner["pid"] or
                    attempt.pid_create_time != owner["create_time"]):
                raise SupervisionError("persisted ownership mismatch")
            payload_path = evidence / "payload.json"
            anchor = None
            if payload_path.exists():
                payload = json.loads(payload_path.read_text())
                anchor = (payload["pid"], payload["create_time"])
            cleanup = cleanup_group(owner["pid"], owner["create_time"], anchor=anchor)
        elif not (evidence / "go.json").exists():
            # No acknowledgement means the handshake worker cannot start a payload.
            cleanup = True
        result_path = evidence / "worker-result.json"
        if cleanup and result_path.exists():
            result = json.loads(result_path.read_text())
            result["cleanup_verified"] = cleanup and result["cleanup_verified"]
            result["execution_status"] = "crashed"
            result["execution_reason"] = "coordinator interrupted; reconciled; " + result["execution_reason"]
            return result
    except BaseException as exc:
        return {"execution_status": "crashed", "execution_reason": "recovery uncertain: " + str(exc),
                "cpu_seconds": None, "cleanup_verified": False}
    return {"execution_status": "crashed", "execution_reason": "recovered without complete CPU receipt",
            "cpu_seconds": None, "cleanup_verified": cleanup}
