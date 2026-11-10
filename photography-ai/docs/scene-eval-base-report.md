# Scene Director held-out evaluation: base model, first run (issue #21)

**Status:** automated results are measured. Human scores are not in yet; the blind review pack is ready. No adapter exists yet (#5), so there is no A/B comparison.

| | |
|---|---|
| model | `mlx-community/Qwen3-VL-2B-Instruct-4bit`, HF commit `9c4f5209e57b31f4b9dfba735de3fb983739c9cc`, no adapter |
| prompts | Scene Director prompt version `2026-11-10.5` from #19 (PR #23), unchanged; prompts.py sha256 `effecabbc40a…` |
| settings | greedy (temperature 0, seed 0), max_side 1024, `keys` JSON format, 1 JSON retry, max_tokens 1600; one call for the scene reading plus one per look |
| fixtures | `scene_eval_v1` v1.0.0, manifest sha256 `091b4fae58b4…`: 20 held-out and 6 dev fixtures |
| criteria | `scene-eval-criteria-v1`, sha256 `eac8a26bb0c2…`, committed in `1c55dcc` before the first run |
| code | `1c55dcc` (only docs, the README and tests were uncommitted during the run) |
| machine | M3 Pro (18 GB), mlx-vlm 0.7.12; model load 2.1 s with weights cached; `HF_HUB_OFFLINE=1` |
| runs | `runs/scene-eval/base-heldout-v1/` and `runs/scene-eval/base-dev-v1/` (git-ignored); reports are copied to [`scene-eval-runs/`](scene-eval-runs/) |

To rerun:

```bash
cd photography-ai
uv run photo-ai scene-eval fetch            # verifies every image's sha256
HF_HUB_OFFLINE=1 uv run photo-ai scene-eval run --split heldout --model qwen3-vl-2b-4bit --eval-id <new id>
```

Decoding is greedy, so a rerun with the same weights and mlx-vlm version should reproduce the text. That was not re-verified in this session.

## Measured: automated checks, held-out split

| automated measure | xhs_aligned (10) | ordinary (10) |
|---|---|---|
| schema-valid runs (3 shot-v2 looks) | 10/10 | 10/10 |
| runs flagged: invented scene detail | 0 | 1 (subway: "train") |
| runs flagged: unsafe direction | 1 (tiled façade: subject placed "on the balcony", 2 looks) | 0 |
| runs flagged: emotion inference | 0 | 0 |
| pose, head and gaze filled on all 3 looks | 10/10 | 10/10 |
| gaze names a target (of 3) | 3.0 | 3.0 |
| look distinctness, fields (0–1) | 0.60 | 0.56 |
| distinct titles (of 3) | 2.0 | 1.8 |
| scene recall (annotated objects named) | 0.82 | 0.73 |
| evidence grounded rate | 0.89 | 0.85 |
| seconds per scene | 29.4 | 27.7 |
| peak memory | 3.05 GB | 2.97 GB |

The dev split (6 scenes, iteration only) is similar: 6/6 valid, distinctness 0.60, 35 s per scene. It has two invented-detail flags:
- `dev-parking-corner`: "a person standing in the parking space" appears as *visible evidence* in an empty garage.
- `dev-shop-shelves`: "sign". This is **my annotation error**: the shop window does carry lettering. A reviewer should clear it as a false positive. It will be corrected in the next manifest version together with a fresh base run, because editing the manifest now would break comparability with this run.

## Not measured yet: what a reader sees in the outputs

I (Claude, an AI reviewer) read all 60 held-out looks. These are observations for the human reviewers to confirm or reject, not scores. AI reviews never count toward a decision under the criteria.

**What the base model gets right:**
- It always returns a complete, valid shot-v2 answer. Every gaze names a target.
- Scene readings are mostly accurate and specific. It reads signs ("NEEDED THINGS FOR SALE", "6年1" in the Tokyo corridor, "15th Street") and notes wet bricks, the white floor arrow and the red pipes.
- It invented no people in empty scenes and inferred no emotions.
- 复古 CCD looks ask for the phone flash at night and in the dark store, as the brief intends.

**Where it fails, including what the automated checks miss:**
1. **Directing strangers as the subject.** This is the most serious failure, and the v1 automated checks cannot see it.
   - 4 of the 7 occupied held-out scenes direct a person already in the photo:
     - crowded sidewalk: "the man in the white t-shirt and black shorts is walking forward";
     - dark store aisle: the silhouetted shopper;
     - hallway: the person pointing;
     - subway: "the person on the platform".
   - A fifth, the café terrace, seats the subject at an occupied table among diners.

   This repeats gap 4 from the #19 demo, so the passer-by rule in the prompt is not working.
2. **Unsafe or improper placements the checks miss.**
   - Underground car park: "standing in the middle of the aisle", which is the driving lane.
   - Orange café chairs: "seated on the table", three times.
   - Subway: the gaze goes "down at the tracks" and the subject stands "near the platform" edge.
   - Only the balcony case was flagged. Humans need to score safety on all of these.
3. **Camera and gaze contradictions.** Many looks put the camera "behind the subject" while the gaze is "the lens". The night-street run does this in all three looks. White stairs, look 1: "the eyes look at the wall, directly at the camera".
4. **Little real variety.**
   - In 8 of 20 runs all three looks have the same `body_pose` text.
   - Titles repeat ("silent ascent" × 3, "window glow" × 3).
   - The wide, medium and close plans mostly change the framing words, not the shot.
5. **Expression defaults to "a soft closed-mouth smile"** in 28 of 60 looks, including 清冷感 looks. Some cues copy the brief ("an easy half-smile or simply relaxed", "neutral, no big smile").
6. **Prompt text leaks into answers.**
   - The dark-store run's `body_pose` for looks 2–3 is the look plan copied verbatim: "waist up or three-quarter body, the camera in a different place from the earlier looks, and a different pose".
   - A dev answer's gaze is "the lens, a named thing in the target photo…", copied from the field description.

   Schema validation only rejects copies of field descriptions that are exact and complete, so these pass as valid.
7. **Ambiguous spaces are filled with a guess, not a check.**
   - Tiled façade (no ground visible): the subject is put on an upper-floor balcony.
   - Low light: no advice on holding still, Night mode or bracing the phone.

**Group difference:** on automated measures the two groups are close: 10/10 valid each, distinctness 0.60 vs 0.56. The ordinary group's real problems are concentrated in occupied and low-light scenes (items 1, 2 and 7). Whether XHS-aligned backgrounds produce better *looks* is the question the human style and practicality scores have to answer.

## Blind review pack, ready for human scoring

- **Pack:** `runs/scene-eval/packs/base-heldout-v1/` holds 20 held-out scenes with one set each.
- **Send to reviewers:** `review.html` only. It is one 3.7 MB offline file with the photos embedded.
- **Reviewers:** Jasmine scores style, which is the deciding vote. Jasmine and the second human reviewer both score evidence, pose and expression, gaze, safety and distinctness, and confirm or clear the three automated flags.
- **Bring back:** `photo-ai scene-eval import-review --pack … --file …` for each exported file, then `photo-ai scene-eval score --pack …`.

These base-only scores are for **calibration**: they set the proposed thresholds and test the rubric on real outputs. The #6 decision does not rest on them. When the adapter exists, run it with the same command, then build an A/B pack:

```bash
photo-ai scene-eval pack --eval-id base-heldout-v1 <adapter id>
```

Reviewers then see base and adapter blind on every scene in shuffled order, so neither system's scores are anchored by an earlier pass.

## For Jasmine to calibrate

1. **Style per starter brief.** Does each look read as 松弛感, 氛围感, 清冷感 or 复古 CCD, and what separates a 1 from a 2? Is "a soft closed-mouth smile" ever acceptable for 清冷感?
2. **Ordinary-place bar.** The proposed set-pass thresholds are 60% for xhs_aligned and 40% for ordinary. Is a lower bar for ordinary places right, and what does "usable in an ordinary place" mean to you?
3. **Expression.** Should omitting the cue be the default for some styles, as the addendum suggests for 清冷感?
4. **The A/B preference rule.** Is "Jasmine prefers the adapter on ≥ 60% of scenes, ≥ 50% in each group" the right bar, given 10 scenes per group?
5. **Occupied scenes.** Should a look that directs a stranger be a safety 0 or a scene-evidence 0, or a separate failure type? The proposed v2 check below needs that answer.

## Proposed for criteria v2 (not applied to this run)

These come from reading held-out output, so they are **not** added to v1, which would mean tuning the criteria to the test set. Implement and calibrate them on `dev`, then freeze them as `scene-eval-criteria-v2` before the adapter run:
- **Passer-by directed:** in occupied scenes, flag direction fields that refer to a person described in `people_in_frame`.
- **Driving-lane and table placements:** add aisle, lane and "on the table" patterns to the fixture `unsafe_terms`.
- **Prompt echo:** flag look fields that copy text from `LOOK_PLANS` or the style brief.
- **Camera/gaze contradiction:** flag "behind the subject" together with a lens gaze. This needs care: "away from the lens" must not count.

## Still blocked or missing

| item | blocked on |
|---|---|
| Human scores for the base run | Jasmine and the second reviewer scoring `review.html` |
| Calibrated thresholds | those scores |
| Adapter run and A/B pack | LoRA pilot (#5), which needs approved labels (#2/#4) |
| Recommendation for #6 | the A/B scores; the Inspiration Director comparison stays on portrait_v1 |
| Private-album fixtures | the owner choosing photos and recording consent; then a new dataset version |
| Fixture gaps | tiled stairs, East Asian XHS places, golden hour or backlight in held-out, vertical phone captures, a subject already in frame, rain or neon. See [scene-eval.md](scene-eval.md#known-fixture-gaps) |
