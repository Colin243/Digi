"""Model registry. Add a model by adding one ModelSpec line."""

from __future__ import annotations

from pathlib import Path

from .base import IMAGE_MARKER, Generation, GenerationParams, ModelSpec, VLMBackend

MODELS: dict[str, ModelSpec] = {
    spec.key: spec
    for spec in [
        ModelSpec(
            "smolvlm2-500m",
            "mlx-community/SmolVLM2-500M-Video-Instruct-mlx",
            "mlx",
            "Baseline. ~1.9 GB download.",
        ),
        ModelSpec(
            "qwen2.5-vl-3b-4bit",
            "mlx-community/Qwen2.5-VL-3B-Instruct-4bit",
            "mlx",
            "Comparison target. 4-bit, ~3.1 GB download.",
        ),
        ModelSpec(
            "qwen2.5-vl-3b-8bit",
            "mlx-community/Qwen2.5-VL-3B-Instruct-8bit",
            "mlx",
            "Comparison target. 8-bit, ~4.1 GB download.",
        ),
        ModelSpec("qwen3-vl-2b-4bit", "mlx-community/Qwen3-VL-2B-Instruct-4bit", "mlx", "Phase 3 candidate. ~1.8 GB download."),
        ModelSpec("smolvlm2-2.2b", "mlx-community/SmolVLM2-2.2B-Instruct-mlx", "mlx",
                  "Phase 3 candidate, bf16 (only official MLX build). ~4.5 GB download."),
        ModelSpec("smolvlm2-2.2b-4bit", str(Path(__file__).resolve().parents[3] / "models" / "smolvlm2-2.2b-4bit"), "mlx",
                  "Local 4-bit conversion of smolvlm2-2.2b: `photo-ai convert smolvlm2-2.2b` (git-ignored models/)."),
        # Registered, not benchmarked yet.
        ModelSpec("qwen3-vl-4b-4bit", "mlx-community/Qwen3-VL-4B-Instruct-4bit", "mlx", "Not yet benchmarked."),
        ModelSpec("fake", "fake", "fake", "Canned output for UI/pipeline testing; no model."),
    ]
}

DEFAULT_MODEL = "smolvlm2-500m"


def resolve_spec(name: str) -> ModelSpec:
    """Accept a registry key, any Hugging Face repo id / local path for an MLX model, or
    "<base>+adapter=<dir>" for a base model with a LoRA adapter (e.g. a Phase 4 run)."""
    if "+adapter=" in name:
        base_name, adapter = name.split("+adapter=", 1)
        base = resolve_spec(base_name)
        adapter_dir = Path(adapter).expanduser()
        if not adapter_dir.is_absolute():
            adapter_dir = Path(__file__).resolve().parents[3] / adapter_dir
        return ModelSpec(f"{base.key}+{adapter_dir.name}", base.repo_id, base.backend,
                         f"LoRA adapter {adapter_dir}", adapter_path=str(adapter_dir))
    if name in MODELS:
        return MODELS[name]
    key = name.rstrip("/").split("/")[-1].lower()
    return ModelSpec(key, name, "mlx", "ad-hoc model id")


def make_backend(name: str) -> VLMBackend:
    spec = resolve_spec(name)
    if spec.backend == "fake":
        from .fake import FakeBackend

        return FakeBackend(spec)
    if spec.backend == "mlx":
        from .mlx_backend import MLXVLMBackend

        return MLXVLMBackend(spec)
    raise ValueError(f"unknown backend {spec.backend!r}")


__all__ = [
    "DEFAULT_MODEL",
    "IMAGE_MARKER",
    "MODELS",
    "Generation",
    "GenerationParams",
    "ModelSpec",
    "VLMBackend",
    "make_backend",
    "resolve_spec",
]
