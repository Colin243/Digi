"""LoRA feasibility smoke test on real image+text rows. Writes <out>/smoke_report.json.

Checks, in order (each recorded pass/fail with numbers):
  1 architecture   LoRA attaches to the language-model Linear layers; vision tower stays frozen
  2 template       the training prompt prefix equals the exact inference prompt (MLXVLMBackend)
  3 masking        loss covers only answer tokens; no image tokens in the supervised span
  4 gradients      finite loss; LoRA B gets gradient at step 0; frozen base weights never change
  5 learning       a short overfit on a few rows lowers the loss (the loop can learn)
  6 checkpoint     adapter saves; a FRESH base + saved adapter reproduces the trained loss
  7 inference      generation through the benchmark backend works with the adapter; timing vs base
  8 practicality   peak unified memory, seconds per optimizer step, projected pilot duration

The rows used here may be unreviewed drafts: that is fine for testing the plumbing and is
recorded in the report. A smoke adapter is never used for evaluation.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

from .lora import LoraConfig, build_batch, evaluate, grad_norm, load_for_training, loss_fn, parameter_report, read_rows, save_adapter


def _prompt_text(user_msg: dict) -> tuple[str, int]:
    from ..backends import IMAGE_MARKER

    parts, n = [], 0
    for c in user_msg["content"]:
        if c["type"] == "image":
            parts.append(IMAGE_MARKER)
            n += 1
        else:
            parts.append(c["text"])
    return "".join(parts), n


def run_smoke(cfg: LoraConfig, n_rows: int = 4, overfit_steps: int = 12, log=print) -> dict:
    import mlx.core as mx
    import mlx.nn as nn
    import mlx.optimizers as optim
    from mlx.utils import tree_flatten

    from ..backends import resolve_spec
    from ..backends.base import GenerationParams
    from ..backends.mlx_backend import MLXVLMBackend

    out = cfg.out_dir
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"config": cfg.__dict__, "checks": {}}

    def check(name, ok, **info):
        report["checks"][name] = {"pass": bool(ok), **info}
        log(f"[{'PASS' if ok else 'FAIL'}] {name}: {json.dumps(info, default=str)[:300]}")

    from ..cases import PROJECT_ROOT

    data_dir = PROJECT_ROOT / cfg.data_dir
    rows_all = read_rows(data_dir / "train.jsonl") + read_rows(data_dir / "valid.jsonl")
    # prefer one row per stage so every call type is exercised
    rows, seen = [], set()
    for r in rows_all:
        if r["meta"]["stage"] not in seen:
            rows.append(r)
            seen.add(r["meta"]["stage"])
    rows = (rows + [r for r in rows_all if r not in rows])[:n_rows]
    report["rows"] = [r["meta"] for r in rows]
    report["rows_are_unreviewed_drafts"] = any(r["meta"].get("label_status") != "approved" for r in rows)

    mx.set_cache_limit(int(cfg.cache_limit_gb * 1024**3))
    mx.reset_peak_memory()
    t0 = time.perf_counter()
    model, processor = load_for_training(cfg)
    report["load_s"] = round(time.perf_counter() - t0, 1)

    # 1 architecture
    pr = parameter_report(model)
    check("architecture", pr["lora_layers"] > 0 and pr["vision_tower_trainable_tensors"] == 0, **pr,
          model_class=type(model).__name__, base_quantization=getattr(model.config, "quantization", None))

    # 2 template parity with inference
    backend = MLXVLMBackend(resolve_spec("qwen3-vl-2b-4bit"))
    backend._model, backend._processor = model, processor  # reuse loaded weights; no adapter effect on text
    mismatches = []
    for r in rows:
        text, n = _prompt_text(r["messages"][0])
        infer = backend.format_prompt(text, n)
        train_prefix = processor.apply_chat_template(r["messages"][:-1], add_generation_prompt=True, tokenize=False)
        if infer != train_prefix:
            mismatches.append(r["meta"])
    check("template_parity", not mismatches, rows_checked=len(rows), mismatches=mismatches)

    # 3 masking
    cache = out / "image_cache"
    cache.mkdir(exist_ok=True)
    batches = [build_batch(processor, model.config, r, cfg.max_side, cache) for r in rows]
    itok = getattr(model.config, "image_token_id", None) or getattr(model.config, "image_token_index", None)
    mask_info = []
    ok_mask = True
    for b, r in zip(batches, rows):
        import numpy as np

        ids, cm = np.array(b["input_ids"][0]), np.array(b["completion_mask"][0]).astype(bool)
        sup = ids[cm]
        n_img_sup = int((sup == itok).sum()) if itok is not None else 0
        decoded = processor.tokenizer.decode(sup.tolist())
        answer = r["messages"][1]["content"][0]["text"]
        ok = n_img_sup == 0 and decoded.strip().startswith(answer[:40].strip())
        ok_mask &= ok
        mask_info.append({"stage": r["meta"]["stage"], "tokens_total": b["_n_total"], "tokens_supervised": int(cm.sum()),
                          "image_tokens_in_prompt": int((ids == itok).sum()) if itok is not None else 0,
                          "image_tokens_in_supervised": n_img_sup, "supervised_starts_with_answer": ok})
    check("masking", ok_mask, rows=mask_info)

    # 4 gradients + frozen base
    value_and_grad = nn.value_and_grad(model, lambda m, b: loss_fn(m, b)[0])
    frozen_name, frozen_before = None, None
    for name, v in tree_flatten(model.parameters()):
        if "language_model" in name and name.endswith("q_proj.linear.weight"):
            frozen_name, frozen_before = name, mx.array(v)
            break
    loss0, grads = value_and_grad(model, batches[0])
    mx.eval(loss0, grads)
    flat = dict(tree_flatten(grads))
    b_norm = sum(float(mx.sum(v.astype(mx.float32) ** 2)) for k, v in flat.items() if k.endswith("lora_b")) ** 0.5
    a_norm = sum(float(mx.sum(v.astype(mx.float32) ** 2)) for k, v in flat.items() if k.endswith("lora_a")) ** 0.5
    check("gradients", bool(mx.isfinite(loss0)) and b_norm > 0, loss=float(loss0), grad_norm_total=grad_norm(grads),
          grad_norm_lora_b=b_norm, grad_norm_lora_a=a_norm,
          note="lora_a has zero gradient at step 0 because B starts at 0; it becomes nonzero after the first update",
          gradient_tensors=len(flat), only_lora_tensors=all(("lora_a" in k or "lora_b" in k) for k in flat))

    # 5 learning: short overfit
    opt = optim.AdamW(learning_rate=2e-4)
    model.train()
    losses, step_times = [], []
    mx.reset_peak_memory()
    for step in range(overfit_steps):
        b = batches[step % len(batches)]
        ts = time.perf_counter()
        loss, g = value_and_grad(model, b)
        opt.update(model, g)
        mx.eval(model.parameters(), opt.state, loss)
        step_times.append(time.perf_counter() - ts)
        losses.append(float(loss))
    model.eval()
    first = sum(losses[: len(batches)]) / len(batches)
    last_eval = evaluate(model, batches)
    frozen_after = dict(tree_flatten(model.parameters())).get(frozen_name)
    base_unchanged = frozen_after is not None and bool(mx.array_equal(frozen_before, frozen_after))
    _, g_after = value_and_grad(model, batches[0])
    a_after = sum(float(mx.sum(v.astype(mx.float32) ** 2)) for k, v in tree_flatten(g_after) if k.endswith("lora_a")) ** 0.5
    check("learning", last_eval < first and base_unchanged and a_after > 0,
          mean_loss_first_pass=first, loss_after_steps=last_eval, losses=[round(x, 4) for x in losses],
          frozen_weight_checked=frozen_name, frozen_weight_unchanged=base_unchanged, grad_norm_lora_a_after=a_after,
          peak_memory_training_gb=round(mx.get_peak_memory() / 1e9, 2),
          seconds_per_row_step=round(sum(step_times[1:]) / max(len(step_times) - 1, 1), 2),
          step_seconds=[round(x, 2) for x in step_times], cache_limit_gb=cfg.cache_limit_gb)

    # 6 checkpoint round trip in a fresh model instance
    adapter_file = out / "adapters.safetensors"
    size = save_adapter(model, adapter_file)
    trained_loss = evaluate(model, batches)
    from mlx_vlm import load

    del model
    mx.clear_cache()
    fresh, fresh_proc = load(cfg.base_model, adapter_path=str(out))
    reloaded_loss = evaluate(fresh, [build_batch(fresh_proc, fresh.config, r, cfg.max_side, cache) for r in rows])
    del fresh
    mx.clear_cache()
    base_only, base_proc = load(cfg.base_model)
    base_loss = evaluate(base_only, [build_batch(base_proc, base_only.config, r, cfg.max_side, cache) for r in rows])
    check("checkpoint", abs(reloaded_loss - trained_loss) < 1e-2 and base_loss > reloaded_loss,
          adapter_file=str(adapter_file), adapter_mb=round(size / 1e6, 2),
          files=sorted(p.name for p in out.iterdir() if p.is_file()),
          trained_loss=trained_loss, reloaded_loss=reloaded_loss, base_model_loss=base_loss)

    # 7 inference with adapter through the benchmark backend
    from ..prompts import target_scene_only

    tgt_row = next((r for r in rows if r["meta"]["stage"] == "target_scene"), rows[0])
    img = _resized_first(tgt_row, cfg.max_side, cache)
    timings = {}
    texts = {}
    for label, backend_ in (("base", MLXVLMBackend(resolve_spec("qwen3-vl-2b-4bit"))),
                            ("adapter", MLXVLMBackend(replace(resolve_spec("qwen3-vl-2b-4bit"), adapter_path=str(out))))):
        backend_._model, backend_._processor = (base_only, base_proc) if label == "base" else (None, None)
        if label == "adapter":
            del base_only
            mx.clear_cache()
            backend_.load()
        backend_.generate(target_scene_only(), [img] if img else [], GenerationParams(max_tokens=8))  # warm-up
        ts = time.perf_counter()
        gen = backend_.generate(target_scene_only(), [img] if img else [], GenerationParams(max_tokens=200))
        timings[label] = {"wall_s": round(time.perf_counter() - ts, 2), "gen_tps": gen.generation_tps,
                          "peak_gb": gen.peak_memory_gb, "tokens": gen.generation_tokens}
        texts[label] = gen.text[:300]
        backend_.unload()
    check("inference_with_adapter", bool(texts.get("adapter")), timings=timings, sample_outputs=texts,
          note="smoke adapter overfit on a few unreviewed rows; output quality here is meaningless")

    # 8 practicality
    spr = report["checks"]["learning"]["seconds_per_row_step"]
    pilot_rows = 96
    proj = {"seconds_per_row_forward_backward": spr,
            "projected_minutes_per_epoch_96_rows": round(pilot_rows * spr / 60, 1),
            "projected_minutes_200_steps_x4_accum": round(200 * 4 * spr / 60, 1),
            "peak_memory_training_gb": report["checks"]["learning"]["peak_memory_training_gb"],
            "machine_memory_gb": 18, "grad_checkpoint": cfg.grad_checkpoint,
            "longest_row_tokens": max(b["_n_total"] for b in batches)}
    check("practicality", proj["peak_memory_training_gb"] < 12, **proj)
    report["all_pass"] = all(c["pass"] for c in report["checks"].values())
    (out / "smoke_report.json").write_text(json.dumps(report, indent=1, default=str))
    return report


def _resized_first(row: dict, max_side: int, cache: Path) -> str | None:
    from .lora import _resized

    return _resized(row["images"][:1], max_side, cache)[0] if row["images"] else None
