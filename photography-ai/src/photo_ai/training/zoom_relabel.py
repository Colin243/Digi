"""Zoom relabel pass: turn shot-v3 draft labels into shot-v4 (prompt v11) labels.

  photo-ai train-data zoom-relabel --step backup                 # labels -> labels.before-zoom (once)
  photo-ai train-data zoom-relabel --step worklist --out w.json  # what each look says now, and what to fix
  photo-ai train-data zoom-relabel --step apply --file edits.json --source "ai-draft:<who>"
  photo-ai train-data zoom-relabel --step report                 # zoom_fit over the labels, and v4 readiness

The pass is a field edit. Per look it may change only:
  zoom_or_lens          "<amount>x: <reason under 10 words>", amount 1x to 2x
  why_each_choice       exactly 2 reasons (the lens/distance reason moves into zoom_or_lens)
  distance_and_framing  the distance for the chosen zoom (about amount x the 1x distance)
  needs_on_site_check   optional, 1-2 items, e.g. "Room to step back 4 m"
Everything else (camera fields, steps, scene reading, the other parts of the answer) stays byte-identical.

edits.json: [{"example_id": ..., "looks": [{<the fields above>} x 3], "note": optional}, ...]

Rules enforced here:
  * the backup must exist before anything is applied, and is never overwritten;
  * approved labels are skipped (an edit would send them back to draft; re-review them by hand instead);
  * rejected labels are skipped;
  * an edit for one example is applied whole or not at all: every look must pass check_look();
  * status stays "draft"; the history records who drafted the change.
"""

from __future__ import annotations

import json
import re
import shutil

from .. import framing
from .assemble import load_examples
from .export import has_zoom
from .labels import (
    _now,
    labels_dir,
    load_label,
    load_labels,
    save_label,
    validate_answer,
)
from .pool import data_dir

BACKUP = "labels.before-zoom"
EDITABLE = ("zoom_or_lens", "why_each_choice", "distance_and_framing", "needs_on_site_check")
_AMOUNT_HEAD = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*x\s*:\s*(.+)$", re.IGNORECASE)


def backup(dataset: str = "train_v1") -> str:
    src, dst = labels_dir(dataset), data_dir(dataset) / BACKUP
    if dst.exists():
        raise FileExistsError(f"{dst} already exists; it is the pre-zoom copy and is never overwritten")
    shutil.copytree(src, dst)
    return str(dst)


def _words(s: str) -> int:
    return len(re.findall(r"[A-Za-z0-9'°.-]+", s))


def check_look(look: dict) -> list[str]:
    """Hard checks on one relabelled look. framing.zoom_fit's reason_matches/lean stay informational."""
    errs = []
    z = look.get("zoom_or_lens")
    m = _AMOUNT_HEAD.match(z) if isinstance(z, str) else None
    if not m:
        errs.append(f"zoom_or_lens must read '<amount>x: <reason>', got {z!r}")
    else:
        amount, reason = float(m.group(1)), m.group(2).strip()
        if not framing.ZOOM_MIN <= amount <= framing.ZOOM_MAX:
            errs.append(f"zoom {amount}x is outside 1x-2x")
        if not 3 <= _words(reason) < 10:
            errs.append(f"zoom reason must be 3-9 words, got {_words(reason)}: {reason!r}")
    why = look.get("why_each_choice")
    if not (isinstance(why, list) and len(why) == 2 and all(isinstance(r, str) and r.strip() for r in why)):
        errs.append("why_each_choice must be exactly 2 reasons")
    elif any(_words(r) >= 12 for r in why):
        errs.append("each why_each_choice reason must be under 12 words")
    checks = look.get("needs_on_site_check")
    if not (isinstance(checks, list) and 1 <= len(checks) <= 2):
        errs.append("needs_on_site_check must have 1-2 items")
    fit = framing.zoom_fit(look)
    if not (fit["in_range"] and fit["reason"]):
        errs.append("zoom_fit: amount not in range or no reason")
    if fit["distance_not_scaled"]:
        errs.append("zoomed 1.5x+ but distance_and_framing keeps the 1x distance")
    return errs


def worklist(dataset: str = "train_v1") -> list[dict]:
    """One entry per draft label: the photos, the scene, and each look's current fields plus zoom_fit."""
    examples = {e["example_id"]: e for e in load_examples(dataset)}
    from .pool import load_pool

    pool = {i["id"]: i for i in load_pool(dataset)["images"]}
    out = []
    for lab in load_labels(dataset):
        if lab["status"] != "draft":
            continue
        ex = examples[lab["example_id"]]
        ans = lab["answer"]
        looks = []
        for c in ans["compositions"]:
            looks.append({
                **{k: c.get(k) for k in ("title", "scene_reading", "setup_choice", "camera_position", "camera_height",
                                          "camera_angle", "subject_position", "visible_evidence", *EDITABLE)},
                "zoom_fit": framing.zoom_fit(c),
                "setup": framing.classify(c),
            })
        out.append({
            "example_id": lab["example_id"],
            "target_photo": pool[ex["target"]]["file"],
            "subject": ex.get("subject"),
            "target_scene": ans.get("target_scene", {}).get("description"),
            "aesthetic_summary": ans.get("aesthetic", {}).get("summary"),
            "looks": looks,
        })
    return out


def apply_edits(dataset: str, edits: list[dict], source: str) -> dict:
    if not (data_dir(dataset) / BACKUP).exists():
        raise FileNotFoundError(f"run the backup step first ({BACKUP})")
    if not source.startswith("ai-draft:") and not source.startswith("human:"):
        raise ValueError("source must be 'ai-draft:<who>' or 'human:<name>'")
    examples = {e["example_id"]: e for e in load_examples(dataset)}
    applied, skipped = [], {}
    for e in edits:
        eid = e["example_id"]
        lab = load_label(dataset, eid)
        if lab is None:
            skipped[eid] = "no label"
            continue
        if lab["status"] != "draft":
            skipped[eid] = f"status {lab['status']} (only drafts are relabelled)"
            continue
        looks = e.get("looks") or []
        if len(looks) != 3:
            skipped[eid] = "needs exactly 3 looks"
            continue
        extra = sorted({k for lk in looks for k in lk} - set(EDITABLE))
        if extra:
            skipped[eid] = f"fields outside the zoom edit: {extra}"
            continue
        new = [{**c, **{k: v for k, v in lk.items()}} for c, lk in zip(lab["answer"]["compositions"], looks)]
        problems = [f"look {i}: {p}" for i, c in enumerate(new, 1) for p in check_look(c)]
        if problems:
            skipped[eid] = "; ".join(problems[:4])
            continue
        lab["answer"] = {**lab["answer"], "compositions": new}
        lab["schema_errors"] = validate_answer(lab["answer"], len(examples[eid]["inspiration"]))
        amounts = ", ".join(c["zoom_or_lens"].split(":")[0] for c in new)
        lab["history"].append({"at": _now(), "by": source, "action": "zoom-relabelled",
                               "note": f"shot-v4 (prompt v11): zoom {amounts} with a reason, 2 reasons, distance "
                                       f"for the zoom. Still an unreviewed draft. {e.get('note', '')}".strip()})
        save_label(dataset, lab)
        applied.append(eid)
    return {"applied": len(applied), "skipped": skipped}


def report(dataset: str = "train_v1") -> dict:
    labs = [lab for lab in load_labels(dataset) if lab["status"] != "rejected"]
    looks = [c for lab in labs for c in lab["answer"]["compositions"]]
    relabelled = [lab for lab in labs if any(h["action"] == "zoom-relabelled" for h in lab["history"])]
    failing = {lab["example_id"]: [p for i, c in enumerate(lab["answer"]["compositions"], 1) for p in
                                    (f"look {i}: {x}" for x in check_look(c))][:2]
               for lab in labs}
    amounts = [framing.zoom_fit(c)["amount"] for c in looks]
    return {
        "labels": len(labs),
        "relabelled": len(relabelled),
        "v4_exportable": sum(has_zoom(lab["answer"]) for lab in labs),
        "passing_check_look": sum(1 for v in failing.values() if not v),
        "amounts": {str(a): amounts.count(a) for a in sorted(set(amounts), key=lambda x: (x is None, x))},
        **framing.summarize_zoom(looks),
        "failing": {k: v for k, v in failing.items() if v},
    }


def load_edits(path) -> list[dict]:
    return json.loads(open(path).read())
