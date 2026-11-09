"""Prompt text, kept in one place so prompt changes are easy to diff and version.

Bump PROMPT_VERSION whenever wording changes; it is saved with every run so
results from different prompt revisions are never compared by accident.

v1 put field descriptions inside the JSON template; SmolVLM2-500M copied them
back verbatim. v2 lists field meanings as prose and shows a blank JSON shape.
"""

from __future__ import annotations

import json

PROMPT_VERSION = "2026-11-09.2"

# field -> meaning. Lists are marked with a trailing "[]" on the key.
AESTHETIC_FIELDS = {
    "summary": "one or two sentences on the visual style the photos share",
    "color_palette[]": "2-4 dominant colors or tones",
    "lighting": "light quality, direction, time of day",
    "mood": "the emotional feel in a few words",
    "composition_patterns[]": "2-4 recurring framing or layout choices",
    "subject_treatment": "how people or subjects are shown",
}

TARGET_FIELDS = {
    "description": "one sentence on what is in the target scene",
    "key_elements[]": "2-4 subjects, lines, shapes or light sources to use",
    "constraints[]": "1-3 things that limit the shot, e.g. clutter or harsh light",
}

COMPOSITION_FIELDS = {
    "title": "a short name",
    "framing": "wide, medium or close-up",
    "orientation": "portrait, landscape or square",
    "camera_position": "where to stand and the camera height/angle",
    "subject_placement": "where the main subject sits in the frame",
    "zoom_or_lens": "zoom amount or focal length feel",
    "lighting_tip": "how to use or fix the light",
    "why_it_matches": "how it echoes the inspiration style",
    "steps[]": "2-4 short actionable steps",
}

ALL_FIELD_DESCRIPTIONS = {
    d for f in (AESTHETIC_FIELDS, TARGET_FIELDS, COMPOSITION_FIELDS) for d in f.values()
}


def _blank(fields: dict) -> dict:
    return {k.removesuffix("[]"): ([] if k.endswith("[]") else "") for k in fields}


def _guide(title: str, fields: dict) -> str:
    lines = [f"{title}:"]
    for k, v in fields.items():
        kind = "list of strings" if k.endswith("[]") else "string"
        lines.append(f"- {k.removesuffix('[]')} ({kind}): {v}")
    return "\n".join(lines)


_RULES = (
    "Rules: answer with ONLY one JSON object, no markdown, no commentary. "
    "Write your own words about THESE photos; do not repeat the field descriptions. "
    "Be concrete and practical: things a person holding a phone or compact camera can do now. "
    "Do not repeat list items."
)


def _shape(obj) -> str:
    return json.dumps(obj, separators=(", ", ": "))


def single_pass(n_inspiration: int) -> str:
    shape = {
        "aesthetic": _blank(AESTHETIC_FIELDS),
        "target_scene": _blank(TARGET_FIELDS),
        "compositions": [_blank(COMPOSITION_FIELDS)] * 3,
    }
    return (
        f"You are a photography coach. The first {n_inspiration} images are INSPIRATION photos "
        "showing the style the photographer likes. The LAST image is the TARGET scene they are "
        "about to photograph. Describe the shared aesthetic, describe the target scene, and "
        "recommend exactly 3 different, practical compositions for the target scene in that "
        "aesthetic.\n\n"
        f"{_guide('aesthetic', AESTHETIC_FIELDS)}\n{_guide('target_scene', TARGET_FIELDS)}\n"
        f"{_guide('each of the 3 compositions', COMPOSITION_FIELDS)}\n\n"
        f"{_RULES}\nFill in this JSON:\n{_shape(shape)}"
    )


def stage1_aesthetic(n_inspiration: int) -> str:
    return (
        f"You are a photography coach. These {n_inspiration} images are inspiration photos "
        "showing the style a photographer likes. Describe the aesthetic they share.\n\n"
        f"{_guide('Fields', AESTHETIC_FIELDS)}\n\n"
        f"{_RULES}\nFill in this JSON:\n{_shape(_blank(AESTHETIC_FIELDS))}"
    )


def stage2_compositions(aesthetic: dict) -> str:
    shape = {"target_scene": _blank(TARGET_FIELDS), "compositions": [_blank(COMPOSITION_FIELDS)] * 3}
    return (
        "You are a photography coach. The image is the TARGET scene a photographer is about to "
        f"shoot. They want to match this aesthetic:\n{_shape(aesthetic)}\n\n"
        "Describe the target scene, then recommend exactly 3 different, practical compositions "
        "for photographing it in that aesthetic.\n\n"
        f"{_guide('target_scene', TARGET_FIELDS)}\n"
        f"{_guide('each of the 3 compositions', COMPOSITION_FIELDS)}\n\n"
        f"{_RULES}\nFill in this JSON:\n{_shape(shape)}"
    )


RETRY_SUFFIX = (
    "\n\nYour previous answer was not valid. "
    "Reply again with ONLY the filled-in JSON object, starting with '{' and ending with '}'."
)
