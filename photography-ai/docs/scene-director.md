# Scene Director: one photo, three XHS-style portrait looks (issue #19)

> **Experimental.** The held-out evaluation (#21) found that the base model sometimes directs strangers already in the photo, or suggests unsafe spots such as a driving lane or a café table. The CLI, the UI tab and every rendered result say so. Results also carry an automated `directs_people_in_frame` check next to the unsafe and emotion checks, and the rendered result shows any flags. Treat looks as suggestions to check on site.

The Scene Director takes **one scene photo**, with or without a person in it, and a **style brief**. It returns three portrait looks to shoot there. No reference photos are needed. It uses the base model chosen in Phase 3, **Qwen3-VL-2B-Instruct 4-bit**, with no fine-tuning. The Inspiration Director (3–5 reference photos plus a target) still works as before.

```bash
uv run photo-ai scene -t scene.jpg --style relaxed_candid          # or dreamy_atmospheric / cool_editorial / vintage_ccd
uv run photo-ai scene -t scene.jpg --brief "she prefers seated poses"   # free-text brief, with or without --style
uv run photo-ai ui                                                  # "Scene Director" tab
uv run photo-ai scene-demo                                          # the reproducible demo below
```

## Shared, versioned shot format

Both directors write shots in one versioned format, recorded on every run as `shot_format`. Runs saved before this change count as `v1`. All new fields are optional on the base schema, so older runs still validate and render.

| field | shot-v1 | shot-v2 |
|---|---|---|
| title, uses_principle, camera_position, camera_height, camera_angle, subject_position | ✓ | ✓ |
| distance_and_framing (framing), lighting_tip (light) | optional | **required** |
| visible_evidence, needs_on_site_check, steps, orientation, zoom_or_lens | ✓ | ✓ |
| `body_pose` | — | **required**: stance or seat, weight, arms and hands, using only surfaces visible in the photo |
| `head_direction` | — | **required**: head turn and chin up, down or level |
| `gaze` | — | **required**: the lens, a named thing in the scene, or a direction out of frame |
| `expression_cue` | — | **optional**: one small expression the subject *may choose*; empty when it adds little |

How each mode uses it:
- **Scene mode** always writes shot-v2. It also adds `target_scene.people_in_frame` (observable facts only, or "none") and a `style` block.
- **Inspiration mode** writes shot-v1 by default. Pass `--shot-format v2` (decomposed strategy) to opt in.

The shot-v1 prompts are byte-identical to prompt v4, which is tested. That keeps the Phase 3 benchmark and the LoRA training template unchanged. Scene and shot-v2 runs record prompt version `2026-11-10.5`.

## Starter style briefs

| key | 中文 | what the brief steers |
|---|---|---|
| `relaxed_candid` | 松弛感 | eye level or a little lower; half to full body; mid-action poses (a slow step, hand in pocket, leaning on something stable); gaze away or a casual glance back |
| `dreamy_atmospheric` | 氛围感 | backlight, glow, or shooting past something close to the lens; warm or pastel; slow, quiet poses; gaze down, into the distance, or eyes softly closed |
| `cool_editorial` | 清冷感 | clean lines and negative space; cool, even light; upright, minimal gestures, chin level or slightly down; steady gaze or clean profile; neutral expression |
| `vintage_ccd` | 复古 CCD | point-and-shoot angle, 4:3, central subject; hard direct light, saying whether to use the phone flash; playful poses; gaze into the lens |

The full brief text is in `prompts.STYLE_BRIEFS`. Every brief goes through the same rules:
- Ground every shot in what the photo shows.
- Put assumptions in *Check on site*.
- Treat expression as **voluntary creative direction**. The prompt forbids guessing anyone's mood.
- Keep directions safe: no traffic, ledges, railings, water or climbing.
- Treat people already in the photo as passers-by.

## How a run works

The scene photo is downscaled to a 1024 px long edge. Then the model makes four calls, each with only that one photo:

1. **scene**: a JSON description of the scene: description, key elements, constraints, `people_in_frame`.
2. **look 1, look 2, look 3**: one shot-v2 look per call (the scene call is capped at 600 tokens and each look at 900, both also capped by `--max-tokens`; each stage records the limit it used), each with a different plan: **wide** (full body), **medium** (waist up, a new camera spot and pose), and **close** (head and shoulders, new use of light, new gaze). Each call lists the earlier looks and asks for a clearly different one.

Step 2 started as a single call for all three looks. On Qwen3-VL-2B that produced one look written three times (see *demo v1* below), so it was split.

## Reproducible Mac demo

To reproduce:
1. `uv run photo-ai dataset fetch` (once, for the CC0 photos).
2. `uv run photo-ai scene-demo --demo-id <id>`.

The fixtures are in [`configs/scene_demo.json`](../configs/scene_demo.json). They reuse permitted CC0 Unsplash target photos from the portrait_v1 suite. Their case annotations work as grounding checks: they list objects that are present, and people who must *not* be claimed.

| fixture | scene | why |
|---|---|---|
| indoor-empty-cafe | empty café window counter with stools | indoor, empty |
| outdoor-white-stair | white wall with a black-railed staircase | outdoor, empty, clean lines |
| lowlight-neon-cafe | café front with a pink neon sign at night | **low light**, one passer-by in frame |
| park-path-shade | shady park path under oaks | outdoor, empty |
| street-with-people | tree-lined street, bicycle, two seated people | **people already in the scene** |
| red-stair-× 4 | empty covered staircase with red railings | **same scene, all four styles** |

Each run saves to `runs/` with the demo id as its label, so it appears in the **Evaluate** tab for **blind** scoring. The demo also writes `runs/<demo id>.md`.

**Run:** M3 Pro, 18 GB, mlx-vlm 0.7.12, greedy decoding, 2026-11-10. Model load 2.4 s (weights cached).

| | demo v1 (one call for 3 looks) | **demo v2 (one call per look, shipped)** |
|---|---|---|
| valid shot-v2 output | 9 / 9 | 9 / 9 |
| look diversity (0 = three identical looks, 1 = all fields differ), mean | **0.11** (0.00–0.36) | **0.60** (0.43–0.86) |
| scene time, mean | 22.9 s | 35.3 s |
| peak memory | 3.05 GB | 3.05 GB |
| pose / head / gaze filled | 27 / 27 | 27 / 27 |
| people hallucinated in empty scenes | 0 | 0 |
| emotion inferred / unsafe direction flagged | 0 / 0 | 0 / 0 |

Demo v2 per fixture:

| fixture | style | s | scene recall | evidence grounded | look diversity |
|---|---|---|---|---|---|
| indoor-empty-cafe | 松弛感 | 30.9 | 0.83 | 0.76 | 0.64 |
| outdoor-white-stair | 清冷感 | 30.4 | 1.00 | 0.93 | 0.50 |
| lowlight-neon-cafe | 复古 CCD | 33.5 | 0.86 | 1.00 | 0.57 |
| park-path-shade | 氛围感 | 44.3 | 0.80 | 1.00 | 0.43 |
| street-with-people | 松弛感 | 28.5 | 0.83 | 0.78 | 0.43 |
| red-stair-relaxed | 松弛感 | 33.8 | 0.80 | 0.79 | 0.57 |
| red-stair-dreamy | 氛围感 | 35.1 | 0.80 | 1.00 | 0.86 |
| red-stair-editorial | 清冷感 | 42.7 | 0.80 | 0.82 | 0.71 |
| red-stair-ccd | 复古 CCD | 38.0 | 0.80 | 0.84 | 0.64 |

Notes on these numbers:
- *Scene recall* is the share of the annotated scene objects that the model names.
- *Evidence grounded* is the share of `visible_evidence` items that name an annotated object.
- These checks only show what the model *mentions*. They don't judge whether a look is good; the blind scores are for that.
- The unsafe check was narrowed after the first pass: it had flagged "leaning slightly on the railing", which is a safe direction. Both demos were re-scored with the final check. No run has a remaining flag.

## Quality gaps

I read every look in demo v2. These are the gaps to check in blind scoring and to target in the #20 rubric and the LoRA labels:

1. **Looks still repeat inside a run.** Per-look calls fixed the copying, but titles often repeat ("silent ascent" × 3, "neon glow" × 3). Poses also vary less than camera positions do. For example, all three red-stair 清冷感 looks are "standing upright, body slightly angled right".
2. **Styles blur together on the same scene.** On the red staircase, 松弛感, 清冷感 and 复古 CCD differ mostly in the expression and light wording, not in camera or pose. 复古 CCD now asks for the phone flash, but it rarely uses a straight-on snapshot angle or playful poses.
3. **The expression cue defaults to "a soft closed-mouth smile",** even for 清冷感. Sometimes it copies the brief's own wording ("an easy half-smile or simply relaxed", "neutral, no big smile"). It never inferred emotion, though.
4. **Passers-by become the subject.** In the neon café and street scenes, the looks direct "the person" already in the photo, or seat the subject on an occupied bench, despite the prompt rule. Scenes with people need human review before any of their looks are trusted.
5. **Contradictions between fields.** One look has "camera behind the subject" with "gaze: the lens". Another has "back to the camera" with "gaze down the staircase", which is fine for 氛围感 but undermines a "look at the lens" CCD look.
6. **Low light gets light-source advice but no stability advice.** The neon café looks use the sign as key light, but never mention holding still, Night mode or bracing the phone.
7. **It's slower.** Four calls average 35 s per scene against 23 s for one call. That is acceptable for a Mac demo. It is relevant to the iPhone budget (#7).

**No problems found with:**
- schema validity: 9/9;
- invented people in empty scenes;
- inferred emotion;
- unsafe directions: none after the regex fix;
- gaze specificity: every gaze names the lens, a scene object or a direction.

## Next

- Score `scene-demo-v2` blind in the Evaluate tab, as a human rater.
- Feed gaps 1–5 into the #20 annotation rubric. Style fit, pose variety and the passer-by rule are where labelled scene-mode examples would help the LoRA pilot (#5) most.
- Run the four calls through the iPhone harness (#7) to measure on-device latency.
