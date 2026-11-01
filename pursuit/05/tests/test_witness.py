import json

from pursuit05 import cli
from pursuit05.proposer import MODEL_ID
from pursuit05.witness import Witness


def _offline_witness(tmp_path):
    rc = cli.main(["demo", "--offline", "--witness-dir", str(tmp_path),
                   "cut wasted cultivation volume"])
    assert rc == 0
    paths = list(tmp_path.glob("*.json"))
    assert len(paths) == 1
    return paths[0]


def test_replay_round_trip(tmp_path):
    path = _offline_witness(tmp_path)
    assert cli.main(["replay", str(path)]) == 0


def test_witness_has_model_and_versions(tmp_path):
    path = _offline_witness(tmp_path)
    witness = Witness.read(path)
    assert witness.model_id == MODEL_ID
    assert witness.provider_id == "meta"
    assert witness.source == "fixture"
    assert witness.goal
    assert witness.cell_ids == ["9/0.002/4", "9/0.002/5"]
    assert set(witness.versions) >= {"python", "pufferlib", "torch", "muse"}
    assert witness.replay_command.startswith("python -m pursuit05 replay ")
    assert witness.timestamps["started"] <= witness.timestamps["finished"]


def test_replay_detects_corruption(tmp_path, capsys):
    path = _offline_witness(tmp_path)
    obj = json.loads(path.read_text())
    obj["arms"]["9/0.002/4"]["L"]["W"] += 1.0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(obj))
    assert cli.main(["replay", str(bad)]) == 1
    out = capsys.readouterr().out
    assert "MISMATCH L 9/0.002/4" in out


def test_replay_rescores_stored_static_policy(tmp_path, capsys):
    path = _offline_witness(tmp_path)
    obj = json.loads(path.read_text())
    obj["arms"]["9/0.002/5"]["S"]["W"] += 1.0
    bad = tmp_path / "bad-s.json"
    bad.write_text(json.dumps(obj))
    assert cli.main(["replay", str(bad)]) == 1
    assert "MISMATCH S 9/0.002/5" in capsys.readouterr().out


def test_replay_reports_unreadable_arm_cleanly(tmp_path, capsys):
    path = _offline_witness(tmp_path)
    obj = json.loads(path.read_text())
    del obj["arms"]["9/0.002/4"]["H"]["policy"]
    bad = tmp_path / "bad-h.json"
    bad.write_text(json.dumps(obj))
    assert cli.main(["replay", str(bad)]) == 1
    out = capsys.readouterr().out
    assert "MISMATCH H 9/0.002/4" in out
    assert "Traceback" not in out


def test_replay_command_points_at_witness(tmp_path):
    from pathlib import Path

    path = _offline_witness(tmp_path)
    witness = Witness.read(path)
    target = witness.replay_command.rsplit(" ", 1)[-1]
    assert Path(target).resolve() == path.resolve()


def test_demo_rejects_long_goal(tmp_path, capsys):
    rc = cli.main(["demo", "--offline", "--witness-dir", str(tmp_path),
                   "x" * 2001])
    assert rc == 1
    err = capsys.readouterr().err
    assert "past the 2000 cap" in err
    assert "Traceback" not in err


def test_offline_proposals_carry_tries_and_usage(tmp_path):
    path = _offline_witness(tmp_path)
    witness = Witness.read(path)
    for entry in witness.proposals.values():
        assert entry["tries"] == 1
        assert entry["usage"]["input_tokens"] > 0
    assert set(witness.versions) >= {"screen_src", "git_head"}


def test_validated_hit_rejects_bad_shape():
    from pursuit05.cells import CellRegistry

    reg = CellRegistry()
    cell = reg.find("9/0.002/4")
    assert cli._validated_hit({}, cell) is None
    assert cli._validated_hit({"9/0.002/4": {"S": {}}}, cell) is None
    bad = {"9/0.002/4": {"S": {"W": 1.0, "inf": 0.0, "pacc": 1.0,
                               "policy": {"ath": [0], "fth": 0}},
                         "H": {"W": 1.0, "inf": 0.0, "pacc": 1.0}}}
    assert cli._validated_hit(bad, cell) is None


def test_fixture_cell_tag_mismatch_refused(tmp_path, capsys, monkeypatch):
    import shutil

    from pursuit05 import proposer

    shutil.copy(proposer.FIXTURES_DIR / "proposals.json",
                tmp_path / "proposals.json")
    obj = json.loads((tmp_path / "proposals.json").read_text())
    obj["entries"][0]["cell_tag"] = "cell-9-0.002-5"
    (tmp_path / "proposals.json").write_text(json.dumps(obj))
    monkeypatch.setattr(proposer, "FIXTURES_DIR", tmp_path)
    out = tmp_path / "wit"
    rc = cli.main(["demo", "--offline", "--witness-dir", str(out), "goal"])
    assert rc == 1
    assert "does not match" in capsys.readouterr().err


def test_offline_wrong_regime_refused(tmp_path, capsys):
    rc = cli.main(["demo", "--offline", "--regime", "6/0.002",
                   "--witness-dir", str(tmp_path), "goal"])
    assert rc == 1
    assert "does not match" in capsys.readouterr().err


def test_replay_warns_on_unknown_arms(tmp_path, capsys):
    path = _offline_witness(tmp_path)
    obj = json.loads(path.read_text())
    obj["arms"]["9/0.002/4"]["X"] = dict(obj["arms"]["9/0.002/4"]["L"])
    extra = tmp_path / "extra.json"
    extra.write_text(json.dumps(obj))
    assert cli.main(["replay", str(extra)]) == 0
    assert "unknown; skipped" in capsys.readouterr().err


def test_replay_refuses_empty_witness(tmp_path, capsys):
    path = _offline_witness(tmp_path)
    obj = json.loads(path.read_text())
    obj["arms"] = {}
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps(obj))
    assert cli.main(["replay", str(empty)]) == 1
    assert "no known arms" in capsys.readouterr().err


def test_demo_bad_env_limit_clean_error(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("PURSUIT05_MAX_TOKENS", "abc")
    rc = cli.main(["demo", "--offline", "--witness-dir", str(tmp_path),
                   "goal"])
    assert rc == 1
    assert "Traceback" not in capsys.readouterr().err


def test_demo_bad_witness_dir_clean_error(tmp_path, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    rc = cli.main(["demo", "--offline", "--witness-dir",
                   str(blocker / "sub"), "goal"])
    assert rc == 1
    assert "cannot write witness" in capsys.readouterr().err


def test_live_proposer_failure_keeps_witness(tmp_path, monkeypatch):
    from pursuit05 import proposer

    def boom(prompt, schema, workdir, tag):
        raise proposer.ExecFailed("down")

    monkeypatch.setattr(proposer, "run_muse_exec", boom)
    rc = cli.main(["demo", "--witness-dir", str(tmp_path), "goal"])
    assert rc == 0
    paths = list(tmp_path.glob("*.json"))
    assert len(paths) == 1
    witness = Witness.read(paths[0])
    assert "L" not in witness.arms["9/0.002/4"]
    assert any("proposer failed" in n for n in witness.notes)
    assert cli.main(["replay", str(paths[0])]) == 0


def test_p_column_round_trip(tmp_path, capsys, monkeypatch):
    import torch

    from pursuit05.policy import CultivationPolicy

    pt = tmp_path / "policy.pt"
    torch.save(CultivationPolicy().state_dict(), pt)
    monkeypatch.setattr(cli, "_find_policy_checkpoint",
                        lambda n, p: pt)
    out = tmp_path / "w"
    rc = cli.main(["demo", "--offline", "--witness-dir", str(out), "goal"])
    assert rc == 0
    assert "P_W" in capsys.readouterr().out
    paths = list(out.glob("*.json"))
    witness = Witness.read(paths[0])
    assert witness.arms["9/0.002/4"]["P"]["n_evaluated"] == 1
    assert cli.main(["replay", str(paths[0])]) == 0


def test_witness_rejects_bad_file(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"witness_id": "x"}')
    try:
        Witness.read(bad)
    except ValueError as exc:
        assert "misses keys" in str(exc)
    else:
        raise AssertionError("expected ValueError")
