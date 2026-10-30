"""Record existing pytest receipts and read-only host facts for review."""
from pathlib import Path
import datetime
import json
import os
import platform
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psutil
from tools.overnight import preflight, receipts
from tools.overnight.freeze import sha256_file


def main():
    probe = preflight.HostProbes()
    host = {"observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "python": sys.executable, "python_version": platform.python_version(),
            "machine": platform.machine(), "logical_cpus": os.cpu_count()}
    for key, args in [("power_source", ()), ("disk_free_bytes", (str(ROOT),)),
                      ("mem_available_bytes", ()), ("module_versions", ())]:
        try:
            host[key] = getattr(probe, key)(*args)
        except Exception as exc:
            host[key] = {"error": str(exc)}
    host["tools"] = {name: probe.tool_present(name) for name in ("cc", "make", "caffeinate")}
    (ROOT / "docs/overnight-host.json").write_text(json.dumps(host, indent=2) + "\n")
    xml = ET.parse(ROOT / "docs/overnight-tests.xml").getroot()
    suite = xml.find("testsuite") if xml.tag != "testsuite" else xml
    cases = {node.attrib["name"]: node for node in suite.findall("testcase")}
    selected = {}
    base = ROOT / ".pytest-tmp"
    prefixes = ["test_documented_chain_and_shel", "test_live_cli_recovery_kills_d",
                "test_crash_before_go_never_sta", "test_worker_crash_uses_persist",
                "test_live_output_stays_bounded"]
    for prefix in prefixes:
        folder = next(base.glob(prefix + "*")) / "fixture"
        env = json.loads((folder / "overnight-envelope.json").read_text())
        entries = []
        for attempt in env["attempts"]:
            path = Path(attempt["evidence_path"], "receipt.json")
            entry = {"attempt": attempt, "receipt_path": str(path) if path.exists() else None}
            if path.exists():
                data = json.loads(path.read_text())
                keys = ("execution_status", "execution_reason", "cpu_seconds", "cpu_reserved_sec",
                        "cleanup_verified", "log_bytes", "pilot_ok", "gate3_timeout_claim")
                entry.update(receipt_sha256=sha256_file(path),
                             execution={key: data.get(key) for key in keys})
            entries.append(entry)
        selected[prefix] = {"synthetic_only": True, "original_deadline": env["original_deadline"],
                            "cpu_used_sec": env["cpu_used_sec"], "blocked_reason": env["blocked_reason"],
                            "attempts": entries}
    live = []
    for path in base.rglob("owner.json"):
        owner = json.loads(path.read_text())
        try:
            proc = psutil.Process(owner["pid"])
            if (abs(proc.create_time() - owner["create_time"]) < .001 and
                    proc.status() != psutil.STATUS_ZOMBIE):
                live.append({"owner_file": str(path), "pid": owner["pid"]})
        except psutil.NoSuchProcess:
            pass
    native = cases["test_tiny_proof_real_chain"]
    counts = {key: int(suite.attrib[key]) for key in ("tests", "failures", "errors", "skipped")}
    summary = {"checkout": str(ROOT), "synthetic_only_launch_evidence": selected,
               "junit_counts": counts, "tool_hash": receipts.tool_hash(ROOT),
               "native_proof_test": {"passed": native.find("failure") is None and native.find("skipped") is None,
                                     "stdout_in": "docs/overnight-tests.xml"},
               "live_verified_test_workers_after_suite": live}
    (ROOT / "docs/overnight-receipts.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"tests": counts, "live_verified_test_workers": live}, sort_keys=True))
    return 1 if live or counts["errors"] or counts["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
