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

Score the exact static optimum S and the exact history-dependent
optimum H on all cells:

```sh
.venv/bin/python -m pursuit05 optimum
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
are 4, 5. The registry holds out `n = 12` for stage transfer in a
later step.

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
