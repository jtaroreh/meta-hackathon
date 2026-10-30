"""Finite synthetic payloads used only by tests.fixture_cli."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    root = Path(os.environ["OVERNIGHT_ROOT"])
    assert (root / ".synthetic-fixture").is_file()
    action = sys.argv[1]
    from tools.overnight import freeze, proof
    proof.TINY_CHECK_SNIPPET = "print('synthetic baseline controls only')"
    if action == "prepare":
        src = root / "fixture-source"
        freeze.ALLOWLIST = tuple((str(src), str(f.relative_to(src)),
                                  "frozen-source/" + str(f.relative_to(src)))
                                 for f in sorted(src.rglob("*")) if f.is_file())
        freeze.KNOWN_MISSING = ()
        from tools.overnight import prepare
        return prepare.main()
    if action == "pilot":
        from tools.overnight import pilot_18
        return pilot_18.main()
    if action == "sleep":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
        attempt = Path(os.environ["OVERNIGHT_ATTEMPT_DIR"])
        (attempt / "descendant.json").write_text(json.dumps({"pid": child.pid}))
        time.sleep(20)
    if action == "stream":
        for _ in range(128):
            os.write(1, b"x" * 4096)
            time.sleep(0.003)
        time.sleep(1)
    if action == "screen":
        end = time.monotonic() + 0.08
        while time.monotonic() < end:
            pass
        Path(os.environ["TMPDIR"], "bounded.txt").write_text("synthetic")
        print("synthetic screen finished", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
