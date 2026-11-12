"""TrainingMonitor: the only monitor object the training loop talks to.

Per optimizer step (cheap, always):   one "step" event with loss, lr, grad norm, timing and memory.
Every `sample_every` steps (bounded):  one "layer_sample" event with statistics for
                                       `modules_per_sample` LoRA modules, chosen round-robin so all
                                       modules are covered every ceil(n_modules / modules_per_sample)
                                       samples. 0 = all modules each sample.
Never: per-step copies of weights (the "before" values are references to the immutable MLX
arrays the optimizer replaces, kept for sampled modules only until the stats are evaluated),
full gradient histograms, retained graphs, or a second model.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import subprocess
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path

from . import memory
from .architecture import build_architecture, lora_units
from .runlog import LOG_SCHEMA, LOG_VERSION, RunLogWriter
from .stats import DIST_KEYS, clean, distribution, fro, lowrank_diff_fro, lowrank_fro, ratio


@dataclass
class MonitorConfig:
    enabled: bool = True
    sample_every: int = 5          # optimizer steps between layer samples
    modules_per_sample: int = 49   # LoRA modules per sample (196 total -> full coverage every 4 samples)
    max_dist_elems: int = 4096     # entries used for each distribution summary
    queue_size: int = 2048         # buffered events before new ones are dropped
    flush_s: float = 1.0           # writer flush / heartbeat interval
    base_norms: bool = True        # measure ||W0||_F once at start (dequantized, one module at a time)

    @classmethod
    def from_dict(cls, d: dict | None) -> "MonitorConfig":
        d = dict(d or {})
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)


METRIC_DEFINITIONS = {
    "train_loss": {"unit": "nats/token", "cadence": "every optimizer step",
                   "def": "mean over the grad_accum micro-batches of masked next-token cross-entropy on answer tokens"},
    "val_loss": {"unit": "nats/token", "cadence": "step 0, every eval_every steps, and the last step",
                 "def": "token-weighted mean masked cross-entropy over the validation rows (model.eval(), no dropout)"},
    "lr": {"unit": "", "cadence": "every step", "def": "learning rate from the warmup+cosine schedule at this step"},
    "grad_norm": {"unit": "", "cadence": "every step",
                  "def": "global L2 norm of the averaged LoRA gradient BEFORE clipping (clipped when > grad_clip)"},
    "step": {"def": "optimizer step (one update after grad_accum micro-batches)", "cadence": "every step"},
    "epoch": {"def": "training rows consumed / number of training rows", "cadence": "every step"},
    "step_s": {"unit": "s", "cadence": "every step",
               "def": "wall time from the first micro-batch to the evaluated optimizer update; excludes validation and checkpoint saving"},
    "elapsed_s": {"unit": "s", "cadence": "every step", "def": "wall time since the training loop started (after model load and batch building)"},
    "progress": {"def": "step / iters (early stopping can end a run before 1.0)", "cadence": "every step"},
    "mlx_active_gb": {"unit": "GB", "cadence": "every step", "def": memory.__doc__.split("mlx_active_gb")[1].split("mlx_cache_gb")[0].strip()},
    "mlx_cache_gb": {"unit": "GB", "cadence": "every step", "def": "freed MLX buffers kept for reuse (capped by cache_limit_gb); resident but unused"},
    "mlx_peak_gb": {"unit": "GB", "cadence": "every step", "def": "high-water mark of MLX active memory since training started"},
    "proc_footprint_gb": {"unit": "GB", "cadence": "every step",
                          "def": "macOS physical footprint of the training process; ALREADY includes MLX/Metal buffers (unified memory) - do not add the MLX numbers to it"},
    "swap_used_gb": {"unit": "GB", "cadence": "every step", "def": "SYSTEM-wide swap in use (all processes), not this process"},
    "pressure": {"cadence": "every step", "def": "macOS memory-pressure level: 1 normal, 2 warning, 4 critical"},
    "adapter_norm_a": {"cadence": "layer sample", "def": "||A||_F of the LoRA down-projection (d_in x r)"},
    "adapter_norm_b": {"cadence": "layer sample", "def": "||B||_F of the LoRA up-projection (r x d_out); starts at 0"},
    "effective_delta_norm": {"cadence": "layer sample",
                             "def": "||scale * (A B)^T||_F: distance of the layer's effective weight from the frozen base (exact, via r x r Gram matrices)"},
    "effective_delta_rel": {"cadence": "layer sample", "def": "effective_delta_norm / ||W0||_F (W0 dequantized once at start)"},
    "grad_norm_a": {"cadence": "layer sample", "def": "||dL/dA||_F of the averaged pre-clip gradient at that step"},
    "grad_norm_b": {"cadence": "layer sample", "def": "||dL/dB||_F of the averaged pre-clip gradient at that step"},
    "update_norm_a": {"cadence": "layer sample", "def": "||A_after - A_before||_F for that one optimizer step"},
    "update_norm_b": {"cadence": "layer sample", "def": "||B_after - B_before||_F for that one optimizer step"},
    "update_ratio_a": {"cadence": "layer sample", "def": "update_norm_a / ||A_before||_F"},
    "update_ratio_b": {"cadence": "layer sample", "def": "update_norm_b / ||B_before||_F (unavailable while ||B_before|| = 0)"},
    "effective_update_norm": {"cadence": "layer sample", "def": "||dW_after - dW_before||_F: change in effective weight from that one step"},
    "dist_a / dist_b": {"cadence": "layer sample",
                        "def": "mean, std, abs-max, 1/25/50/75/99th percentiles of A (or B) entries from <= max_dist_elems evenly strided entries"},
}

LAYER_FIELDS = ["adapter_norm_a", "adapter_norm_b", "effective_delta_norm", "grad_norm_a", "grad_norm_b",
                "update_norm_a", "update_norm_b", "norm_a_before", "norm_b_before", "effective_update_norm",
                *[f"dist_a_{k}" for k in DIST_KEYS], *[f"dist_b_{k}" for k in DIST_KEYS]]


def sha256_file(path: Path, limit: int | None = None) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _git() -> dict:
    try:
        root = Path(__file__).resolve().parents[4]
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", "photography-ai/src"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return {"commit": head or None, "src_dirty": bool(dirty)}
    except Exception:  # noqa: BLE001
        return {"commit": None, "src_dirty": None}


def base_revision(repo: str) -> dict:
    try:
        from huggingface_hub import snapshot_download

        p = Path(snapshot_download(repo, local_files_only=True))
        return {"repo": repo, "revision": p.name, "local_path": str(p)}
    except Exception as exc:  # noqa: BLE001
        p = Path(repo)
        if p.exists():
            cfg = p / "config.json"
            return {"repo": repo, "revision": f"local:{sha256_file(cfg)[:16]}" if cfg.exists() else "local", "local_path": str(p)}
        return {"repo": repo, "revision": None, "error": str(exc)[:200]}


def rows_hash(rows: list[dict]) -> str:
    h = hashlib.sha256()
    for r in rows:
        h.update(json.dumps(r, sort_keys=True).encode())
        h.update(b"\n")
    return h.hexdigest()


def build_manifest(cfg, mcfg: MonitorConfig, data_dir: Path, train_rows: list, valid_rows: list,
                   kind: str = "train", extra: dict | None = None) -> dict:
    from ... import prompts, schema

    info_path = data_dir / "export_info.json"
    info = json.loads(info_path.read_text()) if info_path.exists() else {}
    try:
        import mlx.core as mx
        import mlx_vlm

        versions = {"mlx": mx.__version__, "mlx_vlm": mlx_vlm.__version__}
    except Exception:  # noqa: BLE001
        versions = {}
    c = asdict(cfg) if hasattr(cfg, "__dataclass_fields__") else dict(cfg)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return {
        "schema": LOG_SCHEMA, "v": LOG_VERSION, "kind": kind,
        "run_id": f"{c.get('run_name')}-{stamp}-{uuid.uuid4().hex[:6]}", "run_name": c.get("run_name"),
        "created": time.time(), "created_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "code": _git(), "versions": versions, "machine": {"platform": platform.platform(),
                                                          "memory_gb": memory.system_memory().get("system_total_gb")},
        "base_model": base_revision(c.get("base_model")),
        "data": {"dir": str(data_dir),
                 "files": {n: sha256_file(data_dir / n) for n in ("train.jsonl", "valid.jsonl", "export_info.json")
                           if (data_dir / n).exists()},
                 "train_rows_used": len(train_rows), "valid_rows_used": len(valid_rows),
                 "train_split_sha256": rows_hash(train_rows), "valid_split_sha256": rows_hash(valid_rows),
                 "stages": c.get("stages"), "export_info": info,
                 "includes_unapproved_drafts": bool(info.get("includes_unapproved_drafts")) or
                 any((r.get("meta") or {}).get("label_status") not in (None, "approved") for r in train_rows + valid_rows),
                 "eval_images_excluded": "enforced upstream by train-data fetch (held-out check), not re-checked here"},
        "versions_prompt_schema": {"prompt_version": prompts.PROMPT_VERSION, "answer_schema_version": schema.SCHEMA_VERSION,
                                   "json_format": info.get("json_format"), "export_prompt_version": info.get("prompt_version")},
        "seed": c.get("seed"),
        "lora": {"targets": c.get("targets"), "rank": c.get("rank"), "alpha": c.get("alpha"),
                 "scale": (c.get("alpha") or 0) / max(c.get("rank") or 1, 1), "dropout": c.get("dropout"),
                 "vision_tower": "frozen, no adapters", "grad_checkpoint": c.get("grad_checkpoint")},
        "optimizer": {"name": "AdamW", "learning_rate": c.get("learning_rate"), "weight_decay": c.get("weight_decay"),
                      "schedule": f"linear warmup 1e-7 -> lr over {c.get('warmup_steps')} steps, then cosine decay",
                      "warmup_steps": c.get("warmup_steps"), "iters": c.get("iters"), "grad_accum": c.get("grad_accum"),
                      "grad_clip": c.get("grad_clip"), "eval_every": c.get("eval_every"), "save_every": c.get("save_every"),
                      "early_stop_patience": c.get("early_stop_patience")},
        "memory_settings": {"cache_limit_gb": c.get("cache_limit_gb"), "grad_checkpoint": c.get("grad_checkpoint"),
                            "max_side": c.get("max_side"), "max_seq_length": c.get("max_seq_length")},
        "train_config": c,
        "monitor": asdict(mcfg),
        "metric_definitions": METRIC_DEFINITIONS,
        **(extra or {}),
    }


class TrainingMonitor:
    def __init__(self, run_dir: Path, mcfg: MonitorConfig):
        self.dir = Path(run_dir)
        self.cfg = mcfg
        self.writer = RunLogWriter(self.dir, mcfg.queue_size, mcfg.flush_s)
        self.units: list[tuple[str, object]] = []
        self.scales: dict[str, float] = {}
        self.base_norm: dict[str, float | None] = {}
        self.cursor = 0
        self.n_samples = 0
        self._pending = None
        self._grads = None
        self.sample_s: list[float] = []
        self.peaks = {"proc_footprint_gb": None, "swap_used_gb": None, "pressure": None}
        self.swap_start = None

    # ---- setup (before the training loop; not timed as step overhead)
    def start(self, model, manifest: dict) -> None:
        self.units = lora_units(model)
        self.scales = {n: float(m.scale) for n, m in self.units}
        arch = build_architecture(model, instrumented={n for n, _ in self.units})
        if self.cfg.base_norms:
            self._measure_base_norms()
        for u in arch["units"]:
            if u["lora"]:
                u["lora"]["base_weight_norm"] = self.base_norm.get(u["name"])
        mem = memory.snapshot()
        self.swap_start = mem.get("swap_used_gb")
        manifest["memory_at_start"] = mem
        manifest["lora"]["resolved_modules"] = len(self.units)
        manifest["sampling"] = {"layer_sample_every_steps": self.cfg.sample_every,
                                "modules_per_sample": self.cfg.modules_per_sample or len(self.units),
                                "full_coverage_every_steps": self.cfg.sample_every * math.ceil(
                                    len(self.units) / max(self.cfg.modules_per_sample or len(self.units), 1)),
                                "step_metrics": "every optimizer step"}
        self.writer.write_json("manifest.json", manifest)
        self.writer.write_json("architecture.json", arch)
        self.writer.extra_status = {"run_id": manifest["run_id"], "iters": manifest["optimizer"]["iters"]}
        self.writer.emit("start", run_id=manifest["run_id"], lora_modules=len(self.units),
                         memory=mem, params={"total": arch["totals"]["total_params"],
                                             "trainable": arch["totals"]["trainable_params"]})

    def _measure_base_norms(self) -> None:
        import mlx.core as mx

        for n, m in self.units:
            lin = getattr(m, "linear", None)
            try:
                if type(lin).__name__ == "QuantizedLinear":
                    w = mx.dequantize(lin.weight, lin.scales, lin.biases, group_size=lin.group_size, bits=lin.bits,
                                      mode=getattr(lin, "mode", "affine"))
                else:
                    w = lin.weight
                v = fro(w)
                mx.eval(v)
                self.base_norm[n] = float(v)
                del w
            except Exception:  # noqa: BLE001
                self.base_norm[n] = None

    # ---- per step
    def is_sample_step(self, step: int) -> bool:
        return self.cfg.sample_every > 0 and step % self.cfg.sample_every == 0 and bool(self.units)

    def before_update(self, step: int, grads) -> None:
        """Call after gradients are accumulated, BEFORE clipping and opt.update. Keeps references only."""
        if not self.is_sample_step(step):
            self._pending = None
            return
        k = self.cfg.modules_per_sample or len(self.units)
        k = min(k, len(self.units))
        idx = [(self.cursor + i) % len(self.units) for i in range(k)]
        self.cursor = (self.cursor + k) % len(self.units)
        from mlx.utils import tree_flatten

        flat = dict(tree_flatten(grads))
        self._pending = [(self.units[i][0], self.units[i][1], self.units[i][1].lora_a, self.units[i][1].lora_b,
                          flat.get(self.units[i][0] + ".lora_a"), flat.get(self.units[i][0] + ".lora_b")) for i in idx]

    def after_update(self, step: int, rec: dict) -> None:
        mem = memory.snapshot()
        for k in self.peaks:
            v = mem.get(k)
            if v is not None and (self.peaks[k] is None or v > self.peaks[k]):
                self.peaks[k] = v
        self.writer.emit("step", **{k: clean(v) if isinstance(v, float) else v for k, v in rec.items()}, **mem)
        if self._pending:
            t0 = time.perf_counter()
            self._emit_layer_sample(step)
            self.sample_s.append(time.perf_counter() - t0)
            self._pending = None

    def _emit_layer_sample(self, step: int) -> None:
        import mlx.core as mx

        nan = mx.array(float("nan"))
        rows, names = [], []
        for name, mod, a0, b0, ga, gb in self._pending:
            a, b, s = mod.lora_a, mod.lora_b, self.scales[name]
            vals = [fro(a), fro(b), lowrank_fro(a, b, s),
                    fro(ga) if ga is not None else nan, fro(gb) if gb is not None else nan,
                    fro(a - a0), fro(b - b0), fro(a0), fro(b0), lowrank_diff_fro(a0, b0, a, b, s, s),
                    *distribution(a, self.cfg.max_dist_elems), *distribution(b, self.cfg.max_dist_elems)]
            rows.append(mx.stack([v.astype(mx.float32).reshape(()) for v in vals]))
            names.append(name)
        table = mx.stack(rows)
        mx.eval(table)
        data = table.tolist()
        modules = {}
        for name, row in zip(names, data):
            d = {f: clean(v) for f, v in zip(LAYER_FIELDS, row)}
            d["update_ratio_a"] = ratio(d["update_norm_a"], d.pop("norm_a_before"))
            d["update_ratio_b"] = ratio(d["update_norm_b"], d.pop("norm_b_before"))
            d["effective_delta_rel"] = ratio(d["effective_delta_norm"], self.base_norm.get(name))
            modules[name] = d
        self.n_samples += 1
        self.writer.emit("layer_sample", step=step, sample_index=self.n_samples, modules=modules)

    def eval(self, step: int, val_loss) -> None:
        self.writer.emit("eval", step=step, val_loss=clean(val_loss) if val_loss is not None else None)

    def checkpoint(self, step: int, path: Path, kind: str) -> None:
        self.writer.emit("checkpoint", step=step, path=str(path), checkpoint_kind=kind,
                         bytes=path.stat().st_size if path.exists() else None)

    def note(self, msg: str, **kw) -> None:
        self.writer.emit("note", message=msg, **kw)

    def close(self, state: str, summary: dict | None = None) -> None:
        mem = memory.snapshot()
        self.writer.emit("summary", state=state, summary=summary or {}, memory_at_end=mem,
                         peak_proc_footprint_gb=self.peaks["proc_footprint_gb"],
                         peak_swap_used_gb=self.peaks["swap_used_gb"], swap_at_start_gb=self.swap_start,
                         max_pressure=self.peaks["pressure"], layer_samples=self.n_samples,
                         layer_sample_s_median=sorted(self.sample_s)[len(self.sample_s) // 2] if self.sample_s else None,
                         dropped_total=self.writer.dropped_total, write_errors=self.writer.write_errors)
        self.writer.close(state)
