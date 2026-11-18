# Zoom versus distance: retraining plan (2026-11-14)

Digi is getting a continuous **1x to 2x zoom on the main camera only**. The Director should decide, for each look, whether to zoom in and step back or to stay at 1x and step closer, and say why in one line. The rules are in [annotation-guide.md § Zoom versus distance](annotation-guide.md#zoom-versus-distance-shot-v4). The prompt is **v11 / shot-v4** (`--shot-format v4`), and the check is `framing.zoom_fit`.

Nothing here has been trained. The numbers below come from the label files, the tokenizer, and one base-model bench (see "Base model on v11").

## What changed in the prompt (v11)

- `zoom_or_lens`: one amount from 1x to 2x, then under 10 words on why: `"2x: <reason>"`.
- `distance_and_framing`: the distance for the chosen zoom.
- `why_each_choice`: **exactly 2** reasons (height, tilt) instead of 3. The distance or lens reason moves into `zoom_or_lens`.
- The zoom rules (`framing.ZOOM_RULES`) are added to the reasoning rules. The setups' repeated "use the 1x main lens" sentence is dropped in v11 only, because the zoom rules state the lens once.
- v10 (shot-v3) and all older prompts are byte-identical. `tests/test_zoom.py` pins their hashes.

## Phone-time cost (estimate)

The cost is in the compositions call only (36.9 tok/s decode, 622 tok/s prefill on the iPhone 17 Pro; `phone_projection.py`).

| | tokens | seconds |
|---|---|---|
| prompt: v11 vs v10 compositions prompt (Qwen3-VL tokenizer) | +223 | +0.36 prefill |
| output per look: zoom field with reason (~14) vs v10 zoom field (~8) | +6 | |
| output per look: the dropped third reason | −13 | |
| output per analysis (3 looks) | about −23 | about −0.6 decode |
| **net per analysis** | | **about −0.3 s** |

Starting point: the v10 trim run projected **59.9 s full / 36.2 s on-site** (budgets 60 / 30). v11 should land at about **59.6 s / 35.9 s**. On-site still misses its 30 s soft budget, as v10 already did.

**Risk:** if the trained model keeps three reasons *and* adds the zoom reason, output grows by about 42 tokens: about +1.5 s in total, and the full analysis goes over 60 s. The acceptance gate below checks this.

## Base model on v11 (bench `zoom-base-v4-20261114`, 2026-11-15)

This is the base Qwen3-VL-2B with no adapter, run on the 14 `portrait_v1` cases (decomposed, greedy, keys, 1024 px). It is compared with the same model on v10 (`blind-base-trim-4B-20261114`). The base model matters because it is the on-device fallback.

| measure | base v10 | trim adapter v10 | **base v11** |
|---|---|---|---|
| runs schema-valid | 14/14 | 14/14 | 14/14 |
| looks with a zoom amount within 1–2x | 42/42 | 42/42 | 42/42 |
| zoom reason matches the amount | 0/42 | 3/42 | 8/42 |
| zoomed 1.5x+ but kept the 1x distance | – | – | **35/36** |
| `why_each_choice` with exactly 2 reasons | – | – | 42/42 |
| setup contradictions (wrong tilt) | 1 | 4 | 3 |
| compositions tokens, median | 1730.5 | 982.5 | 1688.5 |
| projected iPhone full / on-site s, median | 87.7 / 56.2 | 59.9 / 36.2 | 85.5 / 55.4 |

**The format works from the prompt alone.** Every look states an amount within range in the `"<amount>x: <reason>"` form, every look has 2 reasons, and the base model's output got 42 tokens shorter (−2.2 s projected). The base model is still far over budget either way; only the adapter gets under 60 s.

**The judgement does not.**
- **It zooms in but stays put.** 35 of 36 zoomed looks keep the setup's 1x distance ("2x … about 1.2 m away"), so the photo would crop the subject. `zoom_fit` now reports this as `distance_not_scaled`. It flags 2 of the 132 draft-label looks.
- **It defaults to 2x:** 27 looks at 2x, 9 at 1.5x, 6 at 1x. That includes 9 full-body looks at 2x, which lose the low-camera effect.
- **One zoom line per scene.** 9 of 14 cases repeat the same zoom line on all three looks.
- **The reasons are long and often not about zoom:** 15 words median against a limit of 10, for example "to emphasize the height of the castle and the scale of the scene", and contradictions such as "1x: zooming in to …".

So training is needed for the trade-off itself, and the relabelled data must show it: zoomed looks with doubled distances, and 1x looks where the place matters. The acceptance gate below now includes "zoomed 1.5x+ but kept the 1x distance ≤ 10% of zoomed looks".

## Relabel, or a new batch?

**Relabel first. Labelling a new batch isn't needed to get the field.** The 44 draft labels (132 looks, 35 train / 9 valid examples, all `ai-draft`, none approved) already state a lens on every look:

| measure on the current drafts | looks |
|---|---|
| amount stated | 132 / 132 |
| every amount within 1x to 2x | 117 / 132 (7 say 0.5x, 5 say "1x or 0.5x", 3 say 3x) |
| zoomed in (> 1x) | 40 / 132 |
| `zoom_or_lens` alone gives a reason | 53 / 132 |
| reason matches the amount, counting the third `why_each_choice` reason | 91 / 132 |
| close-up at 1x (leans 2x) | 7 |

So the relabel pass is a **field edit on the existing examples**, with no new photos:

1. Back up `data/train_v1/labels` to `labels.before-zoom`, as earlier passes did.
2. For each look, rewrite `zoom_or_lens` as `"<amount>x: <reason>"`. Move the lens or distance reason out of `why_each_choice`, leaving 2 reasons. Double the distance in `distance_and_framing` when the look zooms to 2x. Fix the 15 out-of-range looks. Revisit the 7 close-ups at 1x. Add "room to step back N m" to `needs_on_site_check` where needed.
3. The tool is `photo-ai train-data zoom-relabel` (`training/zoom_relabel.py`):
   ```
   photo-ai train-data zoom-relabel --step backup                      # labels -> labels.before-zoom, never overwritten
   photo-ai train-data zoom-relabel --step worklist --out work.json    # each draft's looks + zoom_fit, for the drafters
   photo-ai train-data zoom-relabel --step apply --file edits.json --source "ai-draft:<who>"
   photo-ai train-data zoom-relabel --step report                      # zoom_fit totals, v4 readiness, failing looks
   ```
   An edit may change only `zoom_or_lens`, `why_each_choice`, `distance_and_framing` and `needs_on_site_check`. The tool applies an example's edit whole or not at all: each look needs `"<amount>x: <3-9 words>"` within 1–2x, exactly 2 reasons, 1–2 on-site checks, and a distance scaled to the zoom. It skips approved and rejected labels, keeps status `draft`, and records a `zoom-relabelled` history entry. The edits were drafted by Claude Code subagents that looked at each target photo, as in the earlier passes.
4. Check: `train-data export --shot-format v4 --include-unapproved` should skip 0 labels for zoom. Before the pass it kept 29 of 44, and even those still carried 3 reasons.

**Done 2026-11-15.** All 44 drafts were relabelled and still unreviewed; the 3 rejected labels were left alone. The backup is `data/train_v1/labels.before-zoom`.

| measure | before | after |
|---|---|---|
| exportable as v4 (0 skipped for zoom) | 29 / 44 | 44 / 44 |
| looks with an amount within 1–2x | 117 / 132 | 132 / 132 |
| zoom reason matches the amount | 91 / 132 | 132 / 132 |
| amounts (1x / 1.5x / 2x) | 85 / 0 / 39, plus 7 at 0.5x and 1 at 3x | 77 / 1 / 54 |
| scenes mixing 1x and 2x | – | 39 / 44 |
| the same zoom line on all 3 looks | – | 0 / 44 |
| zoomed but kept the 1x distance | 2 | 0 |
| lean mismatches | 7 | 3 (each says why: arm's length, a tight hall, sky kept in view) |
| looks with a setup contradiction | 14 | 14 (camera fields untouched) |
| compositions tokens per label, median | 1028 | 1005 |

The five all-1x scenes are a narrow sidewalk, a forest path, a snowy lane pinned at 4–5 m, a parking deck, and a round library made of scenery looks. Many 2x looks add "Room to step back N m", because most target photos don't show the space behind the camera. Reviewers should check those first.

**When a new batch is worth it.** One field edit can't teach *contrast*: when to pick 2x over 1x *in the same place*. Of the 40 zoomed looks, 26 are half body or close-up at 2x, so the data mostly says "portraits zoom". The earlier v3 runs also copied `setup_choice` across looks (19/42 on 2B). If the eval below shows the model always writing one amount, or 2x only for close-ups, add **10–15 contrast examples**. These are targets with visible room behind the camera and a background shape worth enlarging, plus a few tight interiors, each labelled with at least one 1x look and one 2x look (`train-data assemble --reserve --batch 3`). Do this after #2, so the review queue doesn't grow before the first human pass.

## How this interacts with the human review (#2 / #4)

- **Relabel before reviewers approve anything.** Editing an approved label sends it back to draft, so zooming after review means reviewing twice. If v11 is adopted, run the relabel pass first and review the v4 labels once. Add one checklist line for reviewers: *zoom amount within 1–2x, the reason fits the look, and the distance matches the zoom.*
- **The relabel commits the labels to v11.** Shot-v4 labels have 2 reasons; v10 asks for exactly 3. Exporting relabelled labels with `--shot-format v3` would train a v10 prompt on 2-reason answers. Keep `labels.before-zoom` for any further v3 work. Otherwise, treat v11 as the format for the #4 pilot release.
- **No quality claims until #2 is done.** Every adapter trained before that (including the run below) is `UNREVIEWED`. It is useful for checking format, length and phone time, not for checking whether the zoom choices are good.
- The `zoom_fit` check is keyword matching. It finds missing, out-of-range or reversed reasons. Whether 2x is right for *that* photo stays a reviewer judgment.

## Run

- **Base-model check: done** (see "Base model on v11" above). It took 14 minutes.
- **Training:** `configs/lora_bootstrap_r16_zoom.json` is a copy of the v10 trim config. Only `run_name` and `data_dir` (`sft-UNREVIEWED-zoom`) change: 2B, r16, 120 iters, seed 0. That makes it directly comparable with `reason-trim-r16-v3-20261113`. It takes about 1 h on the Mac. **Not started; ask first.** Stay on 2B: 4B projected 61 s for v10 and trains for 3 h.
  ```
  photo-ai train-data export --shot-format v4 --include-unapproved   # then move sft-UNREVIEWED-smoke to sft-UNREVIEWED-zoom
  photo-ai lora train --config configs/lora_bootstrap_r16_zoom.json
  ```
- **Eval:** bench the adapter (unfused; fusing into 4-bit loses most of the adapter's effect) with `--shot-format v4` on `portrait_v1`, then `python -m photo_ai.training.bootstrap_eval <trim bench> <zoom bench>`.

**Acceptance gate (format, not quality):**

| measure | gate |
|---|---|
| looks with an amount within 1–2x | ≥ 90% |
| zoom reason matches the amount | ≥ 75% |
| amounts used | both 1x and 2x appear; zoomed share between 25% and 75% |
| zoomed 1.5x+ but kept the 1x distance | ≤ 10% of zoomed looks |
| one zoom line repeated on all 3 looks | ≤ 3 of 14 cases |
| setup contradictions | no more than trim |
| compositions tokens, median | ≤ trim's |
| projected iPhone full / on-site | ≤ 60 s / ≤ 36.2 s |

## Phone side (not in this PR)

DirectorKit currently shows `zoomOrLens` as text. Once v11 ships, the guidance can read the leading `"<amount>x"` and turn it into a cue ("zoom to 2x, then step back to about 2.4 m"). This needs coordinating with the session building the zoom control.
