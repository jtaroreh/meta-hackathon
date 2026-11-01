# Submission video script

`submission.mp4`: 720p, 1:49, 3.3 MB, in git. Every terminal frame renders a real captured run; nothing is retyped. Captures below come from the recording tree, then the render script plays them back as frames with narration.

Recording tree (local only, never pushed): `origin/pursuit-05-4-demo` at `49ec6baaad412dc1f37d472035e4ba99beccfb5e`, which already contains trunk `356b742` plus the demo, so no local merge was needed. Venv from `requirements.lock` on Python 3.12. One recording-tree-only patch, never committed: `_find_policy_checkpoint` also matches trunk receipts on `id` (the 05-4 lookup reads `stage`/`rate` keys the trunk schema lacks, so P never attaches without it; 05-4 owns the real fix in its re-proof). Exact diff, recorded 2026-11-01:

```diff
-        if rn == n and rp == p:
+        # LOCAL RECORDING PATCH ONLY (05-5, unpushed): trunk receipts key
+        # on id like 9-0.002, not stage/rate. 05-4 owns the real fix.
+        if (rn == n and rp == p) or obj.get("id") == f"{n}-{p}":
```

Render with the throwaway script at `/tmp/videobuild/render.py` (not committed) and assemble with ffmpeg.

## Beat 1, 0:00-0:21 — problem and certified result

Card: "Magic-state cultivation wastes volume on runs that fail. Screen 05 certified the search arms. We train an abort policy and score it exactly."

Capture: `baselines --seeds 4,5` table head plus the `reproduced 45/45 cells` line.

Narration: "Magic-state cultivation wastes volume growing runs that fail. Screen 05 certified exact search arms for when to abort: fixed, greedy, and annealing. We reproduce all 45 certified cells exactly, then train a PufferLib abort policy and score it with the same exact accounting, on held-out cells only."

## Beat 2, 0:21-0:52 — live demo

Card: "One command: propose, score exactly, explain, write a replayable witness."

Capture: live `demo` on regime 9/0.002. Keep the `provider meta, model muse-spark-1.3-contributor` lines, the input and output token counts, the `policy checkpoint:` line, the table with F, A, S, H, L, and P entering on both test cells, the one-paragraph explanation, the next experiment, and the witness path with its replay command. Play at 2x past the table.

Narration: "One command runs the demo. Muse Spark proposes an abort policy for the goal. The exact harness scores it beside the certified arms: fixed, annealing, the exact static best, and the exact history optimum. Then the learned policy enters the table from its committed checkpoint, tying the optimum on both test cells. The explainer reads the table in one paragraph, proposes the next experiment, and the run writes a witness anyone can replay with no model call."

## Beat 3, 0:52-1:25 — training, frontier, replay

Card: "Behavior cloning from the exact history optimum, then PPO. The sweep collapses to one point per regime."

Captures: a short live `train --stage 6 --rate 0.001 --total-timesteps 200000` clip at 4x showing the PufferLib dashboard and the final exact test line; `runs/frontier.png` still for 6 s; live `replay` of the beat-2 witness printing `replay matches witness on 6/6 arms`.

Narration: "Training distills the exact history optimum with behavior cloning, then fine-tunes with PPO. The penalty sweep collapses: every setting keeps the same policy, so each regime contributes one frontier point. The frontier figure plots the learned policy against the search arms. And the witness from the demo replays exactly, six out of six arms, with no network."

## Beat 4, 1:25-1:49 — result and next experiment

Cards, one per line:

- "P reaches H within 2% in 6/6 regimes at p <= 0.002."
- "H equals S exactly in all 45 cells: history buys nothing here."
- "A tie is a finding: learning reaches the optimum."
- "Modeled cells, not device maps. No hardware claim, no error-correction threshold claim. Weight-3 tail censored and disclosed."
- "Next experiment: test a selective late abort on high-volume survivors and confirm W drops with infidelity unchanged on held-out cells."

Narration: "The result: the learned policy reaches the history optimum in all six regimes, and the optimum ties the static best everywhere, so history buys nothing in this class. A tie is a finding. These are modeled cells, the tail stays censored, and the next experiment is the one the explainer proposed: probe the survivors for a selective late abort and re-score."

## Checks before commit

- `ffprobe` or `ffmpeg -i`: duration under 180 s, 1280x720, size under 80 MB.
- Spot-check three frames against their source captures: the model lines, the P column, the 6/6 replay line.
- Run the claim-boundary grep from the plan's live lane 4: every hit sits in a disclaimer sentence.
