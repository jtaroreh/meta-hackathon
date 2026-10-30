"""Durable budgets and lock admission."""
import time

import pytest

from tools.overnight import envelope as env


def make_store(tmp_path, budget=7200):
    store = env.EnvelopeStore(tmp_path / "env.json")
    store.create("run", 3600, budget, "cfg", cutoff_sec=900)
    return store


def test_lock_and_deadline_preserved(tmp_path):
    store = make_store(tmp_path)
    deadline = store.envelope.original_deadline
    with pytest.raises(env.LockedError):
        env.EnvelopeStore(tmp_path / "env.json").open_existing()
    store.close()
    reopened = env.EnvelopeStore(tmp_path / "env.json")
    reopened.open_existing()
    assert reopened.envelope.original_deadline == deadline
    with pytest.raises(env.ExpiredError):
        reopened.check_launchable(now=deadline - 899)
    reopened.close()


def test_zero_cpu_and_cutoff_block(tmp_path):
    store = make_store(tmp_path, budget=0)
    with pytest.raises(env.EnvelopeError, match="CPU"):
        store.check_launchable()
    store.close()


def test_reservation_survives_resume_and_cannot_be_refunded(tmp_path):
    store = make_store(tmp_path)
    attempt = store.begin_attempt("18", tmp_path / "evidence", time.time() + 10, 100)
    store.finish(attempt, {"execution_status": "finished", "execution_reason": "ok",
                           "cpu_seconds": 0.001, "cleanup_verified": True})
    with pytest.raises(env.EnvelopeError, match="finalized"):
        store.finish(attempt, {})
    assert store.envelope.cpu_used_sec == 100
    store.close()
    reopened = env.EnvelopeStore(tmp_path / "env.json")
    reopened.open_existing()
    assert reopened.envelope.cpu_used_sec == 100
    assert reopened.screen_cpu_used("18") == 100
    reopened.close()


def test_missing_accounting_blocks_recovery(tmp_path):
    store = make_store(tmp_path)
    store.begin_attempt("18", tmp_path / "evidence", time.time() + 10, 100)
    store.close()
    reopened = env.EnvelopeStore(tmp_path / "env.json")
    reopened.open_existing()
    assert reopened.recover() == ["18-a01"]
    assert reopened.envelope.cpu_used_sec == 100
    with pytest.raises(env.EnvelopeError, match="uncertain"):
        reopened.check_launchable()
    reopened.close()


def test_atomic_write(tmp_path):
    import json
    path = tmp_path / "value.json"
    env.atomic_write_json(path, {"a": 1})
    assert json.loads(path.read_text()) == {"a": 1}
    assert list(tmp_path.glob("*.tmp.*")) == []
