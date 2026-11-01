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


def test_witness_rejects_bad_file(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"witness_id": "x"}')
    try:
        Witness.read(bad)
    except ValueError as exc:
        assert "misses keys" in str(exc)
    else:
        raise AssertionError("expected ValueError")
