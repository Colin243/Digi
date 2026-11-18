"""MLX-VLM backend (Apple silicon). Works for any model family mlx-vlm supports,
including SmolVLM2 and Qwen2.5-VL, so comparing models is just a different repo id.

Prompts are formatted with the model's own Hugging Face chat template
(processor.apply_chat_template). Diagnostics showed this matches mlx-vlm's helper
for images-first prompts, while mlx-vlm 0.7.12's helper mangles interleaved
text/image content (it emits empty user turns), so we never use it for those.
"""

from __future__ import annotations

import gc
import time
from importlib import metadata

from .base import IMAGE_MARKER, Generation, GenerationParams, ModelSpec

# Tokens that open one image block, used to count images that reached the model.
_IMAGE_START_TOKENS = ("<global-img>", "<|vision_start|>")


def _version(pkg: str) -> str | None:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return None


def build_messages(prompt: str, n_images: int) -> list[dict]:
    """User message content: images at marker positions, or all images first."""
    if IMAGE_MARKER in prompt:
        pieces = prompt.split(IMAGE_MARKER)
        if len(pieces) - 1 != n_images:
            raise ValueError(f"prompt has {len(pieces) - 1} image markers but {n_images} images")
        content: list[dict] = []
        for i, text in enumerate(pieces):
            if text.strip():
                content.append({"type": "text", "text": text})
            if i < n_images:
                content.append({"type": "image"})
    else:
        content = [{"type": "image"}] * n_images + [{"type": "text", "text": prompt}]
    return [{"role": "user", "content": content}]


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
        if self.spec.adapter_path:
            self._model, self._processor = load(self.spec.repo_id, adapter_path=self.spec.adapter_path)
        else:
            self._model, self._processor = load(self.spec.repo_id)
        self.load_seconds = time.perf_counter() - t0
        return self.load_seconds

    def format_prompt(self, prompt: str, n_images: int) -> str:
        self.load()
        msgs = build_messages(prompt, n_images)
        if getattr(self._processor, "chat_template", None):
            return self._processor.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
        from mlx_vlm.prompt_utils import apply_chat_template  # fallback for template-less processors

        if IMAGE_MARKER in prompt:
            raise ValueError("interleaved images need a processor chat template")
        return apply_chat_template(self._processor, self._model.config, prompt, num_images=n_images)

    def generate(self, prompt: str, images: list[str], params: GenerationParams, on_text=None) -> Generation:
        import mlx.core as mx
        from mlx_vlm import generate

        formatted = self.format_prompt(prompt, len(images))
        mx.random.seed(params.seed)
        kwargs = {"max_tokens": params.max_tokens, "temperature": params.temperature}
        if params.repetition_penalty:
            kwargs["repetition_penalty"] = params.repetition_penalty

        if hasattr(mx, "reset_peak_memory"):
            mx.reset_peak_memory()
        t0 = time.perf_counter()
        if on_text is None:
            result = generate(
                self._model, self._processor, formatted, image=images or None, verbose=False, **kwargs
            )
        else:
            result = self._stream(formatted, images, kwargs, on_text)
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

    def generate_batch(self, items: list[tuple[str, list[str]]], params: GenerationParams) -> list[Generation] | None:
        """Several (prompt, [one image]) requests in one batched pass. Returns None when this model or input cannot
        be batched (several images in one request, or mlx-vlm raising), so the caller falls back to one at a time.
        Each Generation carries an equal share of the batch's wall time so stage times still add up to real time."""
        if not items or any(len(images) != 1 for _, images in items):
            return None
        if params.temperature != 0 or params.repetition_penalty:
            return None  # batching here is greedy-only; sampled or penalised runs take the normal path
        import mlx.core as mx

        try:
            from mlx_vlm.generate.ar import batch_generate

            prompts_ = [self.format_prompt(prompt, 1) for prompt, _ in items]
            mx.random.seed(params.seed)
            if hasattr(mx, "reset_peak_memory"):
                mx.reset_peak_memory()
            t0 = time.perf_counter()
            resp = batch_generate(self._model, self._processor, images=[images[0] for _, images in items],
                                  prompts=prompts_, max_tokens=params.max_tokens, verbose=False, greedy_sampling=True)
            wall = time.perf_counter() - t0
        except Exception:  # noqa: BLE001 - any batching failure means "do it the slow, known-good way"
            return None
        clean = getattr(self._processor, "clean_output", None)
        stats = resp.stats
        share = wall / len(items)
        return [Generation(text=clean(t) if callable(clean) else t, wall_seconds=share,
                           prompt_tokens=stats.prompt_tokens // len(items) if stats.prompt_tokens else None,
                           generation_tokens=stats.generation_tokens // len(items) if stats.generation_tokens else None,
                           prompt_tps=stats.prompt_tps, generation_tps=stats.generation_tps,
                           peak_memory_gb=stats.peak_memory, finish_reason=None,
                           extra={"batched": len(items), "batch_wall_s": round(wall, 3)})
                for t in resp.texts]

    def _stream(self, formatted: str, images: list[str], kwargs: dict, on_text):
        """mlx-vlm's generate() is a loop over stream_generate(); this is the same loop, passing each piece of
        text on as it arrives. It resets the stop tokens and cleans the final text exactly as generate() does."""
        from mlx_vlm import stream_generate
        from mlx_vlm.generate.common import GenerationResult

        tokenizer = getattr(self._processor, "tokenizer", self._processor)
        tokenizer.stopping_criteria.reset(self._model.config.eos_token_id)
        text, last = "", None
        for response in stream_generate(self._model, self._processor, formatted, images or None, **kwargs):
            if response.is_draft:
                continue
            text += response.text
            last = response
            if response.text:
                on_text(response.text)
        clean_output = getattr(self._processor, "clean_output", None)
        if callable(clean_output):
            text = clean_output(text)
        if last is None:
            import mlx.core as mx

            return GenerationResult(text=text, peak_memory=mx.get_peak_memory() / 1e9)
        return GenerationResult(
            text=text, prompt_tokens=last.prompt_tokens, generation_tokens=last.generation_tokens,
            prompt_tps=last.prompt_tps, generation_tps=last.generation_tps, peak_memory=last.peak_memory,
            finish_reason=last.finish_reason,
        )

    def inspect_inputs(self, prompt: str, images: list[str]) -> dict:
        import numpy as np
        from mlx_vlm.utils import prepare_inputs

        formatted = self.format_prompt(prompt, len(images))
        cfg = self._model.config
        itok = getattr(cfg, "image_token_id", None) or getattr(cfg, "image_token_index", None)
        inputs = prepare_inputs(self._processor, images=images, prompts=formatted, image_token_index=itok)
        ids = np.array(inputs["input_ids"]).ravel()
        tok = getattr(self._processor, "tokenizer", self._processor)
        starts = {}
        for t in _IMAGE_START_TOKENS:
            tid = tok.convert_tokens_to_ids(t)
            if isinstance(tid, int) and tid != getattr(tok, "unk_token_id", None):
                starts[t] = int((ids == tid).sum())
        pv = inputs.get("pixel_values")
        ip = getattr(self._processor, "image_processor", None)
        size = getattr(ip, "size", None)
        return {
            "formatted_prompt": formatted,
            "n_images_given": len(images),
            "image_start_tokens": starts,
            "images_seen": sum(starts.values()) if starts else None,
            "input_tokens": int(ids.size),
            "image_tokens": int((ids == itok).sum()) if itok is not None else None,
            "pixel_values_shape": list(getattr(pv, "shape", []) or []),
            "image_processor_size": dict(size) if hasattr(size, "keys") else str(size),
        }

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
