# Speeding up the Mac as the local Director API

Status: research, 2026-11-14. Measured on the benchmark Mac (Apple M3 Pro, 14-core GPU, 18 GB, ~150 GB/s memory
bandwidth, on AC power, Low Power Mode off), mlx 0.32.4, mlx-vlm 0.7.12. Probe scripts were scratch work; the
benchmarks are under `runs/benchmarks/` (git-ignored).

## Where the time goes today

One inspiration analysis with the 2B reasoning adapter (`photo-ai server` runs the decomposed shot-v3 pipeline)
takes about **57 s** on this Mac. Token counts from bench `reason-r16-v3-20261112`, median per run:

| stage | calls | prompt tokens | generated tokens |
|---|---|---|---|
| photo notes | 4 | 731 each | 72 each |
| target scene | 1 | 850 | 166 |
| aesthetic from notes | 1 | 634 | 316 |
| compositions (3 looks) | 1 | 2,427 | 1,285 |

Prefill (reading the prompt and image) is about 11 s of the 57 s. **Decoding (writing the answer) is about 75%
of the time**, and the compositions call alone is about half. Scene mode is similar: one scene call (~180 tokens)
then one call per look (~500 tokens each, run one after another, ~8 s each), 41 s median with the base 2B.

So speed comes from two levers: **fewer generated tokens** and **more tokens per second**.

## What was measured

Decode speed, tokens/s, idle Mac, same prompts (beach-lifestyle case):

| model | short stages | compositions |
|---|---|---|
| 2B base, no adapter | 94-99 | 80 |
| 2B + reasoning adapter, unfused (served today) | 51-56 | 35-44 |
| 4B base, no adapter | 42-45 | 42 |
| 4B + reasoning adapter, unfused | 27-29 | 24-26 |

The unfused LoRA adapter costs about **40% of decode speed** (196 extra small matrix multiplies per token on 2B,
252 on 4B). Fixing that is the biggest single lever, but the obvious fix does not work:

### Fusing the adapter into the 4-bit weights loses the training

`LoRALinear.fuse()` adds the adapter to the dequantized weights and re-quantizes to 4-bit. It restores base
speed, but the adapter's change is mostly smaller than the 4-bit rounding step, so most of it is rounded away:

| variant (2B) | decode t/s | output vs unfused adapter |
|---|---|---|
| unfused adapter | 52 | reference |
| fused, re-quantized 4-bit | 84 | different (text similarity 0.1-0.2, about the same as the base model) |
| fused, 8-bit | 58 | same opening, then greedy drift (0.6-1.0) |
| fused, unquantized | 36 | close (0.4-0.65) |

On the 14-case benchmark the fused 4-bit 2B model was **no faster end to end and broken**: 8/14 valid (adapter:
14/14), and its compositions call usually ran to the 2,600-token cap (median 4,003 generated tokens vs 2,104),
so the analysis took 62 s instead of 57 s. The 4B behaves the same way (fused 4-bit 42 t/s but loses the adapter;
fused 8-bit faithful but no faster than unfused, 26 t/s).

**Consequence for the phone plan:** `docs/hybrid-director-plan.md` step 5 expects that fusing the 2B adapter in
Swift (`fuse(with:)`) brings speed back to base speed. If Swift re-quantizes to 4-bit the same way, the speed
will come back and the adapter's behaviour will mostly not. Check output fidelity there, not only speed.

### Batching independent calls: not usable yet

mlx-vlm's `batch_generate` runs several prompts in one decode loop:

- **Inspiration first stages** (4 photo notes + target scene, already independent): 18.9 s sequential vs 18.8 s
  batched. No gain, because the photos have different shapes and are processed in separate groups.
- **Scene looks** (5 looks, batched without the "earlier looks" summary each look normally sees): 45.7 s ->
  30.9 s (aggregate 152 t/s). But the batched outputs were wrong: 2 of 5 came back in Chinese and none matched the
  sequential output. mlx-vlm 0.7.12's batch path does not handle Qwen3-VL's prompts correctly. Batching all
  looks also means no look reaches the phone until all are done.

### Speculative decoding: not available for this model family

mlx-vlm 0.7.12 supports DFlash/EAGLE-3/MTP drafters, but the Qwen3-VL language model lacks the cache rollback
they need (`rollback_speculative_cache`), and published drafters target Qwen3.5 (for example a Qwen3.5-4B DFlash
drafter). It is an option only with a switch to Qwen3.5 and retraining.

### The 4B benchmark time was inflated

The 4B benchmark measured 142 s per analysis because it ran right after 3 hours of training with ~17 GB of swap
in use (decode 18 t/s). On an idle Mac the same 4B adapter decodes at 24-29 t/s, about **97 s** per analysis.

## Estimated time per inspiration analysis

Benchmark token counts x speeds measured on the idle Mac. The model is calibrated: it predicts 56 s for today's
2B adapter, which measured 57 s.

| setup | full analysis | first shot, if looks stream |
|---|---|---|
| 2B adapter, unfused (today) | ~56 s | ~37 s |
| 2B base, no adapter (speed ceiling for 2B on this Mac) | ~35 s | ~24 s |
| 4B adapter, unfused, idle Mac | ~97 s | ~67 s |
| 4B base, no adapter (speed ceiling for 4B) | ~63 s | ~45 s |

## Recommendations, in order

1. **Keep the server Mac free of training and other heavy jobs.** Swap after training cut the 4B's speed by a
   third. Cheap guard: have `/v1/health` report memory pressure, and refuse new work while swapping heavily.
2. **Stream inspiration-mode looks as they are written. Done (2026-11-14).** When a listener is attached (the
   server), the compositions call streams its text, and each look is validated on its own and sent as soon as its
   JSON object closes (`parsing.ArrayItemStream`, `pipeline._look_streamer`). Benchmarks and the CLI keep the
   non-streaming path. Streaming produces the same text as before (checked token for token). Measured through
   the real server with the base 2B on beach-lifestyle: shots arrived at 37.6 s, 46.8 s and 59.1 s, where all
   three used to arrive together at ~59 s. Scene mode already sent one look at a time.

   Found while testing: the 2B reasoning adapter (`bootstrap-r16-reasoning-UNREVIEWED`) no longer works with the
   current prompts. It was trained and benchmarked on prompt version 2026-11-12.7. With 2026-11-13.10, it writes
   only the four reasoning fields per look and skips `title` and the camera fields, so every inspiration request
   fails validation, streamed or not. Serve the base model, or retrain the adapter on the current prompts.
3. **Generate fewer tokens.** 26% of compositions output (~340 of ~1,330 tokens) is JSON keys and punctuation
   across 21 fields per look. Shorter keys, fewer fields (for example dropping `steps`, which restates the camera
   fields), or a compact line format converted to JSON on the server cut decode time about one-for-one. This
   needs prompt, schema and label changes plus retraining, so do it with the next label revision.
4. **Make the adapter cheaper without fusing.** Options to test, cheapest first: train on fewer modules (for
   example attention only, or rank 8); fuse into the unquantized base and then quantize with a calibrated method
   (mlx DWQ/AWQ-style) instead of plain rounding; or briefly fine-tune the fused 4-bit model again to recover
   the adapter. Any of these must pass the 14-case benchmark with 14/14 valid before serving it.
5. **Use 4B on the Mac only if quality justifies ~1.7x the time.** Fused 8-bit does not speed it up.
6. **Hardware is the remaining multiplier.** Decode for these models is limited mostly by memory bandwidth.
   M4 Pro (~273 GB/s) and M4 Max (~546 GB/s) should be roughly 1.5-3x faster than this M3 Pro (estimate, not
   measured). A cloud GPU remains the route to the "online is fast" target in `hybrid-director-plan.md`.
7. **Revisit later:** batching once mlx-vlm fixes Qwen3-VL batch output (scene looks would save about a third),
   and speculative decoding if the project moves to Qwen3.5.
