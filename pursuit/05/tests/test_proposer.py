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


def test_schema_file_matches_builder():
    path = proposer.SCHEMAS_DIR / "proposal.json"
    assert json.loads(path.read_text()) == proposal_schema(3)


def test_fixture_proposals_validate():
    fixture = load_fixture()
    assert len(fixture["entries"]) >= 2
    for entry in fixture["entries"]:
        prop, tr = fixture_proposal(entry, 3)
        assert len(prop.ath) == 2
        assert tr.usage["input_tokens"] <= proposer.PER_CALL_BUDGET
        assert tr.provider_id == "meta"
        assert tr.model_id == MODEL_ID


def test_schema_rejects_bad_json():
    good = {"abort_thresholds": [1, 2], "final_threshold": 0,
            "rationale": "why"}
    validate_proposal(good, 3)
    bads = [
        {"abort_thresholds": [1], "final_threshold": 0, "rationale": "why"},
        {"abort_thresholds": [1, 2, 3], "final_threshold": 0,
         "rationale": "why"},
        {"abort_thresholds": [1, 5], "final_threshold": 0, "rationale": "why"},
        {"abort_thresholds": [1.0, 2], "final_threshold": 0,
         "rationale": "why"},
        {"abort_thresholds": [True, 2], "final_threshold": 0,
         "rationale": "why"},
        {"abort_thresholds": [1, 2], "final_threshold": 3, "rationale": "why"},
        {"abort_thresholds": [1, 2], "final_threshold": 1.0,
         "rationale": "why"},
        {"abort_thresholds": [1, 2], "final_threshold": True,
         "rationale": "why"},
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
        _, tr = fixture_proposal(entry, 3)
        guard.add(tr.usage)
    want_in = sum(e["usage"]["input_tokens"] for e in fixture["entries"])
    want_out = sum(e["usage"]["output_tokens"] for e in fixture["entries"])
    assert guard.input_total == want_in
    assert guard.output_total == want_out
    assert guard.total == want_in + want_out


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
    usage = {"input_tokens": 25001, "output_tokens": 5}
    with pytest.raises(CallOverBudget) as info:
        check_call_budget(usage)
    assert info.value.usage == usage


def test_validate_explanation_rejects_loose_output():
    good = {"explanation": "why", "next_experiment": "next"}
    assert proposer.validate_explanation(good) == good
    bads = [
        {"explanation": "", "next_experiment": "next"},
        {"explanation": "why", "next_experiment": ""},
        {"explanation": "why"},
        {"explanation": "why", "next_experiment": "next", "extra": 1},
        {"explanation": "why", "next_experiment": 5},
        "not an object",
    ]
    for bad in bads:
        with pytest.raises(ProposalError):
            proposer.validate_explanation(bad)


def test_rule_render_footer_and_diff_count():
    table = {(0, (1,)): True, (0, (2,)): False, (1, (1, 0)): True}
    assert proposer.count_rule_diffs(table, (0, 0)) == 2
    text = proposer.render_table_rules(table, (0, 0), 0, 1, "P")
    assert text.splitlines()[-1] == (
        "final accept weight <= 1 (P rule) *differs from S*")
    assert sum(line.endswith("*differs from S*")
               for line in text.splitlines()) == 3
    same = proposer.render_table_rules(table, (0, 0), 0, 0, "H")
    assert same.splitlines()[-1] == "final accept weight <= 0 (H rule)"


_USAGE = {"input_tokens": 10, "output_tokens": 5, "reasoning_tokens": 0,
          "calls": 1}


def _proposal_json(ath):
    return json.dumps({"abort_thresholds": list(ath), "final_threshold": 0,
                       "rationale": "why"})


def _stub_exec(texts):
    calls = []

    def fake(prompt, schema, workdir, tag):
        calls.append(tag)
        text = texts[min(len(calls) - 1, len(texts) - 1)]
        if isinstance(text, Exception):
            raise text
        tr = proposer.Transcript("meta", MODEL_ID, dict(_USAGE), text,
                                 "completed")
        return proposer.ExecResult(tr, workdir / f"{tag}.jsonl")

    fake.calls = calls
    return fake


def _loop(monkeypatch, tmp_path, texts, scorer):
    monkeypatch.setattr(proposer, "run_muse_exec", _stub_exec(texts))
    guard = SpendGuard(limit=10**9)
    return proposer.run_proposal_loop(
        "goal", "summary", 3, 78.0, 0.0005, scorer, guard, tmp_path,
        tag="cell"), guard


def test_loop_accepts_first_try(monkeypatch, tmp_path):
    def scorer(ath, fth):
        return {"W": 10.0, "inf": 0.0005, "pacc": 1.0}

    loop, guard = _loop(monkeypatch, tmp_path, [_proposal_json((0, 0))],
                        scorer)
    assert loop.failed is False
    assert loop.best.ath == (0, 0)
    assert len(loop.attempts) == 1
    assert guard.calls == 1


def test_loop_repairs_then_accepts(monkeypatch, tmp_path):
    def scorer(ath, fth):
        if tuple(ath) == (3, 3):
            return {"W": 500.0, "inf": 0.0005, "pacc": 1.0}
        return {"W": 10.0, "inf": 0.0005, "pacc": 1.0}

    loop, _ = _loop(monkeypatch, tmp_path,
                     [_proposal_json((3, 3)), _proposal_json((0, 0))],
                     scorer)
    assert loop.failed is False
    assert loop.best.ath == (0, 0)
    assert len(loop.attempts) == 2
    assert "not below F W" in loop.attempts[0].reason


def test_loop_ranks_all_dominated(monkeypatch, tmp_path):
    def scorer(ath, fth):
        return {"W": 100.0 + sum(ath), "inf": 0.0005, "pacc": 1.0}

    loop, _ = _loop(
        monkeypatch, tmp_path,
        [_proposal_json((3, 3)), _proposal_json((2, 2)),
         _proposal_json((1, 1))],
        scorer)
    assert loop.failed is True
    assert loop.best.ath == (1, 1)
    assert len(loop.attempts) == 3


def test_loop_raises_when_all_invalid(monkeypatch, tmp_path):
    def scorer(ath, fth):
        raise AssertionError("scorer must not run")

    fake = _stub_exec(["not json"])
    monkeypatch.setattr(proposer, "run_muse_exec", fake)
    guard = SpendGuard(limit=10**9)
    with pytest.raises(ProposalError):
        proposer.run_proposal_loop(
            "goal", "summary", 3, 78.0, 0.0005, scorer, guard, tmp_path,
            tag="cell")
    assert len(fake.calls) == 3


def test_loop_treats_scorer_error_as_reject(monkeypatch, tmp_path):
    def scorer(ath, fth):
        raise ValueError("boom")

    fake = _stub_exec([_proposal_json((0, 0))])
    monkeypatch.setattr(proposer, "run_muse_exec", fake)
    guard = SpendGuard(limit=10**9)
    with pytest.raises(ProposalError):
        proposer.run_proposal_loop(
            "goal", "summary", 3, 78.0, 0.0005, scorer, guard, tmp_path,
            tag="cell")
    assert len(fake.calls) == 3


def test_exec_flags_match_overhead_chosen():
    from pathlib import Path

    root = Path(proposer.__file__).resolve().parents[1]
    overhead = json.loads((root / "runs" / "exec-overhead.json").read_text())
    assert proposer.EXEC_FLAGS == overhead["chosen"]["flags"]


def test_transcript_identity_checked():
    good = proposer.Transcript("meta", MODEL_ID, dict(_USAGE), "{}", "completed")
    proposer.check_transcript_identity(good)
    for provider, model in (("other", MODEL_ID), ("meta", "other-model")):
        bad = proposer.Transcript(provider, model, dict(_USAGE), "{}",
                                  "completed")
        with pytest.raises(proposer.ExecFailed):
            proposer.check_transcript_identity(bad)


def test_explainer_prompt_names_source_and_cell():
    text = proposer.build_explainer_prompt(
        "g", "T", "R", "S", "exact H optimum", "9/0.002/4")
    assert "exact H optimum as abort rules for cell 9/0.002/4" in text


def test_dominance_reason_names_bound_or_volume():
    assert proposer.dominance_reason(10.0, 0.0005, 78.0, 0.0005) is None
    over_inf = proposer.dominance_reason(10.0, 0.5, 78.0, 0.0005)
    assert over_inf is not None and "bound" in over_inf
    over_w = proposer.dominance_reason(90.0, 0.0005, 78.0, 0.0005)
    assert over_w is not None and "W" in over_w
