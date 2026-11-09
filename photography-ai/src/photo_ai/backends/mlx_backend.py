"""MLX-VLM backend (Apple silicon). Works for any model family mlx-vlm supports,
including SmolVLM2 and Qwen2.5-VL, so comparing models is just a different repo id."""

from __future__ import annotations

import gc
import time
from importlib import metadata

from .base import Generation, GenerationParams, ModelSpec


def _version(pkg: str) -> str | None:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return None


class MLXVLMBackend:
    def __init__(self, spec: ModelSpec):
        self.spec = spec
        self.load_seconds: float | None = None
        self._model = None
        self._processor = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> float:
        if self.is_loaded:
            return 0.0
        from mlx_vlm import load  # imported lazily so tests/fake backend never need MLX

        t0 = time.perf_counter()
        self._model, self._processor = load(self.spec.repo_id)
        self.load_seconds = time.perf_counter() - t0
        return self.load_seconds

    def generate(self, prompt: str, images: list[str], params: GenerationParams) -> Generation:
        import mlx.core as mx
        from mlx_vlm import generate
        from mlx_vlm.prompt_utils import apply_chat_template

        self.load()
        mx.random.seed(params.seed)
        formatted = apply_chat_template(
            self._processor, self._model.config, prompt, num_images=len(images)
        )
        kwargs = {"max_tokens": params.max_tokens, "temperature": params.temperature}
        if params.repetition_penalty:
            kwargs["repetition_penalty"] = params.repetition_penalty

        if hasattr(mx, "reset_peak_memory"):
            mx.reset_peak_memory()
        t0 = time.perf_counter()
        result = generate(
            self._model, self._processor, formatted, image=images or None, verbose=False, **kwargs
        )
        wall = time.perf_counter() - t0
        return Generation(
            text=result.text,
            wall_seconds=wall,
            prompt_tokens=result.prompt_tokens,
            generation_tokens=result.generation_tokens,
            prompt_tps=result.prompt_tps,
            generation_tps=result.generation_tps,
            peak_memory_gb=result.peak_memory,
            finish_reason=getattr(result, "finish_reason", None),
        )

    def unload(self) -> None:
        self._model = self._processor = None
        gc.collect()
        try:
            import mlx.core as mx

            mx.clear_cache()
        except Exception:
            pass

    def runtime_info(self) -> dict:
        info = {"mlx": _version("mlx"), "mlx_vlm": _version("mlx-vlm"), "transformers": _version("transformers")}
        try:
            import mlx.core as mx

            info["device"] = str(mx.default_device())
            dev = mx.device_info() if hasattr(mx, "device_info") else mx.metal.device_info()
            info["device_name"] = dev.get("device_name")
            info["memory_gb"] = round(dev.get("memory_size", 0) / 1e9, 1)
        except Exception as exc:  # pragma: no cover - informational only
            info["device_error"] = repr(exc)
        return info
