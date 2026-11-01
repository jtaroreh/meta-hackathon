"""Every number in RESULTS.md traces to a committed receipt.

RESULTS.md ends with a receipt index: one JSON object per line, each
naming a file under runs/, a field path, and the exact value. This
module checks each line against its file, checks that each indexed
float renders into the prose with the same %.10g format eval prints,
and recomputes the D1/D2 censuses plus the transfer tie from the
indexed values and the exact solvers. Prose may round a tabled value
to fewer digits only in a summary range that this module re-derives;
tables and the index carry exact values.
"""

import json
import re
from pathlib import Path

import torch

from pursuit05 import dp, exact, screen, train
from pursuit05.cells import CellRegistry
from pursuit05.policy import CultivationPolicy

PURSUIT05_DIR = Path(__file__).resolve().parents[1]
RESULTS = PURSUIT05_DIR / "RESULTS.md"
REGIMES = [
    "6-0.001",
    "6-0.002",
    "6-0.005",
    "9-0.001",
    "9-0.002",
    "9-0.005",
    "12-0.001",
    "12-0.002",
    "12-0.005",
]
CENSUS_REGIMES = [r for r in REGIMES if float(r.split("-")[1]) <= 0.002]

D2_LINE = (
    "P beats S in 0/6, beats A in 1/6, and reaches H within 2% in 6/6 at p <= 0.002"
)
D1_LINE = (
    "on test seeds, H's W is at least 10% below S's W, both "
    "within the F-anchored bound, in 0/6 (stage, rate) "
    "cells at p <= 0.002"
)


def _doc_text():
    return RESULTS.read_text()


def _prose_text():
    text = _doc_text()
    fence = "```json-index"
    head, _, _ = text.partition(fence)
    return head


def _index_entries():
    entries = []
    for line in _doc_text().splitlines():
        if line.startswith('{"file": "runs/'):
            entries.append(json.loads(line))
    assert entries, "receipt index is empty"
    return entries


def _resolve(doc, path):
    cur = doc
    for step in path:
        if isinstance(step, dict):
            ((key, want),) = step.items()
            cur = next(it for it in cur if it[key] == want)
        else:
            cur = cur[step]
    return cur


def _read_runs(rel):
    return json.loads((PURSUIT05_DIR / rel).read_text())


def test_every_number_in_results_has_a_receipt():
    for e in _index_entries():
        assert _resolve(_read_runs(e["file"]), e["path"]) == e["value"], e


def test_every_cited_runs_file_exists():
    for rel in sorted(set(re.findall(r"runs/[\w./-]+", _doc_text()))):
        assert (PURSUIT05_DIR / rel).exists(), rel


def _is_cell_detail(path):
    return "cells" in path and path[-1] in ("W", "inf")


def test_rendered_floats_appear_in_prose():
    prose = _prose_text()
    for e in _index_entries():
        if isinstance(e["value"], float) and not _is_cell_detail(e["path"]):
            assert f"{e['value']:.10g}" in prose, e


_FLOAT_RE = re.compile(r"^-?\d+\.\d+(e[+-]?\d+)?$|^-?\d+e[+-]?\d+$")
_INT_RE = re.compile(r"^-?\d+$")


def _indexed_scalars():
    floats, ints = set(), set()

    def add(v):
        if isinstance(v, bool):
            return
        if isinstance(v, float):
            floats.add(f"{v:.10g}")
        elif isinstance(v, int):
            ints.add(str(v))
        elif isinstance(v, list):
            for it in v:
                add(it)
        elif isinstance(v, dict):
            for it in v.values():
                add(it)

    for e in _index_entries():
        add(e["value"])
    return floats, ints


def test_table_numbers_have_index_entries():
    floats, ints = _indexed_scalars()
    rows = [ln for ln in _prose_text().splitlines() if ln.startswith("|")]
    assert rows, "no tables in RESULTS.md"
    for row in rows:
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if set(row) <= set("|-: "):
            continue
        if cells[0] in ("regime",):
            continue
        for cell in cells[1:]:
            for part in cell.rstrip("*").strip().split("/"):
                part = part.strip()
                if _FLOAT_RE.match(part):
                    assert part in floats, (row, part)
                elif _INT_RE.match(part):
                    assert part in ints, (row, part)


def _indexed():
    out = {}
    for e in _index_entries():
        out[(e["file"], json.dumps(e["path"], sort_keys=True))] = e["value"]
    return out


def _arms(idx, reg, arm):
    key = json.dumps(["arms", reg, arm, "mean_W"])
    keyi = json.dumps(["arms", reg, arm, "mean_inf"])
    return idx[("runs/frontier.json", key)], idx[("runs/frontier.json", keyi)]


def _p_point(idx, reg, lam=1000):
    base = ["points", {"lam": lam}]
    w = idx[(f"runs/{reg}/receipt.json", json.dumps(base + ["mean_W"], sort_keys=True))]
    inf = idx[
        (f"runs/{reg}/receipt.json", json.dumps(base + ["mean_inf"], sort_keys=True))
    ]
    return w, inf


def _bound(idx, reg):
    return idx[("runs/frontier.json", json.dumps(["arms", reg, "bound"]))]


def test_ties_are_exact():
    idx = _indexed()
    for reg in REGIMES:
        pw, pinf = _p_point(idx, reg)
        hw, hinf = _arms(idx, reg, "H")
        sw, sinf = _arms(idx, reg, "S")
        assert (pw, pinf) == (hw, hinf) == (sw, sinf), reg


def test_d2_census_recomputes():
    idx = _indexed()
    beats_s = beats_a = near_h = 0
    beater = None
    for reg in CENSUS_REGIMES:
        pw, pinf = _p_point(idx, reg)
        bound = _bound(idx, reg)
        ok = pinf <= bound
        sw, sinf = _arms(idx, reg, "S")
        aw, ainf = _arms(idx, reg, "A")
        hw, _ = _arms(idx, reg, "H")
        if pw <= 0.9 * sw and ok and sinf <= bound:
            beats_s += 1
        if pw <= 0.9 * aw and ok and ainf <= bound:
            beats_a += 1
            beater = reg
        if pw <= 1.02 * hw and ok:
            near_h += 1
    assert (beats_s, beats_a, near_h) == (0, 1, 6)
    assert beater == "12-0.001"
    assert D2_LINE in _prose_text()


def test_lam_sweep_collapses_and_bc_won_everywhere():
    idx = _indexed()
    kept = []
    for reg in REGIMES:
        means = [_p_point(idx, reg, lam) for lam in (1000, 5000, 10000)]
        assert means[0] == means[1] == means[2], reg
        for lam in (1000, 5000, 10000):
            key = json.dumps(["points", {"lam": lam}, "kept_from"], sort_keys=True)
            kept.append(idx[(f"runs/{reg}/receipt.json", key)])
            akey = json.dumps(["points", {"lam": lam}, "bc_agreement"], sort_keys=True)
            assert idx[(f"runs/{reg}/receipt.json", akey)] == 1.0, (reg, lam)
    tkey = json.dumps(["points", 0, "kept_from"])
    kept.append(idx[("runs/transfer-6-9/receipt.json", tkey)])
    akey = json.dumps(["points", 0, "bc_agreement"])
    assert idx[("runs/transfer-6-9/receipt.json", akey)] == 1.0
    assert len(kept) == 28
    assert set(kept) == {"bc"}


def test_tails_uniform_within_regime():
    idx = _indexed()
    for reg in REGIMES:
        n, p = reg.split("-")
        tails = set()
        for seed in ("4", "5"):
            key = json.dumps(
                ["points", {"lam": 1000}, "cells", f"{n}/{p}/{seed}", "tail"],
                sort_keys=True,
            )
            tails.add(idx[(f"runs/{reg}/receipt.json", key)])
        assert len(tails) == 1, reg


def test_worker_range_matches_receipts():
    idx = _indexed()
    walls = [
        idx[(f"runs/{reg}/receipt.json", json.dumps(["worker_s"]))] for reg in REGIMES
    ]
    assert len(walls) == 9
    lo, hi = min(walls), max(walls)
    assert f"{lo:.1f}" == "60.1"
    assert f"{hi:.1f}" == "224.5"
    assert (
        "One regime trains in 60.1 s to 224.5 s of worker wall on the build machine."
    ) in _prose_text()


def test_versions_agree_across_receipts():
    seen = set()
    files = [f"runs/{reg}/receipt.json" for reg in REGIMES]
    files.append("runs/transfer-6-9/receipt.json")
    for rel in files:
        v = _read_runs(rel)["versions"]
        seen.add((v["pufferlib"], v["torch"], v["numpy"]))
    assert seen == {("3.0", "2.15.0", "1.26.4")}


def test_d1_history_optimum_equals_static_everywhere():
    reg = CellRegistry()
    cells = reg.all_cells()
    assert len(cells) == 45
    fallback = 0
    for cell in cells:
        pre = reg.pre(cell)
        finf = screen.run_F(pre, cell.p)["inf"]
        s = exact.best_static(pre, cell.p, finf)
        h = dp.best_history(pre, cell.p, finf)
        fallback += h.fallback
        assert (h.result.W, h.result.inf) == (s.result.W, s.result.inf), cell.cell_id
    assert fallback == 0
    wins = 0
    for n in screen.SIZES:
        for p in screen.P_ERRS:
            if p > 0.002:
                continue
            sub = [c for c in cells if c.n == n and c.p == p and c.seed in (4, 5)]
            mw_h = sum(
                dp.best_history(
                    reg.pre(c), c.p, screen.run_F(reg.pre(c), c.p)["inf"]
                ).result.W
                for c in sub
            ) / len(sub)
            mw_s = sum(
                exact.best_static(
                    reg.pre(c), c.p, screen.run_F(reg.pre(c), c.p)["inf"]
                ).result.W
                for c in sub
            ) / len(sub)
            if mw_h <= 0.9 * mw_s:
                wins += 1
    assert wins == 0
    assert D1_LINE in _prose_text()


def test_transfer_policy_ties_h_on_n12():
    reg = CellRegistry()
    weights = torch.load(
        PURSUIT05_DIR / "runs/transfer-6-9/policy.pt",
        map_location="cpu",
        weights_only=True,
    )
    policy = CultivationPolicy()
    policy.load_state_dict(weights)
    policy.eval()
    cells = [c for c in reg.all_cells() if c.n == 12 and c.seed in (4, 5)]
    assert len(cells) == 6
    scored = train.evaluate_policy(policy, cells, reg)
    base = train.baselines_for_cells(cells, reg)
    for cell in cells:
        got = scored["cells"][cell.cell_id]
        want = base[cell.cell_id]["H"]
        assert (got["W"], got["inf"]) == (want["W"], want["inf"]), cell.cell_id
