# Screen 04 — erasure + biased-noise hybrid decoding (staged in run f5ac1866b1794567ad299c518a43a391)

Design: rotated surface-code X-memory syndrome extraction (screen-built
stim 1.16.0 circuit; stabilizer tiling transcribed the same way as
screen 02, canonical CNOT order, no flags) with explicit heralded
erasure flags plus residual biased Pauli noise. Three decoder arms race
on identical syndromes: HYB (sequential flagged-hyperedge peel +
Union-Find cluster growth on the remainder) vs MWPM-static (pulp MILP
exact perfect matching on static graph distances, X/Z decoded
separately, small subset only) vs UF-static (textbook Union-Find, X/Z
decoded separately, erasure-unaware). No MILP, SMT, OLSQA, Vandaele,
Lau et al., PhasePoly or torch-policy code exists anywhere in this
screen except the pulp MILP exact-matching arm disclosed below (named
blockers, same as all screens).

Hypothesis: sequential syndrome-bit peeling combined with
erasure-informed cluster growth outperforms static edge-weighted MWPM
when hyperedges arise from Rydberg decay leakage and biased Z/erasure
channels.

Model (screen-authored):
- Code: rotated surface code X-memory at d in {5, 7, 9}, rounds = d.
  (Surface branch of "surface/XZZX"; XZZX variant deferred to the next
  experiment.)
- Base circuit noise (stim, residual biased Pauli): 1q locations get
  PAULI_CHANNEL_1(px, py, pz) = p * (1, 1, 10) / 12 (bias eta = 10);
  after each CNOT, independent PAULI_CHANNEL_1 with the same
  distribution on both qubits; every measurement (syndrome M/MX and
  final data MX) carries flip probability p. No DEPOLARIZE1/2 anywhere.
- Heralded erasures (classical overlay, per shot): each data qubit each
  round erased with probability p (95% conversion of a p / 0.95
  leakage process; the <= 5.3% unheralded residue is folded into the
  Pauli budget above, no separate term). An erased qubit takes a
  uniform random Pauli acting after that round's CNOT block
  (intra-block fault timing is resolved by the base circuit noise, not
  the overlay). Syndrome/observable deltas come from exact Pauli-frame
  propagation through the round CNOT structure (screen-computed
  kernels): post-block faults affect round r + 1 onward, never round r;
  X-basis readout flips on Z/Y frame bits; final-readout detectors fire
  only on pre/post-last-CNOT frame disagreement (late errors flip the
  observable with no syndrome — physical, all arms equally).
- Kernel truth: eight validated injection cases cover the kernel
  patterns shot-for-shot against stim injection circuits in
  self-tests (8/8 propagate cases on raw measurement parities, plus
  manual-parity vs compile_m2d_converter agreement on 200 noisy
  shots). Detector
  sampling uses compile_sampler + compile_m2d_converter with
  separate_observables (compile_sampler returns measurements, NOT
  detectors). stim reports detection events relative to deterministic
  outcome (verified); production circuits contain only noise channels,
  so their reference is all-zero and converter output equals raw
  parity.
- Decoders decode the R-round detector volume. Final-readout detectors
  are sampled and recorded but excluded from all three decoders
  equally (stated simplification).
- Arms (same syndromes, same observable):
- HYB: sequential peel + Union-Find cluster growth. Peel: for each
  erased (q, r) in (round, qubit) order, the exact propagated
  single-fault kernel patterns X/Z/Y at (q, r); a pattern is applied
  (defects removed, correction recorded) iff it covers >= 2 still
  uncovered defects, with Y additionally requiring >= 1 covered
  defect on each side (X-subgraph and Z-subgraph) so joint Y
  hyperedges — invisible to separate-subgraph decoders — are resolved
  where flags support them. Growth: textbook Union-Find per X/Z
  subgraph on the remainder (same routine as the UF arm, so HYB equals
  UF on flag-free shots and differs only via flags). Deterministic
  throughout.
- MWPM-static: per X/Z subgraph, complete-graph exact matching with
  APSP static weights (scipy dijkstra) solved as a pulp MILP
  (COIN_CMD single-threaded threads=1 for determinism, binary edge
  variables, degree-1 constraints) — pulp MILP exact matching, small
  sizes only (seed 1, first 20 shots per (d, p), 9 subset cells), with
  its own per-solve time cap 2.0 s; non-Optimal, non-finite-weight,
  or disconnected-pair outcomes raise MWPMTimeout and are recorded
  as skips. No Vandaele/Lau/PhasePoly/torch/OLSQA or MILP-toolbox
  code; pulp is used only for this arm and the tiny cross-check.
- UF-static: textbook Union-Find per X/Z subgraph (odd clusters grow
  one hop, merge, spanning-tree peel; boundary absorbs parity),
  erasure-unaware, static weights.
- Soundness: noiseless sampling gives zero detectors/observables
  (200 shots); fixed-seed resampling is bit-identical; d = 5 validity
  via shortest_graphlike_error (a ValueError there means invalid);
  peel unit checks (empty input stays empty; crafted flagged-Y peels
  to the Y correction with observable 1 and zero residual; crafted
  flagged-X peels to the X correction; unflagged patterns never peel
  to Y); crafted single-mechanism syndromes decode to zero residual
  (UF interior + boundary, MWPM interior + optimal boundary weight);
  fixed 6-defect tiny pairing enumeration solves and agrees with the
  pulp MILP weight to 1e-6.

Controls:
- Gate 1: HYB pooled LER beats UF pooled LER with 2-SE separation in
  >= 1 of 9 (d, p) cells (pools = 5 seeds x 800 shots) AND tiny exact
  solved AND pulp-vs-enumeration weight agreement AND self-tests ok
  AND MWPM-subset directional majority (HYB_sub <= MWPM on >= 5/9
  subset cells, matched first-20 shots of seed 1).
- Gate 2: HYB pooled-mean LER strictly increases across p in
  {0.002, 0.005, 0.010} at >= 2 of 3 distances.
- Gate 3: fixed 6-defect tiny pairing enumeration SOLVES (node cap
  20000) AND the d = 9 target (first p = 0.01 sampled shot, <= 2000
  scanned, with >= 14 defects in one subgraph) CAP-HITS the same node
  cap on the same hardware. Only cap-hit counts as limit-expiry; a
  solved, stopped-guard (wall guard checked every 512 enumeration
  nodes), skipped-guard, or no-qualifying-syndrome target fails
  Gate 3. An outer wall guard or crash is NOT expiry.
- Gate 4: every planned cell complete (HYB + UF at 800/800 shots on
  all 45 cells; MWPM subset at 20/20 on all 9 subset cells; tiny +
  target records present) AND payload wall < 500 s AND zero skip
  records. Any guard-truncated batch records `<arm>-d<d>-p<p>-seed<s>
  -truncated` (or cell/mwpm/target equivalents) with n_evaluated, and
  a truncated run cannot pass G4 clean.

Budgets: wall 900 s, cpu 5400 s (reservation basis; staged generous
after the 01 window lesson). Payload keeps wall ~70-120 s (measured
79.8 s dry run: graphs + kernels < 1 s per (d, p); HYB mean 0.53
ms/shot, UF mean 0.56 ms/shot corpus-wide; MWPM subset mean 31
ms/shot) via ordering (self-tests, tiny exact, target scan +
enumeration, corpus d = 5, 7, 9) plus a 300 s elapsed guard checked
before every cell, every 64 corpus shots, every MWPM shot, and every
512 enumeration nodes. EVERY guard exit records the omitted work
explicitly (remaining cells filled as skipped; whole-phase omissions
append one skip record per planned item). results.json is written at
normal completion; witnesses/checkpoint-<phase>.json is written after
self-tests, tiny, targets, each distance block, and the corpus, so a
supervisor stop still leaves classifiable evidence. Every skip path
publishes (guarded lookups, default-empty records, no unbound
variables, no zero-division).

Baseline disclosure: the static baselines are edge-weighted MWPM
(pulp MILP exact matching as above) and Union-Find; the exact baseline
is bounded-exact pairing enumeration (own cap-hit record counts as
limit-expiry, never as optimum). There is no OLSQA/Vandaele/Lau/
PhasePoly/torch implementation anywhere in this screen.

Limitation (disclosed): erasure Paulis act after each round's CNOT
block (intra-block timing resolved by base noise, not the overlay);
final-readout detectors are excluded from all decoders equally; the
MWPM arm covers only a seed-1 subset (20 shots per (d, p)) for wall
reasons, so MWPM comparisons carry wide SEs and enter Gate 1 only as
a directional majority.

Acceptance (frozen joint Pareto): PURSUE iff hybrid 2-SE wins vs UF in
>= 2 (d, p) cells AND the MWPM-subset directional majority holds on
the SAME hybrid AND Gates 1, 2, 3, 4 pass AND self-tests ok AND the
cycle budget holds (HYB mean per-shot decode wall < MWPM mean AND <
50 ms/shot) — the verified gap (non-graph correlated erasure-Pauli
events, incl. Y hyperedges spanning the X/Z subgraphs that separate
decoders must split) resolved within budget. REJECT iff cells complete
AND MWPM subset complete AND tiny solved AND pulp-matched AND
self-tests ok AND no hybrid 2-SE win vs UF in any cell AND no
MWPM-subset majority. Else UNRESOLVED + next experiment (XZZX variant,
wider bias sweep, time-correlated erasure bursts).
Pursue/reject classification is coordinator-side; the payload reports
numbers + gate evidence and its verdict field is always
unresolved-with-reason. Deterministic given seeds.
