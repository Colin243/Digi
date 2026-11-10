"""Licence-tracked image pool for training, kept apart from the held-out benchmark.

  photo-ai train-data pool      search Commons per datasets/train_v1/spec.json -> data/train_v1/pool.json
  photo-ai train-data fetch     download, hash (sha256 + 64-bit dHash), exclude held-out near-duplicates, split

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


def build_pool(dataset: str = "train_v1", log=print, pause_s: float = 1.0) -> dict:
    spec = load_spec(dataset)
    excluded_titles = heldout_titles(spec)
    pool: dict[str, dict] = {}
    for role, key in (("person", "people_queries"), ("place", "place_queries")):
        for q in spec[key]:
            items = commons.search(q, spec["per_query"], spec["category"])
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


def sample_ids(pool: dict, spec: dict) -> list[str]:
    """Deterministic starter subset: the first N images (Commons relevance order) per query."""
    per = spec.get("fetch_sample", {})
    caps = {"person": per.get("person_per_query", 12), "place": per.get("place_per_query", 5)}
    counts: dict[str, int] = {}
    chosen = []
    order = {q: i for i, q in enumerate(spec["people_queries"] + spec["place_queries"])}
    for it in sorted(pool["images"], key=lambda x: (order.get(x["queries"][0], 999), x["title"])):
        q = it["queries"][0]
        if counts.get(q, 0) < caps[it["role_hint"]]:
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
