# Overnight supervisor and receipt contract

The local CLI admits cooperative foreground process workloads. The T3 coordinator owns provider lifecycle and independent scientific review. Neither component substitutes for the other.

## Ownership and budget state

`EnvelopeStore` holds an exclusive OS lock on one immutable run envelope. Each attempt records its evidence directory, absolute deadline, nonrefundable CPU reservation, worker PID and creation time. One worker creates a new session, writes `owner.json`, and waits for `go.json`. The parent persists the matching identity before writing `go.json`. The worker closes its inherited envelope lock descriptor.

The worker owns a payload and optional caffeinate process in the same session. It checks its coordinator's identity, both wall and monotonic deadlines, AC, disk, available memory, sampled aggregate session RSS and output sizes. It drains stdout through a bounded pipe writer. It reaps the payload once with `wait4`. It cleans all foreground session members even after successful wrapper exit or a caffeinate error. PID 0 is a kernel pseudo-process on macOS and never an owned member.

Recovery reconciles persisted ownership before freeing the active slot. Identity mismatches, inaccessible processes, permission errors, missing CPU receipts and surviving processes block the run. A completed worker receipt can preserve measured usage after a coordinator crash. Recovery still stops autonomous launch. If a worker died, a persisted live payload identity can anchor cleanup of its original session. If neither owner nor payload can establish ownership, cleanup remains uncertain and the run blocks without signalling an unrelated process. A CLI interruption between execution completion and receipt publication also blocks rather than repeating preparation. No recovery path grants a new deadline or refunds CPU.

CPU reservations use logical machine capacity times allocated attempt lifetime. They include handshake and shutdown allowance. Admission uses the minimum of global remaining CPU, cumulative screen CPU, cumulative screen wall time and remaining absolute run time. `select <id>` persists the research screen start before feasibility and model preparation. Its wall clock includes subsequent provider waits and review and never resets on repeated selection or resume. The research launch refuses a missing selection. Preparation and pilot start their local clocks at their first attempt; earlier provider validation still consumes the global deadline. Shutdown overruns add a conservative debit and block further execution. Actual sampled enforcement can overshoot. There is no per-process RLIMIT pretending to bound a process tree.

Detached sessions, malicious daemonization, arbitrary filesystem writes, remote jobs and hard real-time shutdown are outside the supported contract. Foreground descendants are included. Workloads must not change session ownership, leave external workers running, or write outside the admitted output scope. Disk, file growth and RSS are sampled. Only the supervisor's own stdout file has an exact write cap. Other outputs can exceed a threshold before the next observation. `wait4` payload usage may exclude descendants the payload did not wait for. The capacity debit does not depend on that incomplete measurement.

## Files required before launch

`overnight-config.json` fixes exact targets, preparation limits and ordered path IDs. Its semantic hash must equal the envelope's `config_hash`. The tool hash covers Python tools, Python tests, this receipt contract, the scientific plan, the launch prompt and staged pilot files. Executed code must belong to the same checkout whose files were hashed. Any change requires stopping this run; there is no in-run tooling amendment API.

Preparation creates `preparation.json` containing `ok`, a successful `proof`, a relative frozen manifest path, and hashes of its execution receipt, worker receipt and stdout. The envelope stores its hash and the frozen manifest's hash. `verify_manifest` rejects missing or changed entries, injected files and symlinks. The pilot makes a fresh writable execution copy. It cannot reuse an unverified mutable build from preparation.

The pilot's final `receipt.json` records execution, host versions, command, unresolved scientific disposition, false Gate 3 timeout claim, pilot status and hashes of all attempt artifacts. The envelope stores that receipt's hash. Broader launch verifies both the stored receipt and its artifact hashes.

Every broader screen requires `brief.md`, `command.json`, and `run.sh`. The command spec contains `command`, `scope` equal to `research`, `cpu_limit_sec`, `wall_limit_sec`, and `source_files` listing its complete additional local source closure relative to its screen directory. Commands use absolute substitutions `{python}`, `{root}`, `{attempt}`, and `{data}`. They run from `<attempt>/work`. Preparation and pilot use module commands so changes of cwd cannot break imports or interpreter paths. The supervisor assigns writable temp and cache paths under the attempt. Staged source files are inputs; builds and raw output belong under the attempt.

## Coordinator attestations

These JSON files are required under `<output-root>/receipts/`. All artifact paths are relative to the output root. The coordinator writes them only after inspecting actual T3 capability responses or independent review results. The CLI verifies their hashes and bindings. It does not authenticate remote authorship, parse an arbitrary T3 response into a live capability decision, or make a supplied availability boolean true.

Common fields are:

```json
{
  "kind": "capabilities",
  "bindings": {
    "run_id": "<envelope run_id>",
    "config_hash": "<envelope config_hash>",
    "tool_hash": "<envelope tool_hash>"
  },
  "observed_at": 0,
  "valid_until": 0,
  "evidence_file": "receipts/<unmodified raw evidence file>",
  "evidence_sha256": "<sha256 of that file>"
}
```

Replace the example timestamps with Unix seconds. `observed_at` is the coordinator's run-bound attestation time, no earlier than envelope creation. `valid_until` must be in the future and no later than the original run deadline. Raw prior review evidence may be bound only when it inspected the exact same bytes and configuration. Receipts are trusted coordinator attestations, not signed remote certificates. Preserve raw evidence so an independent reviewer can challenge them.

`capabilities.json` has kind `capabilities`. Add `validated_targets` exactly equal to `tools.overnight.receipts.TARGETS`. This means the coordinator compared the requested provider, model and option IDs to real live `orchestrator_capabilities` output. Save that unmodified output as evidence. There is no `available` field and no silent fallback.

`tooling-review.json` has kind `tooling-review`. Add `verdict` equal to `PASS`, `reviewer` exactly equal to the configured advisor target, and `artifacts` containing `tool_hash` and `config_hash` equal to the envelope values. The review must inspect the entire launch implementation, tests, resource policy, prompt, config and staged pilot. This gate opens preparation and the infrastructure pilot, not broader research.

`postpilot-review.json` has kind `postpilot-review`. Add `input_hash` to bindings. Add the same `verdict` and `reviewer` fields. Its `artifacts` must be exactly:

```json
{
  "preparation": "<envelope preparation_hash>",
  "pilot": "<envelope pilot_hash>"
}
```

The raw review must inspect pilot execution, proof, logs, accounting, cleanup and limits. A pilot PASS establishes only infrastructure evidence. It does not establish scientific merit or all four gates.

`screen-<id>-review.json` has kind `screen-<id>-review`. It uses the postpilot bindings and fields. Its `artifacts` adds `screen_files` equal to the hash returned by `screen_artifacts(root, id)`. That function hashes a mapping of every required screen file's relative path to its SHA256, then hashes the mapping using `envelope.digest`. The reviewer must inspect the actual brief, command, complete `source_files` closure and scientific controls, not only their digests. A changed screen needs another matching review. A bare PASS or `independent=true` without the complete binding is insufficient.

Review receipts can be read and checked locally without network access. Independent model availability and cancellation are coordinator responsibilities. Test fixtures use clearly marked synthetic evidence and explicit code injection in `tests/fixture_cli.py`. Production has no fixture option or power override environment variable.

## Scientific evidence

All CLI execution receipts keep scientific disposition unresolved. A separate coordinator record can classify a scientifically valid result after reading witnesses and controls. `gates.py` supplies conservative predicates; its input booleans alone are not evidence that those controls happened.

An exact timeout needs an installed, started real solver, a validated formulation, a solved tiny instance, the frozen solver limit and the solver's own limit-expiry evidence. An outer wall timeout, resource stop, crash or provider failure is infrastructure. A T-count timeout cannot prove joint CNOT and depth hardness. Pareto rejects the known CNOT increase from 136 to 140 even when depth decreases from 5 to 4. Unimplemented Vandaele, Lau et al., PhasePoly and torch policy comparisons remain named blockers. No pilot or local test authorizes an RL recommendation.
