"""Freeze tests use synthetic trees. Symlinks rejected, drift refused."""
import json
import os

import pytest

from tools.overnight import freeze as fr


@pytest.fixture()
def sources(tmp_path):
    src = tmp_path / "src-tree"
    (src / "python").mkdir(parents=True)
    (src / "python" / "a.py").write_text("x = 1\n")
    (src / "real.txt").write_text("data\n")
    (src / "link.txt").symlink_to(src / "real.txt")
    return str(src)


def patched(entries):
    return entries


def test_freeze_copies_and_locks(tmp_path, sources, monkeypatch):
    root = str(tmp_path / "root")
    os.makedirs(root)
    monkeypatch.setattr(fr, "ALLOWLIST", (
        (sources, "python/a.py", "frozen-source/python/a.py"),
        (sources, "real.txt", "frozen-source/real.txt"),
    ))
    monkeypatch.setattr(fr, "KNOWN_MISSING",
                        ((sources, "nope.md", "test missing note"),))
    monkeypatch.setattr(fr, "git_state", lambda p: {"head": "t",
                                                    "status": ""})
    manifest = fr.freeze(root)
    assert len(manifest["entries"]) == 2
    assert manifest["missing"][0]["path"].endswith("nope.md")
    frozen = os.path.join(root, "frozen-source", "python", "a.py")
    with open(frozen) as fh:
        assert fh.read() == "x = 1\n"
    with pytest.raises(OSError):
        with open(frozen, "a") as fh:
            fh.write("mutate\n")
    with open(os.path.join(root, "frozen-source", "SOURCES.md")) as fh:
        saved = json.load(fh)
    assert len(saved["entries"]) == 2


def test_symlink_refused(tmp_path, sources, monkeypatch):
    root = str(tmp_path / "root")
    os.makedirs(root)
    monkeypatch.setattr(fr, "ALLOWLIST", (
        (sources, "link.txt", "frozen-source/link.txt"),
    ))
    monkeypatch.setattr(fr, "git_state", lambda p: {})
    with pytest.raises(fr.FreezeError):
        fr.freeze(root)


def test_input_drift_refused(tmp_path, sources, monkeypatch):
    root = str(tmp_path / "root")
    os.makedirs(root)
    monkeypatch.setattr(fr, "ALLOWLIST", (
        (sources, "python/a.py", "frozen-source/python/a.py"),
    ))
    monkeypatch.setattr(fr, "KNOWN_MISSING", ())
    monkeypatch.setattr(fr, "git_state", lambda p: {})
    fr.freeze(root)
    target = os.path.join(root, "frozen-source", "python", "a.py")
    os.chmod(target, 0o644)
    with open(target, "w") as fh:
        fh.write("drifted\n")
    with pytest.raises(fr.FreezeError):
        fr.verify_manifest(root)


def test_exec_copy_writable_and_separate(tmp_path, sources, monkeypatch):
    root = str(tmp_path / "root")
    os.makedirs(root)
    monkeypatch.setattr(fr, "ALLOWLIST", (
        (sources, "python/a.py", "frozen-source/python/a.py"),
    ))
    monkeypatch.setattr(fr, "KNOWN_MISSING", ())
    monkeypatch.setattr(fr, "git_state", lambda p: {})
    fr.freeze(root)
    exec_dir = fr.make_exec_copy(root)
    target = os.path.join(exec_dir, "python", "a.py")
    with open(target, "a") as fh:
        fh.write("# exec note\n")
    frozen = os.path.join(root, "frozen-source", "python", "a.py")
    with open(frozen) as fh:
        assert fh.read() == "x = 1\n"
    fr.verify_manifest(root)


def test_injected_file_refused(tmp_path, sources, monkeypatch):
    root = str(tmp_path / "root")
    os.makedirs(root)
    monkeypatch.setattr(fr, "ALLOWLIST", ((sources, "real.txt", "frozen-source/real.txt"),))
    monkeypatch.setattr(fr, "KNOWN_MISSING", ())
    monkeypatch.setattr(fr, "git_state", lambda p: {})
    fr.freeze(root)
    with open(os.path.join(root, "frozen-source", "extra.py"), "w") as fh:
        fh.write("unreviewed code")
    with pytest.raises(fr.FreezeError, match="unmanifested"):
        fr.verify_manifest(root)
