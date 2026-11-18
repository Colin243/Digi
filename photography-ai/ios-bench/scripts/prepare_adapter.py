#!/usr/bin/env python3
"""Convert a photo-ai LoRA adapter into the layout mlx-swift-lm's LoRAContainer loads.

    uv run python ios-bench/scripts/prepare_adapter.py data/adapters/<run> <out dir>

Why this is needed (found by reading mlx-swift-lm 3.32.3, LoRAContainer.swift):
- Swift matches `lora_parameters.keys` against module paths RELATIVE to each decoder layer
  ("self_attn.q_proj"), not the absolute paths mlx-vlm writes ("language_model.model.layers.27.self_attn.q_proj").
- `num_layers: -1` (mlx-vlm's "all layers") would trap in Swift (`suffix(-1)`); it needs the real layer count.
- Only language-model layers are adaptable in Swift (`Qwen3VL.loraLayers` = language_model.model.layers). Vision-tower
  LoRA tensors would be rejected as unused keys, so they are dropped here and reported. An adapter trained with the
  vision tower must have that part merged into the base weights separately.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import mlx.core as mx

LAYER = re.compile(r"^language_model\.model\.layers\.(\d+)\.(.+)\.lora_[ab]$")


def convert(src: Path, dst: Path) -> dict:
    cfg = json.loads((src / "adapter_config.json").read_text())
    lp = cfg["lora_parameters"]
    weights = mx.load(str(src / "adapters.safetensors"), stream=mx.cpu)

    kept, dropped, layers, rel_keys = {}, [], set(), set()
    for name, arr in weights.items():
        m = LAYER.match(name)
        if m:
            kept[name] = arr
            layers.add(int(m.group(1)))
            rel_keys.add(m.group(2))
        else:
            dropped.append(name)

    n_layers = max(layers) + 1 if layers else 0
    if sorted(layers) != list(range(n_layers)):
        raise SystemExit(f"adapter does not cover contiguous layers 0..{n_layers - 1}: {sorted(layers)}")

    out_cfg = {
        "fine_tune_type": cfg.get("fine_tune_type", "lora"),
        "num_layers": n_layers,
        "lora_parameters": {
            "rank": lp["rank"],
            "scale": lp["scale"],
            "dropout": lp.get("dropout", 0.0),
            "keys": sorted(rel_keys),
        },
    }
    dst.mkdir(parents=True, exist_ok=True)
    mx.save_safetensors(str(dst / "adapters.safetensors"), kept)
    (dst / "adapter_config.json").write_text(json.dumps(out_cfg, indent=1))
    return {"layers": n_layers, "keys": sorted(rel_keys), "tensors_kept": len(kept), "tensors_dropped": dropped}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    info = convert(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"layers {info['layers']}, keys {info['keys']}")
    print(f"kept {info['tensors_kept']} language-model tensors")
    if info["tensors_dropped"]:
        print(f"DROPPED {len(info['tensors_dropped'])} non-language tensors (vision tower etc.); "
              "merge those into the base weights separately")
