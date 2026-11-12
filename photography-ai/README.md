# Photography AI: local VLM experiments

A standalone Python project for Digi's offline "photography director". You give it 3–5 **inspiration** photos and one **target scene**, which is a different place where you're about to shoot. A local vision-language model describes the inspiration aesthetic and recommends **three concrete compositions** for the target. Recommendations cover camera height, angle, distance, framing and subject position, plus what still has to be checked on site.

It runs fully on-device with [MLX-VLM](https://github.com/Blaizzy/mlx-vlm) on Apple silicon. Nothing here touches the Swift app in `ios/`, and nothing is fine-tuned.

- **Phase 1:** baseline pipeline, upload UI, saved runs with timings.
- **Phase 2:** diagnostics, a benchmark across models and strategies, a human scoring rubric and an evaluation UI. The findings are in [`docs/phase2-benchmark.md`](docs/phase2-benchmark.md).
- **Phase 3:** a 14-scenario portrait/lifestyle dataset (CC0), Qwen2.5-VL-3B vs Qwen3-VL-2B vs SmolVLM2-2.2B, blind side-by-side comparison, rubric v2 with shot diversity, and the model-selection report: [`docs/phase3-model-selection.md`](docs/phase3-model-selection.md).
- **Phase 4 (in progress):** licensed training-data pipeline, AI-drafted labels that only become training data after human approval (the **Label** tab), and LoRA training for Qwen3-VL-2B on MLX with a verified smoke test. How it works, what LoRA changes, and current status: [`docs/phase4-finetuning.md`](docs/phase4-finetuning.md). Labelling standard: [`docs/annotation-guide.md`](docs/annotation-guide.md).
- **Offline iPhone benchmark (issue #7, in progress):** a standalone on-device harness in [`ios-bench/`](ios-bench/README.md) that runs Qwen3-VL-2B with mlx-swift-lm and measures latency, memory, thermals and camera recovery. The method, budgets and go/no-go criteria are in [`docs/iphone-benchmark.md`](docs/iphone-benchmark.md).

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
| `photo-ai ui` | Local web app at http://127.0.0.1:7860. **Scene Director** takes one scene photo and a style brief. **Inspiration Director** takes 3–5 inspiration photos plus a target. Both return recommendations. The **Evaluate** tab views saved runs and scores them with the rubric. |
| `photo-ai scene -t scene.jpg --style relaxed_candid [--brief "…"]` | Scene Director from the command line. One photo, with or without a person, and no reference images. Returns 3 shot-v2 looks. Styles: `relaxed_candid` 松弛感, `dreamy_atmospheric` 氛围感, `cool_editorial` 清冷感, `vintage_ccd` 复古 CCD. Defaults to Qwen3-VL-2B. See [docs/scene-director.md](docs/scene-director.md). |
| `photo-ai scene-demo` | Reproducible Scene Director demo over `configs/scene_demo.json`. It writes `runs/<demo id>.md` and labels its runs so they can be scored blind in the Evaluate tab. |
| `photo-ai scene-eval {validate,fetch,audit,run,pack,import-review,score}` | Held-out Scene Director evaluation (#21). Uses 20 held-out and 6 dev CC0 scenes in two groups (XHS-aligned and ordinary), with criteria declared before any run, an overlap audit against the training pool, and a blind A/B review page for human scoring. See [docs/scene-eval.md](docs/scene-eval.md). |
| `photo-ai analyze -i a.jpg b.jpg c.jpg -t scene.jpg [--model …] [--strategy …] [--shot-format v2]` | One analysis from the command line. `--repeat N` gives warm timings. `--shot-format v2` (decomposed only) adds body pose, head and chin, gaze, and an optional expression cue. |
| `photo-ai diagnose --model … [--case …]` | Checks that images reach the model and that it can see the target. See "Diagnostics" below. |
| `photo-ai bench --models smolvlm2-500m qwen2.5-vl-3b-4bit [--bench-id …]` | Runs every model × case × strategy, plus sampled runs for consistency. It is resumable: rerun with the same `--bench-id` to continue. |
| `photo-ai report [--bench …] [--out file.md]` | Side-by-side comparison table, including any manual scores saved so far. |
| `photo-ai score --run <id> --rater <name> --scores A S T C Q` | Records a rubric score without the UI. |
| `photo-ai dataset fetch` | Downloads the portrait evaluation images listed in `datasets/portrait_v1/manifest.json` into git-ignored `samples/`. `photo-ai dataset attribution` prints sources and licences. |
| `photo-ai bench --suite portrait_v1 --strategies decomposed --consistency-samples 0 --models …` | Phase 3 benchmark on the portrait suite. `--json-format keys` describes the expected JSON as a key list instead of a blank shape. |
| `photo-ai prefer --bench … --case … --rater … --set B --shot B2` | Records a blind side-by-side preference from the command line. `--show` prints this rater's A/B/C order. |
| `photo-ai convert smolvlm2-2.2b` | Quantizes a registered model into git-ignored `models/<key>-4bit`. |
| `photo-ai train-data pool / fetch / assemble [--reserve] / status / qa / export` | Phase 4 training data: Commons search → licence-tracked download with held-out dedup and author split → technique-matched examples → label status and heuristic QA → export **approved** labels as SFT rows (`data/`, git-ignored). |
| `photo-ai train-data import-tags / import-labels --file …` | Imports AI-drafted tags or answers as provisional drafts. |
| `photo-ai train-data audit [--json]` | Dataset-freeze coverage audit (read-only): counts **approved** labels by split, mode, style, pose and expression, and lists gaps. See [docs/annotation-xhs-addendum.md](docs/annotation-xhs-addendum.md). |
| `photo-ai train-data draft --ids …` | Drafts answers with Claude via the API (`uv sync --extra drafting`; paid; drafts stay provisional). |
| `photo-ai lora smoke --config configs/lora_smoke.json` | LoRA feasibility smoke test (architecture, template parity, masking, gradients, learning, checkpoint reload, adapter inference, memory). |
| `photo-ai lora train --config configs/lora_pilot.json` | LoRA pilot on approved labels only; adapters in `data/adapters/<run>/`. |
| `photo-ai monitor serve` | Read-only LoRA training monitor at http://127.0.0.1:7870 (architecture network, layer stats, live metrics, replay, checkpoint compare). `photo-ai ui` also starts it and links it from the **Training monitor** tab. See [`docs/training-monitor.md`](docs/training-monitor.md). |
| `photo-ai runs` | Lists saved runs. |

A fine-tuned adapter runs anywhere a model name is accepted: `--model "qwen3-vl-2b-4bit+adapter=data/adapters/pilot-v1"`.

Ratings are tagged `human` or `ai`. Names starting `claude` are AI reviewers. Reports show your ratings and AI reviewer ratings in separate tables.

The `fake` model returns canned output. Use it to try the UI or pipeline without downloading weights.

## Benchmark cases

`cases/*.json` pairs a fixed inspiration set and target with hand-written ground truth. Each image has a `primary` subject and synonym groups of visible `objects`. `leak_terms` lists things that exist only in the inspiration photos. Image paths are relative to the repo root.

| case | inspiration → target | images |
|---|---|---|
| `commons-landscape-bench` | canyon, painted landscape, canoe → park bench | Wikimedia Commons (free licences) |
| `low-angle-architecture` | statue, church spires, street pole shot from below → staircase up to a pavilion | local references (copyrighted, not in git) |
| `flower-closeup` | close, shallow-focus pansies and a rose → broad park flower bed | local references |
| `minimal-negative-space` (4 inspiration) | sky, lone boat, gull, distant lighthouse → busy sidewalk with a seal sculpture | local references |

These four Phase 2 cases contain no people.

**Portrait suite (`cases/portrait_v1/`, Phase 3):** 14 scenarios across portrait, street, café, fashion and lifestyle. Each has 3–4 Instagram-style inspiration photos sharing one style, plus a different target place. Examples: café window candids → an empty café counter; silhouettes → under a pier at sunset; low-angle hero shots → a corner building. All 69 images are CC0 Unsplash photos hosted on Wikimedia Commons, fetched through the Commons API. Sources, authors and licences are listed in [`datasets/portrait_v1/SOURCES.md`](datasets/portrait_v1/SOURCES.md). The images themselves are never committed: run `photo-ai dataset fetch`. Portrait cases also annotate:

- `style_keywords`: what a correct aesthetic summary should mention.
- `target_absent`: things not in the target, such as a person in an empty staircase. Claiming one of these is present counts as a hallucination.

**Add your own cases.** Copy a JSON, point it at your photos and annotate what is visible. Keep personal photos in `samples/` (git-ignored).

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

**Schema v4 and the shot format.** Every run records `shot_format`; runs saved before v4 count as `v1`.
- **shot-v1** is the composition above.
- **shot-v2** adds `body_pose`, `head_direction` (head and chin), `gaze`, and an optional `expression_cue`, and makes `distance_and_framing` and `lighting_tip` required.
- Scene-mode results carry `"mode": "scene"`, a `style`, and `target_scene.people_in_frame`, but no `aesthetic`.
- All v4 fields are optional on the base models, so v3 results still validate and render.
- The shot-v1 prompts are byte-identical to prompt v4, so the Phase 3 benchmark and the LoRA training template are unchanged.

The prompt includes good and bad examples, such as "Place the subject in the left third" versus "take a wide shot". It also tells the model to transfer technique, not scenery. Validation (`schema.py`) rejects missing actionable fields, fewer than 3 compositions, and text copied from the prompt's field descriptions.

## Scoring

**Human rubric (`evaluation.py`, UI Evaluate tab).** Each run's recommendation set gets 1–5 in each category. Rubric v2 (Phase 3) adds **shot diversity**, for 30 points total. Reports also show "core /25" (the first five categories), so Phase 2 scores stay comparable. Raters can also flag a **hallucination**:

| category | question |
|---|---|
| Aesthetic understanding | Does it correctly interpret the inspiration images? |
| Scene awareness | Does it identify and use elements actually present in the target? |
| Aesthetic transfer | Does it apply the inspiration's principles without copying the original backgrounds? |
| Actionability | Concrete camera height, angle, distance, framing and subject position? |
| Composition quality | Are the shots coherent and right for the aesthetic? |
| Shot diversity (v2) | Are the three shots genuinely different ideas, not one repeated? |

**Blind side-by-side (UI Compare tab, `comparison.py`).** For one benchmark case, every model's recommendations appear as Set A/B/C/D. The order is shuffled per rater and case but stable on reload. You pick the set you'd use and the single shot you'd actually take. Model names are revealed only after saving. Choices are stored in `runs/benchmarks/<bench>/preferences.jsonl`, and the latest choice per rater and case counts.

Scoring is blind by default: the model and strategy stay hidden until you save. Scores are stored in `runs/<run>/scores.json` and `runs/scores.jsonl`, with rater name and time. Saving again as the same rater replaces your earlier score. No model ever scores its own output.

**Automatic checks (`metrics.py`).** These are keyword checks against the case annotations, so they're cheap and auditable but measure mentions, not quality:

- target and inspiration subject identified
- target object recall
- leaked inspiration objects
- specificity: which of {height, angle, distance, frame position, movement, lens} each composition states concretely
- count of generic phrases and of phrases copied from the prompt's own examples
- style recall: expected style keywords that appear in the aesthetic
- invented objects in the target (from `target_absent`, ignoring negated sentences)
- whether the visible-evidence items name real target objects
- shot diversity: how many of position, height, angle, subject position and framing differ across the three shots
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
  benchmarks/<bench_id>/manifest.json, preferences.jsonl
samples/portrait_v1/…                   downloaded evaluation images (git-ignored)
models/<key>-4bit/                      local quantized models (git-ignored)
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
  comparison.py        blind side-by-side preferences
  dataset.py           manifest-driven image download + attribution
  images.py storage.py render.py cli.py app.py
```

To add an MLX model, add one `ModelSpec` line in `backends/__init__.py`, or pass `--model <hf-repo-id>`. A different runtime such as llama.cpp, Core ML or an API needs a class implementing `load / generate / inspect_inputs / unload / runtime_info`. Images go where the prompt has `<<image>>` markers. The prompts, validation, cases, metrics, rubric and UI stay the same, so results remain comparable.

## Privacy

The UI binds to `127.0.0.1` with `share=False`. Copies saved in `runs/` are re-encoded without EXIF/GPS. `runs/` and `samples/` are git-ignored. Don't commit personal photos.
