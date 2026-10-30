"""Local preflight smoke tests for Wave-1 screens.

Run from repo root:  .venv/bin/python -B env/smoke.py
Covers gap-2 proof: MILP (path 06), SMT (path 10), ZX extraction (path 15),
BP-OSD (path 01), qiskit synthesis imports (path 18), stim sampling (path 01/04).
Any failure means the affected path is UNRESOLVED (missing env), never a
solver-timeout verdict.
"""

import numpy as np

failures = []


def check(name, fn):
    try:
        fn()
    except Exception as e:
        failures.append(name)
        print(f"FAIL {name}: {type(e).__name__}: {e}")
    else:
        print(f"ok   {name}")


def milp_higgs():
    from scipy.optimize import LinearConstraint, milp
    c = np.array([-1.0, -1.0])  # maximize x + y
    constraints = LinearConstraint(np.array([[1.0, 2.0]]), -np.inf, 4.0)
    res = milp(c, constraints=constraints, integrality=np.ones(2))
    assert res.success and abs(-res.fun - 4.0) < 1e-6, res


def smt_z3():
    import z3
    x, y = z3.Ints("x y")
    s = z3.Solver()
    s.add(x + y == 5, x - y == 1)
    assert s.check() == z3.sat
    m = s.model()
    assert m[x].as_long() + m[y].as_long() == 5


def zx_extract():
    import pyzx as zx
    c = zx.Circuit(2)
    c.add_gate("CNOT", 0, 1)
    c.add_gate("T", 0)
    c.add_gate("CNOT", 0, 1)
    g = c.to_graph()
    n0 = g.num_vertices()
    zx.simplify.full_reduce(g)
    assert g.num_vertices() <= n0
    c2 = zx.extract_circuit(g.copy())
    assert c2.qubits >= 2


def bp_osd():
    from ldpc import BpOsdDecoder
    h = np.array([[1, 1, 0, 1, 0, 0],
                  [0, 1, 1, 0, 1, 0],
                  [1, 0, 1, 0, 0, 1]], dtype=np.uint8)
    dec = BpOsdDecoder(h, error_rate=0.1, max_iter=10, ms_scaling_factor=1.0,
                       osd_method="OSD_E", osd_order=2)
    syndrome = np.zeros(3, dtype=np.uint8)
    est = dec.decode(syndrome)
    assert (h @ est % 2 == syndrome).all()


def qiskit_baselines():
    from qiskit.synthesis import synth_cnot_count_full_pmh
    from qiskit import QuantumCircuit
    qc = QuantumCircuit(2)
    qc.cx(0, 1)
    mat = np.array([[0, 1], [1, 0]])
    out = synth_cnot_count_full_pmh(mat)
    assert out.num_qubits == 2


def stim_sample():
    import stim
    c = stim.Circuit("X 0\nM 0\nTICK\nM 0")
    s = c.compile_sampler().sample(4)
    assert s.shape == (4, 2) and (s[:, 0] == 1).all()


for name, fn in [("milp-highs", milp_higgs), ("smt-z3", smt_z3),
                 ("zx-extract", zx_extract), ("bp-osd", bp_osd),
                 ("qiskit-synth", qiskit_baselines),
                 ("stim-sample", stim_sample)]:
    check(name, fn)

print(f"numpy {np.__version__}")
if failures:
    raise SystemExit(f"SMOKE FAILED: {failures}")
print("SMOKE PASS: 6/6")
