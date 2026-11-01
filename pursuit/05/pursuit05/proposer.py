from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import NamedTuple

from pursuit05 import screen

MODEL_ID = "muse-spark-1.3-contributor"
EXPECTED_PROVIDER = "meta"
PER_CALL_BUDGET = 25000
DEFAULT_RUN_BUDGET = 200000
MAX_REPAIRS = 2
EXEC_TIMEOUT_S = 240

EXEC_FLAGS = [
    "--preset", "empty",
    "--reasoning-effort", "low",
    "--max-model-steps", "1",
    "--no-foreign-personal-context",
    "--disable-web-tools",
    "--disable-reminders",
    "--disable-request-user-input",
    "--no-session-log",
    "--disable-write",
    "--disable-shell",
    "--approval-mode", "never",
]

SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class ProposalError(ValueError):
    pass


class ExecFailed(RuntimeError):
    pass


class SpendRefused(RuntimeError):
    pass


class CallOverBudget(RuntimeError):
    pass


class Proposal(NamedTuple):
    ath: tuple[int, ...]
    fth: int
    rationale: str


class Transcript(NamedTuple):
    provider_id: str | None
    model_id: str | None
    usage: dict
    text: str | None
    terminal: str | None


class ExecResult(NamedTuple):
    transcript: Transcript
    transcript_path: Path


class Attempt(NamedTuple):
    proposal: Proposal | None
    reason: str
    usage: dict
    provider_id: str | None
    model_id: str | None


class LoopResult(NamedTuple):
    best: Proposal
    w: float
    inf: float
    failed: bool
    fail_reason: str
    attempts: tuple


def proposal_schema(t: int) -> dict:
    n = t - 1
    return {
        "type": "object",
        "title": f"pursuit05-proposal-T{t}",
        "properties": {
            "abort_thresholds": {
                "type": "array",
                "items": {"type": "integer", "enum": list(screen.ABORT_VALS)},
                "minItems": n,
                "maxItems": n,
            },
            "final_threshold": {"type": "integer", "enum": [0, 1, 2]},
            "rationale": {"type": "string"},
        },
        "required": ["abort_thresholds", "final_threshold", "rationale"],
        "additionalProperties": False,
    }


def validate_proposal(obj, t: int) -> Proposal:
    if not isinstance(obj, dict):
        raise ProposalError(f"proposal must be an object, got {type(obj).__name__}")
    keys = set(obj)
    want = {"abort_thresholds", "final_threshold", "rationale"}
    if keys != want:
        raise ProposalError(f"proposal keys must be {sorted(want)}, got {sorted(keys)}")
    ath = obj["abort_thresholds"]
    fth = obj["final_threshold"]
    rat = obj["rationale"]
    if (
        not isinstance(ath, list)
        or len(ath) != t - 1
        or any(v not in screen.ABORT_VALS for v in ath)
    ):
        raise ProposalError(
            f"abort_thresholds must be {t - 1} values from {list(screen.ABORT_VALS)}, "
            f"got {ath!r}"
        )
    if fth not in (0, 1, 2):
        raise ProposalError(f"final_threshold must be 0, 1, or 2, got {fth!r}")
    if not isinstance(rat, str) or not rat.strip():
        raise ProposalError("rationale must be a non-empty string")
    return Proposal(tuple(ath), fth, rat)


def dominance_reason(w: float, inf: float, f_w: float, f_inf: float) -> str | None:
    bound = f_inf * (1.0 + screen.INF_REL) + screen.INF_ABS
    if inf > bound:
        return f"infidelity {inf:.6g} above F-anchored bound {bound:.6g}"
    if w >= f_w:
        return f"W {w:.6g} not below F W {f_w:.6g}"
    return None


def build_proposal_prompt(goal: str, summary: str, f_w: float, f_inf: float) -> str:
    return (
        f"Goal: {goal}\n{summary}\n"
        f"The fixed baseline F never aborts and accepts only weight 0, "
        f"scoring W = {f_w:.6g} and infidelity = {f_inf:.6g}. "
        "Propose abort thresholds (99 means never abort) and a final accept "
        "threshold that cut wasted spacetime volume per accepted output "
        "without raising output infidelity above the baseline bound, "
        "and say why in one sentence."
    )


def build_repair_prompt(prev: Proposal, reason: str, f_w: float, f_inf: float) -> str:
    return (
        "Your previous proposal is rejected. "
        f"Reason: {reason}. "
        f"Previous abort thresholds {list(prev.ath)} with final threshold {prev.fth}. "
        f"The F baseline scores W = {f_w:.6g} and infidelity = {f_inf:.6g}. "
        "Propose thresholds that beat F on W while staying within the "
        "F-anchored infidelity bound, and say why in one sentence."
    )


def build_explainer_prompt(
    goal: str, table_text: str, rules_text: str, s_text: str
) -> str:
    return (
        f"Goal: {goal}\n"
        f"Exact arm table on held-out test cells (modeled ring-plus-chord cells):\n"
        f"{table_text}\n"
        f"Best static policy S: {s_text}\n"
        f"Learned history-dependent policy as abort rules:\n{rules_text}\n"
        "In one paragraph, explain what the learned policy does differently "
        "from the best static policy. Then propose the next experiment."
    )


def parse_transcript(lines: list[str]) -> Transcript:
    provider_id = None
    model_id = None
    usage: dict = {}
    text = None
    terminal = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        pt = ev.get("payload_type", "")
        pay = ev.get("payload", {})
        if pt == "run.model.configured":
            provider_id = pay.get("provider_id")
            model_id = pay.get("model_id")
        elif pt == "run.usage":
            ms = pay.get("models", [{}])
            usage = {
                "input_tokens": ms[0].get("input_tokens", 0),
                "output_tokens": ms[0].get("output_tokens", 0),
                "reasoning_tokens": ms[0].get("reasoning_tokens", 0),
                "calls": pay.get("calls", 0),
            }
        elif pt in ("run.terminal.completed", "run.terminal.failed"):
            terminal = pay.get("terminal")
            text = pay.get("text")
    return Transcript(provider_id, model_id, usage, text, terminal)


def run_muse_exec(prompt: str, schema: dict, workdir: Path, tag: str) -> ExecResult:
    workdir.mkdir(parents=True, exist_ok=True)
    schema_path = workdir / f"{tag}-schema.json"
    schema_path.write_text(json.dumps(schema))
    (workdir / f"{tag}-prompt.txt").write_text(prompt)
    cmd = [
        "muse", "exec", "--json",
        "--model", MODEL_ID,
        "--output-schema", str(schema_path),
        "--workspace", str(workdir),
        *EXEC_FLAGS,
        prompt,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, cwd=workdir,
            timeout=EXEC_TIMEOUT_S, check=False,
        )
    except FileNotFoundError:
        raise ExecFailed("muse binary not found on PATH") from None
    except subprocess.TimeoutExpired:
        raise ExecFailed(f"muse exec timed out after {EXEC_TIMEOUT_S}s") from None
    out_path = workdir / f"{tag}-transcript.jsonl"
    out_path.write_text(proc.stdout)
    if proc.returncode != 0:
        raise ExecFailed(f"muse exec exit {proc.returncode}: {proc.stderr[:300]}")
    tr = parse_transcript(proc.stdout.splitlines())
    if tr.terminal != "completed":
        raise ExecFailed(f"muse exec did not complete: terminal={tr.terminal}")
    if not tr.usage:
        raise ExecFailed("muse exec transcript carries no run.usage event")
    check_call_budget(tr.usage)
    return ExecResult(tr, out_path)


def check_call_budget(usage: dict) -> None:
    spent = usage.get("input_tokens", 0)
    if spent > PER_CALL_BUDGET:
        raise CallOverBudget(
            f"call spent {spent} input tokens, "
            f"past the per-call budget {PER_CALL_BUDGET}"
        )


MIN_CALL_COST = 20000


class SpendGuard:
    def __init__(self, limit: int | None = None) -> None:
        if limit is None:
            limit = int(os.environ.get("PURSUIT05_MAX_TOKENS", DEFAULT_RUN_BUDGET))
        self.limit = limit
        self.total = 0
        self.calls = 0

    def check(self, min_next: int = MIN_CALL_COST) -> None:
        if self.total + min_next > self.limit:
            raise SpendRefused(
                f"spend guard refuses the next call at {self.total} tokens, "
                f"limit {self.limit}"
            )

    def add(self, usage: dict) -> int:
        self.total += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        self.calls += 1
        return self.total


def run_proposal_loop(
    goal: str,
    summary: str,
    t: int,
    f_w: float,
    f_inf: float,
    scorer,
    guard: SpendGuard,
    workdir: Path,
    tag: str,
) -> LoopResult:
    schema = proposal_schema(t)
    attempts: list[Attempt] = []
    prompt = build_proposal_prompt(goal, summary, f_w, f_inf)
    valid: list[tuple[Proposal, float, float, str | None]] = []
    for i in range(1 + MAX_REPAIRS):
        guard.check()
        res = run_muse_exec(prompt, schema, workdir, f"{tag}-try{i}")
        guard.add(res.transcript.usage)
        try:
            prop = validate_proposal(json.loads(res.transcript.text or ""), t)
        except (json.JSONDecodeError, ProposalError) as exc:
            reason = f"schema reject: {exc}"
            attempts.append(
                Attempt(None, reason, res.transcript.usage,
                        res.transcript.provider_id, res.transcript.model_id)
            )
            prompt = (
                f"Your previous output is rejected. Reason: {reason}. "
                f"{build_proposal_prompt(goal, summary, f_w, f_inf)}"
            )
            continue
        w, inf = scorer(prop.ath, prop.fth)
        dom = dominance_reason(w, inf, f_w, f_inf)
        reason = dom or "accepted"
        attempts.append(
            Attempt(prop, reason, res.transcript.usage,
                    res.transcript.provider_id, res.transcript.model_id)
        )
        valid.append((prop, w, inf, dom))
        if dom is None:
            break
        prompt = build_repair_prompt(prop, dom, f_w, f_inf)
    if not valid:
        raise ProposalError(
            "no valid proposal after "
            f"{1 + MAX_REPAIRS} tries: {attempts[-1].reason}"
        )
    ranked = sorted(valid, key=lambda v: (v[3] is not None, v[1]))
    prop, w, inf, dom = ranked[0]
    return LoopResult(prop, w, inf, dom is not None, dom or "",
                      tuple(attempts))


def run_explainer(
    prompt: str, guard: SpendGuard, workdir: Path, tag: str
) -> tuple[dict, Transcript]:
    schema = json.loads((SCHEMAS_DIR / "explanation.json").read_text())
    guard.check()
    res = run_muse_exec(prompt, schema, workdir, f"{tag}-explainer")
    guard.add(res.transcript.usage)
    try:
        obj = json.loads(res.transcript.text or "")
    except json.JSONDecodeError as exc:
        raise ProposalError(f"explainer output is not JSON: {exc}") from None
    if (
        not isinstance(obj, dict)
        or not isinstance(obj.get("explanation"), str)
        or not isinstance(obj.get("next_experiment"), str)
    ):
        raise ProposalError(f"explainer output misses keys: {obj!r}"[:300])
    return obj, res.transcript


def load_fixture() -> dict:
    path = FIXTURES_DIR / "proposals.json"
    return json.loads(path.read_text())


def fixture_proposal(entry: dict, t: int) -> tuple[Proposal, dict]:
    tr = parse_transcript(entry["transcript"])
    if tr.terminal != "completed":
        raise ProposalError("fixture transcript did not complete")
    prop = validate_proposal(json.loads(tr.text or ""), t)
    return prop, tr.usage


def make_workdir(root: Path) -> Path:
    scratch = root / "runs" / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="demo-", dir=scratch))


def render_table_rules(table: dict, s_ath: tuple, s_fth: int, limit: int = 40) -> str:
    lines = []
    for (k, vals) in sorted(table, key=lambda kv: (kv[0], kv[1])):
        if len(lines) >= limit:
            break
        if k >= len(s_ath):
            continue
        action = "abort" if table[(k, vals)] else "continue"
        static = "abort" if vals[k] > s_ath[k] else "continue"
        mark = "" if action == static else " *differs from S*"
        lines.append(f"k={k} cw={list(vals)} -> {action}{mark}")
    lines.append(f"final accept weight <= {s_fth} (S rule)")
    return "\n".join(lines)
