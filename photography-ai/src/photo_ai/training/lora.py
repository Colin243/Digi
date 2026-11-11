"""LoRA fine-tuning of Qwen3-VL-2B (MLX 4-bit) on photography-direction examples.

What happens to the network (details and diagrams: docs/phase4-finetuning.md):
  * The base weights stay frozen: the 4-bit language model, the vision tower and the
    projector are never updated (the vision tower is not even given adapters).
  * Each targeted Linear layer W in the language model gets a low-rank side path:
        y = W x  +  scale * B (A x)        A: r x d_in,  B: d_out x r,  r = rank (e.g. 8)
    B starts at zero, so training starts exactly from the base model's behaviour.
    Only A and B are trained (well under 1% of the parameters).
  * Loss = next-token cross-entropy on the ANSWER tokens only. The prompt and the image
    tokens are inputs, never targets (completion mask), so the model is not taught to
    reproduce prompts or "describe" image placeholders.

Batches are built with the processor's own chat template and mlx-vlm's prepare_inputs,
the same functions MLXVLMBackend uses at inference, and the smoke test asserts that the
training prompt equals the inference prompt for real rows.

  photo-ai lora smoke --config configs/lora_smoke.json
  photo-ai lora train --config configs/lora_pilot.json
"""

from __future__ import annotations

import json
import math
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..cases import PROJECT_ROOT


@dataclass
class LoraConfig:
    run_name: str = "pilot"
    base_model: str = "mlx-community/Qwen3-VL-2B-Instruct-4bit"
    data_dir: str = "data/train_v1/sft"
    output_root: str = "data/adapters"
    targets: list[str] = field(default_factory=lambda: ["q_proj", "k_proj", "v_proj", "o_proj",
                                                         "gate_proj", "up_proj", "down_proj"])
    rank: int = 8
    alpha: float = 16.0
    dropout: float = 0.05
    learning_rate: float = 1e-4
    weight_decay: float = 0.0
    warmup_steps: int = 5
    iters: int = 200
    grad_accum: int = 4
    max_side: int = 768
    max_seq_length: int = 4096
    eval_every: int = 25
    save_every: int = 50
    early_stop_patience: int = 3
    grad_clip: float = 1.0
    seed: int = 0
    # MLX keeps freed buffers in a cache. Uncapped, it grew to 8-9 GB per step on this 18 GB Mac and
    # pushed the system into swap (image rows went from ~3 s to 20-60 s). Capping it fixed that.
    cache_limit_gb: float = 2.0
    # Recompute each decoder layer's activations in the backward pass instead of storing them.
    # Measured on the longest real row (2,971 tokens): peak 19.1 GB -> 8.4 GB, step 37-53 s -> 12 s.
    grad_checkpoint: bool = True
    stages: list[str] = field(default_factory=lambda: ["notes", "target_scene", "aesthetic", "compositions"])

    @classmethod
    def load(cls, path: str | Path) -> "LoraConfig":
        return cls(**json.loads(Path(path).read_text()))

    @property
    def out_dir(self) -> Path:
        return PROJECT_ROOT / self.output_root / self.run_name


# --------------------------------------------------------------------------- data -> batches

def read_rows(path: Path, stages: list[str] | None = None) -> list[dict]:
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [r for r in rows if not stages or r["meta"]["stage"] in stages]


def _resized(paths: list[str], max_side: int, cache_dir: Path) -> list[str]:
    """Same preprocessing as inference (images.prepare): orient, RGB, downscale, strip metadata."""
    from ..images import prepare

    out = []
    for p in paths:
        dest = cache_dir / f"{Path(p).stem}_{max_side}.jpg"
        if not dest.exists():
            prepare(p, dest, "train", max_side)
        out.append(str(dest))
    return out


def build_batch(processor, model_config, row: dict, max_side: int, cache_dir: Path) -> dict:
    """One row -> {input_ids, attention_mask, completion_mask, pixel_values, image_grid_thw, ...}."""
    import mlx.core as mx
    from mlx_vlm.utils import prepare_inputs

    images = _resized(row["images"], max_side, cache_dir) if row["images"] else []
    full = processor.apply_chat_template(row["messages"], add_generation_prompt=False, tokenize=False)
    prefix = processor.apply_chat_template(row["messages"][:-1], add_generation_prompt=True, tokenize=False)
    if not full.startswith(prefix):
        raise ValueError("chat template: full conversation does not start with the prompt prefix")
    itok = getattr(model_config, "image_token_id", None) or getattr(model_config, "image_token_index", None)
    inputs = prepare_inputs(processor, images=images or None, prompts=full, image_token_index=itok)
    prefix_ids = prepare_inputs(processor, images=images or None, prompts=prefix, image_token_index=itok)["input_ids"]
    n_prefix = int(prefix_ids.shape[-1])
    ids = inputs["input_ids"]
    if ids.ndim == 1:
        ids = ids[None]
    T = ids.shape[1]
    completion = (mx.arange(T) >= n_prefix).astype(mx.int32)[None]
    batch = {k: v for k, v in inputs.items() if k not in ("input_ids", "attention_mask")}
    batch.update({
        "input_ids": ids,
        "attention_mask": inputs.get("attention_mask", mx.ones_like(ids)),
        "completion_mask": completion,
    })
    batch["_n_prefix"], batch["_n_total"] = n_prefix, T
    return batch


# --------------------------------------------------------------------------- model

def load_for_training(cfg: LoraConfig):
    """Base model (frozen) + LoRA adapters on the language-model Linear layers."""
    from mlx_vlm import load
    from mlx_vlm.trainer.peft import get_peft_model

    model, processor = load(cfg.base_model)
    model = get_peft_model(model, linear_layers=cfg.targets, rank=cfg.rank, alpha=cfg.alpha,
                           dropout=cfg.dropout, freeze=True, verbose=False)
    if cfg.grad_checkpoint:
        from mlx_vlm.trainer.common.utils import enable_model_gradient_checkpointing

        enable_model_gradient_checkpointing(model.language_model)
    return model, processor


def parameter_report(model) -> dict:
    """Total vs trainable parameters (quantized weights counted at their logical size)."""
    from mlx.utils import tree_flatten
    from mlx_vlm.trainer.core import count_parameters

    total = count_parameters(model) * 1e6
    trainable = dict(tree_flatten(model.trainable_parameters()))
    n_train = sum(v.size for v in trainable.values())
    lora_layers = sorted({k.rsplit(".", 1)[0] for k in trainable})
    vision_total = count_parameters(model.vision_tower) * 1e6 if hasattr(model, "vision_tower") else 0
    return {
        "total_params_M": round(total / 1e6, 1),
        "vision_tower_params_M": round(vision_total / 1e6, 1),
        "trainable_params_M": round(n_train / 1e6, 3),
        "trainable_percent": round(100 * n_train / max(total, 1), 3),
        "trainable_tensors": len(trainable),
        "lora_layers": len(lora_layers),
        "lora_layer_examples": lora_layers[:3],
        "vision_tower_trainable_tensors": sum(1 for k in trainable if k.startswith("vision")),
        "trainable_bytes_fp32_MB": round(n_train * 4 / 1e6, 1),
    }


def loss_fn(model, batch):
    from mlx_vlm.trainer.vlm.sft.runtime import vlm_sft_loss

    clean = {k: v for k, v in batch.items() if not k.startswith("_")}
    loss, metrics = vlm_sft_loss(model, clean, train_on_completions=True)
    return loss, metrics["num_tokens"]


def grad_norm(grads) -> float:
    import mlx.core as mx
    from mlx.utils import tree_flatten

    return float(math.sqrt(sum(float(mx.sum(g.astype(mx.float32) ** 2)) for _, g in tree_flatten(grads))))


def evaluate(model, batches) -> float | None:
    import mlx.core as mx

    if not batches:
        return None
    tot, ntok = 0.0, 0
    for b in batches:
        loss, n = loss_fn(model, b)
        mx.eval(loss, n)
        tot += float(loss) * int(n)
        ntok += int(n)
    return tot / max(ntok, 1)


def save_adapter(model, path: Path) -> int:
    from mlx_vlm.trainer.common.utils import save_trainable_weights

    save_trainable_weights(model, path)
    return path.stat().st_size


# --------------------------------------------------------------------------- training

def train(cfg: LoraConfig, log=print) -> dict:
    import mlx.core as mx
    import mlx.nn as nn
    import mlx.optimizers as optim
    from mlx.utils import tree_map

    mx.random.seed(cfg.seed)
    random.seed(cfg.seed)
    mx.set_cache_limit(int(cfg.cache_limit_gb * 1024**3))
    out = cfg.out_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / "train_config.json").write_text(json.dumps(asdict(cfg), indent=1))
    data_dir = PROJECT_ROOT / cfg.data_dir
    train_rows = read_rows(data_dir / "train.jsonl", cfg.stages)
    valid_rows = read_rows(data_dir / "valid.jsonl", cfg.stages)
    if not train_rows:
        raise SystemExit(f"no training rows in {data_dir}; export approved labels first")
    info = json.loads((data_dir / "export_info.json").read_text()) if (data_dir / "export_info.json").exists() else {}

    mx.reset_peak_memory()
    t0 = time.perf_counter()
    model, processor = load_for_training(cfg)
    load_s = time.perf_counter() - t0
    params = parameter_report(model)
    cache = out / "image_cache"
    cache.mkdir(exist_ok=True)
    train_b = [build_batch(processor, model.config, r, cfg.max_side, cache) for r in train_rows]
    valid_b = [build_batch(processor, model.config, r, cfg.max_side, cache) for r in valid_rows]
    too_long = [b["_n_total"] for b in train_b if b["_n_total"] > cfg.max_seq_length]
    if too_long:
        raise SystemExit(f"{len(too_long)} rows exceed max_seq_length {cfg.max_seq_length} (max {max(too_long)})")

    schedule = optim.join_schedules(
        [optim.linear_schedule(1e-7, cfg.learning_rate, cfg.warmup_steps),
         optim.cosine_decay(cfg.learning_rate, max(cfg.iters - cfg.warmup_steps, 1))], [cfg.warmup_steps])
    opt = optim.AdamW(learning_rate=schedule, weight_decay=cfg.weight_decay)
    value_and_grad = nn.value_and_grad(model, lambda m, b: loss_fn(m, b)[0])
    model.train()

    log_path = out / "train_log.jsonl"
    log_f = open(log_path, "a")
    best_val, bad_evals, history = math.inf, 0, []
    order = list(range(len(train_b)))
    step_t0 = time.perf_counter()
    val0 = evaluate(model, valid_b)
    log_f.write(json.dumps({"step": 0, "val_loss": val0}) + "\n")
    log(f"step 0: val_loss {val0}")
    for step in range(1, cfg.iters + 1):
        acc, losses = None, []
        for _ in range(cfg.grad_accum):
            if not order:
                order = list(range(len(train_b)))
            idx = order.pop(random.randrange(len(order)))
            loss, grads = value_and_grad(model, train_b[idx])
            mx.eval(loss, grads)
            losses.append(float(loss))
            acc = grads if acc is None else tree_map(lambda a, g: a + g, acc, grads)
        acc = tree_map(lambda g: g / cfg.grad_accum, acc)
        gn = grad_norm(acc)
        if cfg.grad_clip and gn > cfg.grad_clip:
            acc = tree_map(lambda g: g * (cfg.grad_clip / gn), acc)
        opt.update(model, acc)
        mx.eval(model.parameters(), opt.state)
        rec = {"step": step, "train_loss": sum(losses) / len(losses), "grad_norm": gn,
               "lr": float(schedule(step)), "peak_memory_gb": mx.get_peak_memory() / 1e9,
               "elapsed_s": time.perf_counter() - step_t0}
        if step % cfg.eval_every == 0 or step == cfg.iters:
            model.eval()
            rec["val_loss"] = evaluate(model, valid_b)
            model.train()
            if rec["val_loss"] is not None:
                if rec["val_loss"] < best_val - 1e-4:
                    best_val, bad_evals = rec["val_loss"], 0
                    save_adapter(model, out / "adapters.safetensors")  # best-so-far
                    rec["saved_best"] = True
                else:
                    bad_evals += 1
        if step % cfg.save_every == 0:
            save_adapter(model, out / "checkpoints" / f"{step:05d}_adapters.safetensors")
        history.append(rec)
        log_f.write(json.dumps(rec) + "\n")
        log_f.flush()
        if step % 5 == 0 or "val_loss" in rec:
            log(f"step {step}: loss {rec['train_loss']:.4f} grad {gn:.3f} "
                f"val {rec.get('val_loss')} peak {rec['peak_memory_gb']:.2f} GB {rec['elapsed_s']:.0f}s")
        if valid_b and bad_evals >= cfg.early_stop_patience:
            log(f"early stop at step {step}: validation loss did not improve for {bad_evals} evaluations")
            break
    log_f.close()
    if not valid_b or not (out / "adapters.safetensors").exists():
        save_adapter(model, out / "adapters.safetensors")
    summary = {
        "run": cfg.run_name, "out_dir": str(out), "data": info, "params": params,
        "train_rows": len(train_b), "valid_rows": len(valid_b), "load_s": round(load_s, 1),
        "steps_done": history[-1]["step"], "train_time_s": round(history[-1]["elapsed_s"], 1),
        "initial_val_loss": val0, "best_val_loss": None if best_val == math.inf else best_val,
        "final_train_loss": history[-1]["train_loss"], "peak_memory_gb": round(mx.get_peak_memory() / 1e9, 2),
        "adapter_mb": round((out / "adapters.safetensors").stat().st_size / 1e6, 2),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary
