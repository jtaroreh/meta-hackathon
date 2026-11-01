# pursuit 05: learned abort policies for cultivation, scored exactly

This program trains an adaptive abort policy for magic-state cultivation
on modeled ring-plus-chord cells and scores it exactly against the
certified screen 05 search arms. The cells are models, not device maps.
The weight-3 tail stays censored and disclosed. No hardware claim, no
threshold claim. This harness prints train and test seeds separately;
later policy numbers cover held-out cells only.

## Setup

Run every command from `pursuit/05` with Python 3.12:

```sh
cd pursuit/05
uv venv -p 3.12 .venv
uv pip install -r requirements.lock
```

## Commands

Reproduce the certified screen record on all 45 cells:

```sh
.venv/bin/python -m pursuit05 reproduce
```

Reproduce one cell:

```sh
.venv/bin/python -m pursuit05 reproduce --cell 12/0.005/1
```

Score the baselines F, G, A, and exact-best static S on all cells:

```sh
.venv/bin/python -m pursuit05 baselines
```

Score the test seeds only:

```sh
.venv/bin/python -m pursuit05 baselines --seeds 4,5
```

Smoke the abort env on one cell:

```sh
.venv/bin/python -m pursuit05 env-smoke --cell 12/0.002/1 --agents 4096 --steps 200
```

The env masks abort on all-zero prefixes and reject on all-zero
finals, matching the exact scorer.

Score the exact static optimum S and the exact history-dependent
optimum H on all cells:

```sh
.venv/bin/python -m pursuit05 optimum
```

Train one pooled policy for a regime (BC from H, then PPO):

```sh
.venv/bin/python -m pursuit05 train --stage 9 --rate 0.002
```

Sweep nominal lam per regime and write the frontier:

```sh
.venv/bin/python -m pursuit05 sweep
```

Score P against F, A, S, and H on held-out cells:

```sh
.venv/bin/python -m pursuit05 eval --all
```

Run the checks:

```sh
.venv/bin/python -m pytest tests -q
.venv/bin/ruff check .
```

## Data shape

`pre` from `precompute` is the frozen world. `cw1` and `cw2` hold
cumulative detector weights per checkpoint, `fw1` and `fw2` final
weights, `nt2` the logical flag for pairs, `spent` the volume at each
abort point, `Vf` the full volume. A policy maps a prefix
`(k, cw[0..k])` to abort or continue, plus a final accept rule on `fw`.

`eval_exact` scores any decider with the screen's binomial accounting.
`best_static` enumerates every static policy and returns the lowest-W
policy within the F-anchored infidelity bound; its `inference_cost_s`
is the enumeration wall time. `joint_win` judges every arm against the
screen's F/G/A infidelity bar. Train seeds are 1, 2, 3 and test seeds
are 4, 5. Reported policy numbers cover held-out cells only:
`eval` refuses train seeds, and receipts hold test-seed scores only.
`train.log` also records exact train-seed W as selection evidence.

## Training

`train` distills the H decision tables of a regime's train cells into
the policy with behavior cloning (three BC seeds, best kept on exact
train W), then fine-tunes with PPO in PufferLib, and keeps the better
checkpoint on exact train-seed W, preferring checkpoints within the
F-anchored bound. When no candidate is feasible, the lowest-W
candidate wins anyway. The receipt records `kept_from`, BC or
finetune, for each reported policy. `sweep` repeats this per nominal
lam in {1000, 5000, 10000} with at most two concurrent trainings and
writes `runs/frontier.json` and `runs/frontier.png`, the learned
volume-versus-infidelity frontier on test seeds with F, S, H, and A
as points. P per regime is the lam with the lowest exact train-seed
W within the bound; ties keep the first lam and the receipt says so.
A PPO-from-scratch ablation per regime is descriptive only. Stage
transfer trains one policy on n = 6, 9 and scores it on n = 12 test
cells.

PuffeRL clamps step rewards to [-1, 1], so the env gets lam / 10000:
effective penalties {0.1, 0.5, 1.0} against the pinned accept bonus
1.0. Raw lam values would collapse to one operating point under the
clamp. Receipts record both the nominal lam and the mapping.

Every reported P score refits a scalar final threshold per eval cell
from the policy's accept votes; `policy.pt` plus that refit, not the
weights alone, reproduces receipt W. The D2 census counts a beat when
P's test-mean W is at least 10% below the other arm with both means
within the F-anchored bound, and counts H-within-2% when P's test-mean
W is at most 1.02 times H's with P within the bound, over the six
p <= 0.002 regimes.

Split caveat (program root ruling: keep the split, disclosed): the
imported screen's `drop_one` maps n = 9 test seed 4 to the same
dropped check as train seed 1, and n = 6 test seeds 4 and 5 to the
same dropped check as each other. An independent SHA-256 check over
each cell's frozen world (`cw1/cw2/fw1/fw2/nt2/spent` plus `L1/Vf/T`)
confirms bit-identical precompute for the three n = 9 (1, 4) pairs
and the three n = 6 (4, 5) pairs; all n = 12 cells are distinct. So
half of each n = 9 test mean is a train cell and each n = 6 test mean
repeats one cell. The D2 headline is robust to this: P ties H and S
bit-exactly in all 18 test cells, including all 15 clean ones, so the
6/6 near-H count stands with or without the duplicated cells.

One `decision_table` forward per cell costs milliseconds, and the
annealing arm costs tens of evaluations near 1 ms each. Both are
small, so no speed win is claimed.

## Decider protocol

A decider answers `decide(k, prefix)` with True to abort or False to
continue, and carries `fth` in {0, 1, 2} for the final accept rule.
It must be pure and deterministic in `(k, prefix)`: rows that share a
prefix share one call. The all-zero prefix always continues and is
never presented, and neither is a prefix no live trajectory reaches.
A policy that conditions on the cell closes over it per cell and
reuses one decider object per cell.

## Environment

`PURSUIT05_SCREEN_SRC` overrides the screen source directory, which
defaults to `screens/05/src` under the repo root. `PURSUIT05_RECORD`
overrides the screen record file below.

`reproduce` reads the screen record from
`overnight-data/cfc1d43d7de946e6988f0158b5508e28/attempts/05-3ca8e6aa423c4275a9919edb9ccb7344/work/results.json`
under the repo root when present, else from that path under
`/Users/joeltaroreh/projects/challenges/meta-hackathon`.
