"""Hashed coordinator attestations. These are an audit contract, not remote authentication."""
from __future__ import annotations

import json
from pathlib import Path
import time

from .envelope import digest
from .freeze import sha256_file, verify_manifest
from .preflight import BlockedError

TARGETS = {
    "workhorse": {"providerInstanceId": "muse", "model": "muse-spark-1.3-contributor",
                  "options": {"reasoningEffort": "xhigh"}},
    "advisor": {"providerInstanceId": "muse", "model": "muse-wonder-1.0",
                "options": {"reasoningEffort": "max"}},
    "takeover": {"providerInstanceId": "codex-pstack", "model": "gpt-6.1-sol",
                 "options": {"reasoningEffort": "high", "serviceTier": "default"}},
}


def read_json(path):
    return json.loads(Path(path).read_text())


def tool_hash(root):
    root = Path(root)
    files = sorted(list((root / "tools").rglob("*.py")) +
                   list((root / "tests").rglob("*.py")) +
                   [p for p in (root / "screens" / "18").rglob("*") if p.is_file()] +
                   [root / "OVERNIGHT_LAUNCH.md", root / "docs/overnight-contract.md",
                    root / "docs/cloud-swarm-readiness-plan.md"])
    return digest({str(p.relative_to(root)): sha256_file(p) for p in files})


def bindings(env, *, inputs=False):
    result = {"run_id": env.run_id, "config_hash": env.config_hash, "tool_hash": env.tool_hash}
    if inputs:
        result["input_hash"] = env.input_hash
    return result


def scoped_file(base, rel):
    path = Path(base, rel).resolve()
    if not path.is_relative_to(Path(base).resolve()) or not path.is_file():
        raise BlockedError("receipt artifact outside scope or absent: " + str(rel))
    return path


def check_receipt(path, env, kind, expected, artifacts=None):
    receipt = read_json(path)
    if receipt.get("kind") != kind or receipt.get("bindings") != expected:
        raise BlockedError("receipt binding mismatch: " + kind)
    if not env.created_at <= receipt.get("observed_at", 0) <= time.time() + 1:
        raise BlockedError("receipt observation time invalid")
    if not time.time() < receipt.get("valid_until", 0) <= env.original_deadline:
        raise BlockedError("receipt expired or exceeds run deadline")
    evidence = scoped_file(env.output_root, receipt.get("evidence_file", ""))
    if sha256_file(evidence) != receipt.get("evidence_sha256"):
        raise BlockedError("raw evidence changed")
    if artifacts is not None and receipt.get("artifacts") != artifacts:
        raise BlockedError("reviewed artifacts changed: " + kind)
    return receipt


def check_capabilities(env):
    receipt = check_receipt(Path(env.output_root, "receipts", "capabilities.json"),
                            env, "capabilities", bindings(env))
    if receipt.get("validated_targets") != TARGETS:
        raise BlockedError("coordinator must validate exact targets and options; no fallback")


def check_review(env, stage, artifacts, *, inputs=False):
    path = Path(env.output_root, "receipts", stage + "-review.json")
    receipt = check_receipt(path, env, stage + "-review", bindings(env, inputs=inputs), artifacts)
    if receipt.get("verdict") != "PASS" or receipt.get("reviewer") != TARGETS["advisor"]:
        raise BlockedError("matching independent advisor PASS required: " + stage)


def verify_inputs(env):
    if not env.preparation or not env.input_hash:
        raise BlockedError("successful preparation and proof required")
    preparation = scoped_file(env.output_root, env.preparation)
    if sha256_file(preparation) != env.preparation_hash:
        raise BlockedError("stored preparation receipt changed")
    receipt = read_json(preparation)
    for name, expected in receipt["evidence"].items():
        if sha256_file(scoped_file(preparation.parent, name)) != expected:
            raise BlockedError("preparation evidence changed")
    frozen_root = scoped_file(env.output_root, receipt["manifest"]).parent.parent
    verify_manifest(str(frozen_root))
    if sha256_file(frozen_root / "frozen-source" / "SOURCES.md") != env.input_hash:
        raise BlockedError("stored input hash changed")
    if receipt.get("ok") is not True or receipt.get("proof", {}).get("ok") is not True:
        raise BlockedError("preparation proof failed")
    return preparation, frozen_root


def screen_artifacts(root, screen_id):
    screen = Path(root, "screens", screen_id)
    manifest = read_json(screen / "command.json")
    paths = ["brief.md", "command.json", "run.sh"] + manifest.get("source_files", [])
    result = {}
    for rel in paths:
        path = scoped_file(screen, rel)
        result[str(path.relative_to(screen))] = sha256_file(path)
    return {"screen_files": digest(result)}


def verify_artifacts(receipt_path):
    receipt_path = Path(receipt_path)
    receipt = read_json(receipt_path)
    expected = receipt["artifact_hashes"]
    actual = {str(p.relative_to(receipt_path.parent)): sha256_file(p)
              for p in sorted(receipt_path.parent.rglob("*"))
              if p.is_file() and p != receipt_path}
    if actual != expected:
        raise BlockedError("execution artifacts changed")
