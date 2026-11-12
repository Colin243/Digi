"""Licence-tracked image pool for training, kept apart from the held-out benchmark.

  photo-ai train-data pool      search Commons per datasets/train_v1/spec.json -> data/train_v1/pool.json
  photo-ai train-data fetch     download, hash (sha256 + 64-bit dHash), exclude held-out near-duplicates, split
  build_angle_candidates()      targeted low/high-angle queries -> data/train_v1/pool.angle-candidates.json
                                (pool.json is never touched; append_candidates() merges with a pool.before-* backup)

Leakage rules (see docs/phase4-finetuning.md):
  * no image whose Commons title appears in a held-out manifest (portrait_v1)
  * no image within `near_duplicate_hamming` dHash bits of any held-out image
  * near-duplicates inside the pool keep only the first copy
  * train/valid are split by photographer (author), so one shoot never spans both splits
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from PIL import Image, ImageOps

from .. import commons
from ..cases import PROJECT_ROOT, REPO_ROOT

DATA_ROOT = PROJECT_ROOT / "data"


def spec_path(dataset: str = "train_v1") -> Path:
    return PROJECT_ROOT / "datasets" / dataset / "spec.json"


def load_spec(dataset: str = "train_v1") -> dict:
    return json.loads(spec_path(dataset).read_text())


def data_dir(dataset: str = "train_v1") -> Path:
    return DATA_ROOT / dataset


def _pid(title: str) -> str:
    return hashlib.sha1(title.encode()).hexdigest()[:12]


def heldout_titles(spec: dict) -> set[str]:
    titles = set()
    for m in spec.get("heldout_manifests", []):
        man = json.loads((PROJECT_ROOT / m).read_text())
        titles |= {i["title"] for s in man["scenarios"] for i in s["images"]}
    return titles


def heldout_image_paths(spec: dict) -> list[Path]:
    paths = []
    for m in spec.get("heldout_manifests", []):
        man = json.loads((PROJECT_ROOT / m).read_text())
        root = PROJECT_ROOT / "samples" / man["dataset"]
        paths += [root / i["file"] for s in man["scenarios"] for i in s["images"]]
    return paths


# The first pool is eye-level-heavy (137 of 163 usable people photos; see docs/phase4-finetuning.md §9).
# These queries target camera-angle techniques and get a larger search limit and starter-sample cap.
ANGLE_QUERIES: dict[str, str] = {
    "low angle portrait": "low",
    "worm's eye": "low",
    "from below": "low",
    "overhead portrait": "overhead",
    "shot from above": "high",
}
ANGLE_SEARCH_LIMIT = 50  # Commons gsrlimit maximum for non-bot clients
ANGLE_SAMPLE_CAP = 20


def angle_queries(spec: dict) -> dict[str, str]:
    """Angle-targeted query -> intended angle. A spec may override with an `angle_queries` mapping."""
    return dict(spec.get("angle_queries") or ANGLE_QUERIES)


def search_limit(query: str, spec: dict) -> int:
    """Commons search limit for one query: angle queries get the higher cap, never below `per_query`."""
    if query in angle_queries(spec):
        return max(spec.get("angle_per_query", ANGLE_SEARCH_LIMIT), spec["per_query"])
    return spec["per_query"]


def is_cc0(item: dict) -> bool:
    return (item.get("license") or "").strip().upper().startswith("CC0")


def build_angle_candidates(dataset: str = "train_v1", log=print, pause_s: float = 1.0,
                           out_name: str = "pool.angle-candidates.json") -> dict:
    """Search the angle queries and write *new* candidates to a separate file (pool.json is only read).

    Same source and category as build_pool. Kept only if CC0, not a held-out title, and not already in
    pool.json. Near-duplicate and photographer-split checks run later in fetch_pool, after download.
    """
    spec = load_spec(dataset)
    excluded_titles = heldout_titles(spec)
    root = data_dir(dataset)
    existing_path = root / "pool.json"
    existing = {i["id"] for i in json.loads(existing_path.read_text())["images"]} if existing_path.exists() else set()
    found: dict[str, dict] = {}
    counts: dict[str, dict] = {}
    for q, angle in angle_queries(spec).items():
        items = commons.search(q, search_limit(q, spec), spec["category"])
        c = {"angle": angle, "results": len(items), "not_cc0": 0, "heldout": 0, "already_in_pool": 0,
             "dup_of_other_angle_query": 0, "new": 0}
        for it in items:
            if not is_cc0(it):
                c["not_cc0"] += 1
                continue
            if it["title"] in excluded_titles:
                c["heldout"] += 1
                continue
            pid = _pid(it["title"])
            if pid in existing:
                c["already_in_pool"] += 1
                continue
            if pid in found:
                found[pid]["queries"].append(q)
                c["dup_of_other_angle_query"] += 1
                continue
            found[pid] = {"id": pid, "role_hint": "person", "angle_hint": angle, "queries": [q], **it}
            c["new"] += 1
        counts[q] = c
        log(f"angle  {q!r:22} {c['results']:3} results, {c['new']:3} new "
            f"({c['already_in_pool']} already in pool, {c['heldout']} held-out, {c['not_cc0']} not CC0)")
        time.sleep(pause_s)
    doc = {"dataset": dataset, "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "source": spec["source"],
           "kind": "angle-candidates", "counts": counts,
           "images": sorted(found.values(), key=lambda x: x["id"])}
    root.mkdir(parents=True, exist_ok=True)
    (root / out_name).write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    return doc


def append_candidates(dataset: str = "train_v1", candidates_name: str = "pool.angle-candidates.json",
                      backup_name: str = "pool.before-angle.json") -> dict:
    """Merge a candidates file into pool.json, first copying pool.json to `backup_name` (never overwritten)."""
    root = data_dir(dataset)
    backup = root / backup_name
    if backup.exists():
        raise FileExistsError(f"{backup} already exists; pick another backup_name")
    pool_text = (root / "pool.json").read_text()
    backup.write_text(pool_text)
    pool = json.loads(pool_text)
    have = {i["id"] for i in pool["images"]}
    cand = json.loads((root / candidates_name).read_text())
    added = [i for i in cand["images"] if i["id"] not in have and is_cc0(i)]
    pool["images"] = sorted(pool["images"] + added, key=lambda x: x["id"])
    (root / "pool.json").write_text(json.dumps(pool, indent=1, ensure_ascii=False))
    return {"added": len(added), "backup": str(backup)}


def build_pool(dataset: str = "train_v1", log=print, pause_s: float = 1.0) -> dict:
    spec = load_spec(dataset)
    excluded_titles = heldout_titles(spec)
    pool: dict[str, dict] = {}
    for role, key in (("person", "people_queries"), ("place", "place_queries")):
        for q in spec[key]:
            items = commons.search(q, search_limit(q, spec), spec["category"])
            kept = 0
            for it in items:
                if it["title"] in excluded_titles:
                    continue
                pid = _pid(it["title"])
                if pid in pool:
                    pool[pid]["queries"].append(q)
                    continue
                pool[pid] = {"id": pid, "role_hint": role, "queries": [q], **it}
                kept += 1
            log(f"{role:6} {q!r:26} {len(items):3} results, {kept:3} new")
            time.sleep(pause_s)
    out = data_dir(dataset)
    out.mkdir(parents=True, exist_ok=True)
    doc = {"dataset": dataset, "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "source": spec["source"],
           "excluded_heldout_titles": len(excluded_titles), "images": sorted(pool.values(), key=lambda x: x["id"])}
    (out / "pool.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    return doc


def sample_cap(query: str, role: str, spec: dict) -> int:
    """Starter-sample cap per query; angle queries get the higher `angle_per_query` cap."""
    per = spec.get("fetch_sample", {})
    if query in angle_queries(spec):
        return per.get("angle_per_query", ANGLE_SAMPLE_CAP)
    return {"person": per.get("person_per_query", 12), "place": per.get("place_per_query", 5)}[role]


def sample_ids(pool: dict, spec: dict) -> list[str]:
    """Deterministic starter subset: the first N images (Commons relevance order) per query."""
    counts: dict[str, int] = {}
    chosen = []
    queries = spec["people_queries"] + spec["place_queries"] + list(angle_queries(spec))
    order = {q: i for i, q in enumerate(queries)}
    for it in sorted(pool["images"], key=lambda x: (order.get(x["queries"][0], 999), x["title"])):
        q = it["queries"][0]
        if counts.get(q, 0) < sample_cap(q, it["role_hint"], spec):
            counts[q] = counts.get(q, 0) + 1
            chosen.append(it["id"])
    return chosen


def dhash(path: Path, size: int = 8) -> int:
    """64-bit difference hash: robust to resizing/re-encoding, catches near-duplicates."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
        px = list(im.tobytes())
    bits = 0
    for row in range(size):
        for col in range(size):
            left, right = px[row * (size + 1) + col], px[row * (size + 1) + col + 1]
            bits = (bits << 1) | (left > right)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


FINE_SIZE, FINE_MAX_FRACTION = 16, 0.12


def is_near_duplicate(coarse_a: int, coarse_b: int, fine_a: int, fine_b: int, coarse_thr: int) -> bool:
    """Two-stage check: an 8x8 dHash match is only a candidate (smooth skies and plain walls collide);
    it must also agree on a 16x16 dHash (256 bits) within 12%."""
    return hamming(coarse_a, coarse_b) <= coarse_thr and hamming(fine_a, fine_b) <= FINE_MAX_FRACTION * FINE_SIZE**2


def author_split(author: str, val_fraction: float, seed: int) -> str:
    h = int(hashlib.sha256(f"{seed}|{author.strip().lower()}".encode()).hexdigest(), 16) % 10_000
    return "valid" if h < val_fraction * 10_000 else "train"


def fetch_pool(dataset: str = "train_v1", ids: list[str] | None = None, log=print, pause_s: float = 0.5) -> dict:
    """Download images (or only `ids`), then (re)compute exclusions and splits for everything present."""
    spec = load_spec(dataset)
    root = data_dir(dataset)
    pool = json.loads((root / "pool.json").read_text())
    img_dir = root / "images"
    img_dir.mkdir(exist_ok=True)
    wanted = set(ids) if ids else set(sample_ids(pool, spec))
    for it in pool["images"]:
        dest = img_dir / f"{it['id']}.jpg"
        if it["id"] not in wanted or dest.exists():
            continue
        data = commons._get(it["download_url"])
        dest.write_bytes(data)
        it["sha256"] = hashlib.sha256(data).hexdigest()
        log(f"fetched {it['id']} {it['title'][5:60]} ({len(data) // 1024} KB)")
        time.sleep(pause_s)

    held = [(p, dhash(p), dhash(p, FINE_SIZE)) for p in heldout_image_paths(spec) if p.exists()]
    thr = spec["near_duplicate_hamming"]
    seen: list[tuple[str, int, int]] = []
    for it in pool["images"]:
        dest = img_dir / f"{it['id']}.jpg"
        if not dest.exists():
            continue
        h, hf = dhash(dest), dhash(dest, FINE_SIZE)
        it["dhash"] = f"{h:016x}"
        it["file"] = str(dest.relative_to(REPO_ROOT))
        it.pop("excluded", None)
        near_held = [f"{p.parent.name}/{p.name}" for p, hh, hhf in held if is_near_duplicate(h, hh, hf, hhf, thr)]
        near_pool = [pid for pid, hh, hhf in seen if is_near_duplicate(h, hh, hf, hhf, thr)]
        if near_held:
            it["excluded"] = f"near-duplicate of held-out {near_held[0]}"
        elif near_pool:
            it["excluded"] = f"near-duplicate of pool image {near_pool[0]}"
        else:
            seen.append((it["id"], h, hf))
        it["split"] = author_split(it.get("author") or it["title"], spec["split"]["val_fraction"], spec["split"]["seed"])
    if not held:
        log("WARNING: held-out images not found locally (run `photo-ai dataset fetch`); "
            "near-duplicate check against the benchmark was skipped")
    pool["heldout_images_checked"] = len(held)
    (root / "pool.json").write_text(json.dumps(pool, indent=1, ensure_ascii=False))
    return pool


def load_pool(dataset: str = "train_v1") -> dict:
    return json.loads((data_dir(dataset) / "pool.json").read_text())


def usable(pool: dict) -> list[dict]:
    return [i for i in pool["images"] if i.get("file") and not i.get("excluded")]


def attribution_markdown(pool: dict, ids: set[str] | None = None) -> str:
    lines = [f"# {pool['dataset']} image sources", "", pool["source"], ""]
    for it in pool["images"]:
        if ids is not None and it["id"] not in ids:
            continue
        lines.append(f"- `{it['id']}` [{it['title']}]({it['page_url']}) by {it.get('author') or 'unknown'}, {it['license']}")
    return "\n".join(lines)
