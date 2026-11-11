"""Dataset-freeze coverage audit: what the APPROVED labels cover, and where the gaps are.

Read-only over data/<dataset>/: it reads examples.json and labels/*.json and never writes,
creates or edits anything (no approvals, no status changes). Only labels with
status == "approved" are counted, because only those are exported for training.

Counted per example: split, mode (scene-only vs inspiration) and style.
Counted per shot (composition): body-pose bucket, expression-cue bucket and shot format.

Older labels predate the shot-v2 fields (body_pose, head_direction, gaze, optional
expression_cue) and the optional style/mode keys. Missing values count as "unspecified";
nothing here raises on an old or partial label. A shot-v2 shot with no expression_cue counts
as "omitted", which is an acceptable choice (see docs/annotation-xhs-addendum.md), not a gap.

Gaps use the targets from #2 (>= 15 approved train, >= 3 approved valid examples) plus a
per-value minimum for each mode, style, pose and expression. docs/annotation-xhs-addendum.md
explains how a gap becomes a targeted follow-up batch.
"""

from __future__ import annotations

import json
import re
from collections import Counter

from .pool import data_dir

SPLITS = ("train", "valid")
MODES = ("inspiration", "scene-only")
STYLES = ("relaxed_candid", "dreamy_atmospheric", "cool_editorial", "vintage_ccd")
POSES = ("standing", "walking", "sitting", "leaning", "crouching")  # "lying" is counted but not required
EXPRESSIONS = ("omitted", "neutral", "smile", "laugh")
UNSPEC = "unspecified"
SHOT_V2_KEYS = ("body_pose", "head_direction", "gaze", "expression_cue")

MIN_TRAIN, MIN_VALID = 15, 3  # approval targets from #2

STYLE_ALIASES = {
    "relaxed candid": "relaxed_candid", "松弛感": "relaxed_candid",
    "dreamy atmospheric": "dreamy_atmospheric", "氛围感": "dreamy_atmospheric",
    "cool editorial": "cool_editorial", "清冷感": "cool_editorial",
    "vintage ccd": "vintage_ccd", "复古 ccd": "vintage_ccd", "复古ccd": "vintage_ccd",
}
MODE_ALIASES = {"scene-only": "scene-only", "scene_only": "scene-only", "scene": "scene-only",
                "inspiration": "inspiration", "reference": "inspiration"}

# First match wins, so "leaning on the wall, standing" is leaning and "sits ... looks up" is sitting.
POSE_PATTERNS = (
    ("lying", r"\b(lie|lies|lying|reclin\w*)\b|躺"),
    ("sitting", r"\b(sit|sits|sitting|seated|perch\w*)\b|坐"),
    ("crouching", r"\b(crouch\w*|squat\w*|kneel\w*)\b|蹲"),
    ("leaning", r"\b(lean|leans|leaning)\b|靠"),
    ("walking", r"\b(walk|walks|walking|stride|striding|stroll\w*|mid-step)\b|走"),
    ("standing", r"\b(stand|stands|standing)\b|站"),
)
EXPRESSION_PATTERNS = (
    ("laugh", r"\blaugh\w*\b|笑出"),
    ("smile", r"\b(smile|smiles|smiling|grin\w*)\b|微笑"),
    ("neutral", r"\b(neutral|relaxed|soft|calm|still|unposed|natural|no expression|closed mouth|lips together)\b"),
)


def _match(text: str, patterns) -> str:
    for name, pat in patterns:
        if re.search(pat, text, re.I):
            return name
    return "other"


def _norm(value, aliases: dict) -> str:
    if not isinstance(value, str) or not value.strip():
        return UNSPEC
    v = value.strip().lower()
    return aliases.get(v, aliases.get(v.replace("_", " "), v.replace(" ", "_")))


def is_shot_v2(comp: dict) -> bool:
    return isinstance(comp, dict) and any(k in comp for k in SHOT_V2_KEYS)


def pose_bucket(comp: dict) -> str:
    text = comp.get("body_pose") if isinstance(comp, dict) else None
    if not isinstance(text, str) or not text.strip():
        return UNSPEC
    return _match(text, POSE_PATTERNS)


def expression_bucket(comp: dict) -> str:
    if not is_shot_v2(comp):
        return UNSPEC  # shot-v1: the field did not exist yet
    text = comp.get("expression_cue")
    if not isinstance(text, str) or not text.strip():
        return "omitted"
    return _match(text, EXPRESSION_PATTERNS)


def _first(*values):
    return next((v for v in values if isinstance(v, str) and v.strip()), None)


def _read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _read(dataset: str) -> tuple[dict, list[dict], int]:
    """(examples by id, labels, unreadable label files). Never creates directories."""
    root = data_dir(dataset)
    examples = _read_json(root / "examples.json") if (root / "examples.json").exists() else []
    examples = {e["example_id"]: e for e in examples or [] if isinstance(e, dict) and "example_id" in e}
    labels, bad = [], 0
    ldir = root / "labels"
    for p in sorted(ldir.glob("*.json")) if ldir.is_dir() else []:
        lab = _read_json(p)
        if isinstance(lab, dict):
            labels.append(lab)
        else:
            bad += 1
    return examples, labels, bad


def coverage(dataset: str = "train_v1", min_examples: int = 3, min_shots: int = 3) -> dict:
    examples, labels, unreadable = _read(dataset)
    statuses = Counter(lab.get("status", UNSPEC) for lab in labels)
    approved = [lab for lab in labels if lab.get("status") == "approved"]

    split, mode, style, style_split = Counter(), Counter(), Counter(), Counter()
    pose, expression, shot_format = Counter(), Counter(), Counter()
    for lab in approved:
        ex = examples.get(lab.get("example_id"), {})
        answer = lab.get("answer") if isinstance(lab.get("answer"), dict) else {}
        sp = ex.get("split") if ex.get("split") in SPLITS else UNSPEC
        m = _norm(_first(lab.get("mode"), answer.get("mode"), ex.get("mode")), MODE_ALIASES)
        if m == UNSPEC and ex:  # pre-mode examples: inferable from whether inspiration photos were given
            m = "inspiration" if ex.get("inspiration") else "scene-only"
        st = _norm(_first(lab.get("style"), answer.get("style"), ex.get("style")), STYLE_ALIASES)
        split[sp] += 1
        mode[m] += 1
        style[st] += 1
        style_split[f"{st}/{sp}"] += 1
        for comp in answer.get("compositions") or []:
            if not isinstance(comp, dict):
                continue
            pose[pose_bucket(comp)] += 1
            expression[expression_bucket(comp)] += 1
            shot_format["shot-v2" if is_shot_v2(comp) else "shot-v1"] += 1

    gaps = []
    for s, need in (("train", MIN_TRAIN), ("valid", MIN_VALID)):
        if split[s] < need:
            gaps.append(f"split {s}: {split[s]} approved examples, target {need}")
    for name, counts, expected, need, unit in (
        ("mode", mode, MODES, min_examples, "examples"),
        ("style", style, STYLES, min_examples, "examples"),
        ("pose", pose, POSES, min_shots, "shots"),
        ("expression", expression, EXPRESSIONS, min_shots, "shots"),
    ):
        for v in expected:
            if counts[v] < need:
                gaps.append(f"{name} {v}: {counts[v]} approved {unit}, minimum {need}")
        if counts[UNSPEC]:
            gaps.append(f"{name}: {counts[UNSPEC]} approved {unit} have no {name} recorded (unspecified)")
    for st in STYLES:
        if style_split[f"{st}/valid"] == 0:
            gaps.append(f"style {st}: no approved validation example")

    def ordered(counts: Counter, expected) -> dict:
        keys = list(expected) + sorted(k for k in counts if k not in expected)
        return {k: counts[k] for k in keys}

    return {
        "dataset": dataset,
        "labels": dict(statuses),
        "unreadable_labels": unreadable,
        "approved": len(approved),
        "examples_by": {
            "split": ordered(split, SPLITS),
            "mode": ordered(mode, MODES),
            "style": ordered(style, STYLES),
            "style_split": {k: style_split[k] for k in sorted(style_split)},
        },
        "shots_by": {
            "pose": ordered(pose, POSES),
            "expression": ordered(expression, EXPRESSIONS),
            "format": ordered(shot_format, ("shot-v1", "shot-v2")),
        },
        "thresholds": {"train": MIN_TRAIN, "valid": MIN_VALID, "min_examples": min_examples, "min_shots": min_shots},
        "gaps": gaps,
    }


def render(report: dict) -> str:
    def row(label, counts):
        return f"  {label:13} " + (" | ".join(f"{k} {v}" for k, v in counts.items()) or "none")

    lab = report["labels"]
    lines = [f"Coverage audit: {report['dataset']} (approved labels only; read-only)",
             f"  approved {report['approved']} of {sum(lab.values())} labels "
             f"({', '.join(f'{k} {v}' for k, v in sorted(lab.items())) or 'none'})"]
    if report["unreadable_labels"]:
        lines.append(f"  {report['unreadable_labels']} label file(s) could not be read and were skipped")
    lines.append("Examples")
    for k, v in report["examples_by"].items():
        lines.append(row(k.replace("_", " x "), v))
    lines.append("Shots (3 per example)")
    for k, v in report["shots_by"].items():
        lines.append(row(k, v))
    gaps = report["gaps"]
    lines.append(f"Gaps ({len(gaps)})" if gaps else "Gaps: none at these thresholds")
    lines += [f"  - {g}" for g in gaps]
    if gaps:
        lines.append("Close gaps with a targeted reserve batch: docs/annotation-xhs-addendum.md, 'From gap to follow-up batch'.")
    return "\n".join(lines)
