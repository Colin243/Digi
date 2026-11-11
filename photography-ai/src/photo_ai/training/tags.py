"""Per-image technique tags used to group inspiration sets.

Stored in data/<dataset>/tags.json as {pool_id: record}. A record is
  {"tags": {...}, "source": "ai-draft:<who>" | "human:<name>", "status": "draft" | "approved"}
Drafted tags are provisional. They only steer grouping; the reference answers built on
top of them are reviewed separately (labels.py), so a wrong tag cannot silently become a
training target.

Person tags: role, camera_angle, framing, distance, pose, facing, placement, light[], setting,
n_people, usable, notes. Place tags: role, setting, elements[], light[], people_present, usable.
"""

from __future__ import annotations

import json
from datetime import datetime

from .pool import data_dir

CAMERA_ANGLES = ("low", "eye", "high", "overhead")
FRAMINGS = ("close-up", "half-body", "full-body", "environmental")
POSES = ("standing", "sitting", "walking", "leaning", "lying", "candid-motion", "other")
LIGHTS = ("front", "side", "back", "silhouette", "golden-hour", "overcast-soft", "night-artificial",
          "harsh-sun", "window", "shade")
ROLES = ("person", "place", "reject")


def tags_path(dataset: str = "train_v1"):
    return data_dir(dataset) / "tags.json"


def load_tags(dataset: str = "train_v1") -> dict:
    p = tags_path(dataset)
    return json.loads(p.read_text()) if p.exists() else {}


def validate_tags(t: dict) -> list[str]:
    errs = []
    role = t.get("role")
    if role not in ROLES:
        errs.append(f"role must be one of {ROLES}")
    if role == "person" and t.get("usable", True):
        for key, allowed in (("camera_angle", CAMERA_ANGLES), ("framing", FRAMINGS), ("pose", POSES)):
            if t.get(key) not in allowed:
                errs.append(f"{key}={t.get(key)!r} not in {allowed}")
        bad = [x for x in t.get("light", []) if x not in LIGHTS]
        if bad:
            errs.append(f"unknown light tags {bad}")
    if role == "place" and not t.get("elements"):
        errs.append("place needs elements")
    return errs


def import_tags(dataset: str, records: dict | list, source: str) -> int:
    """Merge drafted tags. Never overwrites a human-approved record."""
    if isinstance(records, list):
        records = {r["id"]: r for r in records}
    existing = load_tags(dataset)
    n = 0
    for pid, t in records.items():
        t = {k: v for k, v in t.items() if k != "id"}
        if existing.get(pid, {}).get("status") == "approved":
            continue
        existing[pid] = {"tags": t, "source": source, "status": "draft",
                         "errors": validate_tags(t), "imported_at": datetime.now().isoformat(timespec="seconds")}
        n += 1
    tags_path(dataset).write_text(json.dumps(existing, indent=1, ensure_ascii=False))
    return n
