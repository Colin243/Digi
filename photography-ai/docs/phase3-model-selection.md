# Phase 3: portrait-focused evaluation and model selection (2026-11-09)

**Recommendation: use Qwen3-VL-2B-Instruct (MLX 4-bit) as the base for LoRA fine-tuning and for offline iPhone 17 Pro deployment.**

- **Ahead on every measure:** it beat Qwen2.5-VL-3B on blind preference, rubric scores, hallucination rate, speed and memory. It is also smaller (1.8 GB of weights) and has a Swift MLX implementation.
- **Not shippable as-is:** no model directs well yet. The best mean is 12.4/25 core. Actionability (1.8/5) and shot diversity (1.3/5) are the main gaps. Fine-tuning needs to fix exactly those.
- **SmolVLM2-2.2B is not a viable base.** Details are in section 4.

Machine: M3 Pro, 18 GB, macOS 26.6. Software: mlx 0.32.4, mlx-vlm 0.7.12, transformers 5.22.2, Python 3.12. Settings: `decomposed` strategy, prompt v4, schema v3, greedy decoding, images downscaled to 1024 px. The raw evidence is git-ignored: `runs/benchmarks/bench-phase3/` and `bench-phase3-keys/`, `runs/diagnostics/`, and every run's `run.json`, `raw/` and `scores.json`. The generated tables are in [`bench-phase3-report.md`](bench-phase3-report.md) and [`bench-phase3-keys-report.md`](bench-phase3-keys-report.md), and the Phase 2 results are unchanged in [`phase2-benchmark.md`](phase2-benchmark.md).

## 1. Dataset: `portrait_v1`

There are 14 scenarios. Each has 3–4 inspiration photos sharing one style, plus a different target place. That's 69 images in total, with no image reused.

| category | scenarios |
|---|---|
| café | café window candids → empty café counter |
| portrait | colorful-wall headshots → red-brick/green shopfronts; winter portraits → misty snowy avenue |
| street | night street moody → neon café at night; B&W street portraits → tree-lined street; candid motion → railway platform |
| fashion | minimal urban fashion → white wall + diagonal staircase; low-angle hero → corner building |
| lifestyle | sunset silhouettes → under a pier; golden-hour backlight → shady park path; small figure / big scene → castle lawn; beach lifestyle → mountain lake; couple candids → cherry blossom; seated on steps → covered staircase |

**Licensing:**
- Every image is **CC0**: Unsplash photos published before June 2017, hosted on Wikimedia Commons in *Category:Images from Unsplash*.
- They were fetched through the Commons API with a descriptive User-Agent, sequentially, with backoff. No social platform was scraped.
- `datasets/portrait_v1/manifest.json` (committed) records the source page, author, license, licence URL and download URL for each image. [`SOURCES.md`](../datasets/portrait_v1/SOURCES.md) is the readable attribution list.
- The images go to git-ignored `samples/portrait_v1/` via `photo-ai dataset fetch`, with sha256 values in `fetched.json`.
- The photos show identifiable people, so the manifest restricts them to local evaluation. Review personality rights before training on them or publishing outputs.

**Annotation:** each case lists, per image:
- the main subject and visible objects;
- inspiration-only "leak" terms;
- `style_keywords` that a correct reading should mention;
- `target_absent`: things not in the target that a model might invent.

One annotation error was found and corrected during review. The night-street target does contain people (diners and a pedestrian), so mentioning them is not a hallucination.

**Fit to the real use case:** this is much closer than Phase 2, since it has real portrait, lifestyle and fashion styles. Still, it is Western Unsplash-era photography, not actual Xiaohongshu content. Most targets are empty places, and the subject is always "a friend posing", so pose and wardrobe direction get little testing.

## 2. Compatibility (checked before downloading weights)

| model | MLX build | mlx-vlm module | processor and template | Swift MLX (`mlx-swift-lm` `Libraries/MLXVLM/Models`) |
|---|---|---|---|---|
| Qwen2.5-VL-3B-Instruct | `mlx-community/…-4bit`, 3.1 GB | `qwen2_5_vl` | OK | `Qwen25VL.swift` |
| Qwen3-VL-2B-Instruct | `mlx-community/…-4bit`, 1.8 GB | `qwen3_vl` | OK (`Qwen3VLProcessor`) | `Qwen3VL.swift` |
| SmolVLM2-2.2B-Instruct | `mlx-community/…-mlx`, **bf16 only**, 4.5 GB | `smolvlm` | OK | `SmolVLM2.swift` |

These checks were made from `config.json` and the processor files before any weights were downloaded.

There is no official quantized MLX build of SmolVLM2-2.2B; the one 4-bit upload is third-party. So I benchmarked the official bf16 weights and also converted them locally with `photo-ai convert smolvlm2-2.2b`. mlx-vlm quantized only part of the model, giving an average of **9.96 bits per weight** and 2.6 GB on disk. "smolvlm2-2.2b-4bit" below means that partial quantization.

## 3. Results

### Measured: deterministic numbers, no judgment involved

14 cases per model, decomposed strategy, about 7 model calls per analysis, warm model.

| | Qwen3-VL-2B 4-bit | Qwen2.5-VL-3B 4-bit | SmolVLM2-2.2B bf16 | SmolVLM2-2.2B "4-bit" |
|---|---|---|---|---|
| Schema-valid outputs (prompt v4) | 13/14 (93%) | **14/14** | 0/14 | 0/14 |
| Schema-valid (keys-format variant) | **14/14** | — | 14/14 | — |
| Inference per analysis, mean / max | **38 s / 56 s** (keys: 34 s) | 59 s / 78 s | 36 s / 39 s (keys: 76 s / 124 s) | 38 s / 42 s |
| Peak memory (MLX) | **3.05 GB** | 4.10 GB | 5.52 GB | 4.93 GB |
| Weights on disk | **1.8 GB** | 3.1 GB | 4.5 GB | 2.6 GB |
| Image tokens per 1024 px image | **≈690** | ≈920 | ≈1,090 | ≈1,090 |
| Single-image description time | **2.2 s** | 5.6 s | 6.5 s | 4.8 s |
| Model load from disk | 1.1 s | 1.6 s | 2.3 s | 0.7 s |
| Crashes | 0 | 0 | 0 | 1 Metal GPU timeout in ~110 generations |

SmolVLM2-2.2B's "fast" times under prompt v4 aren't a real speed advantage. It returned the blank template almost immediately instead of doing the work.

### Measured: perception diagnostics

5 portrait cases per model, checked by hand where the keyword check was unreliable.

| check | Qwen3-VL-2B | Qwen2.5-VL-3B | SmolVLM2-2.2B | SmolVLM2-2.2B "4-bit" |
|---|---|---|---|---|
| All images reach the model | 5/5 | 5/5 | 5/5 | 5/5 |
| Describes the target alone correctly | 5/5 (recall 0.78) | 5/5 (0.73) | 5/5 (0.72) | 5/5 (0.63) |
| Separates several images, labeled / unlabeled | 1.00 / **1.00** | 1.00 / 0.88 | 0.92 / 0.20 | 0.52 / 0.00 |
| Describes only the labeled TARGET among inspirations | **5/5** | 5/5 | **0/5** | 0/5 |
| Target correct when inspiration text sits beside it | 5/5 | 5/5 | 4/5 | 2/5 |

SmolVLM2-2.2B describes an inspiration photo when asked about the target ("A woman with red hair is sitting at a table…" for an empty café). The keyword check initially scored 2 of those 5 as correct. The diagnostics now also reject answers that mention annotated-absent things, and the rescoring matches a manual read.

### Measured: automatic content checks

These are keyword checks against the annotations. They measure mentions, not quality.

| | Qwen3-VL-2B | Qwen2.5-VL-3B |
|---|---|---|
| Inspiration subject identified | 100% | 100% |
| Style keyword recall | **0.90** | 0.79 |
| Target object recall | **0.90** | 0.80 |
| Runs with invented objects in the target | **0** | 1 |
| Visible-evidence items naming real target objects | 0.77 | 0.84 |
| Concrete cue types per shot (of 6) | 3.6 | 4.0 |
| Generic phrases (copied from prompt examples) | **10 (4)** | 63 (16) |
| Shot diversity: fields differing / text dissimilarity | 0.43 / 0.08 | 0.36 / 0.20 |

### Subjective: blind ratings

**Who rated:** the rater is `claude-blind-reviewer`, three independent Claude subagents. They saw only the photos and anonymized Set A–D text, never model names or anyone else's scores. **No human has rated Phase 3 yet.** These are model-made judgments, used as a second opinion until you score in the Evaluate and Compare tabs.

| rubric (1–5) | Qwen3-VL-2B | Qwen2.5-VL-3B | SmolVLM2-2.2B | SmolVLM2-2.2B "4-bit" |
|---|---|---|---|---|
| Aesthetic understanding | **3.36** | 2.36 | 1.00 | 1.07 |
| Scene awareness | **3.36** | 2.71 | 1.00 | 1.00 |
| Aesthetic transfer | **2.00** | 1.71 | 1.00 | 1.00 |
| Actionability | 1.79 | **1.86** | 1.00 | 1.00 |
| Composition quality | 1.93 | 1.93 | 1.00 | 1.00 |
| Shot diversity | 1.29 | 1.29 | 1.00 | 1.00 |
| **Core /25** (first five) | **12.4** | 10.6 | 5.0 | 5.1 |
| Sets flagged with a hallucination | **14%** | 43% | 0% (no content) | 0% (no content) |
| **Blind preference: set they'd use** | **11/14 (79%)** | 3/14 (21%) | 0 | 0 |
| **Blind preference: single shot they'd shoot** | **11/14** | 3/14 | 0 | 0 |

**Supplementary blind review: keys JSON format** (`bench-phase3-keys`; same rater setup, 14 cases, 2 sets each). This is the fairest test SmolVLM2 got, since it produced valid JSON for every case.

| rubric (1–5) | Qwen3-VL-2B (keys) | SmolVLM2-2.2B (keys) |
|---|---|---|
| Aesthetic understanding | **3.50** | 1.93 |
| Scene awareness | **3.64** | 1.93 |
| Aesthetic transfer | **2.14** | 1.00 |
| Actionability | **2.00** | 1.00 |
| Composition quality | **2.07** | 1.07 |
| Shot diversity | **1.21** | 1.00 |
| **Core /25** | **13.4** | 6.9 |
| Sets flagged with a hallucination | **0%** | 71% |
| Blind preference: set / single shot | **14/14 / 14/14** | 0 / 0 |

SmolVLM2-2.2B's keys-format answers labeled almost every inspiration as "low angle" or "seated". Its shot fields were often unfilled placeholders or copies of the prompt's example sentences. Qwen3-VL-2B scored slightly higher with keys than with the v4 blank shape (13.4 vs 12.4 core, 0% vs 14% flagged), but that's within single-run noise.

**Not comparable with Phase 2's 14.5/25.** Phase 2 was rated by a single non-blind reviewer (me) on four scenery cases. Phase 3 uses blind reviewers on harder portrait cases with a stricter brief. Compare within a phase, not across.

What the reviewers kept saying:
- **Qwen3-VL-2B:** strong, detailed reads of each inspiration photo and of the target, such as the bar counter, stools, glass door, Newbury Park roundel and yellow bin. But all three shots are usually the same idea. It sometimes places the subject oddly ("on the bar table"). It rarely carries the key pose or light, for example asking someone to sit for a seated style or putting the sun behind them for backlight. Its "principles" are often just category names ("camera height", "angle").
- **Qwen2.5-VL-3B:** more scene detail errors. It invented a dock, a pool and wrong colors, and called a cigarette a flower. It also misread angles, such as calling a from-below shot eye level, and leans on the prompt's example phrases.
- **SmolVLM2-2.2B:** no usable output under prompt v4.

## 4. Why not SmolVLM2-2.2B

- Under prompt v4 it returns the blank JSON template unchanged: 0/14 valid in both builds.
- A format check showed that's prompt sensitivity, not an inability to write JSON. Listing the keys in prose gave valid, accurate target descriptions in 10/10 tries (bf16) and 5/5 (4-bit on the keys prompt). The 4-bit build invented URLs when shown a filled-in example.
- A full keys-format rerun made all 14 outputs schema-valid. But the content stayed weak: it named the inspiration subjects in only 15% of cases, only 4% of its "visible evidence" items name real target objects, it copied the prompt's example sentences 75 times, and it took twice as long (76 s).
- It cannot keep an image's role apart from the inspiration photos (0/5), which matters for any prompt that shows the target with the inspiration.
- It is the heaviest at runtime (5.5 GB bf16, 4.9 GB partially quantized), because its image tokens (about 1,090 per image) and vision tower dominate.
- Its 4-bit build had one Metal GPU timeout.

## 5. Recommendation

### Fine-tuning base: Qwen3-VL-2B-Instruct

- **Strongest perception at the smallest size.** It passed every diagnostic, including separating unlabeled images, which Qwen2.5-VL-3B didn't fully manage. It has the best style and target recall, the fewest hallucinations, and was preferred in 79% of blind side-by-sides.
- **Its failures are the kind LoRA fixes.** They are output behaviors: repeated shots, unspecific subject placement, missing pose and light direction, filler "principles". Its perception isn't the problem. A few hundred curated (inspiration set, target, three expert compositions) examples should target exactly these.
- **Cheapest to train and run.** It has the smallest weights and the fewest image tokens, so it's the fastest per call (34–38 s per full analysis versus 59 s for Qwen2.5-VL-3B).
- **Training path exists:** `python -m mlx_vlm.train --train-type lora` (also dora and full), with an optional `--train-vision`. **It hasn't been run on this model yet.**
- **Keep the decomposed strategy and the keys JSON format:** keys gave Qwen3-VL-2B 14/14 valid outputs (v4 gave 13/14) and was 11% faster. The decomposed call structure (per-image notes → target description → aesthetic → compositions) is also a natural format for training examples.

### Offline deployment on iPhone 17 Pro

- **Hardware:** the iPhone 17 Pro has an A19 Pro and **12 GB RAM**, per published specs (e.g. [PhoneArena](https://www.phonearena.com/phones/compare/Apple-iPhone-17-Plus,Apple-iPhone-17-Pro/phones/12494,12495); not verified against Apple’s own spec page).
- **Memory:** Qwen3-VL-2B 4-bit is 1.8 GB of weights. It peaked at 3.05 GB on the Mac for single-image calls at 1024 px. That fits a 12 GB phone, but an app this size likely needs Apple's Increased Memory Limit entitlement, and it should run with the camera session paused. **Unmeasured on device.**
- **Runtime:** `mlx-swift-lm` includes `Qwen3VL.swift`, so the Python setup here has a direct Swift counterpart. The prompt templates, decomposed calls and JSON parsing would need porting. A LoRA adapter can be fused into the weights for shipping.
- **Latency is the biggest open risk.** A full analysis is about 7 model calls and 34–38 s on an M3 Pro. A phone GPU will be slower, by an amount not yet measured. Options:
  - cache inspiration notes, since they don't depend on the target;
  - drop `max_side` from 1024 to 768 px (about 45% fewer image tokens; quality impact unmeasured);
  - stream the first composition;
  - fine-tune so the model needs fewer, shorter calls.
- **Size fallback:** if latency or memory don't fit, Qwen3-VL-2B is already the smallest viable option tested. Anything smaller (SmolVLM2-500M, SmolVLM2-2.2B) failed on perception or output.

## 6. Limitations and open items

- **No human ratings yet.** Every Phase 3 subjective number is from blind Claude reviewers. Please score in the UI: `uv run photo-ai ui`, then **Compare** with your name as rater, and **Evaluate** for the rubric. The report shows each rater separately.
- **Dataset scope:** 14 scenarios of Western CC0 lifestyle photography. There's no real Xiaohongshu imagery (not scraped, by design) and little pose or wardrobe content. Add 5–10 cases from your own collections in `cases/` and `samples/`. Small sample: one greedy run per model per case, so 1–2 point rubric differences are noise.
- **Prompt and format sensitivity:** SmolVLM2's validity depends on the JSON format, and Qwen3-VL-2B was slightly better with keys. The keys variant was run for SmolVLM2-2.2B (bf16) and Qwen3-VL-2B only, not for Qwen2.5-VL-3B or the partially quantized SmolVLM2 build.
- **Keyword metrics are coarse.** Style recall rewards vocabulary. Diversity counts differing fields, not genuinely different ideas. Evidence grounding depends on annotation synonyms.
- **SmolVLM2-2.2B quantization** is partial (9.96 bits per weight), and that build had one GPU timeout.
- **Untested:** LoRA training memory and time, on-device iPhone latency and memory, thermals, Qwen3-VL-4B (registered as `qwen3-vl-4b-4bit`), and lower image resolutions.
