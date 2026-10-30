"""Infrastructure-only pilot. All output remains in the owned attempt."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from . import freeze, proof
from .envelope import atomic_write_json


def main():
    attempt = Path(os.environ["OVERNIGHT_ATTEMPT_DIR"])
    frozen_root = Path(os.environ["OVERNIGHT_FROZEN_ROOT"])
    freeze.verify_manifest(str(frozen_root))
    execution = freeze.make_exec_copy(str(frozen_root), str(attempt / "work" / "exec"))
    result = {"ok": False, "scope": "infrastructure and control validation only",
              "disposition": "unresolved", "gate3_timeout_claim": False,
              "blockers_unresolved": list(proof.MISSING_BASELINES)}
    result["proof"] = proof.tiny_proof(execution, sys.executable)
    if result["proof"]["ok"]:
        out = attempt / "work" / "control-output"
        out.mkdir()
        control = subprocess.run([sys.executable, "-B", str(Path(execution, "python", "run_algebra.py")),
                                  "--n", "6", "--time-limit", "5", "--out", str(out)],
                                 cwd=execution, timeout=60)
        result["algebra_control"] = {"ok": control.returncode == 0,
                                     "out_dir": str(out.relative_to(attempt))}
        result["ok"] = control.returncode == 0
    atomic_write_json(attempt / "pilot.json", result)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
