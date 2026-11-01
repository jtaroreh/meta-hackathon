# Results: learned abort against certified search on held-out cells

Learning reaches but does not beat the exact history optimum: on held-out cells at p <= 0.002, P reaches H within 2% in 6/6 regimes while H equals S exactly in all of them, so history-dependent abort buys nothing within the pinned decider class on these modeled ring-plus-chord cells.

## Headline

The exact answer to "does history help" is no. H, the exact optimum over history-dependent abort plus a final accept rule, equals S, the exact best static policy, bit-exactly in all 45 cells. P, the learned policy, ties H bit-exactly in all 9 regimes on held-out test means. A tie is a finding, not a failure: learning reaches the history optimum, and the optimum itself leaves no headroom over the static best.

Arms: F is the fixed screen policy, A the annealing search, S the exact-best static policy (new), H the exact history-dependent optimum (new), P the learned policy. W is expected cultivation volume (lower is better) and inf is infidelity against the F-anchored bound. Every number below comes from a committed receipt under `runs/`; the receipt index at the end of this file names the file and field for each one. Values render with `%.10g`, the same format `eval` prints.

## Held-out table

Test-mean W per arm over seeds 4 and 5. Rows at p = 0.005 are descriptive only and carry their censored tail mass; no evaluative claim uses them.

| regime | F | A | S | H | P |
|---|---|---|---|---|---|
| 6-0.001 | 7.193415752 | 2.983164857 | 2.983164857 | 2.983164857 | 2.983164857 |
| 6-0.002 | 14.93972502 | 6.204779778 | 6.204779778 | 6.204779778 | 6.204779778 |
| 6-0.005 * | 41.924046 | 17.82404843 | 17.82404843 | 17.82404843 | 17.82404843 |
| 9-0.001 | 47.15883938 | 21.33461812 | 21.33461812 | 21.33461812 | 21.33461812 |
| 9-0.002 | 104.2793531 | 47.58679317 | 47.58679317 | 47.58679317 | 47.58679317 |
| 9-0.005 * | 357.7886586 | 179.5328516 | 179.5328516 | 179.5328516 | 179.5328516 |
| 12-0.001 | 430.622248 | 256.8323163 | 209.0586983 | 209.0586983 | 209.0586983 |
| 12-0.002 | 1235.852886 | 718.0503593 | 687.522406 | 687.522406 | 687.522406 |
| 12-0.005 * | 10635.78127 | 1741.196306 | 8668.840357 | 8668.840357 | 8668.840357 |

Test-mean infidelity per arm, with the F-anchored bound and the censored weight-3 tail mass per regime (identical on both test seeds within each regime).

| regime | F | A | S | H | P | bound | tail |
|---|---|---|---|---|---|---|---|
| 6-0.001 | 0.006985945535 | 0.006985945535 | 0.006985945535 | 0.006985945535 | 0.006985945535 | 0.007685540089 | 8.967673132e-05 |
| 6-0.002 | 0.01393962661 | 0.01393962661 | 0.01393962661 | 0.01393962661 | 0.01393962661 | 0.01533458928 | 0.0006753316981 |
| 6-0.005 * | 0.03454726562 | 0.03454726562 | 0.03454726562 | 0.03454726562 | 0.03454726562 | 0.03800299218 | 0.008812992619 |
| 9-0.001 | 0.0001116532794 | 0.0001116532794 | 0.0001116532794 | 0.0001116532794 | 0.0001116532794 | 0.0001238186074 | 0.001101561283 |
| 9-0.002 | 0.000446666099 | 0.000446666099 | 0.000446666099 | 0.000446666099 | 0.000446666099 | 0.0004923327088 | 0.007628904258 |
| 9-0.005 * | 0.002771757924 | 0.002771757924 | 0.002771757924 | 0.002771757924 | 0.002771757924 | 0.003049933717 | 0.07800934541 |
| 12-0.001 | 0.0284187199 | 0.0284187199 | 0.0284187199 | 0.0284187199 | 0.0284187199 | 0.03126159189 | 0.03074723321 |
| 12-0.002 | 0.05714764884 | 0.05714764884 | 0.05714764884 | 0.05714764884 | 0.05714764884 | 0.06286341373 | 0.152982503 |
| 12-0.005 * | 0.1386571279 | 0.7997724343 | 0.1386571279 | 0.1386571279 | 0.1386571279 | 0.1525238407 | 0.6531490226 |

At 12-0.005, A reports infidelity 0.7997724343 against a bound of 0.1525238407, so A is infeasible there; the row is descriptive. Every other arm in every row sits within its bound.

## D2: the learned policy against the search arms

`P beats S in 0/6, beats A in 1/6, and reaches H within 2% in 6/6 at p <= 0.002`

A beat means P's test-mean W is at least 10% below the other arm with both means within the F-anchored bound. Within 2% means P's W is at most 1.02 times H's W with P within the bound. The single beat over A is regime 12-0.001, where P holds 209.0586983 against A's 256.8323163. P ties H bit-exactly in all 9 regimes, so the 6/6 near-H count follows directly. The census is descriptive over exact means, with no significance claim.

## D1: the history optimum against the static best

`on test seeds, H's W is at least 10% below S's W, both within the F-anchored bound, in 0/6 (stage, rate) cells at p <= 0.002`

D1 is flat: H equals S bit-exactly in all 45 cells, so no regime clears the 10% bar. The equality is exact, on all seeds, with no significance claim. Reproduce the full 45-cell check with `python -m pursuit05 optimum`.

## Transfer row

One policy trained on n = 6, 9 (rates 0.001, 0.002, 0.005, seeds 1, 2, 3) and scored on the n = 12 test cells ties H exactly on all 6 cells. The n = 12 H values it ties are the table rows above: 209.0586983, 687.522406, and 8668.840357. Training record and sidecar live at `runs/transfer-6-9/receipt.json` (selected lam 5000, kept from bc) with weights at `runs/transfer-6-9/policy.pt`. The transfer receipt's own train-stage means are W 45.91104266 with infidelity 0.009800485845, descriptive only. Reproduce the tie with `python -m pursuit05 eval --stages 12 --policy runs/transfer-6-9/policy.pt`; `test_transfer_policy_ties_h_on_n12` checks it per cell.

## Frontier and training detail

The lam sweep collapses: all three nominal lams (1000, 5000, 10000) keep bit-identical test means per regime, so each regime contributes one frontier point. Keep-better kept the BC start on all 28 trained points (27 regime-lam points plus transfer); PPO fine-tuning never won selection. BC reproduction of the H tables is exact (agreement 1.0) on every kept table. One regime trains in 60.1 s to 224.5 s of worker wall on the build machine. The frontier figure is `runs/frontier.png` with data in `runs/frontier.json`.

| regime | kept | lam | tied | worker_s | train bound | scratch W | scratch inf | keys s4/s5 |
|---|---|---|---|---|---|---|---|---|
| 6-0.001 | bc | 1000 | yes | 68.66017217 | 0.002583849279 | 1.795320485 | 0.0257439137 | 43/43 |
| 6-0.002 | bc | 1000 | yes | 60.11140975 | 0.005197784081 | 6.204779778 | 0.01393962661 | 43/43 |
| 6-0.005 | bc | 1000 | yes | 74.94929917 | 0.01320656463 | 10.73455571 | 0.12303041 | 43/43 |
| 9-0.001 | bc | 1000 | yes | 185.380211 | 0.004126721643 | 10.04561097 | 0.0690591339 | 58/43 |
| 9-0.002 | bc | 1000 | yes | 159.578843 | 0.008426659485 | 47.58679317 | 0.000446666099 | 58/43 |
| 9-0.005 | bc | 1000 | yes | 90.48409533 | 0.02220623094 | 89.14526512 | 0.2860537407 | 58/43 |
| 12-0.001 | bc | 1000 | yes | 224.4786446 | 0.03031202126 | 162.5021873 | 0.1079061911 | 181/181 |
| 12-0.002 | bc | 1000 | yes | 201.210907 | 0.05931197776 | 474.1817055 | 0.2504595362 | 181/181 |
| 12-0.005 | bc | 1000 | yes | 206.7248309 | 0.1352899619 | 5119.99107 | 0.4776913984 | 181/181 |

Decision tables hold 43 keys per n = 6 cell, 43 to 58 per n = 9 cell, and 181 per n = 12 cell. The final accept rule refits to fth 0 on all 18 held-out cells. Package versions are pufferlib 3.0, torch 2.15.0, numpy 1.26.4, identical in all 10 receipts.

The PPO-from-scratch ablation is descriptive only: it trains without the BC start and reports test means outside the selection rule, so its W reads below P in regimes where its infidelity breaks the bound (for example 1.795320485 at 6-0.001 with infidelity 0.0257439137 against a bound of 0.007685540089). Nothing in the census uses it.

## Split caveat

Program root ruling: keep the split, disclosed. The imported screen's `drop_one` maps n = 9 test seed 4 to the same dropped check as train seed 1, and n = 6 test seeds 4 and 5 to the same dropped check as each other. An independent SHA-256 check over each cell's frozen world confirms bit-identical precompute for the three n = 9 (1, 4) pairs and the three n = 6 (4, 5) pairs; all n = 12 cells are distinct. So half of each n = 9 test mean is a train cell and each n = 6 test mean repeats one cell. The D2 headline is robust to this: P ties H and S bit-exactly in all 18 test cells, including all 15 clean ones, so the 6/6 near-H count stands with or without the duplicated cells.

## Claim boundary

These cells are modeled ring-plus-chord views, not device maps. The weight-3 tail stays censored: evaluative claims use p <= 0.002 only, and the p = 0.005 rows print as descriptive with their tail mass beside them. No hardware claim and no error-correction threshold claim follow from these numbers. Policy numbers cover held-out cells only. D1 and D2 are descriptive censuses over exact means, with no significance claim. No speed win is claimed.

## Receipt index

Each line below is one JSON object with the receipt file, the field path, and the exact value. `tests/test_results_doc.py` checks every line against its file. A `{"lam": N}` step selects the sweep point with that nominal lam.

```json-index
{"file": "runs/frontier.json", "path": ["arms", "6-0.001", "F", "mean_W"], "value": 7.19341575234543}
{"file": "runs/frontier.json", "path": ["arms", "6-0.001", "F", "mean_inf"], "value": 0.006985945535093383}
{"file": "runs/frontier.json", "path": ["arms", "6-0.001", "A", "mean_W"], "value": 2.9831648572152005}
{"file": "runs/frontier.json", "path": ["arms", "6-0.001", "A", "mean_inf"], "value": 0.006985945535093383}
{"file": "runs/frontier.json", "path": ["arms", "6-0.001", "S", "mean_W"], "value": 2.9831648572152005}
{"file": "runs/frontier.json", "path": ["arms", "6-0.001", "S", "mean_inf"], "value": 0.006985945535093383}
{"file": "runs/frontier.json", "path": ["arms", "6-0.001", "H", "mean_W"], "value": 2.9831648572152005}
{"file": "runs/frontier.json", "path": ["arms", "6-0.001", "H", "mean_inf"], "value": 0.006985945535093383}
{"file": "runs/frontier.json", "path": ["arms", "6-0.001", "bound"], "value": 0.007685540088602723}
{"file": "runs/frontier.json", "path": ["arms", "6-0.002", "F", "mean_W"], "value": 14.939725020517344}
{"file": "runs/frontier.json", "path": ["arms", "6-0.002", "F", "mean_inf"], "value": 0.01393962661431721}
{"file": "runs/frontier.json", "path": ["arms", "6-0.002", "A", "mean_W"], "value": 6.204779777682063}
{"file": "runs/frontier.json", "path": ["arms", "6-0.002", "A", "mean_inf"], "value": 0.01393962661431721}
{"file": "runs/frontier.json", "path": ["arms", "6-0.002", "S", "mean_W"], "value": 6.204779777682063}
{"file": "runs/frontier.json", "path": ["arms", "6-0.002", "S", "mean_inf"], "value": 0.01393962661431721}
{"file": "runs/frontier.json", "path": ["arms", "6-0.002", "H", "mean_W"], "value": 6.204779777682063}
{"file": "runs/frontier.json", "path": ["arms", "6-0.002", "H", "mean_inf"], "value": 0.01393962661431721}
{"file": "runs/frontier.json", "path": ["arms", "6-0.002", "bound"], "value": 0.015334589275748932}
{"file": "runs/frontier.json", "path": ["arms", "6-0.005", "F", "mean_W"], "value": 41.92404599835575}
{"file": "runs/frontier.json", "path": ["arms", "6-0.005", "F", "mean_inf"], "value": 0.03454726561550982}
{"file": "runs/frontier.json", "path": ["arms", "6-0.005", "A", "mean_W"], "value": 17.82404842783997}
{"file": "runs/frontier.json", "path": ["arms", "6-0.005", "A", "mean_inf"], "value": 0.03454726561550982}
{"file": "runs/frontier.json", "path": ["arms", "6-0.005", "S", "mean_W"], "value": 17.82404842783997}
{"file": "runs/frontier.json", "path": ["arms", "6-0.005", "S", "mean_inf"], "value": 0.03454726561550982}
{"file": "runs/frontier.json", "path": ["arms", "6-0.005", "H", "mean_W"], "value": 17.82404842783997}
{"file": "runs/frontier.json", "path": ["arms", "6-0.005", "H", "mean_inf"], "value": 0.03454726561550982}
{"file": "runs/frontier.json", "path": ["arms", "6-0.005", "bound"], "value": 0.0380029921770608}
{"file": "runs/frontier.json", "path": ["arms", "9-0.001", "F", "mean_W"], "value": 47.15883938006752}
{"file": "runs/frontier.json", "path": ["arms", "9-0.001", "F", "mean_inf"], "value": 0.00011165327944984764}
{"file": "runs/frontier.json", "path": ["arms", "9-0.001", "A", "mean_W"], "value": 21.334618116025695}
{"file": "runs/frontier.json", "path": ["arms", "9-0.001", "A", "mean_inf"], "value": 0.00011165327944984764}
{"file": "runs/frontier.json", "path": ["arms", "9-0.001", "S", "mean_W"], "value": 21.334618116025695}
{"file": "runs/frontier.json", "path": ["arms", "9-0.001", "S", "mean_inf"], "value": 0.00011165327944984764}
{"file": "runs/frontier.json", "path": ["arms", "9-0.001", "H", "mean_W"], "value": 21.334618116025695}
{"file": "runs/frontier.json", "path": ["arms", "9-0.001", "H", "mean_inf"], "value": 0.00011165327944984764}
{"file": "runs/frontier.json", "path": ["arms", "9-0.001", "bound"], "value": 0.00012381860739483241}
{"file": "runs/frontier.json", "path": ["arms", "9-0.002", "F", "mean_W"], "value": 104.27935310001332}
{"file": "runs/frontier.json", "path": ["arms", "9-0.002", "F", "mean_inf"], "value": 0.00044666609895223613}
{"file": "runs/frontier.json", "path": ["arms", "9-0.002", "A", "mean_W"], "value": 47.58679316514615}
{"file": "runs/frontier.json", "path": ["arms", "9-0.002", "A", "mean_inf"], "value": 0.00044666609895223613}
{"file": "runs/frontier.json", "path": ["arms", "9-0.002", "S", "mean_W"], "value": 47.58679316514615}
{"file": "runs/frontier.json", "path": ["arms", "9-0.002", "S", "mean_inf"], "value": 0.00044666609895223613}
{"file": "runs/frontier.json", "path": ["arms", "9-0.002", "H", "mean_W"], "value": 47.58679316514615}
{"file": "runs/frontier.json", "path": ["arms", "9-0.002", "H", "mean_inf"], "value": 0.00044666609895223613}
{"file": "runs/frontier.json", "path": ["arms", "9-0.002", "bound"], "value": 0.0004923327088474598}
{"file": "runs/frontier.json", "path": ["arms", "9-0.005", "F", "mean_W"], "value": 357.78865855083325}
{"file": "runs/frontier.json", "path": ["arms", "9-0.005", "F", "mean_inf"], "value": 0.0027717579241786005}
{"file": "runs/frontier.json", "path": ["arms", "9-0.005", "A", "mean_W"], "value": 179.53285160203293}
{"file": "runs/frontier.json", "path": ["arms", "9-0.005", "A", "mean_inf"], "value": 0.0027717579241786005}
{"file": "runs/frontier.json", "path": ["arms", "9-0.005", "S", "mean_W"], "value": 179.53285160203293}
{"file": "runs/frontier.json", "path": ["arms", "9-0.005", "S", "mean_inf"], "value": 0.0027717579241786005}
{"file": "runs/frontier.json", "path": ["arms", "9-0.005", "H", "mean_W"], "value": 179.53285160203293}
{"file": "runs/frontier.json", "path": ["arms", "9-0.005", "H", "mean_inf"], "value": 0.0027717579241786005}
{"file": "runs/frontier.json", "path": ["arms", "9-0.005", "bound"], "value": 0.0030499337165964613}
{"file": "runs/frontier.json", "path": ["arms", "12-0.001", "F", "mean_W"], "value": 430.62224797691897}
{"file": "runs/frontier.json", "path": ["arms", "12-0.001", "F", "mean_inf"], "value": 0.02841871990008263}
{"file": "runs/frontier.json", "path": ["arms", "12-0.001", "A", "mean_W"], "value": 256.8323162823772}
{"file": "runs/frontier.json", "path": ["arms", "12-0.001", "A", "mean_inf"], "value": 0.02841871990008263}
{"file": "runs/frontier.json", "path": ["arms", "12-0.001", "S", "mean_W"], "value": 209.05869827732658}
{"file": "runs/frontier.json", "path": ["arms", "12-0.001", "S", "mean_inf"], "value": 0.02841871990008263}
{"file": "runs/frontier.json", "path": ["arms", "12-0.001", "H", "mean_W"], "value": 209.05869827732658}
{"file": "runs/frontier.json", "path": ["arms", "12-0.001", "H", "mean_inf"], "value": 0.02841871990008263}
{"file": "runs/frontier.json", "path": ["arms", "12-0.001", "bound"], "value": 0.031261591890090895}
{"file": "runs/frontier.json", "path": ["arms", "12-0.002", "F", "mean_W"], "value": 1235.8528856219555}
{"file": "runs/frontier.json", "path": ["arms", "12-0.002", "F", "mean_inf"], "value": 0.0571476488418205}
{"file": "runs/frontier.json", "path": ["arms", "12-0.002", "A", "mean_W"], "value": 718.0503593000105}
{"file": "runs/frontier.json", "path": ["arms", "12-0.002", "A", "mean_inf"], "value": 0.0571476488418205}
{"file": "runs/frontier.json", "path": ["arms", "12-0.002", "S", "mean_W"], "value": 687.5224059699183}
{"file": "runs/frontier.json", "path": ["arms", "12-0.002", "S", "mean_inf"], "value": 0.0571476488418205}
{"file": "runs/frontier.json", "path": ["arms", "12-0.002", "H", "mean_W"], "value": 687.5224059699183}
{"file": "runs/frontier.json", "path": ["arms", "12-0.002", "H", "mean_inf"], "value": 0.0571476488418205}
{"file": "runs/frontier.json", "path": ["arms", "12-0.002", "bound"], "value": 0.06286341372600256}
{"file": "runs/frontier.json", "path": ["arms", "12-0.005", "F", "mean_W"], "value": 10635.78126915238}
{"file": "runs/frontier.json", "path": ["arms", "12-0.005", "F", "mean_inf"], "value": 0.1386571278920128}
{"file": "runs/frontier.json", "path": ["arms", "12-0.005", "A", "mean_W"], "value": 1741.1963064491276}
{"file": "runs/frontier.json", "path": ["arms", "12-0.005", "A", "mean_inf"], "value": 0.7997724342908106}
{"file": "runs/frontier.json", "path": ["arms", "12-0.005", "S", "mean_W"], "value": 8668.84035676414}
{"file": "runs/frontier.json", "path": ["arms", "12-0.005", "S", "mean_inf"], "value": 0.1386571278920128}
{"file": "runs/frontier.json", "path": ["arms", "12-0.005", "H", "mean_W"], "value": 8668.84035676414}
{"file": "runs/frontier.json", "path": ["arms", "12-0.005", "H", "mean_inf"], "value": 0.1386571278920128}
{"file": "runs/frontier.json", "path": ["arms", "12-0.005", "bound"], "value": 0.15252384068121405}
{"file": "runs/6-0.001/receipt.json", "path": ["seeds_eval"], "value": [4, 5]}
{"file": "runs/6-0.001/receipt.json", "path": ["selected_lam"], "value": 1000}
{"file": "runs/6-0.001/receipt.json", "path": ["selection_tied"], "value": true}
{"file": "runs/6-0.001/receipt.json", "path": ["train_bound"], "value": 0.0025838492794191393}
{"file": "runs/6-0.001/receipt.json", "path": ["worker_s"], "value": 68.66017216600449}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 1000}, "mean_W"], "value": 2.9831648572152005}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 1000}, "mean_inf"], "value": 0.006985945535093383}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 1000}, "kept_from"], "value": "bc"}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 1000}, "bc_agreement"], "value": 1.0}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 5000}, "mean_W"], "value": 2.9831648572152005}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 5000}, "mean_inf"], "value": 0.006985945535093383}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 5000}, "kept_from"], "value": "bc"}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 5000}, "bc_agreement"], "value": 1.0}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 10000}, "mean_W"], "value": 2.9831648572152005}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 10000}, "mean_inf"], "value": 0.006985945535093383}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 10000}, "kept_from"], "value": "bc"}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 10000}, "bc_agreement"], "value": 1.0}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.001/4", "W"], "value": 2.9831648572152005}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.001/4", "inf"], "value": 0.006985945535093383}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.001/4", "tail"], "value": 8.967673131580903e-05}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.001/4", "keys"], "value": 43}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.001/4", "fth"], "value": 0}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.001/5", "W"], "value": 2.9831648572152005}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.001/5", "inf"], "value": 0.006985945535093383}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.001/5", "tail"], "value": 8.967673131580903e-05}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.001/5", "keys"], "value": 43}
{"file": "runs/6-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.001/5", "fth"], "value": 0}
{"file": "runs/6-0.001/receipt.json", "path": ["scratch", "mean_W"], "value": 1.7953204846817954}
{"file": "runs/6-0.001/receipt.json", "path": ["scratch", "mean_inf"], "value": 0.02574391369956877}
{"file": "runs/6-0.002/receipt.json", "path": ["seeds_eval"], "value": [4, 5]}
{"file": "runs/6-0.002/receipt.json", "path": ["selected_lam"], "value": 1000}
{"file": "runs/6-0.002/receipt.json", "path": ["selection_tied"], "value": true}
{"file": "runs/6-0.002/receipt.json", "path": ["train_bound"], "value": 0.005197784081350531}
{"file": "runs/6-0.002/receipt.json", "path": ["worker_s"], "value": 60.11140975000308}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 1000}, "mean_W"], "value": 6.204779777682063}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 1000}, "mean_inf"], "value": 0.01393962661431721}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 1000}, "kept_from"], "value": "bc"}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 1000}, "bc_agreement"], "value": 1.0}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 5000}, "mean_W"], "value": 6.204779777682063}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 5000}, "mean_inf"], "value": 0.01393962661431721}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 5000}, "kept_from"], "value": "bc"}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 5000}, "bc_agreement"], "value": 1.0}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 10000}, "mean_W"], "value": 6.204779777682063}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 10000}, "mean_inf"], "value": 0.01393962661431721}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 10000}, "kept_from"], "value": "bc"}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 10000}, "bc_agreement"], "value": 1.0}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.002/4", "W"], "value": 6.204779777682063}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.002/4", "inf"], "value": 0.01393962661431721}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.002/4", "tail"], "value": 0.0006753316980763202}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.002/4", "keys"], "value": 43}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.002/4", "fth"], "value": 0}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.002/5", "W"], "value": 6.204779777682063}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.002/5", "inf"], "value": 0.01393962661431721}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.002/5", "tail"], "value": 0.0006753316980763202}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.002/5", "keys"], "value": 43}
{"file": "runs/6-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.002/5", "fth"], "value": 0}
{"file": "runs/6-0.002/receipt.json", "path": ["scratch", "mean_W"], "value": 6.204779777682063}
{"file": "runs/6-0.002/receipt.json", "path": ["scratch", "mean_inf"], "value": 0.01393962661431721}
{"file": "runs/6-0.005/receipt.json", "path": ["seeds_eval"], "value": [4, 5]}
{"file": "runs/6-0.005/receipt.json", "path": ["selected_lam"], "value": 1000}
{"file": "runs/6-0.005/receipt.json", "path": ["selection_tied"], "value": true}
{"file": "runs/6-0.005/receipt.json", "path": ["train_bound"], "value": 0.013206564630457046}
{"file": "runs/6-0.005/receipt.json", "path": ["worker_s"], "value": 74.94929916699039}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 1000}, "mean_W"], "value": 17.82404842783997}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 1000}, "mean_inf"], "value": 0.03454726561550982}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 1000}, "kept_from"], "value": "bc"}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 1000}, "bc_agreement"], "value": 1.0}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 5000}, "mean_W"], "value": 17.82404842783997}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 5000}, "mean_inf"], "value": 0.03454726561550982}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 5000}, "kept_from"], "value": "bc"}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 5000}, "bc_agreement"], "value": 1.0}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 10000}, "mean_W"], "value": 17.82404842783997}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 10000}, "mean_inf"], "value": 0.03454726561550982}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 10000}, "kept_from"], "value": "bc"}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 10000}, "bc_agreement"], "value": 1.0}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.005/4", "W"], "value": 17.82404842783997}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.005/4", "inf"], "value": 0.03454726561550982}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.005/4", "tail"], "value": 0.008812992618991794}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.005/4", "keys"], "value": 43}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.005/4", "fth"], "value": 0}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.005/5", "W"], "value": 17.82404842783997}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.005/5", "inf"], "value": 0.03454726561550982}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.005/5", "tail"], "value": 0.008812992618991794}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.005/5", "keys"], "value": 43}
{"file": "runs/6-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "6/0.005/5", "fth"], "value": 0}
{"file": "runs/6-0.005/receipt.json", "path": ["scratch", "mean_W"], "value": 10.734555707691229}
{"file": "runs/6-0.005/receipt.json", "path": ["scratch", "mean_inf"], "value": 0.12303041002780599}
{"file": "runs/9-0.001/receipt.json", "path": ["seeds_eval"], "value": [4, 5]}
{"file": "runs/9-0.001/receipt.json", "path": ["selected_lam"], "value": 1000}
{"file": "runs/9-0.001/receipt.json", "path": ["selection_tied"], "value": true}
{"file": "runs/9-0.001/receipt.json", "path": ["train_bound"], "value": 0.004126721643298605}
{"file": "runs/9-0.001/receipt.json", "path": ["worker_s"], "value": 185.38021095699514}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 1000}, "mean_W"], "value": 21.334618116025695}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 1000}, "mean_inf"], "value": 0.00011165327944984764}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 1000}, "kept_from"], "value": "bc"}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 1000}, "bc_agreement"], "value": 1.0}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 5000}, "mean_W"], "value": 21.334618116025695}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 5000}, "mean_inf"], "value": 0.00011165327944984764}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 5000}, "kept_from"], "value": "bc"}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 5000}, "bc_agreement"], "value": 1.0}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 10000}, "mean_W"], "value": 21.334618116025695}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 10000}, "mean_inf"], "value": 0.00011165327944984764}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 10000}, "kept_from"], "value": "bc"}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 10000}, "bc_agreement"], "value": 1.0}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.001/4", "W"], "value": 16.071625560741438}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.001/4", "inf"], "value": 0.00013818807396867133}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.001/4", "tail"], "value": 0.0011015612828059497}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.001/4", "keys"], "value": 58}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.001/4", "fth"], "value": 0}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.001/5", "W"], "value": 26.59761067130995}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.001/5", "inf"], "value": 8.511848493102397e-05}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.001/5", "tail"], "value": 0.0011015612828059497}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.001/5", "keys"], "value": 43}
{"file": "runs/9-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.001/5", "fth"], "value": 0}
{"file": "runs/9-0.001/receipt.json", "path": ["scratch", "mean_W"], "value": 10.04561096576279}
{"file": "runs/9-0.001/receipt.json", "path": ["scratch", "mean_inf"], "value": 0.06905913389552792}
{"file": "runs/9-0.002/receipt.json", "path": ["seeds_eval"], "value": [4, 5]}
{"file": "runs/9-0.002/receipt.json", "path": ["selected_lam"], "value": 1000}
{"file": "runs/9-0.002/receipt.json", "path": ["selection_tied"], "value": true}
{"file": "runs/9-0.002/receipt.json", "path": ["train_bound"], "value": 0.008426659485189699}
{"file": "runs/9-0.002/receipt.json", "path": ["worker_s"], "value": 159.5788429999884}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 1000}, "mean_W"], "value": 47.58679316514615}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 1000}, "mean_inf"], "value": 0.00044666609895223613}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 1000}, "kept_from"], "value": "bc"}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 1000}, "bc_agreement"], "value": 1.0}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 5000}, "mean_W"], "value": 47.58679316514615}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 5000}, "mean_inf"], "value": 0.00044666609895223613}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 5000}, "kept_from"], "value": "bc"}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 5000}, "bc_agreement"], "value": 1.0}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 10000}, "mean_W"], "value": 47.58679316514615}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 10000}, "mean_inf"], "value": 0.00044666609895223613}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 10000}, "kept_from"], "value": "bc"}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 10000}, "bc_agreement"], "value": 1.0}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.002/4", "W"], "value": 35.836046432304755}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.002/4", "inf"], "value": 0.0005527982406595122}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.002/4", "tail"], "value": 0.007628904258026377}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.002/4", "keys"], "value": 58}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.002/4", "fth"], "value": 0}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.002/5", "W"], "value": 59.33753989798754}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.002/5", "inf"], "value": 0.00034053395724496007}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.002/5", "tail"], "value": 0.007628904258026377}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.002/5", "keys"], "value": 43}
{"file": "runs/9-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.002/5", "fth"], "value": 0}
{"file": "runs/9-0.002/receipt.json", "path": ["scratch", "mean_W"], "value": 47.58679316514615}
{"file": "runs/9-0.002/receipt.json", "path": ["scratch", "mean_inf"], "value": 0.00044666609895223613}
{"file": "runs/9-0.005/receipt.json", "path": ["seeds_eval"], "value": [4, 5]}
{"file": "runs/9-0.005/receipt.json", "path": ["selected_lam"], "value": 1000}
{"file": "runs/9-0.005/receipt.json", "path": ["selection_tied"], "value": true}
{"file": "runs/9-0.005/receipt.json", "path": ["train_bound"], "value": 0.02220623094301685}
{"file": "runs/9-0.005/receipt.json", "path": ["worker_s"], "value": 90.48409533300583}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 1000}, "mean_W"], "value": 179.53285160203293}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 1000}, "mean_inf"], "value": 0.0027717579241786005}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 1000}, "kept_from"], "value": "bc"}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 1000}, "bc_agreement"], "value": 1.0}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 5000}, "mean_W"], "value": 179.53285160203293}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 5000}, "mean_inf"], "value": 0.0027717579241786005}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 5000}, "kept_from"], "value": "bc"}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 5000}, "bc_agreement"], "value": 1.0}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 10000}, "mean_W"], "value": 179.53285160203293}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 10000}, "mean_inf"], "value": 0.0027717579241786005}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 10000}, "kept_from"], "value": "bc"}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 10000}, "bc_agreement"], "value": 1.0}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.005/4", "W"], "value": 135.00427688634676}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.005/4", "inf"], "value": 0.0034295086856035197}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.005/4", "tail"], "value": 0.07800934541342805}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.005/4", "keys"], "value": 58}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.005/4", "fth"], "value": 0}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.005/5", "W"], "value": 224.0614263177191}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.005/5", "inf"], "value": 0.0021140071627536814}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.005/5", "tail"], "value": 0.07800934541342805}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.005/5", "keys"], "value": 43}
{"file": "runs/9-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "9/0.005/5", "fth"], "value": 0}
{"file": "runs/9-0.005/receipt.json", "path": ["scratch", "mean_W"], "value": 89.14526512410414}
{"file": "runs/9-0.005/receipt.json", "path": ["scratch", "mean_inf"], "value": 0.28605374070531303}
{"file": "runs/12-0.001/receipt.json", "path": ["seeds_eval"], "value": [4, 5]}
{"file": "runs/12-0.001/receipt.json", "path": ["selected_lam"], "value": 1000}
{"file": "runs/12-0.001/receipt.json", "path": ["selection_tied"], "value": true}
{"file": "runs/12-0.001/receipt.json", "path": ["train_bound"], "value": 0.030312021257619115}
{"file": "runs/12-0.001/receipt.json", "path": ["worker_s"], "value": 224.4786445830032}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 1000}, "mean_W"], "value": 209.05869827732658}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 1000}, "mean_inf"], "value": 0.02841871990008263}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 1000}, "kept_from"], "value": "bc"}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 1000}, "bc_agreement"], "value": 1.0}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 5000}, "mean_W"], "value": 209.05869827732658}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 5000}, "mean_inf"], "value": 0.02841871990008263}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 5000}, "kept_from"], "value": "bc"}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 5000}, "bc_agreement"], "value": 1.0}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 10000}, "mean_W"], "value": 209.05869827732658}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 10000}, "mean_inf"], "value": 0.02841871990008263}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 10000}, "kept_from"], "value": "bc"}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 10000}, "bc_agreement"], "value": 1.0}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.001/4", "W"], "value": 208.93506238242207}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.001/4", "inf"], "value": 0.028388699643831096}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.001/4", "tail"], "value": 0.030747233210408897}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.001/4", "keys"], "value": 181}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.001/4", "fth"], "value": 0}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.001/5", "W"], "value": 209.1823341722311}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.001/5", "inf"], "value": 0.028448740156334158}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.001/5", "tail"], "value": 0.030747233210408897}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.001/5", "keys"], "value": 181}
{"file": "runs/12-0.001/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.001/5", "fth"], "value": 0}
{"file": "runs/12-0.001/receipt.json", "path": ["scratch", "mean_W"], "value": 162.50218730233308}
{"file": "runs/12-0.001/receipt.json", "path": ["scratch", "mean_inf"], "value": 0.10790619112800443}
{"file": "runs/12-0.002/receipt.json", "path": ["seeds_eval"], "value": [4, 5]}
{"file": "runs/12-0.002/receipt.json", "path": ["selected_lam"], "value": 1000}
{"file": "runs/12-0.002/receipt.json", "path": ["selection_tied"], "value": true}
{"file": "runs/12-0.002/receipt.json", "path": ["train_bound"], "value": 0.05931197776249388}
{"file": "runs/12-0.002/receipt.json", "path": ["worker_s"], "value": 201.2109070430015}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 1000}, "mean_W"], "value": 687.5224059699183}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 1000}, "mean_inf"], "value": 0.0571476488418205}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 1000}, "kept_from"], "value": "bc"}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 1000}, "bc_agreement"], "value": 1.0}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 5000}, "mean_W"], "value": 687.5224059699183}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 5000}, "mean_inf"], "value": 0.0571476488418205}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 5000}, "kept_from"], "value": "bc"}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 5000}, "bc_agreement"], "value": 1.0}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 10000}, "mean_W"], "value": 687.5224059699183}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 10000}, "mean_inf"], "value": 0.0571476488418205}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 10000}, "kept_from"], "value": "bc"}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 10000}, "bc_agreement"], "value": 1.0}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.002/4", "W"], "value": 687.3374802937533}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.002/4", "inf"], "value": 0.05703601211622601}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.002/4", "tail"], "value": 0.15298250295806298}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.002/4", "keys"], "value": 181}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.002/4", "fth"], "value": 0}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.002/5", "W"], "value": 687.7073316460833}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.002/5", "inf"], "value": 0.05725928556741499}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.002/5", "tail"], "value": 0.15298250295806298}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.002/5", "keys"], "value": 181}
{"file": "runs/12-0.002/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.002/5", "fth"], "value": 0}
{"file": "runs/12-0.002/receipt.json", "path": ["scratch", "mean_W"], "value": 474.18170551986015}
{"file": "runs/12-0.002/receipt.json", "path": ["scratch", "mean_inf"], "value": 0.25045953621588607}
{"file": "runs/12-0.005/receipt.json", "path": ["seeds_eval"], "value": [4, 5]}
{"file": "runs/12-0.005/receipt.json", "path": ["selected_lam"], "value": 1000}
{"file": "runs/12-0.005/receipt.json", "path": ["selection_tied"], "value": true}
{"file": "runs/12-0.005/receipt.json", "path": ["train_bound"], "value": 0.13528996188889414}
{"file": "runs/12-0.005/receipt.json", "path": ["worker_s"], "value": 206.72483091699542}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 1000}, "mean_W"], "value": 8668.84035676414}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 1000}, "mean_inf"], "value": 0.1386571278920128}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 1000}, "kept_from"], "value": "bc"}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 1000}, "bc_agreement"], "value": 1.0}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 5000}, "mean_W"], "value": 8668.84035676414}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 5000}, "mean_inf"], "value": 0.1386571278920128}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 5000}, "kept_from"], "value": "bc"}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 5000}, "bc_agreement"], "value": 1.0}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 10000}, "mean_W"], "value": 8668.84035676414}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 10000}, "mean_inf"], "value": 0.1386571278920128}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 10000}, "kept_from"], "value": "bc"}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 10000}, "bc_agreement"], "value": 1.0}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.005/4", "W"], "value": 8674.597776843271}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.005/4", "inf"], "value": 0.13811731505744812}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.005/4", "tail"], "value": 0.6531490226433037}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.005/4", "keys"], "value": 181}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.005/4", "fth"], "value": 0}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.005/5", "W"], "value": 8663.082936685008}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.005/5", "inf"], "value": 0.13919694072657743}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.005/5", "tail"], "value": 0.6531490226433037}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.005/5", "keys"], "value": 181}
{"file": "runs/12-0.005/receipt.json", "path": ["points", {"lam": 1000}, "cells", "12/0.005/5", "fth"], "value": 0}
{"file": "runs/12-0.005/receipt.json", "path": ["scratch", "mean_W"], "value": 5119.991069847648}
{"file": "runs/12-0.005/receipt.json", "path": ["scratch", "mean_inf"], "value": 0.4776913984430376}
{"file": "runs/6-0.001/receipt.json", "path": ["versions", "pufferlib"], "value": "3.0"}
{"file": "runs/6-0.001/receipt.json", "path": ["versions", "torch"], "value": "2.15.0"}
{"file": "runs/6-0.001/receipt.json", "path": ["versions", "numpy"], "value": "1.26.4"}
{"file": "runs/transfer-6-9/receipt.json", "path": ["trained_on"], "value": {"stages": [6, 9], "rates": [0.001, 0.002, 0.005], "seeds": [1, 2, 3]}}
{"file": "runs/transfer-6-9/receipt.json", "path": ["seeds_eval"], "value": [4, 5]}
{"file": "runs/transfer-6-9/receipt.json", "path": ["selected_lam"], "value": 5000.0}
{"file": "runs/transfer-6-9/receipt.json", "path": ["points", 0, "mean_W"], "value": 45.911042657657}
{"file": "runs/transfer-6-9/receipt.json", "path": ["points", 0, "mean_inf"], "value": 0.009800485844583515}
{"file": "runs/transfer-6-9/receipt.json", "path": ["points", 0, "kept_from"], "value": "bc"}
{"file": "runs/transfer-6-9/receipt.json", "path": ["points", 0, "bc_agreement"], "value": 1.0}
```

## Reproduce

```sh
cd pursuit/05
.venv/bin/python -m pursuit05 eval --all
.venv/bin/python -m pursuit05 eval --stages 12 --policy runs/transfer-6-9/policy.pt
.venv/bin/python -m pursuit05 optimum
.venv/bin/python -m pytest tests/test_results_doc.py -q
```
