"""Structured output the models are asked to produce (schema v4).

Validation is lenient about *shape* (a bare string where a list is expected is
wrapped; duplicate list items are dropped) but strict about *content*: the
fields that make advice actionable must be present and non-empty, and nothing
may be copied verbatim from the prompt's field descriptions.

v3 adds, versus v2:
  aesthetic.per_image          one line per inspiration photo (verifies it saw each one)
  aesthetic.principles         transferable techniques, separate from the original backgrounds
  composition.camera_height / camera_angle / subject_position / distance_and_framing
  composition.visible_evidence what in the target photo the shot relies on (inferred from the still)
  composition.needs_on_site_check  what the photo cannot show (requires moving the camera / more info)

v4 adds the versioned *shot format* shared by the Scene Director and the Inspiration Director:
  shot-v1  the v3 composition (camera, subject position, framing, light, evidence, checks)
  shot-v2  shot-v1 plus subject direction: body_pose, head_direction (head/chin), gaze and an
           optional expression_cue; framing and light become required.
  target_scene.people_in_frame  who is visible in the scene photo (observable only), or "none".
Every v4 field is optional on the base models, so v3 / shot-v1 results still validate and render.

shot-v3 (prompt v7) is shot-v1 with reasoning before the instructions: scene_reading, setup_choice,
why_each_choice (>= 2 reasons) and fix_if_wrong (>= 1), all required in ShotV3 and optional elsewhere.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

SCHEMA_VERSION = 4
SHOT_FORMATS = ("v1", "v2", "v3")


def _as_list(value: Any) -> Any:
    """Wrap a bare string into a list; drop empty and duplicate items (small models loop)."""
    if isinstance(value, str):
        value = [p.strip() for p in value.replace(";", ",").split(",")]
    if isinstance(value, list):
        seen, out = set(), []
        for item in value:
            if isinstance(item, dict):  # e.g. {"photo": 1, "description": "..."}
                item = "; ".join(str(v) for v in item.values())
            key = item.strip().lower() if isinstance(item, str) else repr(item)
            if item and key not in seen:
                seen.add(key)
                out.append(item)
        return out
    return value


def _as_text(value: Any) -> Any:
    """Join a list into one string for fields that are meant to be prose."""
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return value


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)


class Aesthetic(_Lenient):
    per_image: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    principles: list[str] = Field(default_factory=list)
    color_palette: list[str] = Field(default_factory=list)
    lighting: str = ""
    mood: str = ""
    composition_patterns: list[str] = Field(default_factory=list)
    subject_treatment: str = ""

    _lists = field_validator("per_image", "principles", "color_palette", "composition_patterns", mode="before")(_as_list)
    _texts = field_validator("summary", "lighting", "mood", "subject_treatment", mode="before")(_as_text)


class TargetScene(_Lenient):
    description: str = Field(min_length=1)
    key_elements: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    people_in_frame: str = ""

    _lists = field_validator("key_elements", "constraints", mode="before")(_as_list)
    _texts = field_validator("description", "people_in_frame", mode="before")(_as_text)


class Composition(_Lenient):
    # shot-v3 reasoning (optional here; required in ShotV3)
    scene_reading: str = ""
    setup_choice: str = ""
    why_each_choice: list[str] = Field(default_factory=list)
    fix_if_wrong: list[str] = Field(default_factory=list)
    title: str = Field(min_length=1)
    uses_principle: str = ""
    camera_position: str = Field(min_length=1)
    camera_height: str = Field(min_length=1)
    camera_angle: str = Field(min_length=1)
    subject_position: str = Field(min_length=1)
    distance_and_framing: str = ""
    orientation: str = ""
    zoom_or_lens: str = ""
    lighting_tip: str = ""
    visible_evidence: list[str] = Field(default_factory=list)
    needs_on_site_check: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    # shot-v2 subject direction (optional here so shot-v1 results stay valid)
    body_pose: str = ""
    head_direction: str = ""
    gaze: str = ""
    expression_cue: str = ""

    _lists = field_validator("visible_evidence", "needs_on_site_check", "steps", "why_each_choice", "fix_if_wrong",
                             mode="before")(_as_list)
    _texts = field_validator(
        "scene_reading", "setup_choice", "title", "uses_principle", "camera_position", "camera_height", "camera_angle", "subject_position",
        "distance_and_framing", "orientation", "zoom_or_lens", "lighting_tip",
        "body_pose", "head_direction", "gaze", "expression_cue", mode="before",
    )(_as_text)


class ShotV2(Composition):
    """shot-v2: framing, light and subject direction are required; the expression cue stays optional."""

    distance_and_framing: str = Field(min_length=1)
    lighting_tip: str = Field(min_length=1)
    body_pose: str = Field(min_length=1)
    head_direction: str = Field(min_length=1)
    gaze: str = Field(min_length=1)


class ShotV3(Composition):
    """shot-v3: the shot-v1 composition plus the reasoning that comes before the instructions."""

    scene_reading: str = Field(min_length=1)
    setup_choice: str = Field(min_length=1)
    why_each_choice: list[str] = Field(min_length=2)
    fix_if_wrong: list[str] = Field(min_length=1)


class CompositionSet(_Lenient):
    compositions: list[Composition] = Field(min_length=3)


class ShotSetV2(_Lenient):
    compositions: list[ShotV2] = Field(min_length=3)


class ShotSetV3(_Lenient):
    compositions: list[ShotV3] = Field(min_length=3)


def shot_set(shot_format: str) -> type[BaseModel]:
    if shot_format not in SHOT_FORMATS:
        raise ValueError(f"shot_format must be one of {SHOT_FORMATS}")
    return {"v2": ShotSetV2, "v3": ShotSetV3}.get(shot_format, CompositionSet)


def shot_format_of(record: dict) -> str:
    """Shot format of a saved run; runs made before shot-v2 existed are shot-v1."""
    return (record.get("config") or {}).get("shot_format") or record.get("shot_format") or "v1"


class RecommendationSet(_Lenient):
    target_scene: TargetScene
    compositions: list[Composition] = Field(min_length=3)


class FullResult(_Lenient):
    aesthetic: Aesthetic
    target_scene: TargetScene
    compositions: list[Composition] = Field(min_length=3)


def _echoes(obj: Any, forbidden: set[str], path: str = "") -> list[str]:
    """Paths whose text is a verbatim copy of a prompt field description."""
    if isinstance(obj, str):
        return [path or "<root>"] if obj.strip().lower().rstrip(".") in forbidden else []
    if isinstance(obj, dict):
        return [e for k, v in obj.items() for e in _echoes(v, forbidden, f"{path}.{k}".lstrip("."))]
    if isinstance(obj, list):
        return [e for i, v in enumerate(obj) for e in _echoes(v, forbidden, f"{path}.{i}")]
    return []


def validate(
    model: type[BaseModel], data: Any, template_text: set[str] | None = None
) -> tuple[dict | None, list[str]]:
    """Return (normalized dict, errors). Normalized output keeps only the first 3 compositions.

    `template_text`: prompt field descriptions; any value copied verbatim from them is an error,
    because a model echoing the template has not actually analyzed the photos.
    """
    try:
        obj = model.model_validate(data)
    except ValidationError as exc:
        errors = [f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()]
        return None, errors
    out = obj.model_dump()
    if "compositions" in out:
        out["compositions"] = out["compositions"][:3]
    if template_text:
        forbidden = {t.strip().lower().rstrip(".") for t in template_text}
        echoed = _echoes(out, forbidden)
        if echoed:
            return None, [f"{p}: copied the prompt's field description" for p in echoed]
    return out, []
