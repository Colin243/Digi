"""Offline comparison of two LoRA adapter checkpoints (never runs inside the training step).

Uses numpy + safetensors only (no MLX, no model), so it can run while training holds the GPU.
For every LoRA module key present in both files:
  delta_norm_a / _b       ||A2 - A1||_F, ||B2 - B1||_F   (adapter-weight change)
  rel_delta_a / _b        that / ||A1||_F (unavailable when ||A1|| = 0, e.g. B of a fresh adapter)
  effective_delta_norm    ||s2 A2 B2 - s1 A1 B1||_F  (change in the EFFECTIVE layer weight)
  effective_norm_1 / _2   ||s A B||_F of each checkpoint alone (distance from the frozen base)
A checkpoint can also be compared with "base" (the zero adapter): then effective_delta_norm is
just ||dW|| of the other checkpoint. These are measurements of weight change only; they say
nothing about what behaviour changed.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .runlog import read_json

BASE = "base"


def _fro(x) -> float:
    x = x.astype(np.float64, copy=False)
    return float(np.sqrt(np.sum(x * x)))


def _lowrank_diff(a1, b1, a2, b2, s1, s2) -> float:
    a1, b1, a2, b2 = (t.astype(np.float64, copy=False) for t in (a1, b1, a2, b2))
    t11 = np.sum((a1.T @ a1) * (b1 @ b1.T))
    t22 = np.sum((a2.T @ a2) * (b2 @ b2.T))
    t12 = np.sum((a1.T @ a2) * (b1 @ b2.T))
    return float(np.sqrt(max(s2 * s2 * t22 + s1 * s1 * t11 - 2 * s1 * s2 * t12, 0.0)))


def _ratio(n, d):
    return None if d is None or d == 0 or not np.isfinite(d) else n / d


def find_adapter_config(path: Path) -> dict | None:
    for d in (path.parent, path.parent.parent):
        c = read_json(d / "adapter_config.json")
        if c:
            return c
    return None


def find_manifest(path: Path) -> dict | None:
    for d in (path.parent, path.parent.parent):
        m = read_json(d / "monitor" / "manifest.json")
        if m:
            return m
    return None


def load_adapter(path: str | Path) -> dict:
    """{"weights": {key: ndarray}, "config": adapter_config|None, "manifest": manifest|None, "path"}"""
    from safetensors.numpy import load_file

    path = Path(path)
    w = load_file(str(path))
    return {"path": str(path), "weights": w, "config": find_adapter_config(path), "manifest": find_manifest(path)}


def _modules(weights: dict) -> dict[str, tuple[str, str]]:
    out = {}
    for k in weights:
        if k.endswith(".lora_a"):
            m = k[: -len(".lora_a")]
            if m + ".lora_b" in weights:
                out[m] = (k, m + ".lora_b")
    return out


def _scale(cfg: dict | None):
    if not cfg:
        return None
    lp = cfg.get("lora_parameters", cfg)
    if "scale" in lp:
        return float(lp["scale"])
    if "alpha" in lp and lp.get("rank"):
        return float(lp["alpha"]) / float(lp["rank"])
    return None


def compatibility(c1: dict, c2: dict) -> dict:
    """Errors make the comparison meaningless; warnings are shown next to the numbers."""
    errors, warnings = [], []
    w1, w2 = c1["weights"], c2["weights"]
    m1, m2 = _modules(w1), _modules(w2)
    only1, only2 = sorted(set(m1) - set(m2)), sorted(set(m2) - set(m1))
    shape_mismatch = [m for m in sorted(set(m1) & set(m2))
                      if w1[m1[m][0]].shape != w2[m2[m][0]].shape or w1[m1[m][1]].shape != w2[m2[m][1]].shape]
    if not set(m1) & set(m2):
        errors.append("no LoRA module keys in common")
    if shape_mismatch:
        errors.append(f"{len(shape_mismatch)} modules have different adapter shapes (rank or layer size differs)")
    if only1 or only2:
        warnings.append(f"module keys differ: {len(only1)} only in A, {len(only2)} only in B (compared on the intersection)")
    s1, s2 = _scale(c1["config"]), _scale(c2["config"])
    if s1 is None or s2 is None:
        warnings.append("adapter scale unavailable for one checkpoint (no adapter_config.json); effective norms unavailable")
    elif s1 != s2:
        warnings.append(f"different LoRA scale ({s1} vs {s2})")
    man1, man2 = c1.get("manifest"), c2.get("manifest")
    if man1 and man2:
        b1, b2 = man1.get("base_model") or {}, man2.get("base_model") or {}
        if b1.get("repo") != b2.get("repo"):
            errors.append(f"different base model ({b1.get('repo')} vs {b2.get('repo')})")
        elif b1.get("revision") != b2.get("revision"):
            errors.append(f"different base revision ({b1.get('revision')} vs {b2.get('revision')})")
        if (man1.get("lora") or {}).get("targets") != (man2.get("lora") or {}).get("targets"):
            warnings.append("different LoRA target lists")
        d1, d2 = man1.get("data") or {}, man2.get("data") or {}
        if d1.get("train_split_sha256") != d2.get("train_split_sha256"):
            warnings.append("trained on different training splits (data hash differs)")
        if d1.get("includes_unapproved_drafts") or d2.get("includes_unapproved_drafts"):
            warnings.append("at least one checkpoint was trained on UNREVIEWED draft labels (smoke data)")
    else:
        warnings.append("run manifest missing for one or both checkpoints: base model/revision identity not verified")
    return {"compatible": not errors, "errors": errors, "warnings": warnings,
            "only_in_a": only1[:50], "only_in_b": only2[:50], "shape_mismatch": shape_mismatch[:50],
            "common_modules": len(set(m1) & set(m2))}


def _zero_like(c: dict) -> dict:
    return {"path": BASE, "weights": {k: np.zeros_like(v) for k, v in c["weights"].items()},
            "config": c["config"], "manifest": c["manifest"]}


def compare(path_a: str | Path, path_b: str | Path) -> dict:
    if str(path_a) == BASE and str(path_b) == BASE:
        raise ValueError("compare needs at least one real checkpoint")
    c2 = load_adapter(path_b) if str(path_b) != BASE else None
    c1 = load_adapter(path_a) if str(path_a) != BASE else _zero_like(c2)
    if c2 is None:
        c2 = _zero_like(c1)
    comp = compatibility(c1, c2)
    out = {"a": str(path_a), "b": str(path_b), "compatibility": comp, "modules": {},
           "kind": "measurement: adapter weight differences (not a quality or behaviour claim)"}
    if not comp["compatible"]:
        return out
    s1, s2 = _scale(c1["config"]), _scale(c2["config"])
    m1, m2 = _modules(c1["weights"]), _modules(c2["weights"])
    for m in sorted(set(m1) & set(m2)):
        a1, b1 = c1["weights"][m1[m][0]], c1["weights"][m1[m][1]]
        a2, b2 = c2["weights"][m2[m][0]], c2["weights"][m2[m][1]]
        if BASE in (str(path_a), str(path_b)):
            # the base model has no adapter: A/B differences against a zero stand-in are meaningless
            rec = {"delta_norm_a": None, "delta_norm_b": None, "rel_delta_a": None, "rel_delta_b": None}
        else:
            da, db = _fro(a2 - a1), _fro(b2 - b1)
            rec = {"delta_norm_a": da, "delta_norm_b": db, "rel_delta_a": _ratio(da, _fro(a1)),
                   "rel_delta_b": _ratio(db, _fro(b1))}
        rec.update({"effective_delta_norm": None, "effective_norm_1": None, "effective_norm_2": None})
        if s1 is not None and s2 is not None:
            z = np.zeros_like(a1)
            zb = np.zeros_like(b1)
            rec["effective_delta_norm"] = _lowrank_diff(a1, b1, a2, b2, s1, s2)
            rec["effective_norm_1"] = _lowrank_diff(z, zb, a1, b1, 1.0, s1)
            rec["effective_norm_2"] = _lowrank_diff(z, zb, a2, b2, 1.0, s2)
            rec["effective_rel_change"] = _ratio(rec["effective_delta_norm"], rec["effective_norm_1"])
        out["modules"][m] = rec
    vals = [r["effective_delta_norm"] for r in out["modules"].values() if r["effective_delta_norm"] is not None]
    out["aggregate"] = {"modules": len(out["modules"]),
                        "effective_delta_norm_total": float(np.sqrt(np.sum(np.square(vals)))) if vals else None,
                        "top_modules_by_effective_delta": sorted(out["modules"],
                                                                key=lambda k: -(out["modules"][k]["effective_delta_norm"] or 0))[:10]}
    return out


def list_checkpoints(run_dir: Path) -> list[dict]:
    """Adapter files of the run that owns this monitor dir (monitor/ lives inside the adapter out dir)."""
    root = Path(run_dir).parent
    out = []
    for p in sorted(root.glob("*.safetensors")) + sorted((root / "checkpoints").glob("*.safetensors")):
        out.append({"path": str(p.resolve()), "name": str(p.relative_to(root)), "bytes": p.stat().st_size})
    return out


if __name__ == "__main__":  # pragma: no cover
    import sys

    print(json.dumps(compare(sys.argv[1], sys.argv[2])["compatibility"], indent=1))
