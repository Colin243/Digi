"""Structured output the models are asked to produce.

Validation is deliberately lenient about *shape* (a bare string where a list is
expected is wrapped) but strict about *content* (required fields must exist and
there must be at least three compositions). Every coercion is visible in the
saved raw output, so nothing is silently invented.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


def _as_list(value: Any) -> Any:
    """Wrap a bare string into a list; drop exact duplicates (small models loop)."""
    if isinstance(value, str):
        value = [p.strip() for p in value.replace(";", ",").split(",")]
    if isinstance(value, list):
        seen, out = set(), []
        for item in value:
            key = item.strip().lower() if isinstance(item, str) else repr(item)
            if item and key not in seen:
                seen.add(key)
                out.append(item)
        return out
    return value


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)


class Aesthetic(_Lenient):
    summary: str = Field(min_length=1)
    color_palette: list[str] = Field(default_factory=list)
    lighting: str = ""
    mood: str = ""
    composition_patterns: list[str] = Field(default_factory=list)
    subject_treatment: str = ""

    _lists = field_validator("color_palette", "composition_patterns", mode="before")(_as_list)


class TargetScene(_Lenient):
    description: str = Field(min_length=1)
    key_elements: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)

    _lists = field_validator("key_elements", "constraints", mode="before")(_as_list)


class Composition(_Lenient):
    title: str = Field(min_length=1)
    framing: str = ""
    orientation: str = ""
    camera_position: str = ""
    subject_placement: str = ""
    zoom_or_lens: str = ""
    lighting_tip: str = ""
    why_it_matches: str = ""
    steps: list[str] = Field(default_factory=list)

    _lists = field_validator("steps", mode="before")(_as_list)


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
        return [path or "<root>"] if obj.strip().lower() in forbidden else []
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
        forbidden = {t.strip().lower() for t in template_text}
        echoed = _echoes(out, forbidden)
        if echoed:
            return None, [f"{p}: copied the prompt's field description" for p in echoed]
    return out, []
