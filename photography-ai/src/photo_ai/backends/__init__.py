"""Model registry. Add a model by adding one ModelSpec line."""

from __future__ import annotations

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
        # Registered for future benchmarks; repos exist on Hugging Face but have NOT been run here yet.
        ModelSpec("smolvlm2-2.2b", "mlx-community/SmolVLM2-2.2B-Instruct-mlx", "mlx", "Candidate, not yet benchmarked."),
        ModelSpec("qwen3-vl-2b-4bit", "mlx-community/Qwen3-VL-2B-Instruct-4bit", "mlx", "Candidate, not yet benchmarked."),
        ModelSpec("qwen3-vl-4b-4bit", "mlx-community/Qwen3-VL-4B-Instruct-4bit", "mlx", "Candidate, not yet benchmarked."),
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
    "IMAGE_MARKER",
    "MODELS",
    "Generation",
    "GenerationParams",
    "ModelSpec",
    "VLMBackend",
    "make_backend",
    "resolve_spec",
]
