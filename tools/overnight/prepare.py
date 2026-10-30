"""Freeze, copy, then prove, inside one supervised preparation attempt."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from . import freeze, proof
from .envelope import atomic_write_json


def main():
    attempt = Path(os.environ["OVERNIGHT_ATTEMPT_DIR"]).resolve()
    work = attempt / "work"
    freeze.freeze(str(work))
    execution = freeze.make_exec_copy(str(work))
    receipt = proof.tiny_proof(execution, str(Path(sys.executable).absolute()))
    data = Path(os.environ["OVERNIGHT_DATA_DIR"])
    result = {"ok": receipt["ok"], "proof": receipt,
              "manifest": str((work / "frozen-source" / "SOURCES.md").relative_to(data)),
              "scope": "infrastructure only"}
    atomic_write_json(attempt / "preparation.json", result)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
