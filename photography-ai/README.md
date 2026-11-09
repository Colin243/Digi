# Photography AI: local VLM experiments

A standalone Python project for Digi's offline "photography director". You give it 3–5 **inspiration** photos and one **target scene**, which is a different place where you're about to shoot. A local vision-language model describes the inspiration aesthetic and recommends **three concrete compositions** for the target. Recommendations cover camera height, angle, distance, framing and subject position, plus what still has to be checked on site.

It runs fully on-device with [MLX-VLM](https://github.com/Blaizzy/mlx-vlm) on Apple silicon. Nothing here touches the Swift app in `ios/`, and nothing is fine-tuned.

- **Phase 1:** baseline pipeline, upload UI, saved runs with timings.
- **Phase 2:** diagnostics, a benchmark across models and strategies, a human scoring rubric and an evaluation UI. The findings are in [`docs/phase2-benchmark.md`](docs/phase2-benchmark.md).

## Setup

Requirements: an Apple-silicon Mac and [uv](https://docs.astral.sh/uv/) (`brew install uv`). uv installs Python 3.12 for this folder. MLX does not support the system Homebrew Python 3.14.

```sh
cd photography-ai
uv sync                 # creates .venv with mlx-vlm, gradio, pillow
uv run pytest           # unit tests, no model download needed
uv run photo-ai models  # list registered models
```

The first real run downloads weights from Hugging Face into `~/.cache/huggingface/hub`: about 1.9 GB for SmolVLM2-500M and 3.1 GB for Qwen2.5-VL-3B 4-bit. After that everything works offline.

## Commands

| command | what it does |
|---|---|
| `photo-ai ui` | Local web app at http://127.0.0.1:7860. The **Analyze** tab takes uploads and returns recommendations. The **Evaluate** tab views saved runs and scores them with the rubric. |
| `photo-ai analyze -i a.jpg b.jpg c.jpg -t scene.jpg [--model …] [--strategy …]` | One analysis from the command line. `--repeat N` gives warm timings. |
| `photo-ai diagnose --model … [--case …]` | Checks that images reach the model and that it can see the target. See "Diagnostics" below. |
| `photo-ai bench --models smolvlm2-500m qwen2.5-vl-3b-4bit [--bench-id …]` | Runs every model × case × strategy, plus sampled runs for consistency. It is resumable: rerun with the same `--bench-id` to continue. |
| `photo-ai report [--bench …] [--out file.md]` | Side-by-side comparison table, including any manual scores saved so far. |
| `photo-ai score --run <id> --rater <name> --scores A S T C Q` | Records a rubric score without the UI. |
| `photo-ai runs` | Lists saved runs. |

The `fake` model returns canned output. Use it to try the UI or pipeline without downloading weights.

## Benchmark cases

`cases/*.json` pairs a fixed inspiration set and target with hand-written ground truth. Each image has a `primary` subject and synonym groups of visible `objects`. `leak_terms` lists things that exist only in the inspiration photos. Image paths are relative to the repo root.

| case | inspiration → target | images |
|---|---|---|
| `commons-landscape-bench` | canyon, painted landscape, canoe → park bench | Wikimedia Commons (free licences) |
| `low-angle-architecture` | statue, church spires, street pole shot from below → staircase up to a pavilion | local references (copyrighted, not in git) |
| `flower-closeup` | close, shallow-focus pansies and a rose → broad park flower bed | local references |
| `minimal-negative-space` (4 inspiration) | sky, lone boat, gull, distant lighthouse → busy sidewalk with a seal sculpture | local references |

There are no portrait or people inspiration photos in the repo, so none of the cases tests "Xiaohongshu-style" posing. **Add your own cases.** Copy a JSON, point it at your photos and annotate what is visible. Keep personal photos in `samples/` (git-ignored).

## Diagnostics

`photo-ai diagnose` saves `runs/diagnostics/<time>_<model>_<case>/diagnostics.json`. It runs these checks:

1. **Plumbing.** It tokenizes the real prompt and counts image-start tokens against images given. It also records the formatted chat template and the processor's resize settings.
2. **Target alone.** Describe only the target photo, then check recall against the annotation.
3. **Each inspiration alone.**
4. **Several images in one prompt**, labeled ("Photo 2: <image>") and unlabeled (images first). Can it list them separately?
5. **Roles.** Inspiration photos and the target are labeled together, and the model is asked to describe only the TARGET.
6. **Text contamination.** The target image is sent alongside the inspiration descriptions as text.

## Strategies

| strategy | model calls | images per call | why |
|---|---|---|---|
| `two_stage` (default) | 2 | labeled inspirations; then target only | The aesthetic is passed on as text, without per-image scenery. |
| `single_pass` | 1 | all, labeled | Fewest calls. Hardest. |
| `decomposed` | n + 3 | at most 1 | Each inspiration alone → notes. Target alone → scene JSON. Text-only → aesthetic. Target + both → compositions. Added because diagnostics showed small models can read single images but confuse several. |

Each strategy retries once if the JSON is invalid. All three save the same record layout.

## Output schema (v3)

```jsonc
{
  "aesthetic": { "per_image": [], "summary", "principles": [], "color_palette": [], "lighting", "mood",
                 "composition_patterns": [], "subject_treatment" },
  "target_scene": { "description", "key_elements": [], "constraints": [] },
  "compositions": [ // exactly 3
    { "title", "uses_principle",
      "camera_position",   // where to stand relative to named things in the target photo   (required)
      "camera_height",     // e.g. "slightly below the subject's waist"                      (required)
      "camera_angle",      // e.g. "tilt up about 15 degrees"                                (required)
      "subject_position",  // where they stand AND where they sit in the frame               (required)
      "distance_and_framing", "orientation", "zoom_or_lens", "lighting_tip",
      "visible_evidence": [],     // what the still photo shows that this shot depends on
      "needs_on_site_check": [],  // what it can't show: behind the camera, true distances, other light, access
      "steps": [] }
  ]
}
```

The prompt includes good and bad examples, such as "Place the subject in the left third" versus "take a wide shot". It also tells the model to transfer technique, not scenery. Validation (`schema.py`) rejects missing actionable fields, fewer than 3 compositions, and text copied from the prompt's field descriptions.

## Scoring

**Human rubric (`evaluation.py`, UI Evaluate tab).** Each run's recommendation set gets 1–5 in each category, 25 points total:

| category | question |
|---|---|
| Aesthetic understanding | Does it correctly interpret the inspiration images? |
| Scene awareness | Does it identify and use elements actually present in the target? |
| Aesthetic transfer | Does it apply the inspiration's principles without copying the original backgrounds? |
| Actionability | Concrete camera height, angle, distance, framing and subject position? |
| Composition quality | Are the shots coherent and right for the aesthetic? |

Scoring is blind by default: the model and strategy stay hidden until you save. Scores are stored in `runs/<run>/scores.json` and `runs/scores.jsonl`, with rater name and time. Saving again as the same rater replaces your earlier score. No model ever scores its own output.

**Automatic checks (`metrics.py`).** These are keyword checks against the case annotations, so they're cheap and auditable but measure mentions, not quality:

- target and inspiration subject identified
- target object recall
- leaked inspiration objects
- specificity: which of {height, angle, distance, frame position, movement, lens} each composition states concretely
- count of generic phrases
- text similarity across sampled runs, for consistency

## What gets saved

```
runs/                                   (git-ignored)
  index.jsonl  scores.jsonl
  <time>_<model>/
    inputs/…                            downscaled copies, EXIF/GPS stripped
    raw/<stage>_attempt<n>.txt          exact model text
    run.json                            config, prompt/schema version, timings, result, errors, auto_metrics
    scores.json                         human rubric scores for this run
  diagnostics/<time>_<model>_<case>/diagnostics.json
  benchmarks/<bench_id>/manifest.json
```

## Layout and adding models

```
src/photo_ai/
  backends/            registry (__init__), interface (base), mlx_backend, fake
  prompts.py           all prompt text + PROMPT_VERSION
  schema.py            output models + validation (SCHEMA_VERSION)
  parsing.py           JSON extraction / repair
  pipeline.py          strategies, retries, timing, run record
  cases.py metrics.py  benchmark cases, automatic checks
  diagnostics.py       plumbing + perception probes
  benchmark.py         model x case x strategy runner, report
  evaluation.py        rubric + score storage
  images.py storage.py render.py cli.py app.py
```

To add an MLX model, add one `ModelSpec` line in `backends/__init__.py`, or pass `--model <hf-repo-id>`. A different runtime such as llama.cpp, Core ML or an API needs a class implementing `load / generate / inspect_inputs / unload / runtime_info`. Images go where the prompt has `<<image>>` markers. The prompts, validation, cases, metrics, rubric and UI stay the same, so results remain comparable.

## Privacy

The UI binds to `127.0.0.1` with `share=False`. Copies saved in `runs/` are re-encoded without EXIF/GPS. `runs/` and `samples/` are git-ignored. Don't commit personal photos.
