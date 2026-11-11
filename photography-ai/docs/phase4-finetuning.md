# Phase 4: photography-specific LoRA fine-tuning of Qwen3-VL-2B

Status and results so far are in [§8](#8-status-2026-11-09). This page explains the whole process: what the model is, what LoRA changes, how the data is built and reviewed, how training works, and how we'll judge it.

---

## 1. The model we're adapting

**Qwen3-VL-2B-Instruct**, in the MLX 4-bit build `mlx-community/Qwen3-VL-2B-Instruct-4bit`. The smoke test measured 2.13 B parameters in total (quantized weights counted at full size). It has two parts:

```
 image ─► VISION TOWER (≈407 M params) ─► patch embeddings ─► merger/projector
                                                                   │  (one "image token" per 32×32 px patch group,
                                                                   ▼   ≈690 tokens for a 1024 px photo)
 text  ─► tokenizer ─► token embeddings ─────────────────► LANGUAGE MODEL (28 decoder layers)
                                                                   │   each layer:  self-attention (q,k,v,o projections)
                                                                   │                 + MLP (gate, up, down projections)
                                                                   ▼
                                                        next-token probabilities ─► answer text
```

- The **vision tower** turns pixels into a sequence of vectors. In the prompt they sit where the `<|image_pad|>` placeholders are.
- The **language model** reads the prompt text and image vectors together and predicts the answer **one token at a time**, each token conditioned on everything before it.
- Each decoder layer has 7 large **linear layers**, which are matrix multiplications. Four are in attention (`q_proj`, `k_proj`, `v_proj`, `o_proj`), deciding which earlier tokens matter. Three are in the MLP (`gate_proj`, `up_proj`, `down_proj`), transforming each token's representation.

## 2. What LoRA changes and what stays frozen

Full fine-tuning would update all 2.1 B weights. That needs far more memory than an 18 GB Mac has (weights plus gradients plus optimizer state in float32), and it can easily damage what the model already knows. **LoRA (Low-Rank Adaptation)** freezes every original weight and adds a small trainable "side path" to chosen linear layers:

```
          x ──► [ W  (frozen, 4-bit) ] ─────────────────────┐
          │                                                 (+) ──► y
          └──► [ A (d_in × r) ] ──► [ B (r × d_out) ] ──×s──┘
                     trainable           trainable

   y = W·x + s · B·(A·x)        r = rank (8),  s = alpha / r = 16 / 8 = 2
```

- **W** is the pretrained weight matrix. It is never updated, and it stays 4-bit quantized. LoRA on a quantized base is often called **QLoRA**.
- **A** and **B** are new and small. With rank 8, a 2048×2048 projection gains only 2048·8 + 8·2048 ≈ 33 K trainable numbers, instead of 4.2 M.
- **B starts at zero**, so at step 0 the side path adds nothing and the model behaves exactly like the original. Training then learns a low-rank correction ΔW = s·B·A. The smoke test confirms this: at step 0 only B gets a gradient, and A starts moving after the first update.
- **What we adapt:** all 7 projections in all 28 decoder layers of the language model. That is 196 LoRA pairs and 8.7 M trainable parameters, **0.41%** of the model.
- **What stays frozen:**
  - the vision tower, including its own linear layers (no adapters);
  - the vision-language merger;
  - token embeddings;
  - the output head;
  - layer norms;
  - every original weight inside the adapted layers.

  The smoke test checks that a base weight is bit-identical before and after training.
- **Why language-only first:** the Phase 3 diagnostics showed Qwen3-VL-2B already *sees* well. It named every target and separated images correctly. What fails is the *direction*: repeated shots, vague angles, missing pose and light. That is behavior of the language side. `--train-vision` exists in mlx-vlm if a later iteration needs it.
- **The adapter is a separate file:** `data/adapters/<run>/adapters.safetensors` (35 MB), plus `adapter_config.json`. The base model is untouched. At inference time it's loaded with `MLXVLMBackend` as `qwen3-vl-2b-4bit+adapter=data/adapters/<run>`. To ship it, it can be fused into the weights later.

## 3. How the loss is calculated

Each training row is one conversation turn exactly as the app will ask it: a **user turn** (prompt text, plus at most one photo) and the **assistant turn** (the human-approved answer).

1. The processor's own chat template turns the row into one token sequence:
   `<|im_start|>user … <|vision_start|><|image_pad|>×690<|vision_end|> … <|im_end|><|im_start|>assistant {answer} <|im_end|>`.
   The smoke test asserts that the prompt part is **byte-identical** to what the benchmark sends at inference time.
2. The model reads tokens 0…n-1 and outputs, at each position, a probability distribution over the ~151 K-token vocabulary for the *next* token.
3. **Cross-entropy:** at each position *t* we take −log P(correct token at t+1). If the model gave the correct next token probability 0.9, the loss there is 0.105. At 0.01 it is 4.6.
4. **Completion mask:** only positions inside the assistant answer count. Prompt text and the ~400–700 image tokens are inputs, never targets, so the model isn't taught to reproduce prompts or "predict" image placeholders. In the smoke test, a row with 489 tokens had **22 supervised tokens**, and none of them were image tokens.
5. **Loss** = the mean of those per-token losses over all supervised tokens.

Gradients of this loss flow backward through the frozen network into A and B. They don't modify the frozen layers, but the backward pass does go through them. The **AdamW** optimizer nudges A and B to make the approved answer's tokens more likely. Other settings:
- the learning rate warms up, then follows a cosine decay;
- gradient norms are clipped to 1.0;
- 4 rows are accumulated per update, since every row has a different length.

**How the model learns from our photography examples:** after seeing many rows where, say, a low-angle inspiration set and a staircase lead to a camera "at knee height on the bottom step, tilted up 15°", the most probable continuation in similar situations shifts toward that kind of concrete instruction. Each kind of row teaches something different:

| row stage | the model learns to… |
|---|---|
| `notes` (1 inspiration photo) | state camera height and angle, framing, placement, pose and light for a single photo |
| `target_scene` (target photo) | list only what's visible: scene awareness and fewer hallucinations |
| `aesthetic` (text only) | turn notes into transferable principles written as instructions |
| `compositions` (target photo + JSON) | produce three *different*, grounded, followable shots with pose and light direction |

**What a lower loss does and doesn't mean.** Training loss falls whenever the model memorizes its rows. **Validation loss** (rows from different photographers, never trained on) only falls when it generalizes, and even then it measures *imitation of our labels*, not photographic quality. That's why the final judgment is the unchanged Phase 3 benchmark with blind human ratings (§7).

## 4. Training data pipeline

```
datasets/train_v1/spec.json (committed)
   │  photo-ai train-data pool      Commons API search, CC0 Unsplash category, 36 queries
   ▼
data/train_v1/pool.json  (821 candidates, licence + author + source per image)
   │  photo-ai train-data fetch     deterministic sample, sha256, dHash; exclude held-out near-duplicates; split by author
   ▼
data/train_v1/images/*.jpg (290 images, 245 photographers, train 239 / valid 51)
   │  tags (AI-drafted, provisional): camera_angle, framing, pose, facing, placement, light, setting | place elements
   ▼
data/train_v1/tags.json
   │  photo-ai train-data assemble  3–4 inspiration photos sharing a technique + a different target place, same split
   ▼
data/train_v1/examples.json
   │  reference answers drafted by Claude (subagents or `train-data draft` via API) → status "draft"
   ▼
data/train_v1/labels/<id>.json   ──►  Label tab: human edits / approves / rejects
   │  photo-ai train-data export    ONLY approved labels; rendered with the exact inference prompts
   ▼
data/train_v1/sft/{train,valid}.jsonl  ──►  photo-ai lora train --config configs/lora_pilot.json
```

**Licensing.** Every image is CC0, from Wikimedia Commons' *Category:Images from Unsplash* (Unsplash photos published before June 2017). The pool records author, licence, licence URL and source page for each image, and `photo-ai train-data attribution` prints them. No Instagram or Xiaohongshu content is used, and nothing is scraped from a social platform. The photos show identifiable people, so use them for local training and evaluation only, and review personality rights before publishing outputs.

**Held-out protection.** The 14 Phase 3 scenarios stay untouched as the evaluation set:
1. Any image whose Commons title is in the portrait_v1 manifest is dropped from the pool.
2. Every pool image is compared with all 69 held-out images by an 8×8 difference hash, then confirmed with a 16×16 hash. A one-stage check flagged a sunset silhouette as a "duplicate" of a fashion shot, so both stages are required.
3. No Phase 3 model output is ever used as a label.

**Train and validation split.** The split is by photographer, so one shoot never ends up on both sides, and examples are assembled within a split.

**Technique balance.** The first assembly took the biggest technique groups first and produced 12 of 19 "eye-level half-body" examples. Assembly is now round-robin across techniques with a per-technique cap, rarest first. The pool is still eye-level-heavy (137 of 163 usable people photos), so low and high angles need targeted collection before scaling (§9).

## 5. Labels: drafts versus approved

| | drafted by AI | approved by a human |
|---|---|---|
| status | `draft` | `approved` |
| provenance | `drafted_by: ai-draft:<model>` | `approved_by: <your name>`, `approved_at` |
| exported for training | **never** (except `--include-unapproved` into a separate `sft-UNREVIEWED-smoke` folder, used only for the plumbing test) | yes |

The code enforces these rules:
- Only a human name can approve. `claude-*` names are refused.
- An answer with schema errors can't be approved.
- Editing an approved label sends it back to `draft`.
- Every action is recorded in the label's history.

The Label tab shows heuristic warnings for each draft: repeated shots, fewer than 3 concrete cue types, no pose or light direction, evidence that doesn't name anything in the target, and generic or copied phrasing. These warnings help the reviewer; they are not a gate. The standard is [`annotation-guide.md`](annotation-guide.md).

## 6. Training configuration (`configs/lora_pilot.json`)

| setting | value | why |
|---|---|---|
| rank / alpha / dropout | 8 / 16 / 0.05 | small enough to resist overfitting a few hundred rows |
| targets | q,k,v,o,gate,up,down in all 28 layers | where the "direction" behavior lives |
| learning rate | 1e-4, 10 warm-up steps, cosine decay | standard for LoRA on 2–3 B models |
| batch | 1 row, gradient accumulation 4 | rows have different lengths and image counts |
| max_side | 768 px | about 45% fewer image tokens than 1024 px; quality impact to be checked in evaluation |
| eval / save | every 15 / 30 steps; best-validation adapter kept | |
| early stop | 3 evaluations without validation-loss improvement | guards against memorizing a small set |
| cache_limit_gb | 2 | stops MLX's buffer cache from pushing the Mac into swap (§8) |

Outputs go to `data/adapters/<run>/`:
- `adapters.safetensors`: the best by validation loss;
- `adapter_config.json`;
- `train_config.json`;
- `train_log.jsonl`: per step, the loss, gradient norm, learning rate, peak memory and elapsed time;
- `checkpoints/`;
- `summary.json`.

## 7. How the fine-tuned model will be judged

1. **Benchmark:** the unchanged Phase 3 held-out benchmark: 14 portrait_v1 cases, `decomposed` strategy, prompt v4, keys JSON format, greedy decoding. The baseline is `bench-phase3-keys` (Qwen3-VL-2B). The fine-tuned run adds `qwen3-vl-2b-4bit+adapter=data/adapters/pilot-v1`. Base and fine-tuned should both be re-run in the same session, so latency and memory compare like for like.
2. **Measured checks:** validity, latency, peak memory, invented objects, concrete cue types, shot diversity, generic phrases, evidence grounding.
3. **Subjective checks:** your **blind** rubric scores (Evaluate tab) and blind side-by-side choices (Compare tab). Reports separate human ratings from AI-reviewer ratings, so neither stands in for the other.
4. **Rules:**
   - No improvement is claimed from lower training loss.
   - No improvement is claimed from longer outputs. The report tracks generation tokens, and the rubric rewards correctness, not length.
   - Format reliability, speed and memory regressions are reported alongside any gains.

## 8. Status (2026-11-09)

**Done:** the training-data infrastructure, the approval workflow, and a passing LoRA feasibility smoke test.

**Not run yet:** the LoRA pilot. Nothing has been approved, so there is no training data. This is on purpose.

### Data

| item | count |
|---|---|
| Candidate images found (Commons, CC0 Unsplash) | 821 |
| Downloaded (deterministic starter sample) | 290, from 245 photographers, all CC0 |
| Excluded as held-out near-duplicates | 0. The first one-stage check flagged 3, all false positives on inspection, and the two-stage check fixed them. All 69 held-out images were checked. |
| Split by photographer | train 239 / valid 51 |
| AI-drafted tags | 290 / 290. 178 people (163 usable), 72 places, 40 rejected as non-portrait (animals, still life, abstract) |
| Technique balance (usable people) | eye-level 137, high 13, low 12, overhead 1 |
| Examples assembled | 22: 19 train, 3 valid. Techniques: low and high angle; walking, sitting and leaning poses; silhouette; window; golden-hour and night light |
| Reference answers drafted by Claude (provisional) | 22. Heuristic warnings on 4 (3 inspiration notes missing a framing or angle word, 1 ungrounded evidence list) |
| **Approved by a human** | **0** |

The drafters flagged several weak examples for your review. t003, t006, t014 and v002 are candidates to reject. Common problems:
- an inspiration set that only loosely shares a technique;
- a target with no visible ground;
- a target whose light can't support the technique, such as golden-hour backlight paired with a night photo.

These notes are attached to each label in the Label tab.

### LoRA smoke test

Run on 4 real rows (one of each stage) from the unreviewed drafts. Report: `data/adapters/smoke-UNREVIEWED/smoke_report.json`.

| check | result |
|---|---|
| architecture | **pass**. 196 LoRA layers (q,k,v,o,gate,up,down × 28); 8.72 M trainable = 0.41% of 2,127.5 M; vision tower (407 M) has 0 trainable tensors |
| template parity | **pass**. Training prompt prefix is byte-identical to the benchmark's inference prompt for every row |
| masking | **pass**. Supervised tokens: notes 89/532, target 220/782, aesthetic 355/929, compositions 1,138/2,713; 0 image tokens supervised |
| gradients | **pass**. Finite loss 2.53; only LoRA tensors get gradients; B nonzero at step 0, A nonzero after step 1 |
| learning | **pass**. Mean loss 2.21 → 0.43 after 16 steps on 4 rows (overfitting on purpose); a frozen base weight is bit-identical afterwards |
| checkpoint | **pass**. A fresh base model + saved adapter reproduces the trained loss exactly (0.4299); base model loss 2.05; adapter 34.9 MB |
| inference with adapter | **pass**. Generation through `MLXVLMBackend` works. Unfused adapter: 57 tok/s vs base 105 tok/s |
| practicality | **pass** (after two fixes below). Peak 7.97 GB; ~5.4 s per row on average; ~11 min per epoch of 128 rows |

**Two problems the smoke test caught and fixed:**
1. **Swap thrash.** MLX's buffer cache grew to 8–9 GB per step. On this Mac, swap was already 21 of 23.5 GB full, so steps that should take 3 s took 20–60 s. Capping the cache at 2 GB (`cache_limit_gb`) gave steady times.
2. **Long rows exceeded RAM.** Compositions rows run about 2.7–3.0 K tokens, with about 1.1–1.3 K supervised. They peaked at 18.6–19.1 GB, more than the Mac has. **Gradient checkpointing** (`grad_checkpoint`, recomputing each layer's activations during backprop) brought the longest row to 8.4 GB and 12 s per step.

**Feasibility verdict:** LoRA on Qwen3-VL-2B 4-bit is practical on this M3 Pro / 18 GB with mlx-vlm 0.7.12. No alternative framework or base model is needed. A 150-step × 4-row pilot is about 55 minutes. Close other heavy processes while it runs. During the smoke test, another project's test runner was competing for CPU, and macOS swap was already near full.

### What needs your review before the pilot

1. Run `uv run photo-ai ui`, open the **Label** tab and review the 22 drafts:
   - fix or approve the good ones;
   - reject the weak ones;
   - follow [`annotation-guide.md`](annotation-guide.md).
2. **Minimum for a meaningful pilot:** about 15 approved training examples (about 90 rows) and the 3 validation examples. Fewer than that, and the pilot will mostly measure memorization.
3. Then run:
   - `photo-ai train-data export` (approved labels only);
   - `photo-ai lora train --config configs/lora_pilot.json`;
   - the held-out evaluation (§7).

### Reserve batch (batch 2, 2026-11-10)

The first review batch has little slack. The pilot needs about 15 approved training examples and all 3 validation examples. Batch 1 has 19 and 3, so rejecting 5 training examples, or any 1 validation example, would block the pilot. A reserve batch is ready so a second review round can start right away. It goes out only if it's needed.

| item | count |
|---|---|
| Extra photos downloaded | 69, all validation-split photographers (53 people, 16 places), same CC0 Commons source. They were downloaded because no validation photos were left unused. Every held-out image was re-checked. One unused *training* photo was then excluded as a near-duplicate of a new validation photo, so no shoot spans both splits. |
| Tags for the new photos | 69, drafted by AI (provisional) |
| Reserve examples | 13 (`train_v1-rt201…rt210`, `train_v1-rv201…rv203`), all marked `"batch": 2`. They use only photos that no batch-1 example uses, and batch-1 examples were not changed. |
| Reference answers drafted (provisional) | 13. Heuristic warnings on 3 (inspiration notes with a missing framing or angle word) |
| Drafter flags | rv201 and rt203 are likely rejects (loose set, or a target with no visible ground). rt205 has one shot on a public road's centre line. rt202's target has a stranger in frame. |

How to build and use it:

```bash
photo-ai train-data assemble --reserve --n-train 10 --n-valid 3     # appends batch 2; refuses to rebuild examples.json
photo-ai train-data review-site --target vercel --batch 2           # -> data/train_v1/review_site_vercel_batch2/
photo-ai train-data import-review --file <her json>                 # same import for either batch
```

Deploy batch 2 to its own address, separate from batch 1. Answers are saved in the reviewer's browser for each site, so batch 1 progress stays where it is. A plain `assemble` now refuses to run when `examples.json` already exists, because rebuilding it would leave existing labels attached to examples that no longer exist.

## 9. Next iteration

- **Review first.** Approve or fix the 22 drafts. Their reviewer notes show the assembly's weak spot.
- **Choose targets that fit the technique.** The assembler picks target places at random, so some pairings can't work (backlight or golden hour against a night photo, seated poses against a facade with no ground). Next version: match target tags to technique, such as daylight and an open sky for backlit sets, sit-able elements for seated sets, and visible ground for full-body sets.
- **Fix the angle imbalance.** Only 12 of 163 usable people photos are low-angle. Add targeted queries ("low angle portrait", "worm's eye", "from below", "overhead portrait") or raise the per-query cap for angle-specific queries before scaling.
- **Scale up gradually.** Only after the first approved batch shows a held-out improvement: draft about 60 more examples (`train-data draft` via the API, with cost approved per batch), keep about 20% in validation, and stay split by photographer.
- **Fuse the adapter before latency tests.** The unfused adapter runs generation at about 55% of base speed. Fusing ΔW into the weights and re-quantizing should bring speed back to base. Measure before claiming any latency number.
- **Weight the stages.** If time is tight, oversample `compositions` rows. Most Phase 3 failures are there. But keep `notes` and `target_scene` rows, so scene awareness and hallucination behavior don't regress.
- **Consider training the vision tower only if the evaluation shows misread angles.** For example, if fine-tuned notes still call low-angle photos "eye level", try `--train-vision` with a lower learning rate.
