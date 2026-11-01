import json

import pytest

from pursuit05 import proposer
from pursuit05.proposer import (
    MODEL_ID,
    CallOverBudget,
    ProposalError,
    SpendGuard,
    SpendRefused,
    build_repair_prompt,
    check_call_budget,
    fixture_proposal,
    load_fixture,
    parse_transcript,
    proposal_schema,
    validate_proposal,
)


def test_proposal_schema_per_cell_threshold_count():
    assert proposal_schema(3)["properties"]["abort_thresholds"]["maxItems"] == 2
    assert proposal_schema(4)["properties"]["abort_thresholds"]["maxItems"] == 3


def test_fixture_proposals_validate():
    fixture = load_fixture()
    assert len(fixture["entries"]) >= 2
    for entry in fixture["entries"]:
        prop, usage = fixture_proposal(entry, 3)
        assert len(prop.ath) == 2
        assert usage["input_tokens"] <= proposer.PER_CALL_BUDGET


def test_schema_rejects_bad_json():
    good = {"abort_thresholds": [1, 2], "final_threshold": 0,
            "rationale": "why"}
    validate_proposal(good, 3)
    bads = [
        {"abort_thresholds": [1], "final_threshold": 0, "rationale": "why"},
        {"abort_thresholds": [1, 2, 3], "final_threshold": 0,
         "rationale": "why"},
        {"abort_thresholds": [1, 5], "final_threshold": 0, "rationale": "why"},
        {"abort_thresholds": [1, 2], "final_threshold": 3, "rationale": "why"},
        {"abort_thresholds": [1, 2], "final_threshold": 0, "rationale": ""},
        {"abort_thresholds": [1, 2], "final_threshold": 0},
        {"abort_thresholds": [1, 2], "final_threshold": 0, "rationale": "why",
         "extra": 1},
        [1, 2, 0],
        "not json",
    ]
    for bad in bads:
        with pytest.raises(ProposalError):
            validate_proposal(bad, 3)


def test_spend_guard_refuses_past_limit(monkeypatch):
    monkeypatch.delenv("PURSUIT05_MAX_TOKENS", raising=False)
    assert SpendGuard().limit == 200000
    monkeypatch.setenv("PURSUIT05_MAX_TOKENS", "1")
    guard = SpendGuard()
    assert guard.limit == 1
    with pytest.raises(SpendRefused):
        guard.check()
    guard = SpendGuard(limit=100)
    guard.add({"input_tokens": 60, "output_tokens": 30})
    guard.check(min_next=5)
    guard.add({"input_tokens": 5, "output_tokens": 6})
    with pytest.raises(SpendRefused):
        guard.check(min_next=5)


def test_spend_guard_sums_fixture_usage():
    fixture = load_fixture()
    guard = SpendGuard(limit=10**9)
    for entry in fixture["entries"]:
        _, usage = fixture_proposal(entry, 3)
        guard.add(usage)
    want = sum(e["usage"]["input_tokens"] + e["usage"]["output_tokens"]
               for e in fixture["entries"])
    assert guard.total == want


def test_repair_feedback_names_reason():
    prop = validate_proposal(
        {"abort_thresholds": [3, 3], "final_threshold": 0,
         "rationale": "why"}, 3)
    reason = "W 127.79 not below F W 78.19"
    text = build_repair_prompt(prop, reason, 78.19, 0.0005)
    assert reason in text
    assert "78.19" in text
    assert "0.0005" in text


def test_parse_transcript_reads_usage_and_model():
    fixture = load_fixture()
    entry = fixture["entries"][0]
    tr = parse_transcript(entry["transcript"])
    assert tr.terminal == "completed"
    assert tr.provider_id == "meta"
    assert tr.model_id == MODEL_ID
    assert tr.usage["input_tokens"] == entry["usage"]["input_tokens"]
    obj = json.loads(tr.text or "")
    assert obj["abort_thresholds"] == list(entry["proposal"]["abort_thresholds"])


def test_call_budget_refuses_over_budget_call():
    check_call_budget({"input_tokens": 25000})
    with pytest.raises(CallOverBudget):
        check_call_budget({"input_tokens": 25001})


def test_dominance_reason_names_bound_or_volume():
    assert proposer.dominance_reason(10.0, 0.0005, 78.0, 0.0005) is None
    over_inf = proposer.dominance_reason(10.0, 0.5, 78.0, 0.0005)
    assert over_inf is not None and "bound" in over_inf
    over_w = proposer.dominance_reason(90.0, 0.0005, 78.0, 0.0005)
    assert over_w is not None and "W" in over_w
