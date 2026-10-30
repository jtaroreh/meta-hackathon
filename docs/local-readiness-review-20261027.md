> Historical review from 2026-10-27. Its PASS does not cover the overnight supervisor. Current launch status is pending fresh independent review; see `overnight-verification.md` and `../OVERNIGHT_LAUNCH.md`.

# Local-readiness review — MacBook M4 Air (2026-10-27)

Verdict: **POLISH-FIRST** (independent advisor: `codex-pstack/gpt-6.1-sol`, medium reasoning).
The M4 Air suits bounded CPU screens, but the plan overstates readiness. No Wave-1 path runs as specified on the stock environment today.

## Coordinator-verified facts

- Machine: Apple M4, 10 cores, 16 GB RAM, Python 3.14.7, Apple clang 21.
- Disk: 96% used, ~8.6 Gi free — tight for 24 screens plus venv, logs, solver traces, swap.
- Repo at `4735c97`: only `README.md` + `.gitignore` tracked; `docs/` (plan) untracked; no `frozen-source/`, `screens/`, `results/` (Step 0 unrun — expected pre-`go`).
- Frozen inputs all located in read-only sources (`phasepoly-swarm-prep` docs + `python/` + `src/`; audit-tree decision guide).
- Coordinator re-check 2026-10-27, stock `python3`: `numpy`, `scipy`, `pyzx`, `qiskit`, `z3`, `pulp`, `ortools`, `pyscipopt`, `ldpc`, `bposd`, `stim` ALL missing. Installed: Pillow, pip, wheel only. No `.venv` in source checkout.

## Blocking gaps (advisor, corroborated where noted)

1. **Stale readiness claims.** Plan line 30 describes tracked files only (`docs/` untracked); Assumptions claim build/run verification that never happened. Fix: distinguish "inputs located" from "runtime verified"; gate worker dispatch on Step-0 preflight. Proof: `git status --short`, frozen manifest, preflight output.
2. **No dependency/baseline inventory.** Wave-1 assumes pyzx (15), MILP backend (06), SMT + OLSQA (10), BP-OSD + noise gen (01), SciPy MILP + Qiskit via baseline modules (18) — none installed (coordinator-confirmed). Fix: repo-local interpreter, pinned deps, one working MILP backend, SMT formulation/backend + identified OLSQA corpus, BP-OSD + noise implementations. Missing software must yield **unresolved**, never an exact-solver-timeout verdict. Proof: `.venv/bin/python -m pip check`, imports, tiny MILP/SMT/BP-OSD/ZX smoke tests.
3. **Incomplete native freeze list.** Step 0 omits `include/*.h`, `python/native.py`, verification/search C sources required by the Makefile/ctypes bridge. Fix: enumerate, copy, include build recipe + smoke inputs. Proof: from frozen copy, `make shared` + `import native; native.load()`. Advisor ran `clang -fsyntax-only` on the four C sources (pass); linking/execution unverified.
4. **No disk/memory/concurrency bounds.** No artifact-size estimate or free-space reserve at 8.6 Gi free. Fix: per-screen output limits, free-space reserve, solver thread limits, explicit concurrency + stop rule, aggregate CPU accounting so parallel solvers respect the 2-CPU-hour cap. Proof: `df`, `du`, one pilot screen with peak memory/size/limits recorded.

No inspected Wave-1 algorithm inherently needs GPU or x86. Nothing was changed by this review.

## Polish + re-review (2026-10-27, later same day)

All 4 gaps closed by coordinator (workhorse `muse-spark-1.3-contributor`):
`env/requirements.local` (59 pins), `env/smoke.py` 6/6 PASS, plan Step-0
inventory + full native freeze list + binding resource envelope + OLSQA-corpus
clarification. Re-review (`codex-pstack/gpt-6.1-sol`, medium): **PASS, ready
for `go`.** Nits: Step-0 commands made verbatim (applied); `.venv` has no
`pip` so `pip check` is unavailable (pins + runtime checks passed instead);
unavailable baselines stay unresolved (already plan rule).
