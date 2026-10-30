# Local research screening plan

This is an autonomous preparation plan for the M4 16 GB machine. The first Muse implementation failed independent review. The bounded takeover is pending fresh independent review. No research run or real pilot has launched in this task.

The executable procedure, resource policy and literal autonomous T3 prompt are in [OVERNIGHT_LAUNCH.md](../OVERNIGHT_LAUNCH.md). The [receipt contract](overnight-contract.md) defines the required gates. Those documents replace the earlier disconnected launch commands and aggregate CPU promises.

The original plan remains read-only at `/Users/joeltaroreh/projects/challenges/meta-hackathon/.git/jtaroreh/overnight/original-plan.md`. Scientific source contracts are `CLOUD_SWARM_RESEARCH_PATHS.md` in the phasepoly checkout and `PUFFERLIB_DECISION_GUIDE.md` in the audit tree. Freeze copies those inputs before any experiment. External checkouts remain read-only.

## Outcome and policy

The long-term objective is to screen 24 paths. This eight-hour run completes only what fits its unchanged envelope. Each considered path ends with pursue, reject on this screen, or unresolved with a named blocker and the exact next experiment that changes the verdict. The infrastructure pilot 18 does not complete a scientific screen. Do not claim guaranteed completion of all paths.

Start with the supervised freeze, exec and proof chain, then the pilot, then independent postpilot review. The coordinator selects the next eligible queued path without another human prompt. Select one screen at a time. Missing baselines can resolve a path as blocked without an empirical launch. Stop the entire run on an unrecoverable process, provider, environment or accounting failure.

Every empirical verdict needs a frozen hypothesis, corpus, controls, seeds, limits, acceptance rule, source hashes, machine and solver versions, raw results, rerunnable command and independently checkable witness or counterexample where possible. Compare baselines before and after changes on identical hardware. Use three small sizes and five fixed seeds where feasible; reserve the largest size for validation after fixing the method. Require physical end-to-end improvements at two sizes. Freeze Pareto or weighted acceptance before running. Never extend the budget after a negative.

No RL recommendation is permitted without all four scientific gates. Gate 1 needs a classical or random positive control. Gate 2 needs non-flat deltas. Gate 3 needs a real, controlled exact-solver limit at target scale on the same hardware. Gate 4 needs physical end-to-end cost. Missing software, missing literature comparisons and outer supervisor kills are unresolved. A T-count decoder timeout does not establish joint CNOT and depth hardness. Reject the known 136-to-140 CNOT tradeoff under Pareto even when depth decreases from 5 to 4.

Muse Spark 1.3 contributor runs the workhorse role at xhigh. Codex GPT 6.1 Sol runs advisor and bounded takeover roles at high/default. These are session-local requested targets. The coordinator must validate live T3 support and save raw capability evidence. No silent fallback, global model edits, cloud compute, GPU training, PufferLib installation, commits or pushes are included.

## Scientific queue

The older headings below group the scientific paths. Dispatch is sequential in the order fixed by `overnight-config.json`, after pilot and independent review. The CPU-capacity reservation policy can permit much less wall time than the original two-CPU-hour plan. Reports keep unattempted paths queued.

### 1. Wave-1 in this repo. Six-domain span (sequential)

Run from this repo. Each screen lives in its own `./screens/<id>/` dir.

| Path | Minimal screen here | Pursue only if |
|---|---|---|
| 01 qLDPC BP-guiding | C11 bitwise parity-check plus min-sum BP at 2 sizes, circuit and phenomenological noise. Standard BP versus damped or annealed versus BP-OSD under fixed microsecond cap | Non-OSD perturbations recover measurable BP to BP-OSD gap fraction on held-out syndromes within latency cap |
| 06 lattice-surgery routing | C11 2D grid, ZZ plus XX split and merge, factory congestion. Sequential A-star versus prioritized planning versus annealing on 10, 20, 30-qubit circuits. MILP timeout check | Lookahead plus rotation beats greedy A-star at 2 sizes or more and MILP fails optimality within 2-CPU-hour cap |
| 10 AOD shuttling | C11 2D grid, row and column order plus spacing. 1k random rollouts versus greedy row-packing versus annealing on 20, 40, 60 qubits versus OLSQA. Cost `sum(t_move/T_2)+N_Rydberg·eps_2Q` | Annealing or lookahead beats greedy at 2 sizes or more and SMT times out (all 4 gates pass) |
| 15 ZX spider-fusion plus gflow | Sparse ZX env with gflow preserved. 1k random versus greedy versus bounded-inflation beam or anneal, terminal deterministic extraction. True extracted CNOT, depth, T | Temporary inflation gives verified extracted savings over `pyzx.full_reduce` at 2 sizes or more without losing extractability |
| 18 phase-polynomial core | C11 engine on rank 6 plus CCZ hypergraphs, inflation caps 0, 2, 4, 8. Full polynomial plus map G preserved. Versus unchanged-support resynthesis, `exact_decode.py`, Amy-Mosca, Amy-Maslov-Mosca, Vandaele, Lau et al., PhasePoly | Gains survive full synthesis plus unchanged-support plus exact small baselines at 2 sizes, all 4 gates pass (must beat the 136 to 140 CNOT-penalty failure mode) |
| 20 photonic fusion routing | C11 stochastic cluster sim, loss and decay timers. Static raster versus largest-component plus age-cutoff over 1k Monte Carlo times 3 lattice sizes at p_fusion 50 percent, 5 to 10 percent loss | Adaptive herald-conditioned policy beats static across multiple loss rates |

### 2. Remaining first-wave here (after harness and review)

- 02 flag gadgets, 04 erasure plus biased hybrid (d=5, 7, 9), 07 AutoCCZ and buffer, 12 mid-circuit reuse (24, 32, 40 wires to 16 physical), 19 Clifford tableau on restricted topologies (n=8, 12, 16), 24 ternary-tree fermion mapping (12, 16, 20 spin-orbitals plus full routing). Each in its own `./screens/<id>/` dir using its doc-specified classical-versus-search comparison and Continue only if bar.

### 3. Second-wave plus high-risk here (strict early exit)

- 03 Floquet, 05 cultivation, 08 qLDPC transversal scheduling, 09 defect-tolerant compilation, 11 QCCD shuttling, 13 crosstalk coloring, 14 multi-QPU teleportation, 16 Pauli-propagation truncation, 17 circuit-knitting cuts, 21 sparse-state BDDs, 22 bosonic stabilization (Fock N 32 or less, watch truncation artifacts), 23 adaptive QPE. Stop at first flat-gradient or missing-baseline signal. Record as unresolved with blocker, not a negative-result extension.

### 4. Coordinator import and funding decision (in this repo)

- Import each `./screens/<id>/` into `<output-root>/results/verdicts.md`. Check Gate 1 (classical or random found 1 plus win), Gate 2 (non-flat deltas), Gate 3 (exact solver times out at target scale or latency on same hardware), Gate 4 (physical end-to-end cost) from evidence files, not summaries. Missing baselines or seeds means unresolved. Rank only certified Pareto or weighted wins at 2 sizes. Keep the full-engine independent-review blocker separate.

## Current blockers

Vandaele, Lau et al., PhasePoly and the torch MinGRU policy are not implemented in the frozen closure. Record each explicitly. Published OLSQA benchmark figures can be a frozen comparison corpus, not a claim of a local OLSQA run. The native proof covers only the copied native chain and tiny controls. Full solver formulations and per-path implementations remain work for separately reviewed screens.

Host launch prerequisites include real AC, at least 4 GiB available memory, 8 GiB free disk, the pinned interpreter closure and native tools. Current observations and exact verification results belong to `docs/overnight-verification.md`; historical readiness reviews do not satisfy current gates.
