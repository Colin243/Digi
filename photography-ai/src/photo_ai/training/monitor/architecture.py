"""Architecture description built from the ACTUAL loaded model object (not from a diagram).

Walks every parameter of the loaded model, groups parameters into units (one Linear / Norm /
Embedding / LoRA-wrapped Linear), and records for each unit: group (vision encoder, connector,
language model), block index, class, parameter shapes, logical parameter counts, trainable
counts, LoRA rank/scale, and whether the monitor samples statistics for it.

Status values:
  frozen          no trainable parameters; receives no gradient; static info only
  trainable       has trainable parameters (here: only LoRA A/B inside language-model Linears)
Instrumentation:
  instrumented    the monitor samples statistics for this unit (see monitor config cadence)
  uninstrumented  no runtime statistics are collected (every frozen unit, and any trainable unit
                  outside the sampler's module list)
"""

from __future__ import annotations

import re

GROUPS = {
    "vision_encoder": "Vision encoder (ViT): patch embedding, position embedding, transformer blocks",
    "connector": "Multimodal connector/projector: patch merger + DeepStack mergers that map vision "
                 "features into the language model's embedding space",
    "language_model": "Language model (Qwen3 decoder): token embedding, decoder layers, final norm",
    "other": "Other modules",
}


def group_of(name: str) -> str:
    if name.startswith(("vision_tower.merger", "vision_tower.deepstack_merger", "multi_modal_projector",
                        "mm_projector", "connector")):
        return "connector"
    if name.startswith(("vision_tower", "vision_model", "visual")):
        return "vision_encoder"
    if name.startswith("language_model"):
        return "language_model"
    return "other"


_BLOCK = re.compile(r"\.(?:blocks|layers|deepstack_merger_list)\.(\d+)(?:\.|$)")


def block_of(name: str):
    m = _BLOCK.search(name)
    return int(m.group(1)) if m else None


def _is_lora(mod) -> bool:
    return hasattr(mod, "lora_a") and hasattr(mod, "lora_b")


def _quant_bits(mod):
    return getattr(mod, "bits", None) if type(mod).__name__.startswith("Quantized") else None


def build_architecture(model, instrumented: set[str] | None = None) -> dict:
    from mlx.utils import tree_flatten

    modules = dict(model.named_modules())
    params = tree_flatten(model.parameters())
    trainable = {k for k, _ in tree_flatten(model.trainable_parameters())}
    units: dict[str, dict] = {}
    for key, arr in params:
        owner, pname = key.rsplit(".", 1) if "." in key else ("", key)
        mod = modules.get(owner)
        unit_name = owner
        if owner.endswith(".linear") and _is_lora(modules.get(owner[: -len(".linear")])):
            unit_name = owner[: -len(".linear")]
            pname = "linear." + pname
        unit_mod = modules.get(unit_name)
        u = units.get(unit_name)
        if u is None:
            u = units[unit_name] = {
                "name": unit_name, "group": group_of(unit_name), "block": block_of(unit_name),
                "class": type(unit_mod).__name__ if unit_mod is not None else None,
                "params": [], "total_params": 0, "trainable_params": 0, "storage_bytes": 0, "lora": None,
            }
            if unit_mod is not None and _is_lora(unit_mod):
                a, b = unit_mod.lora_a, unit_mod.lora_b
                base = getattr(unit_mod, "linear", None)
                u["lora"] = {"rank": int(a.shape[1]), "scale": float(unit_mod.scale), "d_in": int(a.shape[0]),
                             "d_out": int(b.shape[1]), "base_class": type(base).__name__ if base is not None else None,
                             "base_bits": _quant_bits(base) if base is not None else None,
                             "dropout": _dropout_p(unit_mod)}
        bits = _quant_bits(mod)
        shape = [int(s) for s in arr.shape]
        logical = list(shape)
        is_meta = bits is not None and pname.split(".")[-1] in ("scales", "biases")
        if bits is not None and pname.split(".")[-1] == "weight":
            logical = shape[:-1] + [shape[-1] * 32 // bits]
        count = 0 if is_meta else int(_prod(logical))
        is_tr = key in trainable
        u["params"].append({"name": pname, "key": key, "shape": shape, "logical_shape": logical,
                            "dtype": str(arr.dtype).replace("mlx.core.", ""), "trainable": is_tr,
                            "quantization": {"bits": bits} if bits is not None and not is_meta else
                            ("metadata" if is_meta else None), "count": count})
        u["total_params"] += count
        u["trainable_params"] += count if is_tr else 0
        u["storage_bytes"] += int(arr.nbytes)
    inst = set(instrumented or ())
    for u in units.values():
        u["status"] = "trainable" if u["trainable_params"] > 0 else "frozen"
        u["instrumented"] = u["name"] in inst
    groups = {}
    for g, desc in GROUPS.items():
        us = [u for u in units.values() if u["group"] == g]
        if not us and g == "other":
            continue
        blocks = sorted({u["block"] for u in us if u["block"] is not None})
        groups[g] = {"description": desc, "units": len(us), "blocks": len(blocks),
                     "total_params": sum(u["total_params"] for u in us),
                     "trainable_params": sum(u["trainable_params"] for u in us),
                     "lora_units": sum(1 for u in us if u["lora"]),
                     "status": "trainable (LoRA adapters only; base frozen)" if any(u["trainable_params"] for u in us)
                     else "frozen"}
    cfg = getattr(model, "config", None)
    names = set(modules)
    vcfg = getattr(cfg, "vision_config", None)
    ds = getattr(vcfg, "deepstack_visual_indexes", None) if vcfg is not None else None
    dataflow = {"source": "model config (vision_config.deepstack_visual_indexes) and mlx-vlm qwen3_vl forward pass",
                "vision_to_merger": "last vision block -> merger -> image-token embeddings in the language model input",
                "deepstack_visual_indexes": list(ds) if ds else None,
                "deepstack_injects_into_lm_layers": list(range(len(ds))) if ds else None}
    return {
        "dataflow": dataflow,
        "model_class": f"{type(model).__module__}.{type(model).__name__}",
        "model_type": getattr(cfg, "model_type", None),
        "quantization": getattr(cfg, "quantization", None),
        "lm_head": "separate" if any(n.endswith("lm_head") for n in names) else "tied to embed_tokens (no lm_head module)",
        "totals": {"total_params": sum(u["total_params"] for u in units.values()),
                   "trainable_params": sum(u["trainable_params"] for u in units.values()),
                   "units": len(units), "lora_units": sum(1 for u in units.values() if u["lora"]),
                   "instrumented_units": sum(1 for u in units.values() if u["instrumented"]),
                   "trainable_tensors": len(trainable),
                   "vision_trainable_tensors": sum(1 for k in trainable if group_of(k) in ("vision_encoder", "connector"))},
        "groups": groups,
        "units": sorted(units.values(), key=_order),
        "status_definitions": {
            "frozen": "no trainable parameters; gets no gradient; static info only",
            "trainable": "has trainable parameters (LoRA A/B); base weight stays frozen",
            "instrumented": "the monitor samples statistics for it",
            "uninstrumented": "no runtime statistics collected",
        },
    }


def _dropout_p(mod):
    p1 = getattr(getattr(mod, "dropout", None), "_p_1", None)  # nn.Dropout stores keep-prob 1-p
    return None if p1 is None else round(1 - float(p1), 6)


def _prod(xs):
    p = 1
    for x in xs:
        p *= x
    return p


def _order(u):
    g = list(GROUPS).index(u["group"])
    return (g, -1 if u["block"] is None and "embed" in u["name"] else (u["block"] if u["block"] is not None else 10**6), u["name"])


def lora_units(model) -> list[tuple[str, object]]:
    return [(n, m) for n, m in model.named_modules() if _is_lora(m)]
