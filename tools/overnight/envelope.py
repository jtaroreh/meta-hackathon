"""Durable launch ownership and nonrefundable CPU-capacity reservations."""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


class EnvelopeError(RuntimeError):
    pass


class LockedError(EnvelopeError):
    pass


class ExpiredError(EnvelopeError):
    pass


class EvidenceError(EnvelopeError):
    pass


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def atomic_write_json(path, data) -> None:
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp.%d" % os.getpid())
    with tmp.open("x") as fh:
        json.dump(data, fh, indent=2, sort_keys=True, allow_nan=False)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@dataclass
class Attempt:
    attempt_id: str
    screen_id: str
    started_at: float
    evidence_path: str
    deadline: float
    cpu_reserved_sec: float
    pid: int | None = None
    pid_create_time: float | None = None
    ended_at: float | None = None
    execution_status: str = "running"
    execution_reason: str = ""
    disposition: str = "unresolved"
    cpu_seconds: float | None = None


@dataclass
class RunEnvelope:
    run_id: str
    created_at: float
    original_deadline: float
    global_cpu_budget_sec: float
    config_hash: str
    tool_hash: str
    output_root: str
    capacity: int
    cutoff_sec: float = 900.0
    input_hash: str = ""
    cpu_used_sec: float = 0.0
    active_screen: str | None = None
    blocked_reason: str = ""
    preparation: str = ""
    pilot_receipt: str = ""
    preparation_hash: str = ""
    pilot_hash: str = ""
    screen_started_at: dict[str, float] = field(default_factory=dict)
    attempts: list[Attempt] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data["attempts"] = [Attempt(**a) for a in data["attempts"]]
        return cls(**data)

    def remaining_cpu(self):
        return max(0.0, self.global_cpu_budget_sec - self.cpu_used_sec)

    def expired(self, now=None):
        return (time.time() if now is None else now) >= self.original_deadline


class EnvelopeStore:
    def __init__(self, envelope_path):
        self.envelope_path = str(Path(envelope_path).absolute())
        self._lock_fh = None
        self.envelope = None

    def _acquire(self):
        if self._lock_fh:
            raise LockedError("store already open")
        self._lock_fh = open(self.envelope_path + ".lock", "a+")
        try:
            fcntl.flock(self._lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.close()
            raise LockedError("another supervisor owns this envelope") from exc

    def create(self, run_id, deadline_sec, cpu_budget_sec, config_hash,
               input_hash="", now=None, *, tool_hash="", output_root=None,
               capacity=None, cutoff_sec=900.0):
        self._acquire()
        if Path(self.envelope_path).exists():
            self.close()
            raise EnvelopeError("envelope exists; resume it")
        if not all(math.isfinite(v) and v >= 0 for v in
                   (deadline_sec, cpu_budget_sec, cutoff_sec)):
            self.close()
            raise EnvelopeError("invalid budget")
        now = time.time() if now is None else now
        self.envelope = RunEnvelope(
            run_id, now, now + deadline_sec, cpu_budget_sec, config_hash,
            tool_hash, str(Path(output_root or Path(self.envelope_path).parent).resolve()),
            capacity or os.cpu_count() or 1, cutoff_sec, input_hash)
        self.save()
        return self.envelope

    def open_existing(self):
        self._acquire()
        try:
            self.envelope = RunEnvelope.from_dict(json.loads(
                Path(self.envelope_path).read_text()))
        except BaseException:
            self.close()
            raise
        return self.envelope

    def save(self):
        atomic_write_json(self.envelope_path, self.envelope.to_dict())

    def check_launchable(self, now=None):
        env = self.envelope
        now = time.time() if now is None else now
        if env.blocked_reason:
            raise EnvelopeError(env.blocked_reason)
        if now >= env.original_deadline - env.cutoff_sec:
            raise ExpiredError("deadline or final no-launch interval reached")
        if env.remaining_cpu() <= 0:
            raise EnvelopeError("global CPU capacity budget exhausted")
        if env.active_screen or any(a.execution_status == "running" for a in env.attempts):
            raise EnvelopeError("reconcile the active attempt before another launch")

    def screen_cpu_used(self, screen_id):
        return sum(a.cpu_reserved_sec for a in self.envelope.attempts
                   if a.screen_id == screen_id)

    def screen_wall_used(self, screen_id):
        elapsed = sum(max(0, (a.ended_at or time.time()) - a.started_at)
                      for a in self.envelope.attempts if a.screen_id == screen_id)
        if screen_id in self.envelope.screen_started_at:
            elapsed = max(elapsed, time.time() - self.envelope.screen_started_at[screen_id])
        return elapsed

    def begin_attempt(self, screen_id, evidence_path, deadline, cpu_reservation):
        self.check_launchable()
        if cpu_reservation <= 0 or cpu_reservation > self.envelope.remaining_cpu():
            raise EnvelopeError("insufficient CPU capacity budget")
        if Path(evidence_path).exists() or any(a.evidence_path == str(evidence_path)
                                             for a in self.envelope.attempts):
            raise EvidenceError("attempt evidence is append only")
        attempt = Attempt(
            "%s-a%02d" % (screen_id, 1 + sum(a.screen_id == screen_id
                                            for a in self.envelope.attempts)),
            screen_id, time.time(), str(Path(evidence_path).resolve()),
            deadline, cpu_reservation)
        self.envelope.screen_started_at.setdefault(screen_id, attempt.started_at)
        self.envelope.attempts.append(attempt)
        self.envelope.active_screen = screen_id
        self.envelope.cpu_used_sec += cpu_reservation
        self.save()
        return attempt

    def finish(self, attempt, result):
        if attempt.execution_status != "running":
            raise EnvelopeError("attempt already finalized")
        attempt.execution_status = result["execution_status"]
        attempt.execution_reason = result["execution_reason"]
        attempt.cpu_seconds = result.get("cpu_seconds")
        attempt.ended_at = time.time()
        actual_capacity = max(0, attempt.ended_at - attempt.started_at) * self.envelope.capacity
        if actual_capacity > attempt.cpu_reserved_sec:
            self.envelope.cpu_used_sec += actual_capacity - attempt.cpu_reserved_sec
            attempt.cpu_reserved_sec = actual_capacity
            self.envelope.blocked_reason = "reserved lifetime overrun during shutdown; stop this run"
        if attempt.cpu_seconds is None or not result.get("cleanup_verified", False):
            self.envelope.blocked_reason = "uncertain CPU accounting or process cleanup; stop this run"
        self.envelope.active_screen = None
        self.save()

    def recover(self):
        from .supervisor import reconcile
        recovered = []
        for attempt in self.envelope.attempts:
            if attempt.execution_status == "running":
                result = reconcile(attempt)
                self.finish(attempt, result)
                self.envelope.blocked_reason = self.envelope.blocked_reason or "interrupted execution reconciled; autonomous launch stopped"
                self.save()
                recovered.append(attempt.attempt_id)
        return recovered

    def close(self):
        if self._lock_fh is not None:
            fcntl.flock(self._lock_fh, fcntl.LOCK_UN)
            self._lock_fh.close()
            self._lock_fh = None
