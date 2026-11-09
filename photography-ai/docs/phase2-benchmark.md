# Phase 2: SmolVLM2-500M vs Qwen2.5-VL-3B (2026-11-09)

Machine: M3 Pro, 18 GB, macOS 26.6. Software: mlx 0.32.4, mlx-vlm 0.7.12, Python 3.12. Images were downscaled to 1024 px. Prompt v3, schema v3.

Raw evidence (git-ignored):

- `runs/diagnostics/*/diagnostics.json`
- `runs/benchmarks/bench-phase2/manifest.json`, which lists 48 runs
- each run's `run.json`, `raw/` and `scores.json`

The generated table is in [`bench-phase2-report.md`](bench-phase2-report.md). Regenerate it with `uv run photo-ai report --bench bench-phase2`.

> **About the manual scores below:** they come from one rater, `claude-reviewer`. That's Claude reading each output next to the photos, not blind, and **not you**. Treat them as a provisional second opinion. The rubric is meant to be filled in by you in the UI's **Evaluate** tab, which hides the model. The report shows each rater separately, so your scores will sit beside these, not replace them.

## 1. Why SmolVLM2 failed in Phase 1

I checked the pipeline before blaming the model. Run `photo-ai diagnose --model …` to repeat these checks.

| question | finding |
|---|---|
| Do all images reach the model? | **Yes.** The tokenized prompt has one `<global-img>` per image: 4 of 4 and 5 of 5 in every case. Pixel tensor: 52 tiles of 512 px for 4 images. |
| Does the chat template match the model's? | **Yes, for images-first prompts.** mlx-vlm's string is byte-identical to the Hugging Face processor template. **No, for interleaved text and images.** mlx-vlm 0.7.12's helper emits empty user turns. The backend now always uses the processor's own template. |
| Does preprocessing match? | Partly. SmolVLM2's processor **upscales every image back to a 2048 px long edge** and tiles it into 512 px crops, so our 1024 px downscale saved nothing. It costs about 830 tokens per image either way. This is expected processor behavior, not a bug, but it explains the 8k-context pressure. |
| Can it describe the target alone? | **Yes.** It named the main subject in 4 of 4 cases, with object recall of 0.33–0.50. |
| Can it tell inspiration from target? | **No.** Labeled "Inspiration photo 1…3, TARGET photo", it described an inspiration image instead of the target in **4 of 4** cases ("a man sitting in a boat…"). With inspiration text next to the target image, it again missed the target in 4 of 4. |

**Conclusion:** The Phase 1 failure is the model, not the plumbing. SmolVLM2-500M can see a single image, but it can't keep several images apart. It can't hold an image's role, and it lets nearby text override what it sees. Even when every call sees only one image (the `decomposed` strategy), it can't write the larger JSON. It loops, nests keys inside lists and copies the prompt. Per the brief, I stopped there instead of tuning prompts for it.

Qwen2.5-VL-3B passed every check, with one exception: in the flower case it added "purple and white pansies" from the inspiration photos to the target. Qwen **needs labels**. With images listed unlabeled, its per-image accuracy fell to 25–75%; labeled, it was 100%. So the v3 prompts label every image inline.

Per-case diagnostics:

| check (4 cases) | SmolVLM2-500M | Qwen2.5-VL-3B 4-bit |
|---|---|---|
| all images reach model | 4/4 | 4/4 |
| target alone: main subject named | 4/4 | 4/4 |
| target alone: object recall | 0.33–0.50 | 0.67–0.86 |
| each inspiration alone: main subject named | 93% | 100% |
| several images, labeled: per-image accuracy | 0.2–1.0 | 1.0 in every case |
| several images, unlabeled: per-image accuracy | 0.0–1.0 | 0.25–0.75 |
| target among labeled inspirations: named | **0/4** | 4/4 (1 leak) |
| target + inspiration text: named | **0/4** | 4/4 |

## 2. Benchmark

Setup:

- **Runs:** 4 cases × 3 strategies, greedy decoding, plus 3 sampled runs (T=0.7) of `two_stage` per case.
- **Validity:** a run is valid when its JSON passes schema v3, including camera height, angle, position and subject position.
- **Timings:** warm, with the model already loaded.

| | SmolVLM2-500M (best: decomposed) | Qwen2.5-VL-3B 4-bit (best: decomposed) |
|---|---|---|
| Schema-valid, greedy | 1 of 12 runs (0%, 0%, 25% by strategy) | 11 of 12 (100%, 75%, 100%) |
| Inspiration subject identified* | 50% | 93–100% |
| Target subject identified* | 75% (partials) | 100% |
| Target object recall* | 0.42 | 0.62–0.72 |
| Leaked inspiration objects in output* | 0 (it never got that far) | 0 |
| Concrete cue types per composition* (max 6) | 0.0 once copied prompt text is excluded | 3.8–4.1 (two_stage, decomposed); 2.8 (single_pass) |
| Generic or copied phrases | 6, all copied from the prompt | 13–25 |
| **Manual rubric /25** (claude-reviewer, n=4 per cell) | 5.0 / 5.0 / **7.5** | 10.3 / 12.3 / **14.5** |
| Inference per analysis | 20–26 s | 40–47 s |
| Peak memory | 1.9–3.4 GB | 4.1–4.6 GB |
| Model load from disk / first download | 1.4 s / ~1 min (1.9 GB) | 2.4 s / ~5 min (3.1 GB) |
| Throughput (median) | 1073 prompt tok/s, 136 gen tok/s | 347 prompt tok/s, 59 gen tok/s |
| Consistency, T=0.7 × 3 seeds | 0/12 valid | 11/12 valid; composition text similarity 0.28–0.32 |

\* Automatic keyword checks against the hand annotations in `cases/`. They measure mentions, not quality. Known blind spot: Qwen called the seal sculpture a "bird sculpture" in every strategy, and that still counts as a hit because "sculpture" is an accepted synonym.

Manual rubric by category (claude-reviewer, mean of 4 cases):

| model / strategy | aesthetic understanding | scene awareness | aesthetic transfer | actionability | composition quality | total |
|---|---|---|---|---|---|---|
| Qwen / decomposed | 4.0 | 3.5 | 2.5 | 2.5 | 2.0 | **14.5** |
| Qwen / two_stage | 3.75 | 2.5 | 2.75 | 1.75 | 1.5 | 12.25 |
| Qwen / single_pass | 3.0 | 2.5 | 1.75 | 1.5 | 1.5 | 10.25 |
| SmolVLM2 / decomposed | 1.75 | 2.75 | 1.0 | 1.0 | 1.0 | 7.5 |
| SmolVLM2 / two_stage, single_pass | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 5.0 |

What the scores reflect:

- **Qwen sees well and directs poorly.** It reliably names what is in each photo and states the right principle ("low camera angle", "shallow depth of field", "empty space around the subject").
- **Its three compositions are often near-duplicates.** The same height, angle and subject line repeat across all three.
- **Its compositions sometimes contradict the style.** In the minimal case it says to stand 1 m from a sculpture on a cluttered street. In the staircase case it tilts down from the deck.
- **It reuses the prompt's examples where they don't fit.** "Below the subject's waist" appears for flowers, and "Railing leading into frame" appears where there is no railing.
- **Its evidence and on-site-check lists are mostly filler.** It doesn't yet separate what the photo shows from what has to be checked on site.
- **Best single output:** Qwen `decomposed` on the staircase, at 19/25 (reviewer). The subject goes left of the stairs, the camera below waist height, tilted up, with the subject in the left third and framed waist-up. It is grounded in the railings, mural and lampposts it saw.
- **Two hallucination patterns:** a person who isn't in the target ("A person is posing on a set of stairs"), and "bird" for a seal.
- **`decomposed` wins for both models**, matching the diagnostics: one image per call avoids confusing images. It costs about 6 model calls and is about 15% slower than `two_stage` on Qwen.

## 3. Output specificity

Changes in v3:

- **Required actionable fields:** `camera_height`, `camera_angle`, `camera_position` and `subject_position`.
- **Evidence versus assumption:** `visible_evidence` lists what the still photo shows, and `needs_on_site_check` lists what it can't show.
- **Prompt examples:** the prompt shows good and bad examples, and says to transfer technique, not scenery.
- **Automatic tracking:** concrete cues, generic phrases and verbatim copies of the prompt's examples. Copies earn no credit.

Effect: Qwen states 3.8–4.1 of 6 cue types per composition, against near zero in Phase 1. The cues are often still relative ("low", "slightly"), and the on-site-check lists are weak. Wording fixes alone won't get further; this is the clearest target for fine-tuning. Prompt v4 adds "do not reuse the example sentences" and **has not been benchmarked**.

## 4. Recommendation for fine-tuning

**Fine-tune Qwen2.5-VL-3B, starting with 4-bit LoRA through mlx-vlm. Don't fine-tune SmolVLM2-500M.**

- **Qwen's weaknesses are what fine-tuning fixes well.** Its perception and role handling already work. What's missing is a style of output: distinct, scene-grounded, measurable instructions plus honest on-site checks. A few hundred curated examples of (inspiration set, target, expert compositions) teach exactly that.
- **SmolVLM2's weaknesses are capacity limits.** It mixes up images, ignores image roles and can't keep a JSON structure going. Fine-tuning would have to teach perception, role binding and structured generation at once. A 500M model is unlikely to absorb that from a small dataset.
- **Cost on this Mac:** about 4.1–4.6 GB peak at inference and about 40–47 s per analysis. That's acceptable for a research loop. LoRA training memory is still untested.
- **For the eventual iPhone target**, 3B is heavy: about 2–3 GB of weights and several times slower than an M3 Pro. Before committing, benchmark two smaller registered candidates with the same command: `qwen3-vl-2b-4bit` (newer and smaller) and `smolvlm2-2.2b`. Example: `photo-ai bench --models qwen3-vl-2b-4bit smolvlm2-2.2b --bench-id bench-phase2b`. If a 2B model matches Qwen2.5-VL-3B on the diagnostics, it's the better base for an on-device product. `qwen3-vl-4b-4bit` is registered too.
- **Keep the `decomposed` strategy whichever model you pick.** It's also a natural data format for fine-tuning: per-image notes, then a target-scene description, then compositions.

## 5. Remaining limitations

- **No people in the test set.** None of the 4 cases contains Xiaohongshu- or Instagram-style portraits, which is the real use case. All local images are scenery, and three of the four cases use copyrighted reference photos that are only available on this machine. The results say nothing yet about pose, outfit or face-angle advice. **The most important next step is building 3–5 cases from your own portrait inspiration sets.**
- **One rater, not blind.** All manual scores so far are claude-reviewer's. Your blind scores in the Evaluate tab are what should drive decisions, and ideally a second photographer would score too.
- **Small sample.** 4 cases and 12 greedy runs per model. Differences of 1–2 rubric points between strategies are within noise.
- **Coarse automatic metrics.** Keyword recall can't tell "bird sculpture" from "seal sculpture", and the specificity regex rewards phrasing, not correctness.
- **Latency.** About 40–47 s per Qwen analysis on an M3 Pro. Prefill is about 350 tok/s, and four 1024 px images cost about 4,000 tokens. Lowering `--max-side` would cut latency but hasn't been measured for quality loss. iPhone performance is unmeasured.
- **mlx-vlm 0.7.12 helper bug** with interleaved images. We work around it with the processor template. Re-check after upgrading.
- **Qwen 8-bit, LoRA training memory, thermals on long runs and HEIC end to end** are still untested.
