"""Deterministic stand-in backend: lets you exercise the UI, storage and tests
without downloading weights. Its output is canned and says so."""

from __future__ import annotations

import json
import time

from .base import Generation, GenerationParams, ModelSpec

AESTHETIC = {
    "per_image": ["FAKE: photo 1", "FAKE: photo 2", "FAKE: photo 3"],
    "summary": "FAKE BACKEND OUTPUT - warm, low-contrast candid shots with soft window light.",
    "principles": ["low camera height", "subject off-center with negative space"],
    "color_palette": ["warm amber", "muted green"],
    "lighting": "soft side light",
    "mood": "quiet, nostalgic",
    "composition_patterns": ["subject off-center", "negative space"],
    "subject_treatment": "candid, not posed",
}

TARGET = {
    "description": "FAKE BACKEND OUTPUT - a room with a window.",
    "key_elements": ["window", "chair"],
    "constraints": ["mixed light"],
}

COMPOSITION = {
    "title": "Off-center window portrait",
    "uses_principle": "subject off-center with negative space",
    "camera_position": "2 m from the window, to the right of the chair",
    "camera_height": "slightly below the subject's waist",
    "camera_angle": "tilt up about 10 degrees",
    "subject_position": "standing by the window, placed in the left third of the frame",
    "distance_and_framing": "about 2 m, full body",
    "orientation": "portrait",
    "zoom_or_lens": "1x",
    "lighting_tip": "turn the subject toward the window",
    "visible_evidence": ["window on the left wall"],
    "needs_on_site_check": ["whether the light changes later in the day"],
    "steps": ["step back two paces", "place subject on left third", "expose for the face"],
}


def _compositions() -> list[dict]:
    return [dict(COMPOSITION, title=f"{COMPOSITION['title']} {i}") for i in (1, 2, 3)]


def default_response(prompt: str) -> str:
    """Pick the canned answer that matches the prompt type (see prompts.py)."""
    if "In 2-3 sentences" in prompt:
        return "FAKE notes: subject small in the frame, low camera, lots of sky."
    if "Describe this scene for a photographer" in prompt:
        return json.dumps(TARGET)
    if "notes on a photographer" in prompt:
        return json.dumps(AESTHETIC)
    if "is described as" in prompt:
        return json.dumps({"compositions": _compositions()})
    if "Inspiration photo 1" in prompt and "TARGET scene photo" in prompt:
        return json.dumps({"aesthetic": AESTHETIC, "target_scene": TARGET, "compositions": _compositions()})
    if "TARGET scene photo" in prompt:
        return json.dumps({"target_scene": TARGET, "compositions": _compositions()})
    if "Inspiration photo 1" in prompt:
        return json.dumps(AESTHETIC)
    return "FAKE: a photo."


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

    def generate(self, prompt: str, images: list[str], params: GenerationParams) -> Generation:
        self.load()
        self.calls.append((prompt, list(images)))
        t0 = time.perf_counter()
        text = self._responses.pop(0) if self._responses else default_response(prompt)
        return Generation(text=text, wall_seconds=time.perf_counter() - t0, finish_reason="stop")

    def unload(self) -> None:
        self._loaded = False

    def inspect_inputs(self, prompt: str, images: list[str]) -> dict:
        return {"n_images_given": len(images), "images_seen": len(images), "formatted_prompt": prompt}

    def runtime_info(self) -> dict:
        return {"backend": "fake"}
