"""CLI for init, supervised preparation, explicit screens, status and recovery."""
from __future__ import annotations

if __package__ in (None, ""):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "tools.overnight"

import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid

from . import preflight, receipts, supervisor
from .envelope import EnvelopeStore, EnvelopeError, atomic_write_json, digest
from .freeze import sha256_file

RUN_SECONDS = 8 * 3600
CUTOFF_SECONDS = 15 * 60
GLOBAL_CPU_SECONDS = 8 * 3600
CODE_ROOT = Path(__file__).resolve().parents[2]


def load_config(root):
    config = receipts.read_json(root / "overnight-config.json")
    if config.get("targets") != receipts.TARGETS:
        raise EnvelopeError("exact configured Muse and Codex targets required; no fallback")
    queue = config.get("queue", [])
    if len(set(queue)) != len(queue) or any(x not in {"%02d" % i for i in range(1, 25)} for x in queue):
        raise EnvelopeError("invalid ordered queue")
    return config


def stage_gates(root, store, config, stage, screen_id=None):
    env = store.envelope
    store.check_launchable()
    if digest(config) != env.config_hash or receipts.tool_hash(root) != env.tool_hash:
        raise EnvelopeError("configuration or tooling changed since envelope creation")
    receipts.check_capabilities(env)
    receipts.check_review(env, "tooling", {"tool_hash": env.tool_hash, "config_hash": env.config_hash})
    preparation = frozen_root = None
    if stage != "prepare":
        preparation, frozen_root = receipts.verify_inputs(env)
    if stage in ("screen", "selection") and screen_id != "18":
        if not env.pilot_receipt:
            raise EnvelopeError("infrastructure pilot required before broader screens")
        pilot = receipts.scoped_file(env.output_root, env.pilot_receipt)
        if sha256_file(pilot) != env.pilot_hash:
            raise EnvelopeError("stored pilot receipt changed")
        pilot_data = receipts.read_json(pilot)
        receipts.verify_artifacts(pilot)
        if pilot_data.get("execution_status") != "finished" or not pilot_data.get("pilot_ok"):
            raise EnvelopeError("successful infrastructure pilot required")
        common = {"preparation": env.preparation_hash, "pilot": env.pilot_hash}
        receipts.check_review(env, "postpilot", common, inputs=True)
        if stage == "screen":
            receipts.check_review(env, "screen-" + screen_id,
                                  {**common, **receipts.screen_artifacts(root, screen_id)}, inputs=True)
    host = preflight.preflight(env.output_root)
    if time.time() >= env.original_deadline - env.cutoff_sec:
        raise EnvelopeError("preflight consumed launch interval")
    return host, frozen_root


def launch(root, store, config, selection):
    env = store.envelope
    prepare = selection == "prepare"
    if prepare and env.preparation:
        raise EnvelopeError("preparation already complete")
    if selection == "18" and env.pilot_receipt:
        raise EnvelopeError("pilot already complete; do not repeat")
    if not prepare and selection not in config["queue"]:
        raise EnvelopeError("screen not in ordered queue")
    if not prepare and any(a.screen_id == selection and a.execution_status == "finished"
                           for a in env.attempts):
        raise EnvelopeError("screen already finished")
    host, frozen_root = stage_gates(root, store, config,
                                    "prepare" if prepare else "screen", selection)
    if prepare:
        spec = config["preparation"]
        screen_id = "prepare"
    else:
        spec = receipts.read_json(root / "screens" / selection / "command.json")
        screen_id = selection
        if spec.get("scope") != ("infrastructure" if selection == "18" else "research"):
            raise EnvelopeError("screen scope mismatch")
    cpu_limit, wall_limit = spec["cpu_limit_sec"], spec["wall_limit_sec"]
    if not prepare and selection != "18" and selection not in env.screen_started_at:
        raise EnvelopeError("select the screen before feasibility or model preparation")
    if cpu_limit > min(7200, config["screen_cpu_limit_sec"]) or wall_limit > min(9000, config["screen_wall_limit_sec"]):
        raise EnvelopeError("per-screen maximum is 7200 CPU capacity seconds and 9000 wall seconds")
    data = Path(env.output_root)
    evidence = data / "attempts" / (screen_id + "-" + uuid.uuid4().hex)
    replacements = {"python": str(Path(sys.executable).absolute()), "root": str(root),
                    "attempt": str(evidence), "data": str(data)}
    command = [str(arg).format(**replacements) for arg in spec["command"]]
    extra_env = {"PYTHONPATH": str(CODE_ROOT), "OVERNIGHT_ROOT": str(root),
                 "OVERNIGHT_DATA_DIR": str(data), "OVERNIGHT_ATTEMPT_DIR": str(evidence)}
    if frozen_root:
        extra_env["OVERNIGHT_FROZEN_ROOT"] = str(frozen_root)
    result = supervisor.run_screen(store, screen_id, command, str(data), str(evidence),
                                    wall_limit, cpu_limit, extra_env=extra_env)
    receipt = {**vars(result), "bindings": receipts.bindings(env, inputs=True),
               "host_preflight": host, "command": command,
               "scope": "infrastructure" if prepare or selection == "18" else "research",
               "scientific_disposition": "unresolved", "gate3_timeout_claim": False}
    if result.execution_status == "finished":
        try:
            if prepare:
                preparation = evidence / "preparation.json"
                prep = receipts.read_json(preparation)
                manifest = receipts.scoped_file(data, prep["manifest"])
                from .freeze import verify_manifest
                verify_manifest(str(manifest.parent.parent))
                if not prep.get("ok") or not prep.get("proof", {}).get("ok"):
                    raise EnvelopeError("proof did not pass")
                prep["evidence"] = {name: sha256_file(evidence / name)
                                    for name in ("execution.json", "worker-result.json", "stdout.log")}
                atomic_write_json(preparation, prep)
                env.preparation = str(preparation.relative_to(data))
                env.preparation_hash = sha256_file(preparation)
                env.input_hash = sha256_file(manifest)
            elif selection == "18":
                pilot = receipts.read_json(evidence / "pilot.json")
                if not pilot.get("ok") or pilot.get("gate3_timeout_claim") is not False:
                    raise EnvelopeError("pilot must be infrastructure only and successful")
                receipt["pilot_ok"] = True
                receipt["pilot_artifact_sha256"] = sha256_file(evidence / "pilot.json")
        except Exception as exc:
            receipt["execution_status"] = "blocked_env"
            receipt["execution_reason"] = "required artifact absent or invalid: " + str(exc)
            env.blocked_reason = receipt["execution_reason"]
    receipt["artifact_hashes"] = {str(p.relative_to(evidence)): sha256_file(p)
                                   for p in sorted(evidence.rglob("*")) if p.is_file()}
    atomic_write_json(evidence / "receipt.json", receipt)
    if selection == "18" and receipt["execution_status"] == "finished":
        env.pilot_receipt = str((evidence / "receipt.json").relative_to(data))
        env.pilot_hash = sha256_file(evidence / "receipt.json")
    if receipt["execution_status"] != "finished":
        env.blocked_reason = env.blocked_reason or "unrecoverable local execution failure; stop this run"
    store.save()
    print(json.dumps({"receipt": str(evidence / "receipt.json"), **receipt}, sort_keys=True))
    return 0 if receipt["execution_status"] == "finished" else 1



def reconcile_publication(store):
    env = store.envelope
    if env.blocked_reason:
        return
    for attempt in env.attempts:
        receipt = Path(attempt.evidence_path, "receipt.json")
        incomplete = (not receipt.is_file() or
                      (attempt.screen_id == "prepare" and not env.preparation) or
                      (attempt.screen_id == "18" and not env.pilot_receipt))
        if incomplete:
            env.blocked_reason = "execution completed but receipt publication is incomplete; stop this run"
            store.save()
            return

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=CODE_ROOT)
    parser.add_argument("action", choices=["init", "prepare", "select", "run", "recover", "status"])
    parser.add_argument("screen_id", nargs="?")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    store = EnvelopeStore(root / "overnight-envelope.json")
    try:
        if root != CODE_ROOT:
            raise EnvelopeError("run from the checkout containing this CLI; tooling hashes must name executed code")
        if args.action == "init":
            config = load_config(root)
            run_id = uuid.uuid4().hex
            data = root / "overnight-data" / run_id
            env = store.create(run_id, RUN_SECONDS, GLOBAL_CPU_SECONDS, digest(config),
                               tool_hash=receipts.tool_hash(root), output_root=data,
                               cutoff_sec=CUTOFF_SECONDS)
            data.mkdir(parents=True)
            (data / "receipts").mkdir()
            print(json.dumps(env.to_dict(), sort_keys=True))
            return 0
        store.open_existing()
        store.recover()
        reconcile_publication(store)
        if args.action in ("status", "recover"):
            print(json.dumps(store.envelope.to_dict(), sort_keys=True))
            return 0 if not store.envelope.blocked_reason else 3
        config = load_config(root)
        selection = "prepare" if args.action == "prepare" else args.screen_id
        if not selection:
            raise EnvelopeError("explicit screen id required")
        if args.action == "select":
            if selection == "18" or selection not in config["queue"]:
                raise EnvelopeError("select a broader queued research path")
            stage_gates(root, store, config, "selection", selection)
            env = store.envelope
            env.screen_started_at.setdefault(selection, time.time())
            store.save()
            deadline = min(env.original_deadline,
                           env.screen_started_at[selection] + config["screen_wall_limit_sec"])
            print(json.dumps({"screen_id": selection, "deadline": deadline,
                              "started_at": env.screen_started_at[selection]}, sort_keys=True))
            return 0
        return launch(root, store, config, selection)
    except Exception as exc:
        print(json.dumps({"blocked": str(exc)}, sort_keys=True), file=sys.stderr)
        return 3
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
