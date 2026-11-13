# Annotation guide: reference answers for LoRA training

A reference answer is what the model *should* have said for one training example. It has the same four parts the deployed `decomposed` pipeline produces:

- `inspiration_notes`
- `target_scene`
- `aesthetic`
- `compositions`

The model learns to imitate these answers token by token. An answer that is wrong, vague or padded teaches the model to be wrong, vague or padded. **Approve only answers you would actually hand to a photographer standing in that place.**

AI drafters (Claude) and the heuristic checks in the Label tab make a first pass. A draft stays provisional until a human approves it.

## The task being taught

Photography principles move from the inspiration photos to a new place. The reference photos are not recreated: no copying their backgrounds, props or exact poses. The target place is a different environment, and the subject is the photographer's friend.

## Field rules

### inspiration_notes (one per inspiration photo, in order)

Write 2–3 sentences covering what the photo shows and **how it was shot**:

- **Camera height:** ground level, knee, waist, chest, eye level or above the head. Also give the angle: low looking up, level, or high looking down.
- **Framing:** close-up (head/shoulders), half-body (waist up), full-body or environmental (subject small in a large scene).
- **Subject placement:** centered, left third, right third, low in the frame, and how much empty space surrounds the subject.
- **Pose:** standing, sitting, walking, leaning or candid motion. Also where the subject faces and where the hands are.
- **Light:** direction (front, side, back, silhouette), quality (soft, overcast, hard sun, window, neon or street light) and time (golden hour, night).

Describe only what you can see. If you can't tell the camera height, say "roughly eye level". Don't invent a precise number.

### target_scene

- **description:** one or two sentences about the actual place.
- **key_elements:** 3–6 things *visible in the target photo* that a shot can use: surfaces, lines, doorways, steps, light sources, colors.
- **constraints:** what limits the shot (clutter, harsh light, narrow space, traffic, a busy background).

Never list something that isn't in the photo. This is where Phase 3 models hallucinated people, docks, pools and railings.

### aesthetic

- **per_image:** short one-line versions of the notes.
- **summary:** the style the photos share.
- **principles:** 2–4 **transferable techniques** written as instructions ("camera at knee height looking up so the subject towers over the frame"). Bare category names such as "camera height" or "lighting" don't count.
- **color_palette, lighting, mood, composition_patterns, subject_treatment.**

### compositions (exactly 3, genuinely different)

Each shot must differ from the other two in at least two of these: camera position, camera height or angle, framing or distance, pose, and use of light. Three variations of one idea fail.

| field | must contain |
|---|---|
| `title` | short name |
| `uses_principle` | which principle from `aesthetic.principles` it applies |
| `camera_position` | where the photographer stands **relative to named things in the target photo** ("on the second step, at the left railing") |
| `camera_height` | relative to the subject's body or a scene object ("at the subject's knee height") |
| `camera_angle` | direction and rough amount ("tilt up about 15°") |
| `subject_position` | where the subject stands or sits in the scene, **their pose** (stance, where they look, what the hands do), and where they sit in the frame ("left third, feet near the bottom edge") |
| `distance_and_framing` | approximate distance and how much of the body is in frame |
| `orientation`, `zoom_or_lens` | portrait/landscape; 0.5x/1x/2x or a focal-length feel |
| `lighting_tip` | how to use the light **visible in the target photo**: where the light comes from, where to turn the subject, what to expose for |
| `visible_evidence` | facts from the target photo this shot depends on (each one must actually be visible) |
| `needs_on_site_check` | what a still photo can't tell you: what's behind the camera, real distances, whether a spot is reachable or allowed, how the light changes, foot traffic |
| `steps` | 2–4 short actions in order |

### Phone setups for subject photos

When a shot frames a person, use the setup that matches its framing. Write the numbers into `camera_height`, `camera_angle` and `distance_and_framing`, adjusted to what the target place allows. The single source is `src/photo_ai/framing.py`; the Scene Director prompts and the scene-eval setup check read the same definitions.

| framing | camera height | angle | distance | in the frame |
|---|---|---|---|---|
| **Half body** (waist up) | just above the top of the subject's head | tilt down about 10° | about 1.2 m | face in the centre column; one grid row of space above the head |
| **Full body** (standing) | low: crouch so the phone is around the subject's waist or below | tilt up about 10°, toward the eyes | about 2 m | feet touch the bottom edge; head on or just above the top grid line |
| **Seated**, full body | about the subject's stomach height (bend over) | tilt down about 10°, aimed at the stomach | about 1.5 m | whole body along the frame's diagonal; legs crossed and extended toward the subject's better side |

All three use the **1x main lens**. The 0.5x ultra-wide stretches faces and bodies near the frame edges.

- **Why these work:** a camera just above the head keeps the face in proportion; a low camera tilted up lengthens the legs, and feet on the bottom edge stop them looking cut short; the diagonal is the longest line in the frame.
- **Contradictions to fix:** "full body" with "tilt down", or "half body" with "tilt up from below". The scene-eval setup check counts these.
- **Not a template:** close-ups, environmental shots and deliberate style choices (a dramatic worm's-eye shot, a top-down shot) are fine; say why in `uses_principle`.
- **Keep it short.** State each number once. Concise compositions train a model that generates fewer tokens, and on the phone, generated tokens are most of the wait (docs/iphone-benchmark.md, §2).
- **Body language stays neutral.** Say what the setup does ("lengthens the legs"), never judge the subject's body.

### Reasoning fields (shot-v3)

Shot-v3 (prompt v10, `--shot-format v3`) teaches the model to **think before it instructs**. Each composition starts with four reasoning fields; the camera fields that follow must agree with them. A label without these fields still trains shot-v1, but `train-data export --shot-format v3` skips it.

| field | must contain | good | bad |
|---|---|---|---|
| `scene_reading` | 1 sentence: the **visible** part of the target this look is built around | "The dock runs straight into flat water, a ready-made leading line." | "This is a beautiful lake scene." |
| `setup_choice` | starts with the framing: half body, full body, seated, **close-up** (head and shoulders), **scenery** (subject small in a wide view) or **creative** (a deliberate angle or crop outside the three setups), then a few words on **why it fits this spot** | "Full body: the long empty dock leaves room to step back 2 m." / "Close-up: head and shoulders against the dark hall." | "Full body because it looks good." / "None." |
| `why_each_choice` | exactly 3 reasons, under 12 words each: height, tilt, and distance or lens, each naming **the effect on the subject** | "Waist-height camera lengthens the legs." | "Low angle is good." |
| `fix_if_wrong` | exactly 1 "if …, then …" correction the photographer can make on the spot | "If the horizon cuts the head, then crouch lower." | "Make sure it looks right." |

- **Order matters.** Write the reasoning first, then make the camera fields follow from it. If `setup_choice` says full body, `camera_angle` must tilt up. The export writes these keys first so the model learns to reason first.
- **Name the framing first.** Prompt v8 allowed a bare "None"; it became the first word of almost every look the trained model wrote, even full-body ones. Close-up, scenery and creative say what the shot is, and the setup check still treats them as "no setup".
- **No new facts in the reasoning.** Reasons may only use what `visible_evidence` lists or what `needs_on_site_check` flags as a guess.
- **Keep it short: about 35–45 words of reasoning per look.** Every generated token costs phone time (about 37 tokens/s for this stage). Prompt v7 allowed ~90 words and pushed the projected iPhone analysis to 67–70 s against a 60 s budget, so depth must come from specific reasons, not from more words.

#### Instruction word limits (shot-v3)

The reasoning adds about 190 generated tokens per analysis, so in shot-v3 labels the instruction fields make room for it (prompt v10). v9 labels ran about 270 words per look and projected 67 s on the iPhone against a 60 s budget.

| field | limit |
|---|---|
| `uses_principle` | under 12 words |
| `camera_position` | under 14 words, still naming a landmark |
| `subject_position` | under 20 words: spot, pose, place in the frame |
| `lighting_tip` | under 16 words |
| `visible_evidence` | 2–3 items of a few words |
| `needs_on_site_check` | 1–2 items under 8 words |
| `steps` | exactly 2, under 8 words each; don't repeat the camera numbers |

Shot-v1 labels keep the longer rules in the table above.

### Avoid

- Generic phrases: "take a wide shot", "use good lighting", "center the subject", "capture the moment".
- Copying the prompt's example sentences.
- Contradictions, such as "low angle" with "tilt down", or standing behind a wall.
- Advice that needs things not in the place, like a bench that isn't there or a sunset in a photo taken at noon. When light must change, put it in `needs_on_site_check`.
- Moving the inspiration's scenery into the target ("frame them against the ocean" for a café).

## Review checklist (Label tab)

1. Open every inspiration photo and the target photo.
2. Read the heuristic warnings. They catch repeats, missing pose or light, ungrounded evidence and generic phrasing, but not wrong facts.
3. Check every claim about the photos against what you see.
4. Fix wording directly in the JSON editor, then **Save edits**. An edit to an approved label sends it back to draft.
5. **Approve** only when you'd use all three shots. **Reject** if the example itself is poor, for example inspiration photos that don't share a technique, or a target that can't be photographed. Add a note saying why.

Approvals are recorded with your name and time. Only approved labels are exported for training.

For XHS style briefs (relaxed candid, dreamy atmospheric, cool editorial, vintage CCD) and the shot-v2 pose, head, gaze and expression fields, also follow [annotation-xhs-addendum.md](annotation-xhs-addendum.md).
