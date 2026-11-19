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

from .base import IMAGE_MARKER, Generation, GenerationParams, ModelSpec, PromptPrefix

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

    # ---- prompt prefix cache
    # The chat template closes the user turn with END_TOKEN and then adds the assistant header. Everything before
    # END_TOKEN can be read ahead of time. Qwen3.5's linear-attention layers keep a recurrent state that cannot be
    # rewound, so the warm-up must leave the cache holding EXACTLY the tokens the real prompt starts with: it reads
    # the prefix and forces its single generated token to be END_TOKEN, the real prompt's next token. mlx-vlm then
    # reuses the cache with nothing to trim (PromptCacheState) and reads only the short assistant header.
    END_TOKEN = "<|im_end|>"

    def prepare_prefix(self, prompt: str, images: list[str], params: GenerationParams) -> PromptPrefix | None:
        import mlx.core as mx
        from mlx_vlm import stream_generate
        from mlx_vlm.generate.common import PromptCacheState

        formatted = self.format_prompt(prompt, len(images))
        cut = formatted.rfind(self.END_TOKEN)
        tokenizer = getattr(self._processor, "tokenizer", self._processor)
        end_id = tokenizer.convert_tokens_to_ids(self.END_TOKEN) if cut > 0 else None
        if cut <= 0 or not isinstance(end_id, int) or end_id < 0:
            return None  # this model's template has no such marker: no prefix cache, the normal path still works

        def force_end(tokens, logits):
            keep = mx.arange(logits.shape[-1]) == end_id
            return mx.where(keep, logits, mx.full(logits.shape, -1e9, dtype=logits.dtype))

        state = PromptCacheState()
        tokenizer.stopping_criteria.reset(self._model.config.eos_token_id)
        mx.random.seed(params.seed)
        t0 = time.perf_counter()
        for _ in stream_generate(self._model, self._processor, formatted[:cut], images or None, max_tokens=1,
                                 temperature=0.0, prompt_cache_state=state, logits_processors=[force_end]):
            pass
        wall = time.perf_counter() - t0
        ids = state.token_ids or []
        offsets = {int(getattr(c, "offset", 0) or 0) for c in (state.cache or [])}
        if not ids or ids[-1] != end_id or not offsets <= {0, len(ids)}:
            return None  # the cache does not hold exactly prefix + END_TOKEN; reusing it could corrupt the answer
        return PromptPrefix(text=formatted[:cut], state=state, n_tokens=len(ids), wall_seconds=wall)

    def _prefix_fits(self, prefix: PromptPrefix | None, formatted: str) -> bool:
        return (prefix is not None and not prefix.used and prefix.state is not None
                and formatted.startswith(prefix.text) and formatted[len(prefix.text):].startswith(self.END_TOKEN))

    def generate(self, prompt: str, images: list[str], params: GenerationParams, on_text=None,
                 prefix: PromptPrefix | None = None) -> Generation:
        import mlx.core as mx
        from mlx_vlm import generate

        formatted = self.format_prompt(prompt, len(images))
        mx.random.seed(params.seed)
        kwargs = {"max_tokens": params.max_tokens, "temperature": params.temperature}
        if params.repetition_penalty:
            kwargs["repetition_penalty"] = params.repetition_penalty
        cached = self._prefix_fits(prefix, formatted)
        if cached:
            kwargs["prompt_cache_state"] = prefix.state
            prefix.used = True  # generation advances the state; never reuse it

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
            prefix_cached=cached,
        )

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
