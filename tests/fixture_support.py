"""Explicit test-only host injection. Production exposes no bypass option."""
import json
from pathlib import Path
import shutil
import shlex
import sys
import time

from tools.overnight import preflight, receipts, supervisor
from tools.overnight.envelope import RunEnvelope
from tools.overnight.freeze import sha256_file


class FixtureProbes(preflight.HostProbes):
    def power_source(self):
        return "ac"

    def disk_free_bytes(self, path):
        return 100 * 1024 ** 3

    def mem_available_bytes(self):
        return 8 * 1024 ** 3

    def module_versions(self):
        return {name: "synthetic" for name in preflight.REQUIRED_MODULES}

    def tool_present(self, name):
        return True


def fast_settings(monkeypatch):
    monkeypatch.setattr(supervisor, "HANDSHAKE_SEC", 0.3)
    monkeypatch.setattr(supervisor, "TERM_GRACE_SEC", 0.05)
    monkeypatch.setattr(supervisor, "FINALIZE_RESERVE_SEC", 0.2)
    monkeypatch.setattr(supervisor, "WATCHDOG_INTERVAL_SEC", 0.01)


def make_workspace(path):
    source = Path(__file__).resolve().parents[1]
    path.mkdir()
    for name in ("tools", "tests"):
        shutil.copytree(source / name, path / name,
                        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    shutil.copy(source / "OVERNIGHT_LAUNCH.md", path)
    (path / "docs").mkdir()
    for name in ("overnight-contract.md", "cloud-swarm-readiness-plan.md"):
        shutil.copy(source / "docs" / name, path / "docs" / name)
    config = json.loads((source / "overnight-config.json").read_text())
    config["preparation"] = {"command": ["{python}", "-B", "-m", "tests.fixture_payload", "prepare"],
                             "wall_limit_sec": 10, "cpu_limit_sec": 200}
    (path / "overnight-config.json").write_text(json.dumps(config))
    (path / ".synthetic-fixture").write_text("synthetic only")
    wrapper = path / "fixture-python"
    wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) +
                       ' -B -m tests.fixture_interpreter "$@"\n')
    wrapper.chmod(0o755)
    for screen_id, action in (("18", "pilot"), ("01", "screen")):
        screen = path / "screens" / screen_id
        screen.mkdir(parents=True)
        (screen / "brief.md").write_text("Synthetic control only. No scientific claim.")
        from tools.overnight.stage import RUN_SH_TEMPLATE
        (screen / "run.sh").write_text(RUN_SH_TEMPLATE.format(screen_id=screen_id))
        spec = {"command": ["{python}", "-B", "-m", "tests.fixture_payload", action],
                "wall_limit_sec": 10, "cpu_limit_sec": 200,
                "scope": "infrastructure" if screen_id == "18" else "research",
                "source_files": []}
        (screen / "command.json").write_text(json.dumps(spec))
    src = path / "fixture-source"
    (src / "python").mkdir(parents=True)
    (src / "tests").mkdir()
    (src / "Makefile").write_text("shared:\n\tmkdir -p build\n\ttouch build/synthetic-lib\n")
    (src / "python" / "native.py").write_text(
        "from pathlib import Path\ndef load():\n assert Path('build/synthetic-lib').is_file()\n")
    (src / "tests" / "native_checks.py").write_text(
        "from pathlib import Path\nassert Path('build/synthetic-lib').is_file()\nprint('synthetic native checks')\n")
    (src / "python" / "run_algebra.py").write_text(
        "import argparse\nfrom pathlib import Path\np=argparse.ArgumentParser()\n"
        "p.add_argument('--n'); p.add_argument('--time-limit'); p.add_argument('--out')\n"
        "a=p.parse_args()\nPath(a.out,'synthetic.json').write_text('{}')\nprint('synthetic control')\n")
    return path


def load_env(root):
    return RunEnvelope.from_dict(json.loads((Path(root) / "overnight-envelope.json").read_text()))


def attest(root, stage):
    env = load_env(root)
    folder = Path(env.output_root, "receipts")
    raw = folder / (stage + ".synthetic.txt")
    raw.write_text("SYNTHETIC TEST EVIDENCE. This is not a live T3 review or capability result.")
    data = {"kind": stage, "bindings": receipts.bindings(env),
            "observed_at": time.time(), "valid_until": env.original_deadline,
            "evidence_file": str(raw.relative_to(env.output_root)),
            "evidence_sha256": sha256_file(raw)}
    if stage == "capabilities":
        data["validated_targets"] = receipts.TARGETS
    else:
        data.update(verdict="PASS", reviewer=receipts.TARGETS["advisor"])
        if stage == "tooling-review":
            data["artifacts"] = {"tool_hash": env.tool_hash, "config_hash": env.config_hash}
        else:
            data["bindings"] = receipts.bindings(env, inputs=True)
            data["artifacts"] = {"preparation": env.preparation_hash, "pilot": env.pilot_hash}
            if stage.startswith("screen-"):
                screen_id = stage.removeprefix("screen-").removesuffix("-review")
                data["artifacts"].update(receipts.screen_artifacts(root, screen_id))
    (folder / (stage + ".json")).write_text(json.dumps(data))
