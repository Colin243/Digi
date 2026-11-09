"""Deterministic stand-in backend: lets you exercise the UI, storage and tests
without downloading weights. Its output is canned and says so."""

from __future__ import annotations

import json
import time

from .base import Generation, GenerationParams, ModelSpec

_AESTHETIC = {
    "summary": "FAKE BACKEND OUTPUT - warm, low-contrast candid shots with soft window light.",
    "color_palette": ["warm amber", "muted green"],
    "lighting": "soft side light",
    "mood": "quiet, nostalgic",
    "composition_patterns": ["subject off-center", "negative space"],
    "subject_treatment": "candid, not posed",
}

_COMPOSITION = {
    "title": "Off-center window portrait",
    "framing": "medium",
    "orientation": "portrait",
    "camera_position": "chest height, 45 degrees to the window",
    "subject_placement": "left third",
    "zoom_or_lens": "slight zoom, ~50mm feel",
    "lighting_tip": "turn the subject toward the window",
    "why_it_matches": "repeats the soft side light and negative space",
    "steps": ["step back two paces", "place subject on left third", "expose for the face"],
}


class FakeBackend:
    def __init__(self, spec: ModelSpec, responses: list[str] | None = None):
        self.spec = spec
        self.load_seconds: float | None = None
        self._responses = list(responses) if responses else None
        self._loaded = False
        self.calls: list[tuple[str, list[str]]] = []

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> float:
        if self._loaded:
            return 0.0
        self._loaded = True
        self.load_seconds = 0.0
        return 0.0

    def _default_response(self, prompt: str) -> str:
        recs = {
            "target_scene": {
                "description": "FAKE BACKEND OUTPUT - a room with a window.",
                "key_elements": ["window", "chair"],
                "constraints": ["mixed light"],
            },
            "compositions": [dict(_COMPOSITION, title=f"{_COMPOSITION['title']} {i}") for i in (1, 2, 3)],
        }
        if "first" in prompt and "LAST image" in prompt:  # single pass
            return json.dumps({"aesthetic": _AESTHETIC, **recs})
        if "TARGET scene" in prompt:
            return json.dumps(recs)
        return json.dumps(_AESTHETIC)

    def generate(self, prompt: str, images: list[str], params: GenerationParams) -> Generation:
        self.load()
        self.calls.append((prompt, list(images)))
        t0 = time.perf_counter()
        text = self._responses.pop(0) if self._responses else self._default_response(prompt)
        return Generation(text=text, wall_seconds=time.perf_counter() - t0, finish_reason="stop")

    def unload(self) -> None:
        self._loaded = False

    def runtime_info(self) -> dict:
        return {"backend": "fake"}
