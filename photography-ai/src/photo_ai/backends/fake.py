"""Deterministic stand-in backend: lets you exercise the UI, storage and tests
without downloading weights. Its output is canned and says so."""

from __future__ import annotations

import json
import time

from .base import Generation, GenerationParams, ModelSpec, PromptPrefix

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


DIRECTION = {  # shot-v2 fields
    "body_pose": "weight on the back foot, left hand loosely in the coat pocket",
    "head_direction": "head turned toward the window, chin level",
    "gaze": "looking out of the window, past the frame edge",
    "expression_cue": "",
}


REASONING = {  # shot-v3 fields
    "scene_reading": "FAKE: a window on the left wall and a chair by it.",
    "setup_choice": "low and close, with the window as key light",
    "why_each_choice": ["the window gives soft side light", "the chair gives the subject something to lean on"],
    "fix_if_wrong": ["if the light is flat, move closer to the window"],
}


def _compositions(v2: bool = False, v3: bool = False) -> list[dict]:
    extra = {**(DIRECTION if v2 or v3 else {}), **(REASONING if v3 else {})}
    return [dict(COMPOSITION, title=f"{COMPOSITION['title']} {i}", **extra) for i in (1, 2, 3)]


def default_response(prompt: str) -> str:
    """Pick the canned answer that matches the prompt type (see prompts.py)."""
    if "In 2-3 sentences" in prompt:
        return "FAKE notes: subject small in the frame, low camera, lots of sky."
    if "Describe this scene for a photographer" in prompt:
        return json.dumps(TARGET)
    if "notes on a photographer" in prompt:
        return json.dumps(AESTHETIC)
    if "Propose ONE portrait look" in prompt:
        return json.dumps(_compositions(v2=True)[0])
    if "is described as" in prompt:
        return json.dumps({"compositions": _compositions(v2="gaze" in prompt, v3="setup_choice" in prompt)})
    if "Inspiration photo 1" in prompt and "TARGET scene photo" in prompt:
        return json.dumps({"aesthetic": AESTHETIC, "target_scene": TARGET, "compositions": _compositions()})
    if "TARGET scene photo" in prompt:
        return json.dumps({"target_scene": TARGET, "compositions": _compositions()})
    if "Inspiration photo 1" in prompt:
        return json.dumps(AESTHETIC)
    return "FAKE: a photo."


STREAM_CHUNK = 7  # characters per streamed piece; small and odd so pieces split keys, strings and braces


class FakeBackend:
    def __init__(self, spec: ModelSpec, responses: list[str] | None = None):
        self.spec = spec
        self.load_seconds: float | None = None
        self._responses = list(responses) if responses else None
        self._loaded = False
        self.calls: list[tuple[str, list[str]]] = []
        self.prefix_calls: list[tuple[str, list[str]]] = []
        self.prefix_hits: list[bool] = []

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> float:
        if self._loaded:
            return 0.0
        self._loaded = True
        self.load_seconds = 0.0
        return 0.0

    def prepare_prefix(self, prompt: str, images: list[str], params: GenerationParams) -> PromptPrefix | None:
        self.load()
        self.prefix_calls.append((prompt, list(images)))
        return PromptPrefix(text=prompt, state=object(), n_tokens=len(prompt))

    def generate(self, prompt: str, images: list[str], params: GenerationParams, on_text=None,
                 prefix: PromptPrefix | None = None) -> Generation:
        self.load()
        self.calls.append((prompt, list(images)))
        cached = prefix is not None and not prefix.used and prompt == prefix.text
        if cached:
            prefix.used = True
        self.prefix_hits.append(cached)
        t0 = time.perf_counter()
        text = self._responses.pop(0) if self._responses else default_response(prompt)
        if on_text is not None:  # stream in small pieces, like a real model, so callers see partial output
            for i in range(0, len(text), STREAM_CHUNK):
                on_text(text[i:i + STREAM_CHUNK])
        return Generation(text=text, wall_seconds=time.perf_counter() - t0, finish_reason="stop", prefix_cached=cached)

    def generate_batch(self, items: list[tuple[str, list[str]]], params: GenerationParams) -> list[Generation]:
        """Same answers as calling generate() on each item in order (the fake has no padding to disturb them)."""
        return [self.generate(prompt, images, params) for prompt, images in items]

    def unload(self) -> None:
        self._loaded = False

    def inspect_inputs(self, prompt: str, images: list[str]) -> dict:
        return {"n_images_given": len(images), "images_seen": len(images), "formatted_prompt": prompt}

    def runtime_info(self) -> dict:
        return {"backend": "fake"}
