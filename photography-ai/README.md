# Photography AI baseline

A standalone Python experiment for Digi. You give it 3–5 **inspiration** photos and one **target scene**. A local vision-language model describes the inspiration aesthetic and recommends **three practical compositions** for the target, returned as structured JSON. Every run is saved with its inputs, the raw model text, the parsed result and timings.

It runs fully on-device with [MLX-VLM](https://github.com/Blaizzy/mlx-vlm) on Apple silicon. Nothing here touches the Swift app in `ios/`, and no fine-tuning is done. This folder only sets up a baseline to measure against.

## Setup

Requirements: an Apple-silicon Mac and [uv](https://docs.astral.sh/uv/) (`brew install uv`). uv installs Python 3.12 for this folder. MLX does not support the system Homebrew Python 3.14.

```sh
cd photography-ai
uv sync                 # creates .venv with mlx-vlm, gradio, pillow
uv run pytest           # 17 tests, no model download needed
uv run photo-ai models  # list registered models
```

The first real run downloads weights from Hugging Face into `~/.cache/huggingface/hub`: about 1.9 GB for SmolVLM2-500M and 3.1 GB for Qwen2.5-VL-3B 4-bit. After that everything works offline.

## Run

**Upload interface** (opens http://127.0.0.1:7860, bound to localhost only):

```sh
uv run photo-ai ui
```

Drop in 3–5 inspiration photos and a target photo, pick a model and strategy, and click **Analyze**. Choose the `fake` model to try the interface without downloading anything.

**Command line:**

```sh
uv run photo-ai analyze -i insp1.jpg insp2.jpg insp3.jpg -t scene.jpg
uv run photo-ai analyze -i ... -t ... --model qwen2.5-vl-3b-4bit --strategy single_pass --repeat 3 --label kitchen
uv run photo-ai runs    # table of saved runs: validity, load time, inference time, peak memory
```

`--repeat N` keeps the model loaded, so runs 2..N give warm timings. Other flags: `--max-side`, `--max-tokens`, `--temperature`, `--repetition-penalty`, `--seed`, `--json-retries`, `--runs-dir`, `--json`.

## What gets saved

```
runs/                                 (git-ignored)
  index.jsonl                         one summary line per run
  20261109-154100_smolvlm2-500m/
    inputs/inspiration_1.jpg …        downscaled copies with EXIF/GPS stripped
    inputs/target.jpg
    raw/stage1_aesthetic_attempt1.txt exact model text, every attempt
    run.json                          config, prompt version, timings, parsed result, errors, environment
```

Timing fields in `run.json`:

- `model_load_s`: weight load time. It is `null` when the model was already loaded.
- `inference_s`: wall-clock time for all stages.
- Per attempt: `wall_s`, prompt/generation token counts, tokens/second, `peak_memory_gb` and `finish_reason`. `length` means the attempt hit `max_tokens`.

## Output schema

```jsonc
{
  "aesthetic":    { "summary", "color_palette": [], "lighting", "mood", "composition_patterns": [], "subject_treatment" },
  "target_scene": { "description", "key_elements": [], "constraints": [] },
  "compositions": [ // exactly 3 kept
    { "title", "framing", "orientation", "camera_position", "subject_placement",
      "zoom_or_lens", "lighting_tip", "why_it_matches", "steps": [] }
  ]
}
```

Validation lives in `schema.py` (pydantic). It wraps bare strings into lists and drops duplicate list items, because small models loop. It **rejects** a missing `summary`/`description`/`title`, fewer than 3 compositions, and any value copied verbatim from the prompt's field descriptions. JSON extraction (`parsing.py`) handles code fences, surrounding prose, trailing commas, stray closing brackets and truncation. It records which repair it used (`parse_method`).

**"Valid" means schema-valid, not good.** See the baseline below.

## Strategies

| strategy | calls | images per call | notes |
|---|---|---|---|
| `two_stage` (default) | 2 (+retries) | all inspiration, then target only | Aesthetic JSON from stage 1 is passed to stage 2 as text. |
| `single_pass` | 1 (+retries) | all inspiration + target | Bigger prompt and schema. Harder for small models. |

If stage 2 fails, the stage-1 aesthetic is still saved as `partial_result`.

## Layout and adding models

```
src/photo_ai/
  backends/
    __init__.py      model registry (MODELS) + make_backend()
    base.py          VLMBackend protocol, GenerationParams, Generation
    mlx_backend.py   MLX-VLM implementation (any mlx-vlm model family)
    fake.py          canned backend for tests / UI dry runs
  prompts.py         all prompt text + PROMPT_VERSION
  schema.py          output models + validation
  parsing.py         JSON extraction / repair
  images.py          orient, downscale, strip metadata
  pipeline.py        strategies, retries, timing, run record
  storage.py         run folders + index.jsonl
  render.py          markdown views (shared by CLI and UI)
  cli.py, app.py     command line and Gradio interface
```

Qwen2.5-VL-3B is already registered (`qwen2.5-vl-3b-4bit`, `qwen2.5-vl-3b-8bit`) and goes through the same MLX backend. Any other MLX model works ad hoc with `--model <hf-repo-id>`. Non-MLX runtimes such as llama.cpp or an API need a new class in `backends/` that implements `load / generate / unload / runtime_info`. Prompts, validation, storage and the UI stay the same, so runs remain comparable. If you change prompt wording, bump `PROMPT_VERSION`. Every run records it.

## Baseline on this Mac (2026-11-09)

Hardware: M3 Pro, 18 GB. Software: mlx 0.32.4, mlx-vlm 0.7.12, Python 3.12. Model: SmolVLM2-500M, greedy decoding (temperature 0), images downscaled to 1024 px. Inputs: 3 Wikimedia Commons photos already in `research/g12/collection/files` (canyon, painted landscape, canoe) as inspiration and a park bench as the target.

| run | prompt | strategy | schema-valid | inference | peak mem |
|---|---|---|---|---|---|
| cold, first ever (incl. ~61 s download+load) | v1 | two_stage | no: echoed template, looped to 900 tokens | 24.4 s | 2.46 GB |
| warm | v2 | two_stage | **yes** (after 1 JSON retry in stage 1) | 11.6–12.0 s | 2.49 GB |
| warm, rep. penalty 1.15 | v2 | single_pass | no: malformed JSON twice | 13.2 s | 2.94 GB |

Throughput: about 900–1400 prompt tok/s and about 125 generation tok/s. The 3 inspiration images at 1024 px came to about 2,800 prompt tokens. Model load from disk cache took about 0.6 s.

**Quality: not usable yet.**

- Stage 1 described only one inspiration photo (the canoe), not a shared style.
- Stage 2 ignored the target photo and re-described the canoe from the aesthetic text.
- The compositions were filler: "wide / medium / close-up", "center", "well-lit".
- Prompt v1, which put descriptions inside the JSON template, was copied back verbatim. That is why v2 lists field meanings as prose, and why validation now rejects echoed template text.

Greedy decoding is deterministic, so all three warm repeats were identical.

So this is a working measurement setup with an honest weak baseline. The obvious next step is running the same inputs through `qwen2.5-vl-3b-4bit`.

## Still to test on this Mac

- [ ] **Your own photos.** The baseline above used 3 generic Commons images. Try real inspiration sets (5 photos) and real target scenes, including iPhone **HEIC** files. `pillow-heif` is installed, but HEIC has not been run end to end.
- [ ] **Qwen2.5-VL-3B 4-bit and 8-bit** (3.1 / 4.1 GB downloads). Check load time, peak memory with 6 images, and whether it actually looks at the target. Qwen uses dynamic resolution, so check token counts at `--max-side 1024` versus 768.
- [ ] **5 inspiration photos + single_pass on SmolVLM2.** It has an 8k context and roughly 800 tokens per 1024 px image, so check `prompt_tokens` against the limit, or lower `--max-side`.
- [ ] **Memory headroom** with Qwen 8-bit plus the browser plus Xcode open. The registry keeps only one model resident in the UI, but watch for swap.
- [ ] **Interactive UI on a real browser:** drag-and-drop uploads, the gallery preview and model switching. It was checked here only through Gradio's API client and a render screenshot.
- [ ] **Sampling variance:** `--temperature 0.3 --repeat 5 --seed N`, to see how stable recommendations are.
- [ ] **Thermal/battery behavior** on long `--repeat` runs. Throughput was only measured on short runs.

## Privacy

The interface binds to `127.0.0.1` with `share=False`. Copies saved in `runs/` are re-encoded without EXIF/GPS. `runs/` and `samples/` are git-ignored, matching the repo's private-data policy. Don't commit personal photos.
