"""Reference answers ("labels") for training examples, with provenance and approval state.

One file per example: data/<dataset>/labels/<example_id>.json

  {
    "example_id": "...",
    "status": "draft" | "approved" | "rejected",
    "answer": {
      "inspiration_notes": ["one note per inspiration photo, in order"],
      "target_scene": {...TargetScene...},
      "aesthetic": {...Aesthetic...},
      "compositions": [{...Composition...} x 3]
    },
    "provenance": {
      "drafted_by": "ai-draft:<model/agent>" | "human:<name>",
      "drafted_at": ...,
      "edited_by": [names of humans who edited],
      "approved_by": "<human name>" | null,
      "approved_at": ... | null
    },
    "history": [{"at", "by", "action", "note"}],
    "review_notes": "..."
  }

Rules enforced here (not just by convention):
  * imported drafts always start as status "draft", whatever the file says;
  * only a human rater name can approve (AI-reserved names such as claude-* are refused);
  * approving requires the answer to pass schema validation;
  * editing an approved label sends it back to "draft" until re-approved;
  * export.py only ever reads status == "approved" (except an explicit smoke-test flag).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime

from .. import schema
from ..evaluation import rater_kind
from .assemble import load_examples
from .pool import data_dir


def labels_dir(dataset: str = "train_v1"):
    d = data_dir(dataset) / "labels"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_label(dataset: str, example_id: str) -> dict | None:
    p = labels_dir(dataset) / f"{example_id}.json"
    return json.loads(p.read_text()) if p.exists() else None


def load_labels(dataset: str = "train_v1") -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(labels_dir(dataset).glob("*.json"))]


def save_label(dataset: str, label: dict) -> None:
    (labels_dir(dataset) / f"{label['example_id']}.json").write_text(json.dumps(label, indent=1, ensure_ascii=False))


def answer_sha(answer: dict) -> str:
    """Fingerprint of an answer's text, so a review can be tied to the exact version the reviewer saw."""
    return hashlib.sha256(json.dumps(answer, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def validate_answer(answer: dict, n_inspiration: int | None = None) -> list[str]:
    errs = []
    notes = answer.get("inspiration_notes")
    if not isinstance(notes, list) or not all(isinstance(n, str) and n.strip() for n in notes):
        errs.append("inspiration_notes must be a list of non-empty strings")
    elif n_inspiration is not None and len(notes) != n_inspiration:
        errs.append(f"inspiration_notes has {len(notes)} entries for {n_inspiration} photos")
    for key, model in (("target_scene", schema.TargetScene), ("aesthetic", schema.Aesthetic)):
        _, e = schema.validate(model, answer.get(key), None)
        errs += [f"{key}.{x}" for x in e]
    comps = answer.get("compositions")
    if not isinstance(comps, list) or len(comps) != 3:
        errs.append("exactly 3 compositions required")
    else:
        _, e = schema.validate(schema.CompositionSet, {"compositions": comps}, None)
        errs += e
    return errs


def import_drafts(dataset: str, drafts: list[dict], source: str) -> int:
    """Add AI (or other) drafted answers. Never overwrites an approved label."""
    examples = {e["example_id"]: e for e in load_examples(dataset)}
    n = 0
    for d in drafts:
        eid = d["example_id"]
        if eid not in examples:
            raise KeyError(f"unknown example {eid}")
        current = load_label(dataset, eid)
        if current and current["status"] == "approved":
            continue
        label = {
            "example_id": eid,
            "status": "draft",
            "answer": d["answer"],
            "provenance": {"drafted_by": source, "drafted_at": _now(), "edited_by": [],
                           "approved_by": None, "approved_at": None},
            "schema_errors": validate_answer(d["answer"], len(examples[eid]["inspiration"])),
            "history": [{"at": _now(), "by": source, "action": "draft-imported", "note": d.get("note", "")}],
            "review_notes": "",
        }
        save_label(dataset, label)
        n += 1
    return n


def _require_human(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("reviewer name is required")
    if rater_kind(name) != "human":
        raise ValueError(f"{name!r} is an AI reviewer name; only humans can edit or approve training labels")
    return name


def edit_answer(dataset: str, example_id: str, answer: dict, reviewer: str, note: str = "") -> dict:
    reviewer = _require_human(reviewer)
    label = load_label(dataset, example_id)
    example = {e["example_id"]: e for e in load_examples(dataset)}[example_id]
    label["answer"] = answer
    label["schema_errors"] = validate_answer(answer, len(example["inspiration"]))
    if reviewer not in label["provenance"]["edited_by"]:
        label["provenance"]["edited_by"].append(reviewer)
    if label["status"] == "approved":  # any edit needs a fresh approval
        label["status"] = "draft"
        label["provenance"]["approved_by"] = label["provenance"]["approved_at"] = None
    label["history"].append({"at": _now(), "by": reviewer, "action": "edited", "note": note})
    save_label(dataset, label)
    return label


def set_status(dataset: str, example_id: str, status: str, reviewer: str, note: str = "") -> dict:
    reviewer = _require_human(reviewer)
    if status not in ("draft", "approved", "rejected"):
        raise ValueError("status must be draft, approved or rejected")
    label = load_label(dataset, example_id)
    if status == "approved" and label.get("schema_errors"):
        raise ValueError("cannot approve: fix schema errors first: " + "; ".join(label["schema_errors"][:3]))
    label["status"] = status
    if status == "approved":
        label["provenance"]["approved_by"], label["provenance"]["approved_at"] = reviewer, _now()
    else:
        label["provenance"]["approved_by"] = label["provenance"]["approved_at"] = None
    label["review_notes"] = note or label.get("review_notes", "")
    label["history"].append({"at": _now(), "by": reviewer, "action": status, "note": note})
    save_label(dataset, label)
    return label


def status_summary(dataset: str = "train_v1") -> dict:
    examples = load_examples(dataset)
    labels = {lab["example_id"]: lab for lab in load_labels(dataset)}
    by_split = Counter()
    for e in examples:
        lab = labels.get(e["example_id"])
        by_split[(e["split"], lab["status"] if lab else "unlabeled")] += 1
    return {
        "examples": len(examples),
        "labels": dict(Counter(lab["status"] for lab in labels.values())),
        "by_split_status": {f"{s}/{st}": n for (s, st), n in sorted(by_split.items())},
        "approved_human": sum(1 for lab in labels.values() if lab["status"] == "approved"),
        "drafted_by": dict(Counter(lab["provenance"]["drafted_by"] for lab in labels.values())),
    }


# --------------------------------------------------------------------------- creative-director review import

SHOT_WORDS = {"yes": "would shoot", "fix": "needs changes", "no": "skip"}
SET_WORDS = {"yes": "clearly", "fix": "loosely", "no": "not really"}


def import_creative_review(dataset: str, review: dict, reviewer: str | None = None,
                           seen: dict[str, str] | None = None) -> dict:
    """Apply a review from the Shot Review page (shared store doc, download, or "Copy my review" text).

    review = {"name": str, "reviews": {example_id: {"overall": yes|fix|no|None, "set": ..., "shots": [{"v", "fix"}]*3,
              "comment": str}}, "answer_sha": {example_id: sha}}. `seen` gives the same fingerprints when the review
    file predates them (read from the review page that was sent, see review_site.seen_answers).

    Approval is deliberately strict:
      * "Yes, as is" approves only when every shot verdict is "would shoot" or blank AND the answer's current
        fingerprint matches the one the reviewer saw. A review of text that was edited later, or that cannot be
        tied to a version, is recorded but approves nothing (approve_blocked_stale / approve_blocked_unverified).
      * "Yes, after fixes", or a "yes" with any shot marked needs-changes or skip, sends the label back to draft
        (un-approving it if it was approved) with the requested fixes in review_notes.
      * "No" rejects.
    Every example the reviewer touched gets a history entry; nothing is applied for an AI-reserved reviewer name.
    """
    who = _require_human(reviewer or review.get("name", ""))
    seen = {**(seen or {}), **(review.get("answer_sha") or {})}
    counts = Counter()
    for eid, r in review.get("reviews", {}).items():
        lab = load_label(dataset, eid)
        if lab is None:
            counts["unknown_example"] += 1
            continue
        shots = r.get("shots") or []
        parts = [f"Inspiration set shares one look: {SET_WORDS.get(r.get('set'), 'not answered')}."]
        for k, s in enumerate(shots, 1):
            if s.get("v") or s.get("fix"):
                parts.append(f"Shot {k}: {SHOT_WORDS.get(s.get('v'), 'no verdict')}" + (f" - {s['fix'].strip()}" if s.get("fix", "").strip() else ""))
        if (r.get("comment") or "").strip():
            parts.append("Comment: " + r["comment"].strip())
        summary = " ".join(parts)
        current, reviewed = answer_sha(lab["answer"]), seen.get(eid)
        lab["creative_review"] = {"reviewer": who, "overall": r.get("overall"), "set": r.get("set"), "shots": shots,
                                  "comment": r.get("comment", ""), "imported_at": _now(),
                                  "reviewed_answer_sha": reviewed, "answer_sha_at_import": current}
        lab["history"].append({"at": _now(), "by": who, "action": "creative-review", "note": summary})
        save_label(dataset, lab)
        overall = r.get("overall")
        shot_objections = any(s.get("v") in ("fix", "no") for s in shots)
        if overall == "yes" and not shot_objections:
            if reviewed is None or reviewed != current:
                key = "approve_blocked_unverified" if reviewed is None else "approve_blocked_stale"
                why = ("the review can't be tied to the text version it was given" if reviewed is None
                       else "the answer was edited after this review page was built")
                lab = load_label(dataset, eid)
                lab["history"].append({"at": _now(), "by": who, "action": "approval-not-applied", "note": f"Creative director said yes, but {why}; re-review needed."})
                lab["review_notes"] = f"Approval not applied: {why}. " + summary
                save_label(dataset, lab)
                counts[key] += 1
                continue
            if lab.get("schema_errors"):
                counts["approve_blocked_schema"] += 1
                continue
            set_status(dataset, eid, "approved", who, "Creative director: yes, as is. " + summary)
            counts["approved"] += 1
        elif overall == "no":
            set_status(dataset, eid, "rejected", who, "Creative director: no. " + summary)
            counts["rejected"] += 1
        elif overall in ("yes", "fix"):
            note = "Creative director asked for fixes: " + summary
            if lab["status"] != "draft":  # an approved (or rejected) label goes back to draft until fixed and re-approved
                set_status(dataset, eid, "draft", who, note)
                counts["unapproved_for_fixes" if lab["status"] == "approved" else "reopened_for_fixes"] += 1
            lab = load_label(dataset, eid)
            lab["review_notes"] = note
            save_label(dataset, lab)
            counts["needs_fixes"] += 1
        else:
            counts["partial"] += 1
    return dict(counts)
