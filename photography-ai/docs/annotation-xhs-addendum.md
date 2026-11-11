# XHS addendum: style, pose, expression and gaze

This addendum extends [annotation-guide.md](annotation-guide.md). Every rule there still applies. It covers how the **setting** and an **intended style** shape four parts of each shot: camera direction, body pose, visible expression and gaze.

It applies to labels in the shot-v2 format, shared by the Scene Director (#19) and the Inspiration Director:

- **Mode:** `inspiration` (reference photos plus a target place) or `scene-only` (a target place plus a style brief, no references).
- **Style:** one of `relaxed_candid` (松弛感), `dreamy_atmospheric` (氛围感), `cool_editorial` (清冷感) or `vintage_ccd` (复古 CCD).

Older shot-v1 labels remain readable and valid. They simply lack the new fields.

## New shot fields

| field | must contain |
|---|---|
| `body_pose` | stance and weight, where the hands and arms go, and what the body is in contact with ("sitting sideways on the window ledge inside, one knee up, hands loose around the cup") |
| `head_direction` | where the head and chin point **relative to the camera or a named thing in the scene** ("chin a little down, head turned toward the window") |
| `gaze` | one specific target: the lens, a named object or the light, or eyes lowered to a named spot ("at the cup", "past the camera toward the doorway light") |
| `expression_cue` | **optional.** One small, voluntary facial direction the subject can choose to try ("relaxed mouth, no posed smile"). Leave it out when it adds nothing. |

The existing fields keep their meaning. `subject_position` says where the subject stands or sits in the scene and the frame. `body_pose` says what the body does there.

## Observable details vs. subject directions

A label mixes two kinds of statements. Reviewers check them differently.

| | **Observable detail** | **Suggested subject action** |
|---|---|---|
| What it is | Something you can point to in the photo | A direction given to the person being photographed |
| Where it goes | `inspiration_notes`, `target_scene`, `visible_evidence`, `lighting_tip` (the "light comes from" part) | `body_pose`, `head_direction`, `gaze`, `expression_cue`, `steps` |
| Grammar | Present-tense description ("window light from the left", "low brick ledge") | Imperative, addressed to the subject ("sit on the ledge", "look at the cup") |
| Review test | Is it actually visible? | Can the subject do it **safely**, **here**, and is it the subject's choice? |

Keep the two kinds separate:

- A direction must not smuggle in a fact. "Lean on the railing" is fine only if a railing appears in `visible_evidence`.
- An observation must not describe a person's inner state. In an inspiration note, write "eyes closed, face tilted up toward the light", not "she feels peaceful".

## Expression is a direction, not a reading

- Treat expression as **voluntary creative direction** that the subject can accept or ignore. Phrase it as an offer: "try a small closed-mouth smile".
- **Never infer emotion** from a face in any photo, and never claim to know how a person feels. Describe only visible facial details: "mouth open mid-laugh", "eyes toward the window".
- **A neutral or omitted cue is acceptable.** Leave `expression_cue` out, or write "neutral, relaxed face", when the pose and light already carry the style or when the subject is small in the frame. Do not mark a label down for this. Many cool-editorial and environmental shots should omit it.
- Don't stack cues ("smile, then laugh, then look surprised"). Give one, or none.

## How setting and style shape the shot

The setting decides what is *possible*: its surfaces, light and space. The style decides which of those possibilities to *choose*. A style never justifies something the setting doesn't have.

| style | camera direction | body pose | head and gaze | expression | light |
|---|---|---|---|---|---|
| 松弛感 relaxed candid | eye or chest level, slightly off-axis; half-body or environmental | mid-action and asymmetric: sitting sideways, walking, holding something the scene has | head turned from camera; gaze at an object or along the path | optional: relaxed mouth, a small unposed smile | soft, natural, no hard shadows on the face |
| 氛围感 dreamy atmospheric | lower or through a foreground layer (leaves, glass); more space around the subject | slow and soft: standing still, turning, a hand near the face or hair | chin slightly up or down; gaze toward the light or lowered | usually omit or keep neutral | backlight, rim light, haze; expose for the highlights |
| 清冷感 cool editorial | level or slightly low, straight-on; clean graphic framing | still and upright, weight on one leg, hands quiet or in pockets | chin level, head square or in clean profile; gaze at the lens or straight past it | neutral; omitting the cue is the default | hard side light or flat shade; cool, even tones |
| 复古 CCD vintage CCD | eye level, close, a little careless; direct flash or street light | casual snapshot poses: leaning, mid-step, crouching by a wall | gaze at the lens or caught looking off to the side | optional: a candid laugh or neutral | on-camera flash at night, or hard daylight; warm cast |

## Review checks

Score each check **2** (pass), **1** (fixable by editing), or **0** (fail).

1. **Scene evidence.** Every surface, light source and prop that the pose, gaze or camera uses appears in `visible_evidence` and is visible in the target photo. Score 0 if a shot depends on something that isn't there.
2. **Style fit.** The camera, pose, light and (if present) expression match the chosen style in the table above, *and* the setting can actually deliver them. Score 1 for a generic shot that could belong to any style.
3. **Pose and expression fit.** `body_pose` is concrete (stance, hands, contact points) and suits both the place and the style. Any `expression_cue` is phrased as a voluntary offer and claims no emotion. A neutral or omitted cue passes.
4. **Gaze specificity.** `gaze` names one target, such as the lens, a named object, the light, or a lowered spot. Score 1 for a vague phrase like "look natural" or "look into the distance". Score 0 if `head_direction` and `gaze` contradict each other.
5. **Safe directions.** No movement the photo can't verify, such as "step back three meters" with no visible room, or "climb onto the wall". No traffic, roadways, rail tracks, ledges, drops, water edges or private and closed areas. Anything uncertain goes in `needs_on_site_check`. Score 0 for any unsafe direction.

**Good** is 9–10 with no zero: approve. **Borderline** is 6–8 with no zero on checks 1 or 5: fix it in the editor, then approve. **Reject or rewrite** is any zero on checks 1 or 5, or a total below 6.

## Scored examples

The fragments below show only the shot-v2 fields and the field that matters most for the example. Settings are written as a reviewer would see them in the target photo.

### 松弛感 relaxed candid: café window seat

*Visible:* a wooden bar along a large window, two stools, a cup on the bar, soft daylight from the window on the left, plants outside.

- **Good (10).** `body_pose`: "sitting sideways on the left stool, one foot on the stool rail, both hands around the cup." `head_direction`: "head turned toward the window, chin level." `gaze`: "out of the window, past the plants." `expression_cue`: omitted. `visible_evidence`: stools, window bar, cup, window light. *All five pass. Omitting the cue is right because the averted gaze carries the style.*
- **Borderline (8: pose 1, gaze 1).** `body_pose`: "sitting casually." `gaze`: "look natural." `expression_cue`: "relaxed smile". *The pose has no hands or contact points and the gaze has no target. Fix by naming the stool, the cup and a gaze target.*
- **Reject (scene 0, pose 0, safety 0).** `body_pose`: "kneel on the window bar and lean out of the open window." `expression_cue`: "she looks lonely, so let that show." *No open window is visible, climbing onto the bar and leaning out is unsafe, and the cue infers an emotion.*

### 氛围感 dreamy atmospheric: park path at golden hour

*Visible:* a gravel path, tall grass on both sides, a low sun behind trees on the right, haze.

- **Good (10).** Camera: "crouch at the grass edge so blades blur across the bottom of the frame." `body_pose`: "standing on the path, turned three-quarters away, one hand brushing the grass tops." `head_direction`: "chin slightly up, head toward the sun." `gaze`: "toward the bright gap between the trees." `expression_cue`: "neutral, eyes half-closed if the light is too bright." `lighting_tip`: "backlit from the right; expose for the sky so the hair rims."
- **Borderline (8: pose and expression 1, gaze 1).** `gaze`: "dreamy look into the distance." `expression_cue`: "look dreamy." *"Dreamy" is a mood, not a direction. Replace it with a target ("toward the gap in the trees") and a visible detail ("eyes half-closed").*
- **Reject (scene 0, safety 0).** `body_pose`: "walk backwards toward the camera through the grass while spinning." *Moving backwards on ground the photo can't verify is unsafe, and the footing and edges of the grass aren't visible.*

### 清冷感 cool editorial: concrete stairwell

*Visible:* bare concrete stairs, a steel handrail, a hard shaft of light from a high slit window making a diagonal shadow, grey walls.

- **Good (9: scene 1).** `body_pose`: "standing on the third step, weight on the back leg, hands in coat pockets." `head_direction`: "head square to the camera, chin level." `gaze`: "straight into the lens." `expression_cue`: omitted. `lighting_tip`: "put the face in the slit of light and let the shadow cut across the coat." *The coat isn't in the photo, so reword to "hands in pockets". Omitting the expression cue is the right default for this style.*
- **Borderline (7: pose and expression 0, gaze 1).** `body_pose`: "stand elegantly." `expression_cue`: "a cold, distant attitude". `gaze`: missing. *There's no stance or hands, and the cue names an attitude instead of a visible direction; replace it with "neutral" or omit it. Add a gaze target.*
- **Reject (safety 0).** `body_pose`: "sit on the outside of the handrail with legs hanging over the stairwell." *There's a drop. Reject even though the pose would look striking.*

### 复古 CCD vintage CCD: shopfront at night

*Visible:* a lit shop window with a neon sign, a narrow sidewalk, a parked bicycle, a road with passing cars along the right edge.

- **Good (10).** Camera: "close, eye level, on-camera flash on; keep the neon sign in frame behind." `body_pose`: "leaning one shoulder on the shop wall left of the window, one hand on the bicycle seat." `head_direction`: "head turned toward the camera, chin slightly down." `gaze`: "at the lens." `expression_cue`: "optional: a candid laugh, or keep it neutral." `needs_on_site_check`: "whether the shop allows it; keep the subject on the wall side of the sidewalk, away from the road."
- **Borderline (8: style 1, gaze 1).** `gaze`: "look somewhere." Flash isn't mentioned. *There's no flash or snapshot feel and no gaze target. Fix both.*
- **Reject (safety 0).** `body_pose`: "stand in the road at the curb so the car lights streak behind." *Traffic. Reject even though it is on-style.*

## From gap to follow-up batch

Run the audit at dataset freeze, before any LoRA training:

```bash
uv run photo-ai train-data audit --dataset train_v1
```

The audit only reads files. It counts **approved** labels by split, mode, style (with style × split), body-pose bucket, expression bucket and shot format. It lists every value below target: 15 train and 3 valid examples (from #2), and by default 3 examples per mode and style and 3 shots per pose and expression. Missing style, mode or shot-v2 fields count as `unspecified`, which shows how much of the approved set predates this addendum. Share only aggregate counts on GitHub. Use `--json` for a machine-readable copy.

Turning gaps into a targeted batch:

1. **Rank the gaps.** Fill the split targets first, then styles with no validation example, then styles and modes, then pose and expression. Pick the 2–3 gaps one batch can realistically close.
2. **Source permitted imagery only.** Add gap-specific queries ("woman crouching street", "backlit field") to `datasets/<dataset>/spec.json` within the existing CC0 source (Commons, *Images from Unsplash*). Then run `train-data pool` and `fetch`. No Instagram or Xiaohongshu scraping, and no screenshots. Dedup and the held-out exclusion run as usual.
3. **Keep the split rules.** Splits are assigned by photographer. Do not move an image to `valid` to fill a gap. If no unused validation place exists, the batch has no validation examples, and the audit will keep showing that gap.
4. **Assemble a reserve batch** from unused images only. Earlier batches are never changed: `train-data assemble --reserve --batch <n> --n-train <k> --n-valid <m>`.
5. **Draft, then review by hand.** AI drafts start as `draft`. Set `style`, `mode` and the shot-v2 fields. Review with this addendum in the Label tab or with `review-site --batch <n>` and `import-review`. Only a named human can approve.
6. **Re-run the audit** and record the new counts.

Don't close a gap by relabeling approved examples. Any edit, including adding a `style` key, sends an approved label back to `draft` until a human approves it again. Prefer new examples. The audit itself never changes a label or an approval. `scene-only` examples need examples with no inspiration photos, which `assemble` does not build yet. Until it does (#19), the scene-only gap stays open.
