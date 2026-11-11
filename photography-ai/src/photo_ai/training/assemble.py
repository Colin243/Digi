"""Turn tagged pool images into training example skeletons.

An example = 3-4 inspiration photos that share a photographic technique (same camera angle +
framing, same pose + framing, or the same distinctive light) + one target place photo that is
NOT one of them. All images of an example come from the same split (train or valid), and
splits are by photographer (pool.py), so validation never shares a source shoot with training.

Deterministic for a given pool/tags/seed. Output: data/<dataset>/examples.json
"""

from __future__ import annotations

import json
import random
from collections import defaultdict

from .pool import data_dir, load_pool, usable
from .tags import load_tags

DEFAULT_SUBJECT = "a person (the photographer's friend) posing in the scene"
DISTINCT_LIGHTS = ("back", "silhouette", "golden-hour", "night-artificial", "window", "harsh-sun")


def _signatures(t: dict) -> list[tuple[str, str]]:
    sigs = [("angle+framing", f"{t['camera_angle']}|{t['framing']}"),
            ("pose+framing", f"{t['pose']}|{t['framing']}")]
    sigs += [("light", lt) for lt in t.get("light", []) if lt in DISTINCT_LIGHTS]
    return sigs


def _describe(kind: str, value: str) -> str:
    if kind == "angle+framing":
        angle, framing = value.split("|")
        return f"{angle}-angle {framing} shots"
    if kind == "pose+framing":
        pose, framing = value.split("|")
        return f"{pose} poses, {framing}"
    return f"{value} light"


def _candidates(dataset: str, exclude: set[str] = frozenset()) -> tuple[dict, dict, dict]:
    """Tagged, usable people and empty-place photos per split, minus `exclude`."""
    pool = {i["id"]: i for i in usable(load_pool(dataset))}
    tags = load_tags(dataset)
    people = {s: [] for s in ("train", "valid")}
    places = {s: [] for s in ("train", "valid")}
    for pid, rec in sorted(tags.items()):
        t = rec["tags"]
        if pid not in pool or pid in exclude or rec.get("errors") or not t.get("usable", True):
            continue
        split = pool[pid]["split"]
        if t["role"] == "person" and t.get("n_people", 1) <= 2:
            people[split].append(pid)
        elif t["role"] == "place" and not t.get("people_present", False):
            places[split].append(pid)
    return tags, people, places


def _pick(split: str, quota: int, people: list[str], places: list[str], tags: dict, rng: random.Random,
          set_size, max_per_technique: int, make_id) -> list[dict]:
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for pid in people:
        for sig in _signatures(tags[pid]["tags"]):
            groups[sig].append(pid)
    used: set[str] = set()
    targets = list(places)
    rng.shuffle(targets)
    out: list[dict] = []

    # Round-robin over techniques (one set per technique per round, capped), rarest/most
    # distinctive first, so common "eye-level half-body" photos can't crowd out low angles,
    # seated or walking poses and distinctive light. Each image is used at most once.
    def priority(item):
        (kind, value), members = item
        generic = ("eye|" in value) or value.startswith("standing|")
        return (generic, len(members), kind, value)

    order = sorted(groups.items(), key=priority)
    per_sig: dict[tuple[str, str], int] = defaultdict(int)
    progress = True
    while len(out) < quota and targets and progress:
        progress = False
        for (kind, value), members in order:
            if len(out) >= quota or not targets:
                break
            if per_sig[(kind, value)] >= max_per_technique:
                continue
            free = [m for m in members if m not in used]
            if len(free) < set_size[0]:
                continue
            rng.shuffle(free)
            chosen = free[: min(set_size[1], len(free))]
            used.update(chosen)
            per_sig[(kind, value)] += 1
            progress = True
            out.append({
                "example_id": make_id(split, len(out) + 1),
                "split": split,
                "technique": {"kind": kind, "value": value, "description": _describe(kind, value)},
                "inspiration": chosen,
                "target": targets.pop(),
                "subject": DEFAULT_SUBJECT,
            })
    return out


def assemble(dataset: str = "train_v1", n_examples: int = 24, seed: int = 0, set_size=(3, 4),
             max_per_technique: int = 2) -> list[dict]:
    tags, people, places = _candidates(dataset)
    rng = random.Random(seed)
    examples: list[dict] = []
    val_quota = max(1, round(n_examples * 0.2))
    for split, quota in (("valid", val_quota), ("train", n_examples - val_quota)):
        examples += _pick(split, quota, people[split], places[split], tags, rng, set_size, max_per_technique,
                          lambda sp, k: f"{dataset}-{sp[0]}{k:03d}")
    (data_dir(dataset) / "examples.json").write_text(json.dumps(examples, indent=1))
    return examples


def assemble_reserve(dataset: str = "train_v1", n_train: int = 10, n_valid: int = 3, batch: int = 2, seed: int = 1,
                     set_size=(3, 4), max_per_technique: int = 2) -> list[dict]:
    """Append a reserve batch of examples built only from images no existing example uses.

    Reserve examples get ids <dataset>-r<split letter><batch><nn> and "batch": <batch>; existing examples are never
    changed. They are labelled and reviewed like any other example (only approved labels are exported), so a
    reserve batch only matters if the creative director rejects enough of the first one.
    """
    existing = load_examples(dataset)
    if any(e.get("batch", 1) == batch for e in existing):
        raise ValueError(f"batch {batch} already exists; pick a new batch number")
    used = {p for e in existing for p in e["inspiration"] + [e["target"]]}
    tags, people, places = _candidates(dataset, used)
    rng = random.Random(seed)
    new: list[dict] = []
    for split, quota in (("valid", n_valid), ("train", n_train)):
        new += _pick(split, quota, people[split], places[split], tags, rng, set_size, max_per_technique,
                     lambda sp, k: f"{dataset}-r{sp[0]}{batch}{k:02d}")
    for e in new:
        e["batch"] = batch
    (data_dir(dataset) / "examples.json").write_text(json.dumps(existing + new, indent=1))
    return new


def load_examples(dataset: str = "train_v1") -> list[dict]:
    p = data_dir(dataset) / "examples.json"
    return json.loads(p.read_text()) if p.exists() else []
