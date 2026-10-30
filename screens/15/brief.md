# Screen 15 — ZX spider-fusion plus gflow (staged in run f5ac1866b1794567ad299c518a43a391)

Design: sparse ZX rewrite trajectories with temporary inflation, terminal
deterministic extraction, true extracted CNOT/depth/T versus
pyzx.full_reduce. No Vandaele, Lau et al., PhasePoly or torch-policy code
exists anywhere in this screen (named blockers, same as all screens).

Hypothesis: multi-step ZX rewrite sequences that allow temporary spider
inflation cross simplification barriers before deterministic extraction —
reducing final extracted CNOT and T counts where greedy full_reduce gets
trapped.

Model (screen-authored; pyzx 0.10.7 only — no surgery/native code):
- Corpus: random Clifford+T circuits (gates uniform over {CNOT, T, S, H}),
  4*Q gates each, QUBITS in {6,8,10}. N_INST = 3 instances per (size,seed),
  seeds 1-5: 45 instances total (sized so honest work fits the admitted
  window; see Budgets). Initial graph = circuit.to_graph() +
  to_graph_like; the admissibility self-test requires gflow on the
  probe initial graph (plus determinism and lcomp/pivot return types).
- Moves (all semantics-preserving pyzx rules, return-checked): pivot on a
  sorted spider-spider edge, local complementation on a sorted spider, and
  euler_expansion on a sorted graph edge (at most 2 per trajectory — the
  inflation move; unfuse was dropped because to_graph_like normalization
  fuses its output back, net zero, while euler expansion nets +vertices
  that survive normalization with gflow intact, probed on pyzx 0.10.7).
  Every move is applied to a fresh copy of the current state
  (enumerate-on-copy), so vertex IDs are always valid. After every move
  the graph is re-normalized with to_graph_like. Branching capped at
  8 lcomp + 8 pivot + 8 euler sorted candidates per state (24 max);
  spider count capped at 1.6x initial (inflation bound); transposition
  dedupe by (graph, depth, euler-used) key where graph = all vertices
  (type, phase) + all edges (endpoint order, edge type SIMPLE/HADAMARD).
  (Beam search is level-synchronous so depth is implicit there: key
  (graph, euler-used).)
- Arms (extraction ONLY at terminals; beam/anneal search on the cheap
  proxy score = spiders + 4*T-spiders, never on extracted cost):
- F: full_reduce baseline, then extract (the comparison target). On
  inputs where full_reduce breaks gflow or extraction (probed: 17/45
  corpus inputs — full_reduce itself destroys gflow on dense small
  random circuits), F falls back to direct extraction of the initial
  graph-like state, flagged per-instance as identity-fallback; the
  fallback is deterministic and strictly weaker optimization, so the
  control stays conservative.
- A: greedy proxy-score reduction — repeatedly apply the single move
  minimizing score = spiders + 4*T-spiders (sorted tie-break, no
  inflation accepted, 200-step cap).
- B: beam search (width 4, depth 6) over move sequences within the
  inflation cap; extract the best final (up to 4 gflow-holding fallbacks
  by score order).
- C: simulated annealing (100 iters, seeded, fixed cooling) over move
  sequences; extract the best visited state (same fallback rule).
- R: random control — 25 seeded random length-8 sequences per instance,
  extract each, keep best + mean (1125 trajectories screen-wide); every
  blocked rollout's reason (ok/why/twoq) is recorded per rollout, nothing
  aggregated away.
- Terminal rule: gflow verified (zx.gflow.gflow is not None) then
  extract_circuit on a copy; failure (no gflow or extraction raise)
  records an honest arm-blocked entry, never a crash. gflow is verified
  at terminals, not enforced mid-trajectory (trajectories may pass through
  non-gflow states; only terminals must extract). The wall guard is also
  honored inside every arm loop and fallback-extraction loop (greedy
  steps, beam depths, anneal iters, rollouts, per-final extraction):
  a guard stop mid-arm records stopped-guard for that arm.
- Metrics from the extracted circuit: twoq = twoqubitcount() (CNOT+CZ at
  cost 1 each; CNOT/CZ counts also recorded), depth = depth() (pyzx layer
  depth), t = tcount() (pyzx T-gate count; corpus is Clifford+T so phases
  stay in the pi/4 lattice).
- Soundness: every Q=6 terminal (all arms incl. R-best) is matrix-verified
  against its original circuit up to global phase (dim 64); any mismatch
  fails Gate 1.

Controls:
- Gate 1: full_reduce mean CNOT strictly beats random-mean CNOT in every
  (size,seed) cell (pipeline discriminative) AND all Q=6 matrix checks pass
  (extraction sound).
- Gate 2: pooled CNOT spread across {F,A,B,C} > 2*SE at >=2 sizes.
  Gate 2t: same rule on pooled T-count.
- Gate 3 (bounded-exact DFS, same move set via the shared children()
  enumerator): tiny Q=4 circuits (4 instances, seed 0), depth <= 4, node
  cap 20000, extraction cap 8000 — must all SOLVE (optimum proven within
  caps; exactness is relative to the depth-4 exhaustive space, disclosed
  like the 06 candidate model). Terminal = a state that produced zero
  unseen valid successors (no-move states terminate below max depth too;
  states at max depth terminate without expansion). Targets: Q=8
  first-seed first-2 instances, depth <= 6, same caps — must all SOLVE
  within caps (exactness cross-check at the corpus mid-scale; probed:
  both solve in 2-28 s). A cap-hit (nodes == cap or terminals >
  extraction cap, best-so-far kept) or stopped-guard on any target fails
  Gate 3. The wall guard is checked at every node batch AND inside the
  terminal-extraction loop; a guard stop records stopped-guard (neither
  solved nor cap-hit). Arms also run on the tiny instances (gap to
  optimum recorded as validation evidence, not a gate). Hardness
  boundary: 12q depth-6 DFS hits the node cap (probed 20k nodes / ~125 s
  on 12q seed-2 — beyond this screen's 300 s wall-guard budget), so the
  limit-expiry regime is documented but not gated here; it is the
  recorded next experiment.
NEXT_EXPERIMENT: "12q depth-6 DFS cap-hit regime (probed 20k nodes / ~125 s on 12q seed-2, beyond this screen's 300 s wall-guard budget)"
- Gate 4: every planned cell complete (extracted metrics for F/A/B/C +
  R stats on all 45 instances; tiny + target DFS records present) AND
  payload wall time < 500 s.

Budgets: wall 900 s, cpu 5400 s (reservation basis; staged generous after
the 01 window lesson). The supervisor admits min(wall - screen_wall_used,
run-remaining, cpu-remaining/capacity) minus 8.5 s overhead — prompt
select->launch keeps the admitted window near ~540 s. Payload keeps wall
< 500 s via ordering (self-tests, tiny-exact, corpus blocks, target DFS)
plus a 300 s elapsed guard checked at every cell, instance, DFS batch,
inside the extraction loop, and before each extraction burst. EVERY
guard exit records the omitted work explicitly (remaining instances/cells
filled as skipped; whole-phase omissions append one skip record per
planned item — per tiny index, per instance, per target). results.json
is written at normal
completion; witnesses/checkpoint-<phase>.json (accumulated cells) is
written after tiny-exact, after the corpus loop, after each (size,seed)
block, and after the target DFS, so a supervisor stop still leaves
classifiable evidence. Every skip path
publishes (guarded lookups, default-empty records, no unbound variables,
no zero-division).

Baseline disclosure: no MILP comparison anywhere in this screen; the
exact baseline is bounded-exhaustive DFS (own cap-hit record counts as
limit-expiry, never as optimum). There is no Vandaele/Lau/PhasePoly/torch
implementation anywhere in this screen.

Acceptance (frozen joint Pareto, per arm): PURSUE iff some arm in {B,C}
jointly wins at >= 2 sizes, where arm X jointly wins a size iff pooled
twoq(X) beats F by > 2*SE over {F,B,C} AND pooled T(X) <= pooled T(F)
AND pooled depth(X) <= pooled depth(F) — all three on the SAME arm; a
win split across arms (B better twoq, C better T) is NOT a Pareto win.
A CNOT-only win with higher T or depth is NOT a Pareto win (routing
analog of the rejected 136-to-140 tradeoff). Also required: tiny exact
all solved AND targets all solved AND Gates 1, 2, 2t, 4 pass AND
self-tests ok. REJECT iff cells complete AND full tiny evidence AND
Gate-1 controls pass AND no strict pooled twoq win at any size. Else
UNRESOLVED + next experiment.
Pursue/reject classification is coordinator-side; the payload reports
numbers + gate evidence and its verdict field is always
unresolved-with-reason. Deterministic given seeds.
