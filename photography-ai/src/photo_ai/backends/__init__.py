"""Model registry. Add a model by adding one ModelSpec line."""

from __future__ import annotations

from .base import Generation, GenerationParams, ModelSpec, VLMBackend

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
        ModelSpec("fake", "fake", "fake", "Canned output for UI/pipeline testing; no model."),
    ]
}

DEFAULT_MODEL = "smolvlm2-500m"


def resolve_spec(name: str) -> ModelSpec:
    """Accept a registry key, or any Hugging Face repo id / local path for an MLX model."""
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
    "MODELS",
    "Generation",
    "GenerationParams",
    "ModelSpec",
    "VLMBackend",
    "make_backend",
    "resolve_spec",
]
