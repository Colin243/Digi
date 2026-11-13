"""Heuristic quality checks for reference answers, shown to the reviewer before approval.

They target the Phase 3 weaknesses directly: repeated shots, vague camera guidance, missing
pose and light direction, objects that are not in the target photo, generic advice. They are
warnings for a human, not an automatic gate: approval stays a human decision.
"""

from __future__ import annotations

import re

from .. import framing, metrics
from .assemble import load_examples
from .tags import load_tags

POSE_WORDS = r"\b(stand|stands|standing|sit|sits|sitting|seated|walk|walks|walking|lean|leans|leaning|kneel|crouch|step|turn|turns|turned|look|looks|looking|face|faces|facing|hands?|arms?|weight|shoulder|chin|stride|perch)\b"
LIGHT_WORDS = r"\b(light|sun|shade|shadow|backlit|backlight|silhouette|window|golden|overcast|neon|lamp|expose|exposure|flare|glow|bright|dark)\b"


def check_answer(answer: dict, example: dict | None = None, target_elements: list[str] | None = None) -> list[str]:
    issues = []
    comps = answer.get("compositions") or []
    if len(comps) == 3:
        div = metrics.diversity(comps)
        if (div["field_distinct"] or 0) < 0.6:
            issues.append(f"shots too similar (only {div['field_distinct']:.0%} of camera/subject fields differ)")
    for i, c in enumerate(comps, 1):
        sp = metrics.specificity(c)
        if sp["cue_count"] < 3:
            issues.append(f"shot {i}: only {sp['cue_count']} concrete cue types {sp['cue_types']}")
        if sp["generic_count"]:
            issues.append(f"shot {i}: {sp['generic_count']} generic or copied phrase(s)")
        if not re.search(POSE_WORDS, str(c.get("subject_position", "")) + " " + " ".join(c.get("steps", [])), re.I):
            issues.append(f"shot {i}: no pose direction for the subject")
        if not re.search(LIGHT_WORDS, str(c.get("lighting_tip", "")), re.I):
            issues.append(f"shot {i}: lighting_tip gives no light direction")
        if not c.get("visible_evidence"):
            issues.append(f"shot {i}: no visible_evidence")
        if not c.get("needs_on_site_check"):
            issues.append(f"shot {i}: no needs_on_site_check")
        issues += [f"shot {i}: {m}" for m in framing.setup_contradictions(c)]
        if target_elements and c.get("visible_evidence"):
            grounded = [e for e in c["visible_evidence"] if metrics.mentions(e, target_elements)]
            if not grounded:
                issues.append(f"shot {i}: visible_evidence names nothing from the target's tagged elements")
    notes = answer.get("inspiration_notes") or []
    for i, n in enumerate(notes, 1):
        if not re.search(r"\b(low|eye[- ]level|level|high|overhead|above|below|chest|waist|knee|hip|shoulder|ground|"
                         r"looking (?:up|down)|tilt(?:ed)?|from below|from above)\b", n, re.I):
            issues.append(f"inspiration note {i}: camera height/angle not stated")
        if not re.search(r"\b(close|half|waist|full|body|head|wide|framed|framing|frame|torso|figure|tight|crop(?:ped)?|"
                         r"portrait|landscape|small in|fills?)\b", n, re.I):
            issues.append(f"inspiration note {i}: framing not stated")
    return issues


def check_label(label: dict, dataset: str = "train_v1") -> list[str]:
    example = {e["example_id"]: e for e in load_examples(dataset)}.get(label["example_id"])
    elements = None
    if example:
        t = load_tags(dataset).get(example["target"], {}).get("tags", {})
        elements = [w for e in t.get("elements", []) for w in re.findall(r"[a-z]{4,}", e.lower())] or None
    return list(label.get("schema_errors", [])) + check_answer(label["answer"], example, elements)
