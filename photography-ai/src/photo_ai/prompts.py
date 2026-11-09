"""Prompt text, kept in one place so prompt changes are easy to diff and version.

Bump PROMPT_VERSION whenever wording changes; it is saved with every run so
results from different prompt revisions are never compared by accident.

History
  v1 (2026-11-09.1) field descriptions inside the JSON template -> SmolVLM2 copied them.
  v2 (2026-11-09.2) descriptions as prose, blank JSON shape.
  v3 (2026-11-09.3) schema v3 (camera height/angle, evidence vs on-site checks); every image
     is labeled inline ("Inspiration photo 2: <image>"), because diagnostics showed
     Qwen2.5-VL mixes up unlabeled images and both models need explicit roles;
     specificity rules with good/bad examples; new "decomposed" strategy prompts.
     Benchmark bench-phase2 ran on v3.
  v4 (2026-11-09.4) adds "do not reuse the example sentences" after SmolVLM2 copied them
     verbatim into titles. Not yet benchmarked.
"""

from __future__ import annotations

import json

from .backends import IMAGE_MARKER

PROMPT_VERSION = "2026-11-09.4"

DEFAULT_SUBJECT = "a person (the photographer's friend) posing in the scene"

# field -> meaning. Lists are marked with a trailing "[]" on the key.
AESTHETIC_FIELDS = {
    "per_image[]": "one short line per inspiration photo, in order: what it shows and how it was shot",
    "summary": "one or two sentences on the visual style the photos share",
    "principles[]": "2-4 transferable techniques (camera height, angle, framing, subject placement, negative space, light) that could be reused somewhere else",
    "color_palette[]": "2-4 dominant colors or tones",
    "lighting": "light quality, direction, time of day",
    "mood": "the emotional feel in a few words",
    "composition_patterns[]": "2-4 recurring framing or layout choices",
    "subject_treatment": "how people or subjects are shown",
}

TARGET_FIELDS = {
    "description": "one or two sentences on what is in the target scene",
    "key_elements[]": "3-6 specific things visible in the target photo that a shot can use (objects, lines, surfaces, light sources)",
    "constraints[]": "1-3 things in the target photo that limit the shot, e.g. clutter or harsh light",
}

COMPOSITION_FIELDS = {
    "title": "a short name",
    "uses_principle": "which inspiration principle this shot transfers",
    "camera_position": "where to stand, relative to named things in the target photo",
    "camera_height": "camera height relative to the subject's body or a scene object",
    "camera_angle": "which way to tilt or turn the camera and roughly how much",
    "subject_position": "where the subject stands in the scene and where they sit in the frame",
    "distance_and_framing": "approximate distance and how much of the subject is in frame",
    "orientation": "portrait, landscape or square",
    "zoom_or_lens": "zoom amount or focal length feel",
    "lighting_tip": "how to use the light that is visible in the target photo",
    "visible_evidence[]": "things you can actually see in the target photo that this shot depends on",
    "needs_on_site_check[]": "things the still photo cannot tell you, which the photographer must check by moving the camera or looking around",
    "steps[]": "2-4 short actionable steps",
}

ALL_FIELD_DESCRIPTIONS = {
    d for f in (AESTHETIC_FIELDS, TARGET_FIELDS, COMPOSITION_FIELDS) for d in f.values()
}

GOOD_EXAMPLES = [
    "Hold the camera slightly below the subject's waist.",
    "Place the subject in the left third of the frame.",
    "Tilt up slightly to emphasize height.",
    "Move to the right of the subject so the railing leads into the frame.",
]
BAD_EXAMPLES = ["take a wide shot", "use good lighting", "center the subject", "capture the moment"]

SPECIFICITY_RULES = f"""Make every composition concrete enough to follow without guessing.
Good: {" ".join(f'"{g}"' for g in GOOD_EXAMPLES)}
Bad (too generic, never write these): {", ".join(f'"{b}"' for b in BAD_EXAMPLES)}.
Only use things that are visible in the TARGET photo. Do not bring objects or backgrounds from the inspiration photos into the target scene; transfer the technique, not the scenery.
Separate what you can see from what you are assuming: put visible facts in visible_evidence, and put anything the still photo cannot show (what is behind the camera, true distances, light at another time, whether a spot is reachable) in needs_on_site_check.
Write new instructions for THIS scene; do not reuse the example sentences above."""

_RULES = (
    "Answer with ONLY one JSON object, no markdown, no commentary. "
    "Write your own words about THESE photos; do not repeat the field descriptions. Do not repeat list items."
)


def _blank(fields: dict) -> dict:
    return {k.removesuffix("[]"): ([] if k.endswith("[]") else "") for k in fields}


def _guide(title: str, fields: dict) -> str:
    lines = [f"{title}:"]
    for k, v in fields.items():
        kind = "list of strings" if k.endswith("[]") else "string"
        lines.append(f"- {k.removesuffix('[]')} ({kind}): {v}")
    return "\n".join(lines)


def _shape(obj) -> str:
    return json.dumps(obj, separators=(", ", ": "), ensure_ascii=False)


def _labeled_inspiration(n: int) -> str:
    return "".join(f"Inspiration photo {i}: {IMAGE_MARKER}\n" for i in range(1, n + 1))


TARGET_LABEL = f"TARGET scene photo: {IMAGE_MARKER}\n"


def single_pass(n_inspiration: int, subject: str = DEFAULT_SUBJECT) -> str:
    shape = {
        "aesthetic": _blank(AESTHETIC_FIELDS),
        "target_scene": _blank(TARGET_FIELDS),
        "compositions": [_blank(COMPOSITION_FIELDS)] * 3,
    }
    return (
        _labeled_inspiration(n_inspiration) + TARGET_LABEL + "\n"
        f"You are a photography director. The {n_inspiration} inspiration photos show the style the "
        "photographer wants. The TARGET scene photo is a different place where they will shoot now. "
        f"The subject will be {subject}.\n"
        "Describe the inspiration aesthetic, describe the TARGET scene, and give exactly 3 different "
        "compositions for shooting in the TARGET scene with that aesthetic.\n\n"
        f"{_guide('aesthetic', AESTHETIC_FIELDS)}\n{_guide('target_scene', TARGET_FIELDS)}\n"
        f"{_guide('each of the 3 compositions', COMPOSITION_FIELDS)}\n\n"
        f"{SPECIFICITY_RULES}\n{_RULES}\nFill in this JSON:\n{_shape(shape)}"
    )


def stage1_aesthetic(n_inspiration: int) -> str:
    return (
        _labeled_inspiration(n_inspiration) + "\n"
        f"You are a photography director. These {n_inspiration} inspiration photos show the style a "
        "photographer wants to recreate somewhere else. Describe each photo, then the style they share "
        "and the techniques that could transfer to a different location.\n\n"
        f"{_guide('Fields', AESTHETIC_FIELDS)}\n\n{_RULES}\nFill in this JSON:\n{_shape(_blank(AESTHETIC_FIELDS))}"
    )


def stage2_compositions(aesthetic: dict, subject: str = DEFAULT_SUBJECT) -> str:
    shape = {"target_scene": _blank(TARGET_FIELDS), "compositions": [_blank(COMPOSITION_FIELDS)] * 3}
    style = {k: v for k, v in aesthetic.items() if k != "per_image"}  # keep inspiration scenery out
    return (
        TARGET_LABEL + "\n"
        "You are a photography director. The TARGET scene photo shows where the photographer will "
        f"shoot now. The subject will be {subject}. They want to recreate this style from other photos:\n"
        f"{_shape(style)}\n\n"
        "Describe the TARGET scene, then give exactly 3 different compositions for shooting in it with that style.\n\n"
        f"{_guide('target_scene', TARGET_FIELDS)}\n{_guide('each of the 3 compositions', COMPOSITION_FIELDS)}\n\n"
        f"{SPECIFICITY_RULES}\n{_RULES}\nFill in this JSON:\n{_shape(shape)}"
    )


# --- decomposed strategy: one image per call, then text-guided composition ------------

def image_notes() -> str:
    return (
        f"Photo: {IMAGE_MARKER}\n"
        "In 2-3 sentences, say what this photo shows and how it was shot: camera height and angle, "
        "framing, where the main subject sits in the frame, how much empty space there is, and the light."
    )


def target_scene_only() -> str:
    return (
        TARGET_LABEL + "\n"
        "Describe this scene for a photographer who is standing there now.\n\n"
        f"{_guide('Fields', TARGET_FIELDS)}\n\n{_RULES}\nFill in this JSON:\n{_shape(_blank(TARGET_FIELDS))}"
    )


def aesthetic_from_notes(notes: list[str]) -> str:
    listed = "\n".join(f"Inspiration photo {i}: {n}" for i, n in enumerate(notes, 1))
    shape = _blank(AESTHETIC_FIELDS)
    return (
        "You are a photography director. Here are notes on a photographer's inspiration photos:\n"
        f"{listed}\n\n"
        "Describe the style they share and the techniques that could transfer to a different location. "
        "For per_image, summarize each note in one line, in order.\n\n"
        f"{_guide('Fields', AESTHETIC_FIELDS)}\n\n{_RULES}\nFill in this JSON:\n{_shape(shape)}"
    )


def compositions_from_parts(aesthetic: dict, target: dict, subject: str = DEFAULT_SUBJECT) -> str:
    style = {k: v for k, v in aesthetic.items() if k != "per_image"}
    shape = {"compositions": [_blank(COMPOSITION_FIELDS)] * 3}
    return (
        TARGET_LABEL + "\n"
        f"You are a photography director. The TARGET scene photo is described as:\n{_shape(target)}\n\n"
        f"The photographer wants to recreate this style from other photos:\n{_shape(style)}\n\n"
        f"The subject will be {subject}. Give exactly 3 different compositions for shooting in the "
        "TARGET scene with that style.\n\n"
        f"{_guide('each of the 3 compositions', COMPOSITION_FIELDS)}\n\n"
        f"{SPECIFICITY_RULES}\n{_RULES}\nFill in this JSON:\n{_shape(shape)}"
    )


RETRY_SUFFIX = (
    "\n\nYour previous answer was not valid. "
    "Reply again with ONLY the filled-in JSON object, starting with '{' and ending with '}'."
)
