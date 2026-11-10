"""Prepare everything the iPhone benchmark app bundles. Run from photography-ai/:

    uv run --no-project --with pillow --with huggingface_hub \
        python ios-bench/scripts/prepare_assets.py [--case cafe-window-candid] [--skip-model]

Writes three things into ios-bench/Resources/:

  prompts.json       committed. The decomposed-strategy prompts from src/photo_ai/prompts.py
                     (default --json-format keys, the format Phase 3 recommends for Qwen3-VL-2B),
                     rendered with sentinels the app fills in at run time, plus the
                     per-stage max_tokens used by pipeline._decomposed. Regenerate after any
                     prompt change so the phone runs the same prompt version as the Mac.
  BenchImages/       git-ignored. One portrait_v1 case, downscaled exactly like
                     images.prepare() (EXIF transpose, RGB, LANCZOS thumbnail, JPEG q92, no
                     metadata) to each benchmark size, plus manifest.json.
  Model/             git-ignored. The pinned mlx-community/Qwen3-VL-2B-Instruct-4bit snapshot
                     (~1.8 GB), copied as real files (no symlinks), plus REVISION.json.

The weights come from the local Hugging Face cache when they are there; otherwise this
downloads them once. The app itself never touches the network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
PROJECT = BENCH.parent  # photography-ai/
RES = BENCH / "Resources"
sys.path.insert(0, str(PROJECT / "src"))

from photo_ai import prompts  # noqa: E402

MODEL_REPO = "mlx-community/Qwen3-VL-2B-Instruct-4bit"
# The snapshot Phase 3 benchmarked on the Mac (docs/phase3-model-selection.md).
MODEL_REVISION = "9c4f5209e57b31f4b9dfba735de3fb983739c9cc"
SIZES = (768, 1024)
DEFAULT_CASE = "cafe-window-candid"

# Sentinels the app replaces with earlier stages' outputs.
NOTE = "__NOTE_{i}__"
STYLE = "__STYLE_JSON__"
TARGET = "__TARGET_JSON__"


def export_prompts(n_inspiration: int, json_format: str) -> dict:
    with prompts.json_format(json_format):
        return _export_prompts(n_inspiration, json_format)


def _export_prompts(n_inspiration: int, json_format: str) -> dict:
    # compositions_from_parts serializes dicts with _shape(); a one-key dict renders as
    # {"__STYLE_JSON__": ""} and the app swaps that whole token for the stage output.
    style_sentinel, target_sentinel = {STYLE: ""}, {TARGET: ""}
    comps = prompts.compositions_from_parts(style_sentinel, target_sentinel)
    return {
        "prompt_version": prompts.PROMPT_VERSION,
        "json_format": json_format,
        "image_marker": prompts.IMAGE_MARKER,
        "subject": prompts.DEFAULT_SUBJECT,
        "n_inspiration": n_inspiration,
        "sentinels": {
            "note": NOTE,
            "style_json": prompts._shape(style_sentinel),
            "target_json": prompts._shape(target_sentinel),
        },
        # Same per-stage token caps as pipeline._decomposed (compositions uses RunConfig.max_tokens).
        "stages": {
            "image_notes": {"prompt": prompts.image_notes(), "max_tokens": 200},
            "target_scene": {"prompt": prompts.target_scene_only(), "max_tokens": 500},
            "aesthetic_from_notes": {
                "prompt": prompts.aesthetic_from_notes([NOTE.format(i=i) for i in range(1, n_inspiration + 1)]),
                "max_tokens": 900,
            },
            "compositions": {"prompt": comps, "max_tokens": 1600},
        },
        "generation": {"temperature": 0.0, "repetition_penalty": None, "json_retries": 0},
    }


def export_images(case_id: str, samples: Path) -> dict:
    from PIL import Image, ImageOps

    case_file = PROJECT / "cases" / "portrait_v1" / f"{case_id}.json"
    case = json.loads(case_file.read_text())
    out = RES / "BenchImages"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / ".gitkeep").touch()  # the Xcode folder reference needs the folder to exist
    srcs = [("inspiration", i, e["file"]) for i, e in enumerate(case["inspiration"], 1)]
    srcs.append(("target", 1, case["target"]["file"]))
    images = []
    for role, idx, rel in srcs:
        src = samples / Path(rel).relative_to("photography-ai/samples")
        if not src.is_file():
            sys.exit(f"missing {src}. Run `uv run photo-ai dataset fetch` first (or pass --samples).")
        entry = {"role": role, "index": idx, "source": rel, "files": {}}
        for size in SIZES:
            with Image.open(src) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                entry["original_size"] = list(im.size)
                if max(im.size) > size:
                    im.thumbnail((size, size), Image.Resampling.LANCZOS)
                name = f"{role}_{idx}_{size}.jpg"
                im.save(out / name, "JPEG", quality=92)
                entry["files"][str(size)] = {"file": name, "size": list(im.size)}
        images.append(entry)
    manifest = {"case": case_id, "suite": "portrait_v1", "license_note": case.get("license_note"),
                "sizes": list(SIZES), "images": images}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def export_model() -> Path:
    from huggingface_hub import snapshot_download

    snap = Path(snapshot_download(MODEL_REPO, revision=MODEL_REVISION))
    out = RES / "Model"
    for f in out.iterdir() if out.exists() else []:
        if not f.name.startswith("."):  # keep .gitkeep
            shutil.rmtree(f) if f.is_dir() else f.unlink()
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    for f in sorted(snap.iterdir()):
        if f.is_file():
            shutil.copyfile(f.resolve(), out / f.name)  # dereference the cache symlinks
            files[f.name] = (out / f.name).stat().st_size
    config_sha = hashlib.sha256((out / "config.json").read_bytes()).hexdigest()
    (out / "REVISION.json").write_text(json.dumps(
        {"repo_id": MODEL_REPO, "revision": MODEL_REVISION, "config_sha256": config_sha, "files": files}, indent=1))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", default=DEFAULT_CASE, help="portrait_v1 case id")
    ap.add_argument("--samples", type=Path, default=PROJECT / "samples",
                    help="folder that holds portrait_v1/ (default photography-ai/samples)")
    ap.add_argument("--json-format", choices=prompts.JSON_FORMATS, default="keys",
                    help="how the expected JSON is described; Phase 3 recommends keys for Qwen3-VL-2B")
    ap.add_argument("--skip-model", action="store_true", help="only prompts and images")
    ap.add_argument("--prompts-only", action="store_true")
    a = ap.parse_args()

    RES.mkdir(exist_ok=True)
    case = json.loads((PROJECT / "cases" / "portrait_v1" / f"{a.case}.json").read_text())
    p = export_prompts(len(case["inspiration"]), a.json_format)
    (RES / "prompts.json").write_text(json.dumps(p, indent=1, ensure_ascii=False) + "\n")
    print(f"prompts.json: prompt v{p['prompt_version']} ({p['json_format']} format), {p['n_inspiration']} inspiration photos")
    if a.prompts_only:
        return
    m = export_images(a.case, a.samples)
    print(f"BenchImages/: {len(m['images'])} images x sizes {m['sizes']} from {a.case}")
    if not a.skip_model:
        out = export_model()
        print(f"Model/: {MODEL_REPO}@{MODEL_REVISION[:12]} -> {out}")


if __name__ == "__main__":
    main()
