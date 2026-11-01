import json
from pathlib import Path

import torch

from pursuit05 import dp, exact, screen, train
from pursuit05.cells import TEST_SEEDS, CellRegistry
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
EXPECTED_INDEX_COUNT = 352
SPLIT_ANALYSIS_CLEAN_CELLS = 15

D2_LINE = (
    "P beats S in 0/6, beats A in 1/6, and reaches H within 2% in 6/6 at p <= 0.002"
)
D1_LINE = (
    "on test seeds, H's W is at least 10% below S's W, both "
    "within the F-anchored bound, in 0/6 (stage, rate) "
    "cells at p <= 0.002"
)
OPENING = (
    "Learning reaches but does not beat the exact history optimum: on held-out "
    "cells at p <= 0.002, P reaches H within 2% in 6/6 regimes while H equals S "
    "exactly in all of them, so history-dependent abort buys nothing within the "
    "pinned decider class on these modeled ring-plus-chord cells."
)


def _doc_text():
    return RESULTS.read_text()


def _prose_text():
    text = _doc_text()
    head, _, _ = text.partition("```json-index")
    return head


def _index_block_lines():
    _, _, rest = _doc_text().partition("```json-index")
    block, _, _ = rest.partition("```")
    return [ln for ln in block.splitlines() if ln.strip()]


def _index_entries():
    entries = []
    for line in _index_block_lines():
        obj = json.loads(line)
        assert set(obj) == {"file", "path", "value"}, line
        assert obj["file"].startswith("runs/"), line
        entries.append(obj)
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


def _indexed():
    out = {}
    for e in _index_entries():
        out[(e["file"], json.dumps(e["path"], sort_keys=True))] = e["value"]
    return out


def test_index_is_complete_and_well_formed():
    entries = _index_entries()
    assert len(entries) == EXPECTED_INDEX_COUNT
    counts = {}
    for e in entries:
        counts[e["file"]] = counts.get(e["file"], 0) + 1
    assert counts.pop("runs/frontier.json") == 81
    assert counts.pop("runs/transfer-6-9/receipt.json") == 7
    for reg in REGIMES:
        want = 32 if reg == "6-0.001" else 29
        assert counts.pop(f"runs/{reg}/receipt.json") == want, reg
    assert counts == {}
    got = {(e["file"], json.dumps(e["path"], sort_keys=True)) for e in entries}
    want = set()
    for reg in REGIMES:
        for arm in ("F", "A", "S", "H"):
            for field in ("mean_W", "mean_inf"):
                want.add(("runs/frontier.json", json.dumps(["arms", reg, arm, field])))
        want.add(("runs/frontier.json", json.dumps(["arms", reg, "bound"])))
    for reg in REGIMES:
        f = f"runs/{reg}/receipt.json"
        n, p = reg.split("-")
        for field in (
            "seeds_eval",
            "selected_lam",
            "selection_tied",
            "train_bound",
            "worker_s",
        ):
            want.add((f, json.dumps([field])))
        for lam in (1000, 5000, 10000):
            for field in ("mean_W", "mean_inf", "kept_from", "bc_agreement"):
                want.add(
                    (f, json.dumps(["points", {"lam": lam}, field], sort_keys=True))
                )
        for seed in ("4", "5"):
            for field in ("W", "inf", "tail", "keys", "fth"):
                want.add(
                    (
                        f,
                        json.dumps(
                            [
                                "points",
                                {"lam": 1000},
                                "cells",
                                f"{n}/{p}/{seed}",
                                field,
                            ],
                            sort_keys=True,
                        ),
                    )
                )
        for field in ("mean_W", "mean_inf"):
            want.add((f, json.dumps(["scratch", field])))
    for key in ("pufferlib", "torch", "numpy"):
        want.add(("runs/6-0.001/receipt.json", json.dumps(["versions", key])))
    for path in (["trained_on"], ["seeds_eval"], ["selected_lam"]):
        want.add(("runs/transfer-6-9/receipt.json", json.dumps(path)))
    for field in ("mean_W", "mean_inf", "kept_from", "bc_agreement"):
        want.add(("runs/transfer-6-9/receipt.json", json.dumps(["points", 0, field])))
    assert got == want


def test_every_number_in_results_has_a_receipt():
    for e in _index_entries():
        assert _resolve(_read_runs(e["file"]), e["path"]) == e["value"], e


def test_every_cited_runs_file_exists():
    import re

    for rel in sorted(set(re.findall(r"runs/[\w./-]+", _doc_text()))):
        assert (PURSUIT05_DIR / rel).exists(), rel


def _is_cell_detail(path):
    return "cells" in path and path[-1] in ("W", "inf")


def _is_presence_exempt(entry):
    if _is_cell_detail(entry["path"]):
        return True
    if entry["path"] and entry["path"][-1] == "bc_agreement":
        return True
    return entry["file"] == "runs/transfer-6-9/receipt.json" and entry["path"] == [
        "selected_lam"
    ]


def test_rendered_floats_appear_in_prose():
    prose = _prose_text()
    for e in _index_entries():
        if isinstance(e["value"], float) and not _is_presence_exempt(e):
            assert f"{e['value']:.10g}" in prose, e


def _tables(prose):
    tables, cur = [], []
    for ln in prose.splitlines():
        if ln.startswith("|"):
            cur.append(ln)
        elif cur:
            tables.append(cur)
            cur = []
    if cur:
        tables.append(cur)
    return tables


def _row_cells(row):
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _sel_lam(idx, reg):
    return idx[(f"runs/{reg}/receipt.json", json.dumps(["selected_lam"]))]


def _point(idx, reg, lam, field):
    return idx[
        (
            f"runs/{reg}/receipt.json",
            json.dumps(["points", {"lam": lam}, field], sort_keys=True),
        )
    ]


def _arms(idx, reg, arm):
    key = json.dumps(["arms", reg, arm, "mean_W"])
    keyi = json.dumps(["arms", reg, arm, "mean_inf"])
    return idx[("runs/frontier.json", key)], idx[("runs/frontier.json", keyi)]


def _bound(idx, reg):
    return idx[("runs/frontier.json", json.dumps(["arms", reg, "bound"]))]


def _cell_val(idx, reg, cid, field):
    lam = _sel_lam(idx, reg)
    return idx[
        (
            f"runs/{reg}/receipt.json",
            json.dumps(["points", {"lam": lam}, "cells", cid, field], sort_keys=True),
        )
    ]


def test_tables_match_receipts_positionally():
    idx = _indexed()
    tables = _tables(_prose_text())
    assert len(tables) == 3
    heads = [_row_cells(t[0]) for t in tables]
    assert heads[0] == ["regime", "F", "A", "S", "H", "P"]
    assert heads[1] == ["regime", "F", "A", "S", "H", "P", "bound", "tail"]
    assert heads[2][0:4] == ["regime", "kept", "lam", "tied"]
    for ti, (table, ncols) in enumerate(zip(tables, (6, 8, 9))):
        assert set(table[1]) <= set("|-: "), table[1]
        seen = set()
        for row in table[2:]:
            cells = _row_cells(row)
            assert len(cells) == ncols, row
            raw_reg = cells[0]
            starred = raw_reg.endswith("*")
            reg = raw_reg.rstrip("*").strip()
            assert reg in REGIMES, row
            if ti < 2:
                assert starred == (reg.split("-")[1] == "0.005"), row
            else:
                assert not starred, row
            seen.add(reg)
        assert seen == set(REGIMES)
    for row in tables[0][2:]:
        cells = _row_cells(row)
        reg = cells[0].rstrip("*").strip()
        lam = _sel_lam(idx, reg)
        for pos, arm in enumerate(("F", "A", "S", "H"), start=1):
            assert cells[pos] == f"{_arms(idx, reg, arm)[0]:.10g}", (row, arm)
        assert cells[5] == f"{_point(idx, reg, lam, 'mean_W'):.10g}", row
    for row in tables[1][2:]:
        cells = _row_cells(row)
        reg = cells[0].rstrip("*").strip()
        lam = _sel_lam(idx, reg)
        for pos, arm in enumerate(("F", "A", "S", "H"), start=1):
            assert cells[pos] == f"{_arms(idx, reg, arm)[1]:.10g}", (row, arm)
        assert cells[5] == f"{_point(idx, reg, lam, 'mean_inf'):.10g}", row
        assert cells[6] == f"{_bound(idx, reg):.10g}", row
        n, p = reg.split("-")
        assert cells[7] == f"{_cell_val(idx, reg, f'{n}/{p}/4', 'tail'):.10g}", row
    for row in tables[2][2:]:
        cells = _row_cells(row)
        reg = cells[0]
        lam = _sel_lam(idx, reg)
        f = f"runs/{reg}/receipt.json"
        assert cells[1] == _point(idx, reg, lam, "kept_from"), row
        assert cells[2] == str(int(lam)), row
        tied = idx[(f, json.dumps(["selection_tied"]))]
        assert cells[3] == ("yes" if tied else "no"), row
        assert cells[4] == f"{idx[(f, json.dumps(['worker_s']))]:.10g}", row
        assert cells[5] == f"{idx[(f, json.dumps(['train_bound']))]:.10g}", row
        assert cells[6] == f"{idx[(f, json.dumps(['scratch', 'mean_W']))]:.10g}", row
        assert cells[7] == f"{idx[(f, json.dumps(['scratch', 'mean_inf']))]:.10g}", row
        n, p = reg.split("-")
        k4 = _cell_val(idx, reg, f"{n}/{p}/4", "keys")
        k5 = _cell_val(idx, reg, f"{n}/{p}/5", "keys")
        assert cells[8] == f"{k4}/{k5}", row


def test_ties_are_exact():
    idx = _indexed()
    for reg in REGIMES:
        lam = _sel_lam(idx, reg)
        pw, pinf = _point(idx, reg, lam, "mean_W"), _point(idx, reg, lam, "mean_inf")
        hw, hinf = _arms(idx, reg, "H")
        sw, sinf = _arms(idx, reg, "S")
        assert (pw, pinf) == (hw, hinf) == (sw, sinf), reg
    n = len(REGIMES)
    prose = _prose_text()
    assert (
        f"P, the learned policy, ties H bit-exactly in all {n} regimes "
        "on held-out test means."
    ) in prose
    assert f"P ties H bit-exactly in all {n} regimes," in prose


def test_d2_census_recomputes():
    idx = _indexed()
    beats_s = beats_a = near_h = 0
    beater = None
    for reg in CENSUS_REGIMES:
        lam = _sel_lam(idx, reg)
        pw, pinf = _point(idx, reg, lam, "mean_W"), _point(idx, reg, lam, "mean_inf")
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
    lam = _sel_lam(idx, beater)
    pw = _point(idx, beater, lam, "mean_W")
    aw, _ = _arms(idx, beater, "A")
    prose = _prose_text()
    assert D2_LINE in prose
    assert (
        f"The single beat over A is regime {beater}, where P holds "
        f"{pw:.10g} against A's {aw:.10g}."
    ) in prose
    assert f"so the {near_h}/6 near-H count follows directly." in prose


def test_lam_sweep_collapses_and_bc_won_everywhere():
    idx = _indexed()
    lams = set()
    for e in _index_entries():
        if len(e["path"]) > 1 and isinstance(e["path"][1], dict):
            lams.add(e["path"][1]["lam"])
    assert lams == {1000, 5000, 10000}
    kept = []
    for reg in REGIMES:
        means = [
            (_point(idx, reg, lam, "mean_W"), _point(idx, reg, lam, "mean_inf"))
            for lam in sorted(lams)
        ]
        assert means[0] == means[1] == means[2], reg
        for lam in sorted(lams):
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
    prose = _prose_text()
    triple = ", ".join(str(lam) for lam in sorted(lams))
    assert (
        f"all three nominal lams ({triple}) keep bit-identical test means "
        "per regime, so each regime contributes one frontier point."
    ) in prose
    assert (
        f"Keep-better kept the BC start on all {len(kept)} trained points "
        f"({len(kept) - 1} regime-lam points plus transfer); "
        "PPO fine-tuning never won selection."
    ) in prose
    assert "(agreement 1.0)" in prose


def test_tails_uniform_within_regime():
    idx = _indexed()
    for reg in REGIMES:
        n, p = reg.split("-")
        tails = {_cell_val(idx, reg, f"{n}/{p}/{seed}", "tail") for seed in ("4", "5")}
        assert len(tails) == 1, reg
    assert "(identical on both test seeds within each regime)" in _prose_text()


def test_eval_seeds_are_4_and_5():
    idx = _indexed()
    assert list(TEST_SEEDS) == [4, 5]
    for reg in REGIMES:
        assert idx[(f"runs/{reg}/receipt.json", json.dumps(["seeds_eval"]))] == [
            4,
            5,
        ], reg
    assert "Test-mean W per arm over seeds 4 and 5." in _prose_text()


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
    pufferlib, torch_v, numpy_v = next(iter(seen))
    assert (
        f"Package versions are pufferlib {pufferlib}, torch {torch_v}, "
        f"numpy {numpy_v}, identical in all {len(files)} receipts."
    ) in _prose_text()


def test_keys_and_final_rule():
    idx = _indexed()
    fths = set()
    stage_keys = {}
    for reg in REGIMES:
        n, p = reg.split("-")
        for seed in ("4", "5"):
            cid = f"{n}/{p}/{seed}"
            fths.add(_cell_val(idx, reg, cid, "fth"))
            stage_keys.setdefault(n, set()).add(_cell_val(idx, reg, cid, "keys"))
    assert fths == {0}

    def span(n):
        lo, hi = min(stage_keys[n]), max(stage_keys[n])
        return str(lo) if lo == hi else f"{lo} to {hi}"

    ntest = len(REGIMES) * len(TEST_SEEDS)
    assert (
        f"Decision tables hold {span('6')} keys per n = 6 cell, "
        f"{span('9')} per n = 9 cell, and {span('12')} per n = 12 cell. "
        f"The final accept rule refits to fth 0 on all {ntest} held-out cells."
    ) in _prose_text()


def test_a_infeasible_sentence():
    idx = _indexed()
    for reg in REGIMES:
        bound = _bound(idx, reg)
        for arm in ("F", "A", "S", "H"):
            _, inf = _arms(idx, reg, arm)
            if (reg, arm) == ("12-0.005", "A"):
                assert inf > bound
            else:
                assert inf <= bound, (reg, arm)
    _, ainf = _arms(idx, "12-0.005", "A")
    bound = _bound(idx, "12-0.005")
    assert (
        f"At 12-0.005, A reports infidelity {ainf:.10g} against a bound "
        f"of {bound:.10g}, so A is infeasible there; the row is descriptive."
    ) in _prose_text()
    assert "Every other arm in every row sits within its bound." in _prose_text()


def test_scratch_example():
    idx = _indexed()
    f = "runs/6-0.001/receipt.json"
    w = idx[(f, json.dumps(["scratch", "mean_W"]))]
    inf = idx[(f, json.dumps(["scratch", "mean_inf"]))]
    bound = _bound(idx, "6-0.001")
    assert inf > bound
    assert (
        f"(for example {w:.10g} at 6-0.001 with infidelity {inf:.10g} "
        f"against a bound of {bound:.10g})"
    ) in _prose_text()


def test_transfer_row_sentences():
    idx = _indexed()
    trained = idx[("runs/transfer-6-9/receipt.json", json.dumps(["trained_on"]))]
    stages = ", ".join(str(n) for n in trained["stages"])
    rates = ", ".join(str(p) for p in trained["rates"])
    seeds = ", ".join(str(s) for s in trained["seeds"])
    n12 = len([r for r in REGIMES if r.startswith("12-")]) * len(TEST_SEEDS)
    hvals = [
        f"{_arms(idx, f'12-{p}', 'H')[0]:.10g}" for p in ("0.001", "0.002", "0.005")
    ]
    lam = idx[("runs/transfer-6-9/receipt.json", json.dumps(["selected_lam"]))]
    kept = idx[
        ("runs/transfer-6-9/receipt.json", json.dumps(["points", 0, "kept_from"]))
    ]
    mw = idx[("runs/transfer-6-9/receipt.json", json.dumps(["points", 0, "mean_W"]))]
    mi = idx[("runs/transfer-6-9/receipt.json", json.dumps(["points", 0, "mean_inf"]))]
    prose = _prose_text()
    assert (
        f"One policy trained on n = {stages} (rates {rates}, seeds {seeds}) "
        f"and scored on the n = 12 test cells ties H exactly on all {n12} cells."
    ) in prose
    assert (
        "The n = 12 H values it ties are the table rows above: "
        f"{hvals[0]}, {hvals[1]}, and {hvals[2]}."
    ) in prose
    assert f"(selected lam {int(lam)}, kept from {kept})" in prose
    assert (
        f"The transfer receipt's own train-stage means are W {mw:.10g} "
        f"with infidelity {mi:.10g}, descriptive only."
    ) in prose


def test_split_caveat_counts():
    ntest = len(REGIMES) * len(TEST_SEEDS)
    assert ntest == 18
    assert (
        f"P ties H and S bit-exactly in all {ntest} test cells, "
        f"including all {SPLIT_ANALYSIS_CLEAN_CELLS} clean ones, "
        "so the 6/6 near-H count stands with or without the duplicated cells."
    ) in _prose_text()


def test_opening_sentence():
    assert OPENING in _prose_text()


def test_d1_history_optimum_equals_static_everywhere():
    reg = CellRegistry()
    cells = reg.all_cells()
    n = len(cells)
    assert n == 45
    solved = {}
    fallback = 0
    for cell in cells:
        pre = reg.pre(cell)
        finf = screen.run_F(pre, cell.p)["inf"]
        bound = finf * (1.0 + screen.INF_REL) + screen.INF_ABS
        s = exact.best_static(pre, cell.p, finf)
        h = dp.best_history(pre, cell.p, finf)
        fallback += h.fallback
        assert (h.result.W, h.result.inf) == (s.result.W, s.result.inf), cell.cell_id
        solved[cell.cell_id] = (s, h, bound)
    assert fallback == 0
    wins = 0
    for n_ in screen.SIZES:
        for p in screen.P_ERRS:
            if p > 0.002:
                continue
            sub = [c for c in cells if c.n == n_ and c.p == p and c.seed in TEST_SEEDS]
            mw_h = sum(solved[c.cell_id][1].result.W for c in sub) / len(sub)
            mw_s = sum(solved[c.cell_id][0].result.W for c in sub) / len(sub)
            mi_h = sum(solved[c.cell_id][1].result.inf for c in sub) / len(sub)
            mi_s = sum(solved[c.cell_id][0].result.inf for c in sub) / len(sub)
            mb = sum(solved[c.cell_id][2] for c in sub) / len(sub)
            if mw_h <= 0.9 * mw_s and mi_h <= mb and mi_s <= mb:
                wins += 1
    assert wins == 0
    prose = _prose_text()
    assert D1_LINE in prose
    assert (
        f"D1 is flat: H equals S bit-exactly in all {n} cells, "
        "so no regime clears the 10% bar."
    ) in prose
    assert (
        "H, the exact optimum over history-dependent abort plus a final accept rule, "
        f"equals S, the exact best static policy, bit-exactly in all {n} cells."
    ) in prose


def _load_policy(rel):
    weights = torch.load(PURSUIT05_DIR / rel, map_location="cpu", weights_only=True)
    policy = CultivationPolicy()
    policy.load_state_dict(weights)
    policy.eval()
    return policy


def test_regime_policies_reproduce_receipts_live():
    idx = _indexed()
    reg = CellRegistry()
    for regime in REGIMES:
        receipt = _read_runs(f"runs/{regime}/receipt.json")
        assert receipt["seeds_eval"] == list(TEST_SEEDS)
        policy = _load_policy(f"runs/{regime}/policy.pt")
        eval_cells = [reg.find(cid) for cid in receipt["tables"]]
        assert [c.seed for c in eval_cells] == list(TEST_SEEDS)
        scored = train.evaluate_policy(policy, eval_cells, reg)
        base = train.baselines_for_cells(eval_cells, reg)
        for cell in eval_cells:
            cid = cell.cell_id
            got = scored["cells"][cid]
            want_h = base[cid]["H"]
            want_s = base[cid]["S"]
            assert (got["W"], got["inf"]) == (want_h["W"], want_h["inf"]), cid
            assert (got["W"], got["inf"]) == (want_s["W"], want_s["inf"]), cid
            for field in ("W", "inf", "tail", "keys", "fth"):
                assert got[field] == _cell_val(idx, regime, cid, field), (cid, field)
        for arm in ("F", "A", "S", "H"):
            ws = [base[cid][arm]["W"] for cid in base]
            infs = [base[cid][arm]["inf"] for cid in base]
            live_w, live_i = sum(ws) / len(ws), sum(infs) / len(infs)
            want_w, want_i = _arms(idx, regime, arm)
            assert (live_w, live_i) == (want_w, want_i), (regime, arm)
        live_b = sum(base[cid]["bound"] for cid in base) / len(base)
        assert live_b == _bound(idx, regime), regime


def test_transfer_policy_ties_h_on_n12():
    reg = CellRegistry()
    policy = _load_policy("runs/transfer-6-9/policy.pt")
    cells = [c for c in reg.all_cells() if c.n == 12 and c.seed in TEST_SEEDS]
    assert len(cells) == 6
    scored = train.evaluate_policy(policy, cells, reg)
    base = train.baselines_for_cells(cells, reg)
    for cell in cells:
        got = scored["cells"][cell.cell_id]
        want = base[cell.cell_id]["H"]
        assert (got["W"], got["inf"]) == (want["W"], want["inf"]), cell.cell_id
