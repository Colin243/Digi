"""Turn tagged pool images into training example skeletons.

An example = 3-4 inspiration photos that share a photographic technique (same camera angle +
framing, same pose + framing, or the same distinctive light) + one target place photo that is
NOT one of them. All images of an example come from the same split (train or valid), and
splits are by photographer (pool.py), so validation never shares a source shoot with training.

Deterministic for a given pool/tags/seed. Output: data/<dataset>/examples.json
"""

from __future__ import annotations

import json
import logging
import random
import re
from collections import defaultdict

from .pool import data_dir, load_pool, usable
from .tags import load_tags

DEFAULT_SUBJECT = "a person (the photographer's friend) posing in the scene"
DISTINCT_LIGHTS = ("back", "silhouette", "golden-hour", "night-artificial", "window", "harsh-sun")

log = logging.getLogger(__name__)

# --- technique -> target matching -------------------------------------------------------------
# Place tags are free text (setting + elements[]) plus light[], so the checks are keyword-based.
# Keywords are matched on word starts ("sand" hits "sandy", not "thousand").
_NIGHT_LIGHTS = {"night-artificial"}
_NIGHT_WORDS = ("night", "starry")  # not "dark"/"dim": tags use them for shadowed walls in daylight
_INDOOR_WORDS = ("interior", "indoor", "room", "hall", "corridor", "tunnel", "subway", "underground", "underpass",
                 "concourse", "stairwell", "garage", "library", "bookstore", "aisle", "cafeteria", "ceiling",
                 "covered", "arcade", "passageway")
_SKY_WORDS = ("sky", "horizon", "sunset", "setting sun", "sun flare", "sun through", "beach", "ocean", "sea",
              "shore", "coast", "cliff", "field", "meadow", "plain", "hill", "overlook", "viewpoint", "lake",
              "bay", "mountain", "dusk")
_SEAT_WORDS = ("bench", "chair", "seat", "sofa", "couch", "stool", "stair", "step", "ledge", "curb", "kerb",
               "low wall", "fence", "railing", "bleacher", "amphitheater", "grass", "sand", "beach", "dock",
               "pier", "rock", "door step", "doorstep")
_GROUND_WORDS = ("floor", "ground", "pavement", "sidewalk", "street", "road", "path", "sand", "beach", "grass",
                 "field", "meadow", "cobblestone", "asphalt", "platform", "plaza", "courtyard", "alley", "stair",
                 "step", "walkway", "crosswalk", "dirt", "curb", "trail", "deck", "lawn")
_UNREACHABLE_WORDS = ("aerial", "from above", "seen from below", "rooftops", "skyline", "elevated view")


def _has(text: str, words) -> bool:
    return any(re.search(r"\b" + re.escape(w), text) for w in words)


def _place_text(t: dict) -> str:
    return " ".join([t.get("setting", ""), *t.get("elements", [])]).lower()


def place_traits(t: dict) -> set[str]:
    """Which of {"daylight", "open_sky", "seat", "ground"} a place tag record offers."""
    text, lights = _place_text(t), set(t.get("light", []))
    traits = set()
    if not (lights & _NIGHT_LIGHTS) and not _has(text, _NIGHT_WORDS):
        traits.add("daylight")
    if _has(text, _SKY_WORDS) and not _has(text, _INDOOR_WORDS):
        traits.add("open_sky")
    reachable = not _has(text, _UNREACHABLE_WORDS)  # aerial / skyline views: nowhere to stand or sit
    if reachable and _has(text, _SEAT_WORDS):
        traits.add("seat")
    if reachable and _has(text, _GROUND_WORDS):
        traits.add("ground")
    return traits


def required_traits(kind: str, value: str) -> set[str]:
    """What a target must offer for this technique to be reproducible there.

    backlit / silhouette / golden-hour sets need daylight and open sky; seated sets need something to sit on;
    full-body sets need visible ground. Other techniques place no constraint.
    """
    need = set()
    if kind == "light" and value in ("back", "silhouette", "golden-hour"):
        need |= {"daylight", "open_sky"}
    if kind == "pose+framing" and value.split("|")[0] == "sitting":
        need.add("seat")
    if kind in ("angle+framing", "pose+framing") and value.split("|")[1] == "full-body":
        need.add("ground")
    return need


def _take_target(targets: list[str], tags: dict, kind: str, value: str, match: bool) -> str:
    """Pop the next target (from the shuffled end, as before) that fits the technique; else the next one at random."""
    need = required_traits(kind, value) if match else set()
    if need:
        for i in range(len(targets) - 1, -1, -1):
            if need <= place_traits(tags[targets[i]]["tags"]):
                return targets.pop(i)
        log.warning("no target offers %s for %s=%s; falling back to a random target", sorted(need), kind, value)
    return targets.pop()


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
          set_size, max_per_technique: int, make_id, match_targets: bool = False) -> list[dict]:
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
                "target": _take_target(targets, tags, kind, value, match_targets),
                "subject": DEFAULT_SUBJECT,
            })
    return out


def assemble(dataset: str = "train_v1", n_examples: int = 24, seed: int = 0, set_size=(3, 4),
             max_per_technique: int = 2, match_targets: bool = False, write: bool = True) -> list[dict]:
    """Build the first batch from scratch. match_targets defaults off so a rebuild reproduces batch 1 exactly."""
    tags, people, places = _candidates(dataset)
    rng = random.Random(seed)
    examples: list[dict] = []
    val_quota = max(1, round(n_examples * 0.2))
    for split, quota in (("valid", val_quota), ("train", n_examples - val_quota)):
        examples += _pick(split, quota, people[split], places[split], tags, rng, set_size, max_per_technique,
                          lambda sp, k: f"{dataset}-{sp[0]}{k:03d}", match_targets)
    if write:
        (data_dir(dataset) / "examples.json").write_text(json.dumps(examples, indent=1))
    return examples


def assemble_reserve(dataset: str = "train_v1", n_train: int = 10, n_valid: int = 3, batch: int = 2, seed: int = 1,
                     set_size=(3, 4), max_per_technique: int = 2, match_targets: bool = True,
                     write: bool = True) -> list[dict]:
    """Append a reserve batch of examples built only from images no existing example uses.

    Reserve examples get ids <dataset>-r<split letter><batch><nn> and "batch": <batch>; existing examples are never
    changed. Targets are matched to the technique (match_targets, see required_traits), falling back to a random
    target with a warning when none fits. write=False is a dry run. They are labelled and reviewed like any other
    example (only approved labels are exported), so a
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
                     lambda sp, k: f"{dataset}-r{sp[0]}{batch}{k:02d}", match_targets)
    for e in new:
        e["batch"] = batch
    if write:
        (data_dir(dataset) / "examples.json").write_text(json.dumps(existing + new, indent=1))
    return new


def load_examples(dataset: str = "train_v1") -> list[dict]:
    p = data_dir(dataset) / "examples.json"
    return json.loads(p.read_text()) if p.exists() else []
