"""Freeze the dependency closure. Copies, never symlinks.

Immutable inputs live in frozen-source and are made read only. Builds
and runs happen in a separate writable execution copy, because
count_depth.py main writes results beside its own source. The manifest
records byte hashes, dirty git state, and explicit MISSING entries.
It never invents a file. Manifest excludes itself and build artifacts.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess

PHASEPOLY = "/Users/joeltaroreh/projects/phasepoly-swarm-prep"
AUDIT = ("/Users/joeltaroreh/projects/c191a spinoff"
         "/.audit/cloud-swarm-20261024/revision2/frozen-source")

ALLOWLIST = (
    (PHASEPOLY, "docs/CLOUD_SWARM_RESEARCH_PATHS.md",
     "frozen-source/docs/CLOUD_SWARM_RESEARCH_PATHS.md"),
    (AUDIT, "docs/PUFFERLIB_DECISION_GUIDE.md",
     "frozen-source/docs/PUFFERLIB_DECISION_GUIDE.md"),
    (PHASEPOLY, "docs/COUNT_DEPTH_CYCLE.md",
     "frozen-source/docs/COUNT_DEPTH_CYCLE.md"),
    (PHASEPOLY, "docs/THEOREM_BRIEF.md",
     "frozen-source/docs/THEOREM_BRIEF.md"),
    (PHASEPOLY, "docs/07_research_audit.md",
     "frozen-source/docs/07_research_audit.md"),
    (PHASEPOLY, "docs/08_implementation_contract.md",
     "frozen-source/docs/08_implementation_contract.md"),
    (PHASEPOLY, "python/exact_decode.py",
     "frozen-source/python/exact_decode.py"),
    (PHASEPOLY, "python/circuits.py",
     "frozen-source/python/circuits.py"),
    (PHASEPOLY, "python/compiler_baselines.py",
     "frozen-source/python/compiler_baselines.py"),
    (PHASEPOLY, "python/count_depth.py",
     "frozen-source/python/count_depth.py"),
    (PHASEPOLY, "python/search.py",
     "frozen-source/python/search.py"),
    (PHASEPOLY, "python/reference.py",
     "frozen-source/python/reference.py"),
    (PHASEPOLY, "python/native.py",
     "frozen-source/python/native.py"),
    (PHASEPOLY, "python/native_search.py",
     "frozen-source/python/native_search.py"),
    (PHASEPOLY, "python/run_algebra.py",
     "frozen-source/python/run_algebra.py"),
    (PHASEPOLY, "src/phase_poly.c",
     "frozen-source/src/phase_poly.c"),
    (PHASEPOLY, "src/verification.c",
     "frozen-source/src/verification.c"),
    (PHASEPOLY, "src/matroid.c",
     "frozen-source/src/matroid.c"),
    (PHASEPOLY, "src/search.c",
     "frozen-source/src/search.c"),
    (PHASEPOLY, "include/phase_poly.h",
     "frozen-source/include/phase_poly.h"),
    (PHASEPOLY, "include/verification.h",
     "frozen-source/include/verification.h"),
    (PHASEPOLY, "include/matroid.h",
     "frozen-source/include/matroid.h"),
    (PHASEPOLY, "include/search.h",
     "frozen-source/include/search.h"),
    (PHASEPOLY, "Makefile",
     "frozen-source/Makefile"),
    (PHASEPOLY, "tests/native_checks.py",
     "frozen-source/tests/native_checks.py"),
    (PHASEPOLY, "RESEARCH_RESULTS.md",
     "frozen-source/RESEARCH_RESULTS.md"),
    (AUDIT, "AGENTS.md",
     "frozen-source/AGENTS.md"),
)

KNOWN_MISSING = (
    (PHASEPOLY, "AGENTS.md",
     "absent from phasepoly checkout; paths doc instructs reading it; "
     "audit tree copy frozen instead; not invented"),
)

BUILD_NAMES = ("build", "__pycache__", "results", ".DS_Store")


class FreezeError(Exception):
    pass


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_state(path: str) -> dict:
    def run(*args):
        try:
            out = subprocess.run(["git", "-C", path, *args],
                                 capture_output=True, text=True,
                                 timeout=15)
            return out.stdout.strip()
        except Exception:
            return "unknown"
    return {"head": run("rev-parse", "HEAD"),
            "status": run("status", "--porcelain")}


def freeze(root: str) -> dict:
    """Copy allowlisted regular files. Reject symlinks."""
    entries = []
    for base, src_rel, dst_rel in ALLOWLIST:
        src = os.path.join(base, src_rel)
        dst = os.path.join(root, dst_rel)
        if os.path.islink(src):
            raise FreezeError("symlink refused: %s" % src)
        if not os.path.isfile(src):
            raise FreezeError("allowlist source absent: %s" % src)
        if os.path.exists(dst) or os.path.islink(dst):
            raise FreezeError("destination exists; freeze once: %s" % dst)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        os.chmod(dst, 0o444)
        entries.append({"source": src, "dest": dst_rel,
                        "sha256": sha256_file(dst)})
    missing = []
    for base, rel, note in KNOWN_MISSING:
        if not os.path.exists(os.path.join(base, rel)):
            missing.append({"path": os.path.join(base, rel), "note": note})
    manifest = {
        "entries": entries,
        "missing": missing,
        "phasepoly_git": git_state(PHASEPOLY),
        "audit_git": git_state(AUDIT),
        "meta_git": git_state(root),
    }
    manifest_path = os.path.join(root, "frozen-source", "SOURCES.md")
    with open(manifest_path, "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
    _readonly_tree(os.path.join(root, "frozen-source"), skip=("SOURCES.md",))
    return manifest


def _readonly_tree(path: str, skip: tuple = ()) -> None:
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in BUILD_NAMES]
        for name in filenames:
            if name in skip or name in BUILD_NAMES:
                continue
            full = os.path.join(dirpath, name)
            if os.path.isfile(full) and not os.path.islink(full):
                mode = os.stat(full).st_mode
                os.chmod(full, mode & ~ (stat.S_IWUSR | stat.S_IWGRP
                                         | stat.S_IWOTH))


def make_exec_copy(root: str, name: str = "exec") -> str:
    """Writable copy for builds and runs. Frozen tree stays untouched."""
    root = os.path.abspath(root)
    src = os.path.join(root, "frozen-source")
    dst = os.path.join(root, name)
    if os.path.exists(dst):
        raise FreezeError("exec copy exists: %s" % dst)
    shutil.copytree(src, dst, symlinks=False,
                    ignore=shutil.ignore_patterns(*BUILD_NAMES))
    for dirpath, _, filenames in os.walk(dst):
        for filename in filenames:
            full = os.path.join(dirpath, filename)
            mode = os.stat(full).st_mode
            os.chmod(full, mode | stat.S_IWUSR)
    return dst


def verify_manifest(root: str) -> None:
    """Refuse content drift, injected files, unsafe paths and symlinks."""
    from pathlib import Path
    root = str(Path(root).resolve())
    tree = Path(root).resolve() / "frozen-source"
    manifest_path = tree / "SOURCES.md"
    manifest = json.loads(manifest_path.read_text())
    expected = {"SOURCES.md"}
    for entry in manifest["entries"]:
        rel = Path(entry["dest"])
        if rel.is_absolute() or ".." in rel.parts or rel.parts[0] != "frozen-source":
            raise FreezeError("unsafe manifest path")
        target = Path(root) / rel
        local = str(target.relative_to(tree))
        if local in expected:
            raise FreezeError("duplicate manifest entry")
        expected.add(local)
        if target.is_symlink() or sha256_file(target) != entry["sha256"]:
            raise FreezeError("input drift: " + str(rel))
    actual = set()
    for path in tree.rglob("*"):
        if path.is_symlink():
            raise FreezeError("symlink in frozen closure")
        if path.is_file():
            actual.add(str(path.relative_to(tree)))
    if actual != expected:
        raise FreezeError("unmanifested or missing frozen inputs")
