# Hackathon pursuit plan — one path to demo

Status: proposal, 2026-10-29. No scaffold built. Official Rules acceptance still open.

## What counts

- Build window Oct 26–Nov 4. Only that work may appear in demo. Showing older work risks disqualification.
- Submit with public repo, working demo video link, all members added. Video is 3 minutes.
- Must use Meta models via Meta Model API or open weights. Dev-time build help alone is risky. Keep one visible runtime call so tooling credit is airtight. User notes this repo is built throughout with Muse Spark 1.3 — recorded as supporting evidence, not the sole proof.
- Judging: impact 30, creative Meta-tool use 25, demo including video 25, technical depth 20.
- Indie track assumed. Frontier theme. Startup track only if you say so.
- You keep ownership but grant organizers a broad reuse license. Nothing shared is confidential. Do not submit private code.
- Avoid anti-project shapes. A plain wrapper or simple analyzer will score poorly.

## Demo to build

Pick one path now. Do not wait for all 24 screens.

Recommended: path 18 phase-polynomial core. It has an exact decoder, a known failure mode, and a clear win condition. Fallback: path 15 ZX spider-fusion.

Demo loop, all new in `pursuit/<id>/`:

1. User states a small circuit goal in plain language.
2. Muse Spark via Meta Model API proposes an optimization or inflation choice.
3. Local verifier checks it: exact decode, unchanged-support resynthesis, CNOT and depth numbers.
4. UI shows proposed versus baseline plus one checkable witness.

This scores on every axis. Frontier fit, Meta-model use is real, verification gives depth, witness makes the video concrete.

## 3-minute video beats

- 0:00–0:30 problem and why it matters.
- 0:30–1:30 live run with visible Meta API call.
- 1:30–2:30 verifier output and witness.
- 2:30–3:00 result and next experiment.

Record the live run, not slides. Keep one command reproducible from the repo.

## Submission checklist

- [ ] Public repo with `pursuit/<id>/` all dated Oct 26–Nov 4.
- [ ] `NEW_IN_HACKATHON.md` plus dated build log. Old frozen copies stay out of the demo.
- [ ] Spend guard for Meta API calls. Claim the $150 credit. Spend-limit emails do not stop billing.
- [ ] README with run command, model versions, hardware, and video link.
- [ ] Video link works without login. Under 3 minutes.
- [ ] All members added to submission. One track only.
- [ ] Official Rules accepted. No pre-window code in demo path.

## Timeline after screens

- Finish screens and `results/verdicts.md` first. No pursuit scaffold until then.
- Then: minimal API loop plus local verifier, witness, README plus build log plus spend guard, video, submit.
- Note: Nov 4 9pm ET is fixed. If screens run long, pursuit scope must shrink to fit. Deadline does not move.

## Sequence with screens

No pause, no pilot shortcut. Finish all 24 screens first with full evidence rules. Pursuit starts only after `results/verdicts.md` picks a winner. Graduate that winner's witness into `pursuit/` without reusing pre-window code in the demo.

## Next action

Run the 24 screens. Pursuit choice waits for `results/verdicts.md`.
