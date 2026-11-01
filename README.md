# Learned abort policies for cultivation, scored exactly

This repo trains an adaptive abort policy for magic-state cultivation with PufferLib and scores it exactly against the certified screen 05 search arms plus two new exact baselines. The learned policy reaches the exact history optimum on held-out cells, and the optimum itself ties the exact static best, so history-dependent abort buys nothing within the pinned decider class. See [pursuit/05/RESULTS.md](pursuit/05/RESULTS.md) for the numbers and [pursuit/05/media/submission.mp4](pursuit/05/media/submission.mp4) for the 3-minute video.

## Judge path

You need Python 3.12, `uv`, and a C compiler: PufferLib builds its extension from source during install. Clone and run the offline demo; it uses recorded transcripts and committed checkpoints, so it makes no model call.

```sh
git clone https://github.com/jtaroreh/meta-hackathon.git
cd meta-hackathon/pursuit/05
uv venv -p 3.12 .venv
uv pip install -r requirements.lock
.venv/bin/python -m pursuit05 demo --offline "cut wasted cultivation volume at p = 0.002 without raising infidelity"
```

You should see the provider/model line, the token counts, the `transcript: fixture` label, the `policy checkpoint:` line naming the run's policy file, the arm table with F, A, S, H, L, and P on the two test cells, the explanation with its next experiment, and finally a witness path with its replay command. Fresh clone to table runs under 10 minutes (77 s on the build machine). Then verify the witness without any model call:

```sh
.venv/bin/python -m pursuit05 replay witnesses/<id>.json
```

You should see `replay matches witness on 6/6 arms`, using the witness id the demo printed.

For the live call instead of the fixture, drop `--offline` on a machine with Muse Code 1.4.14 or later where `muse usage` prints `api_key`. The model is `muse-spark-1.3-contributor` throughout, as proposer and explainer, and a spend guard caps each run at 200,000 model tokens.

## Layout

- `pursuit/05/RESULTS.md`: the held-out table, the D1 and D2 outcomes in plain words, and the receipt index behind every number.
- `pursuit/05/README.md`: every command, the data shape, and the training setup.
- `pursuit/05/BUILD_LOG.md`: the dated build log.
- `pursuit/05/media/`: the submission video, its script, and review captures.
- `NEW_IN_HACKATHON.md`: what this build added, what it imports, and what it leaves out.
- `screens/05/src/run05.py`: the certified screen, imported and never edited.

Built with `muse-spark-1.3-contributor`, PufferLib 3.0, torch 2.15.0, numpy 1.26.4, Python 3.12. Timing ran on a 16GB MacBook Air; that names the build machine only and carries no hardware claim. These cells are modeled ring-plus-chord views, not device maps, and no error-correction threshold claim follows from them.
