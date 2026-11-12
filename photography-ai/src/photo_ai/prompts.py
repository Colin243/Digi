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
     verbatim into titles. Benchmark bench-phase3 (portrait suite) ran on v4.
  json_format="keys" (variant of v4, same wording): the answer format is described as
     "a JSON object with keys: ..." instead of a blank JSON shape to fill in. Added after
     SmolVLM2-2.2B returned the blank shape unchanged; recorded in each run's config.
  v5 (2026-11-10.5) shot-v2 and the Scene Director. New prompts only: the v4 prompts above are
     byte-identical when shot_format="v1", so the Phase 3 benchmark and LoRA training templates
     are unchanged. Runs record PROMPT_VERSION for shot-v1 inspiration runs and
     PROMPT_VERSION_V5 for scene-mode or shot-v2 runs (see version_for).
  v6 (2026-11-12.6) Scene Director look plans carry the three phone-portrait setups from framing.py
     (half body: camera just above the head, tilt down; full body: crouch, tilt up, feet on the bottom
     edge; seated: stomach height, diagonal). Only LOOK_PLANS changed; v4 prompts stay byte-identical,
     so the Phase 3 benchmark, the iPhone harness and LoRA training templates are unchanged. The
     setups reach the v4 pipeline through training labels instead (docs/annotation-guide.md).
     Scene-eval runs on v5 are not comparable with v6 runs.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

from . import framing
from .backends import IMAGE_MARKER

PROMPT_VERSION = "2026-11-09.4"
PROMPT_VERSION_V5 = "2026-11-12.6"  # name kept: the scene-mode / shot-v2 prompt version


def version_for(mode: str = "inspiration", shot_format: str = "v1") -> str:
    return PROMPT_VERSION if (mode == "inspiration" and shot_format == "v1") else PROMPT_VERSION_V5

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

# shot-v2: the subject-direction fields shared by Scene Director and Inspiration Director.
DIRECTION_FIELDS = {
    "body_pose": "stance or seated position, weight, arms and hands, using only surfaces visible in the photo",
    "head_direction": "which way the head turns and whether the chin lifts, drops or stays level",
    "gaze": "exactly where the eyes look: the lens, a named thing in the scene, or a direction out of frame",
    "expression_cue": "optional: one small expression the subject may choose, such as a soft closed-mouth smile; leave empty if it adds little",
}
COMPOSITION_FIELDS_V2 = {**COMPOSITION_FIELDS, **DIRECTION_FIELDS}
SCENE_SHOT_FIELDS = {
    **COMPOSITION_FIELDS_V2,
    "title": "a short name for this look",
    "uses_principle": "which part of the style brief this look puts into practice",
}
DIRECTOR_TARGET_FIELDS = {
    **TARGET_FIELDS,
    "people_in_frame": "who is visible in the photo, where they are and what they are physically doing, or the word none; describe only what can be seen",
}

ALL_FIELD_DESCRIPTIONS = {
    d for f in (AESTHETIC_FIELDS, TARGET_FIELDS, COMPOSITION_FIELDS, DIRECTION_FIELDS, SCENE_SHOT_FIELDS,
                DIRECTOR_TARGET_FIELDS) for d in f.values()
}

# Starter style briefs (XHS / 小红书 portrait vocabulary). Each brief steers camera, light, pose,
# gaze and expression; the model still has to ground every shot in the scene photo.
STYLE_BRIEFS = {
    "relaxed_candid": {
        "zh": "松弛感", "en": "relaxed candid",
        "brief": "Unforced and lived-in, as if caught between moments. Eye level or slightly below, half-body to "
                 "full-body, the subject a little off-centre with room around them. Soft available light. Poses "
                 "that look mid-action: a slow step, a hand loosely in a pocket or brushing hair back, leaning "
                 "lightly on something stable. Gaze mostly away from the lens or a casual glance back. "
                 "Expression optional: an easy half-smile or simply relaxed.",
    },
    "dreamy_atmospheric": {
        "zh": "氛围感", "en": "dreamy atmospheric",
        "brief": "Soft, hazy and layered. Use backlight, glow, reflections or out-of-focus foreground (shoot "
                 "past something close to the lens). Warm or pastel tones, gentle highlights, plenty of air "
                 "around the subject. Slow, quiet poses: turning the head over the shoulder, a hand near the "
                 "face, standing still in the light. Gaze down, into the distance or eyes softly closed. "
                 "Expression optional: calm, lips relaxed.",
    },
    "cool_editorial": {
        "zh": "清冷感", "en": "cool editorial",
        "brief": "Clean, quiet and composed. Strong lines and clear negative space, cool or neutral tones, "
                 "even light from shade or overcast sky. Upright posture, shoulders relaxed, minimal gestures; "
                 "chin level or slightly down. Gaze steady into the lens or a clean profile looking past the "
                 "frame. Expression optional: neutral, no big smile.",
    },
    "vintage_ccd": {
        "zh": "复古 CCD", "en": "vintage CCD",
        "brief": "Early-2000s compact-camera snapshot. Straight-on or slightly high point-and-shoot angle, 4:3 "
                 "framing, subject fairly central, a bit of everyday background clutter is fine. Hard direct "
                 "light such as the phone flash at night or indoors, bright highlights and slight motion are "
                 "part of the look; in lighting_tip, say whether to turn the phone flash on. Playful, spontaneous poses: a peace sign, a hand toward the lens, a "
                 "half-turn mid-laugh. Gaze straight into the lens. Expression optional: a big natural grin "
                 "or a playful pout.",
    },
    "japanese_fresh": {
        "zh": "日系", "en": "Japanese fresh",
        "brief": "Bright, airy and a little overexposed, like soft Japanese film. Pale, low-contrast colours, lots of "
                 "light and empty space. Eye level, often half or full body with the subject small and off-centre. "
                 "Quiet everyday moments: holding a drink, looking out of a window, a slow walk. Gaze away or down. "
                 "Expression optional: a small natural smile.",
    },
    "hk_retro": {
        "zh": "港风", "en": "Hong Kong retro",
        "brief": "1990s Hong Kong film look: warm, saturated reds and greens, neon or tungsten light, a little "
                 "grain and haze. Slightly low or eye-level angles, half body, the subject framed by signs, doorways "
                 "or street lights. Cool, confident poses: a glance over the shoulder, a hand in the hair, leaning in "
                 "a doorway. Gaze past the lens or a direct stare. Expression optional: unsmiling, cool.",
    },
    "french_chic": {
        "zh": "法式", "en": "French chic",
        "brief": "Effortless and elegant. Soft natural light, muted warm tones, classic architecture or café details. "
                 "Eye level, full or three-quarter body, the subject walking or pausing mid-step, holding a bag or "
                 "a coat. Gaze down or off to the side, sometimes a quick look back. Expression optional: a slight, "
                 "closed-mouth smile.",
    },
    "korean_clean": {
        "zh": "韩系", "en": "Korean clean",
        "brief": "Clean, soft and polished. Even, flattering front or window light, bright skin, simple backgrounds "
                 "with soft pastel or neutral colours. Eye level or slightly high, waist up or close-up, the subject "
                 "centred. Gentle poses: hands near the face, a head tilt, sitting neatly. Gaze into the lens. "
                 "Expression optional: a soft, bright smile.",
    },
}


def style_label(key: str | None) -> str:
    s = STYLE_BRIEFS.get(key or "")
    return f"{s['zh']} {s['en']}" if s else "custom brief"


DIRECTION_RULES = """Direct the subject as a photographer would, using only what the scene allows.
- body_pose, head_direction and gaze must be specific instructions (where the hands go, which way the chin turns, the exact thing the eyes look at).
- expression_cue is optional creative direction the subject may choose to follow. Never guess what anyone in the photo feels, and never describe someone's mood or emotion. Leave expression_cue empty when it adds little.
- Keep every direction safe and checkable: no stepping into traffic, onto ledges, railings or water, and no climbing. Only use walls, seats, steps and ground you can see in the photo; if a pose needs a surface or space the photo does not show, list it in needs_on_site_check."""

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


JSON_FORMATS = ("shape", "keys")
_format = "shape"


@contextmanager
def json_format(fmt: str):
    """Temporarily switch how the expected JSON is described ("shape" = blank JSON, "keys" = prose)."""
    global _format
    if fmt not in JSON_FORMATS:
        raise ValueError(f"json_format must be one of {JSON_FORMATS}")
    old, _format = _format, fmt
    try:
        yield
    finally:
        _format = old


def _describe(obj) -> str:
    if isinstance(obj, dict):
        return "an object with keys: " + "; ".join(f'"{k}" ({_describe(v)})' for k, v in obj.items())
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict):
            return f"a list of exactly {len(obj)} objects, each with keys: " + "; ".join(
                f'"{k}" ({_describe(v)})' for k, v in obj[0].items())
        return "a list of strings"
    return "a string"


def _answer(shape) -> str:
    if _format == "keys":
        return "Return only a JSON " + _describe(shape).replace("an object", "object", 1) + "."
    return f"Fill in this JSON:\n{_shape(shape)}"


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
        f"{SPECIFICITY_RULES}\n{_RULES}\n{_answer(shape)}"
    )


def stage1_aesthetic(n_inspiration: int) -> str:
    return (
        _labeled_inspiration(n_inspiration) + "\n"
        f"You are a photography director. These {n_inspiration} inspiration photos show the style a "
        "photographer wants to recreate somewhere else. Describe each photo, then the style they share "
        "and the techniques that could transfer to a different location.\n\n"
        f"{_guide('Fields', AESTHETIC_FIELDS)}\n\n{_RULES}\n{_answer(_blank(AESTHETIC_FIELDS))}"
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
        f"{SPECIFICITY_RULES}\n{_RULES}\n{_answer(shape)}"
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
        f"{_guide('Fields', TARGET_FIELDS)}\n\n{_RULES}\n{_answer(_blank(TARGET_FIELDS))}"
    )


def aesthetic_from_notes(notes: list[str]) -> str:
    listed = "\n".join(f"Inspiration photo {i}: {n}" for i, n in enumerate(notes, 1))
    shape = _blank(AESTHETIC_FIELDS)
    return (
        "You are a photography director. Here are notes on a photographer's inspiration photos:\n"
        f"{listed}\n\n"
        "Describe the style they share and the techniques that could transfer to a different location. "
        "For per_image, summarize each note in one line, in order.\n\n"
        f"{_guide('Fields', AESTHETIC_FIELDS)}\n\n{_RULES}\n{_answer(shape)}"
    )


def compositions_from_parts(aesthetic: dict, target: dict, subject: str = DEFAULT_SUBJECT,
                            shot_format: str = "v1") -> str:
    """shot_format "v1" returns exactly the v4 prompt (benchmark and training-template parity)."""
    style = {k: v for k, v in aesthetic.items() if k != "per_image"}
    fields = COMPOSITION_FIELDS_V2 if shot_format == "v2" else COMPOSITION_FIELDS
    shape = {"compositions": [_blank(fields)] * 3}
    direction = f"\n{DIRECTION_RULES}" if shot_format == "v2" else ""
    return (
        TARGET_LABEL + "\n"
        f"You are a photography director. The TARGET scene photo is described as:\n{_shape(target)}\n\n"
        f"The photographer wants to recreate this style from other photos:\n{_shape(style)}\n\n"
        f"The subject will be {subject}. Give exactly 3 different compositions for shooting in the "
        "TARGET scene with that style.\n\n"
        f"{_guide('each of the 3 compositions', fields)}\n\n"
        f"{SPECIFICITY_RULES}{direction}\n{_RULES}\n{_answer(shape)}"
    )


# --- Scene Director: one scene photo + a style brief, no reference images ---------------

SCENE_LABEL = f"SCENE photo: {IMAGE_MARKER}\n"


def director_scene() -> str:
    return (
        SCENE_LABEL + "\n"
        "Describe this scene for a photographer who is standing there now and wants to make portraits in it. "
        "If people are visible, say only where they are and what they are physically doing.\n\n"
        f"{_guide('Fields', DIRECTOR_TARGET_FIELDS)}\n\n{_RULES}\n{_answer(_blank(DIRECTOR_TARGET_FIELDS))}"
    )


# Each look is generated in its own call with a different plan. Asked for all three at once,
# Qwen3-VL-2B wrote look 1 and repeated it twice (scene-demo-v1: field diversity 0.00-0.36).
LOOK_PLANS = (
    "WIDE: full body, the subject small to medium in the frame, the camera far enough back to show the "
    "most useful part of the scene. Unless the scene needs more distance, use this setup: "
    + framing.brief("full_body"),
    "MEDIUM: waist up or three-quarter body, the camera in a different place from the earlier looks, and a "
    "different pose. Use this setup: " + framing.brief("half_body"),
    "CLOSE: head and shoulders, using the light or a foreground element in a new way, with a different gaze "
    "from the earlier looks.",
)

# Extra plans for review pages that offer more choices (RunConfig.n_looks up to 5); the default stays three.
EXTRA_LOOK_PLANS = (
    "SEATED OR LEANING: use a seat, step, wall or ledge-free surface that is visible in the photo; a new camera "
    "height from the earlier looks. If the subject sits, use this setup: " + framing.brief("seated"),
    "IN MOTION: a candid moment such as a slow walk, a turn or adjusting hair or clothes, on ground visible in "
    "the photo; framing different from the earlier looks.",
)
ALL_LOOK_PLANS = LOOK_PLANS + EXTRA_LOOK_PLANS

PEOPLE_RULE = ("If people are already visible in the photo, treat them as passers-by: direct only the subject, "
               "place the subject where the photo shows free space, and do not ask strangers to do anything.")


def _style_text(style_key: str | None, brief: str) -> str:
    starter = STYLE_BRIEFS.get(style_key or "")
    parts = []
    if starter:
        parts.append(f"Style: {starter['zh']} ({starter['en']}). {starter['brief']}")
    if brief.strip():
        parts.append(f"The photographer adds: {brief.strip()}")
    return "\n".join(parts) or "Style: natural, flattering portraits that suit this scene."


def scene_look(scene: dict, style_key: str | None = None, brief: str = "", subject: str = DEFAULT_SUBJECT,
               look: int = 1, previous: list[dict] | None = None, total: int = 3) -> str:
    """Prompt for ONE shot-v2 look (look = 1..3); earlier looks are listed so this one differs."""
    shot = _blank(SCENE_SHOT_FIELDS)
    avoid = ""
    if previous:
        lines = [f"- Look {i}: {p.get('title', '')}: camera {p.get('camera_position', '')}; "
                 f"{p.get('distance_and_framing', '')}; pose {p.get('body_pose', '')}; gaze {p.get('gaze', '')}"
                 for i, p in enumerate(previous, 1)]
        avoid = ("Earlier looks for this scene (this one must be clearly different in camera position, framing "
                 "and pose):\n" + "\n".join(lines) + "\n\n")
    return (
        SCENE_LABEL + "\n"
        f"You are a portrait photography director. The SCENE photo is described as:\n{_shape(scene)}\n\n"
        f"{_style_text(style_key, brief)}\n\n"
        f"The subject will be {subject}. {PEOPLE_RULE}\n"
        f"{avoid}Propose ONE portrait look, look {look} of {max(3, total)}, in that style. Plan for this look: {ALL_LOOK_PLANS[look - 1]}\n\n"
        f"{_guide('Fields', SCENE_SHOT_FIELDS)}\n\n"
        f"{SPECIFICITY_RULES}\n{DIRECTION_RULES}\n{_RULES}\n{_answer(shot)}"
    )


RETRY_SUFFIX = (
    "\n\nYour previous answer was not valid. "
    "Reply again with ONLY the filled-in JSON object, starting with '{' and ending with '}'."
)
