"""Invoke only in an isolated synthetic workspace. Never a production launch command."""
import json
from pathlib import Path
import subprocess
import sys
import time

from tools.overnight import preflight, run_one, supervisor
from tests.fixture_support import FixtureProbes


def main():
    args = sys.argv[1:]
    root = Path(args[args.index("--root") + 1]).resolve()
    if not (root / ".synthetic-fixture").is_file():
        raise RuntimeError("test harness requires an isolated synthetic fixture")
    config = json.loads((root / "overnight-config.json").read_text())
    specs = [config["preparation"]]
    specs += [json.loads(p.read_text()) for p in (root / "screens").glob("*/command.json")]
    for spec in specs:
        if (len(spec["command"]) != 5 or spec["command"][:4] !=
                ["{python}", "-B", "-m", "tests.fixture_payload"] or
                spec["command"][4] not in {"prepare", "pilot", "screen", "sleep", "stream"}):
            raise RuntimeError("test harness refuses real research commands")
    preflight.HostProbes = FixtureProbes
    supervisor.LOG_MAX_BYTES = 32768
    if (root / ".delay-handshake").exists():
        original = supervisor.atomic_write_json
        def delayed(path, data):
            if Path(path).name == "go.json":
                time.sleep(2)
            return original(path, data)
        supervisor.atomic_write_json = delayed
    supervisor.HANDSHAKE_SEC = 0.3
    supervisor.TERM_GRACE_SEC = 0.05
    supervisor.FINALIZE_RESERVE_SEC = 0.2
    supervisor.WATCHDOG_INTERVAL_SEC = 0.01
    supervisor._own_caffeinate = lambda pid, seconds: subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return run_one.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
