"""Automatic, model-independent checks. These complement (never replace) human rubric scores.

All matching is plain keyword matching against hand-written case annotations, so
it is cheap, deterministic and easy to audit, but it only measures *mentions*,
not whether advice is good.
"""

from __future__ import annotations

import re
from itertools import combinations

from .cases import Case, CaseImage


def _rx(term: str) -> re.Pattern:
    # word-boundary match, tolerate simple plurals ("bench" -> "benches")
    return re.compile(rf"\b{re.escape(term.lower())}(?:s|es)?\b")


def mentions(text: str, terms: list[str]) -> list[str]:
    t = text.lower()
    return [term for term in terms if _rx(term).search(t)]


def image_recall(text: str, img: CaseImage) -> dict:
    hits = [g for g in img.objects if mentions(text, g)]
    return {
        "primary_hit": bool(mentions(text, img.primary)),
        "object_recall": round(len(hits) / len(img.objects), 3) if img.objects else None,
    }


def leaks(text: str, case: Case) -> list[str]:
    return mentions(text, case.leak_terms)


# --- specificity ----------------------------------------------------------------

# Concrete, checkable instruction cues (camera height, angle, distance, frame position, movement).
SPECIFIC_CUES = {
    "height": r"\b(eye[- ]level|waist|knee|chest|shoulder|hip|ground[- ]level|crouch|kneel|squat|overhead|above (?:the )?head|below (?:the )?(?:subject|waist|eye))",
    "angle": r"\b(tilt|angle[ds]? (?:up|down)|look(?:ing)? up|low[- ]angle|high[- ]angle|\d+\s?(?:°|degrees?)|bird'?s[- ]eye|worm'?s[- ]eye|dutch)",
    "distance": r"\b(\d+(?:\.\d+)?\s?(?:m|meters?|metres?|feet|ft|steps?|paces?)\b|arm'?s length|step (?:back|closer|forward)|close[- ]up|full[- ]body|half[- ]body|head(?:[- ]and[- ]|-to-)shoulders?)",
    "frame_position": r"\b((?:left|right|top|bottom|lower|upper) (?:third|quarter|half|edge|corner)|rule of thirds|third of the frame|centered|off[- ]center|foreground|background|lower third|upper third)",
    "movement": r"\b(move|walk|step|stand|position yourself|go to|shift|toward|towards)\b.{0,40}\b(left|right|behind|closer|back|side|toward|towards)",
    "lens": r"\b(\d+\s?mm|[0-9.]+x zoom|zoom (?:in|out)|wide[- ]angle|telephoto|portrait mode|0\.5x|1x|2x|3x|5x)",
}

GENERIC_PHRASES = [
    r"\bwell[- ]lit\b", r"\bgood light(?:ing)?\b", r"\bnatural light(?:ing)?\b(?! from)", r"\btake a (?:wide|medium|close[- ]up) shot\b",
    r"\bcapture the (?:beauty|essence|moment)\b", r"\bbe creative\b", r"\bexperiment with\b", r"^\s*(?:wide|medium|close[- ]up|center|close|far|middle)\s*$",
]


def composition_text(comp: dict) -> str:
    parts = []
    for v in comp.values():
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            parts.extend(str(x) for x in v)
    return "\n".join(parts)


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def _prompt_examples() -> set[str]:
    from .prompts import BAD_EXAMPLES, GOOD_EXAMPLES

    return {_normalize(x) for x in [*GOOD_EXAMPLES, *BAD_EXAMPLES]}


def copied_examples(comp: dict) -> list[str]:
    """Field values that are verbatim copies of the prompt's good/bad example sentences."""
    examples = _prompt_examples()
    vals = [v for v in comp.values() if isinstance(v, str)] + [
        x for v in comp.values() if isinstance(v, list) for x in v if isinstance(x, str)]
    return [v for v in vals if _normalize(v) in examples]


def specificity(comp: dict) -> dict:
    """Concrete cues in the composition. Text copied from the prompt's examples earns no credit."""
    copied = set(copied_examples(comp))
    comp = {k: v for k, v in comp.items() if not (isinstance(v, str) and v in copied)}
    text = composition_text(comp).lower()
    cues = sorted(k for k, rx in SPECIFIC_CUES.items() if re.search(rx, text))
    values = [v for v in comp.values() if isinstance(v, str)] + [
        x for v in comp.values() if isinstance(v, list) for x in v if isinstance(x, str)
    ]
    generic = sum(1 for v in values for rx in GENERIC_PHRASES if re.search(rx, v.lower()))
    return {"cue_types": cues, "cue_count": len(cues), "generic_count": generic + len(copied),
            "copied_prompt_examples": len(copied)}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", text.lower())}


def jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta | tb) if ta | tb else 1.0


def pairwise_similarity(texts: list[str]) -> float | None:
    pairs = list(combinations(texts, 2))
    if not pairs:
        return None
    return round(sum(jaccard(a, b) for a, b in pairs) / len(pairs), 3)


def evaluate_result(result: dict | None, case: Case | None) -> dict:
    """Auto metrics for one run's parsed result. Works with partial results."""
    if not result:
        return {"has_result": False}
    out: dict = {"has_result": True}
    comps = result.get("compositions") or []
    if comps:
        specs = [specificity(c) for c in comps]
        out["specific_cue_types_mean"] = round(sum(s["cue_count"] for s in specs) / len(specs), 2)
        out["generic_phrases_total"] = sum(s["generic_count"] for s in specs)
        out["copied_prompt_examples"] = sum(s["copied_prompt_examples"] for s in specs)
        out["per_composition"] = specs
        out["distinct_compositions"] = round(1 - (pairwise_similarity([composition_text(c) for c in comps]) or 0), 3)
    if case is None:
        return out
    target_text = composition_text(result.get("target_scene") or {})
    comps_text = "\n".join(composition_text(c) for c in comps)
    out["target_recall"] = image_recall(target_text, case.target)
    out["target_mentioned_in_compositions"] = image_recall(comps_text, case.target)["object_recall"]
    out["leaks_in_target"] = leaks(target_text, case)
    out["leaks_in_compositions"] = leaks(comps_text, case)
    aes = result.get("aesthetic") or {}
    per_image = aes.get("per_image") or []
    if per_image:
        out["inspiration_primary_hits"] = [
            image_recall(str(per_image[i]) if i < len(per_image) else "", img)["primary_hit"]
            for i, img in enumerate(case.inspiration)
        ]
    return out
