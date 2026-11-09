"""Evaluation datasets described by a committed manifest; images are downloaded, never committed.

  photo-ai dataset fetch [--manifest datasets/portrait_v1/manifest.json]

Downloads each image to samples/<dataset>/<scenario>/<role>.jpg (git-ignored), sequentially,
with a descriptive User-Agent and backoff on HTTP 429 (Wikimedia's API etiquette), and writes
samples/<dataset>/fetched.json with sha256 of what was received.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from .cases import PROJECT_ROOT

UA = "DigiPhotographyAI-eval/0.1 (local research; non-commercial evaluation)"
DEFAULT_MANIFEST = PROJECT_ROOT / "datasets" / "portrait_v1" / "manifest.json"
SAMPLES_DIR = PROJECT_ROOT / "samples"


def _download(url: str, tries: int = 6) -> bytes:
    for i in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or i == tries - 1:
                raise
            time.sleep(int(exc.headers.get("Retry-After") or 0) or 5 * (i + 1))
    raise RuntimeError("unreachable")


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict:
    return json.loads(Path(path).read_text())


def dataset_dir(manifest: dict) -> Path:
    return SAMPLES_DIR / manifest["dataset"]


def fetch(manifest_path: Path = DEFAULT_MANIFEST, log=print, pause_s: float = 0.5) -> dict:
    manifest = load_manifest(manifest_path)
    root = dataset_dir(manifest)
    lock_path = root / "fetched.json"
    lock = json.loads(lock_path.read_text()) if lock_path.exists() else {}
    for scen in manifest["scenarios"]:
        for img in scen["images"]:
            dest = root / img["file"]
            if dest.exists() and img["file"] in lock:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = _download(img["download_url"])
            dest.write_bytes(data)
            lock[img["file"]] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                                 "source": img["page_url"], "license": img["license"]}
            log(f"fetched {img['file']} ({len(data) // 1024} KB, {img['license']})")
            time.sleep(pause_s)
    root.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock, indent=1))
    return lock


def attribution_markdown(manifest: dict) -> str:
    lines = [f"# {manifest['dataset']} sources", "", manifest["source"], "", manifest["usage"], ""]
    for scen in manifest["scenarios"]:
        lines.append(f"## {scen['id']} ({scen['category']})")
        for img in scen["images"]:
            author = img.get("author") or "unknown"
            lines.append(f"- `{img['file']}` — [{img['title']}]({img['page_url']}) by {author}, "
                         f"{img['license']}")
        lines.append("")
    return "\n".join(lines)
