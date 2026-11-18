"""Scene Director and scenery rows for fine-tuning, plus a mixed dataset with the Inspiration rows.

The Inspiration exporter (export.py) only teaches the Inspiration Director's four calls. A model trained only
on that stops following the Scene Director format: the first Qwen3.5 adapter returned 0 of 20 valid answers on
the held-out Scene Director test because it dropped the pose fields. This module renders the other two modes with
the exact inference prompts, one row per model call:

  scene mode     "scene"  : prompts.director_scene()                        -> {description, key_elements, constraints, people_in_frame}
                 "look1-3": prompts.scene_look(scene, style, "", subject, k, earlier looks, 3)   -> one ShotV2 look, zoom_or_lens
                            moved ahead of distance_and_framing (prompt v15; --scene-distance-first for the old order)
  scenery mode   "scenery_scene": prompts.scenery_scene()                    -> the same four fields
                 "scenery_look1-3": prompts.scenery_look(scene, mood note, k, earlier looks)      -> one ShotScenery look

Answer files are JSON lists written by the drafting passes:
  scene   : [{"example_id","photo_id","style_key","scene":{...},"looks":[3]}]
  scenery : [{"example_id","photo_id","mood","brief","scene":{...},"looks":[3]}]

    uv run python -m photo_ai.training.export_modes --scene a.json b.json --scenery c.json d.json \
        --base data/train_v1/sft-UNREVIEWED-zoom3 --out data/train_v1/sft-UNREVIEWED-mix1 --valid-photos id1 id2 ...
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .. import prompts
from .export import _j, _row, _zoom_first
from .pool import data_dir


def _image(photo_id: str) -> str:
    return str(data_dir("train_v1") / "images" / f"{photo_id}.jpg")


def scene_rows(ex: dict, split: str, json_format: str = "keys", zoom_first: bool = True) -> list[dict]:
    """zoom_first (prompt v15, the default): the look prompt lists zoom_or_lens directly ahead of
    distance_and_framing and each target is written in that key order. Only the export reorders; the answer files
    are not changed, and the distance text is kept as drafted (no "at <amount>x")."""
    meta = {"example_id": ex["example_id"], "split": split, "label_status": "draft", "approved_by": None, "mode": "scene"}
    img = [_image(ex["photo_id"])]
    rows = []
    with prompts.json_format(json_format):
        rows.append(_row(prompts.director_scene(), img, _j(ex["scene"]), {**meta, "stage": "scene"}))
        done: list[dict] = []
        for k, look in enumerate(ex["looks"], 1):
            p = prompts.scene_look(ex["scene"], ex["style_key"], "", prompts.DEFAULT_SUBJECT, k, list(done), len(ex["looks"]),
                                   zoom_first=zoom_first)
            target = _zoom_first(look, name_zoom=False) if zoom_first else look
            rows.append(_row(p, img, _j(target), {**meta, "stage": f"look{k}"}))
            done.append(look)
    return rows


def scenery_rows(ex: dict, split: str, json_format: str = "keys") -> list[dict]:
    meta = {"example_id": ex["example_id"], "split": split, "label_status": "draft", "approved_by": None, "mode": "scenery", "mood": ex.get("mood")}
    img = [_image(ex["photo_id"])]
    rows = []
    with prompts.json_format(json_format):
        rows.append(_row(prompts.scenery_scene(), img, _j(ex["scene"]), {**meta, "stage": "scenery_scene"}))
        done: list[dict] = []
        for k, look in enumerate(ex["looks"], 1):
            rows.append(_row(prompts.scenery_look(ex["scene"], ex.get("brief", ""), k, list(done)), img, _j(look), {**meta, "stage": f"scenery_look{k}"}))
            done.append(look)
    return rows


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def build(scene_files: list[Path], scenery_files: list[Path], base: Path, out: Path, valid_photos: set[str],
          scene_zoom_first: bool = True) -> dict:
    train, valid = _read(base / "train.jsonl"), _read(base / "valid.jsonl")
    n = {"inspiration_train": len(train), "inspiration_valid": len(valid), "scene": 0, "scenery": 0}

    def scene_fn(ex, split):
        return scene_rows(ex, split, zoom_first=scene_zoom_first)

    for files, fn, key in ((scene_files, scene_fn, "scene"), (scenery_files, scenery_rows, "scenery")):
        for f in files:
            for ex in json.loads(Path(f).read_text()):
                split = "valid" if ex["photo_id"] in valid_photos else "train"
                (valid if split == "valid" else train).extend(fn(ex, split))
                n[key] += 1
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("train.jsonl", train), ("valid.jsonl", valid)):
        (out / name).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    info = {**n, "train_rows": len(train), "valid_rows": len(valid), "base": str(base), "valid_photos": sorted(valid_photos),
            "scene_zoom_first": scene_zoom_first,
            "scene_prompt_version": prompts.PROMPT_VERSION_V15 if scene_zoom_first else prompts.PROMPT_VERSION_V5}
    (out / "export_info.json").write_text(json.dumps(info, indent=1))
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", nargs="*", default=[], type=Path)
    ap.add_argument("--scenery", nargs="*", default=[], type=Path)
    ap.add_argument("--base", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--valid-photos", nargs="*", default=[])
    ap.add_argument("--scene-distance-first", action="store_true",
                    help="render scene looks with the pre-v15 order (distance_and_framing before zoom_or_lens)")
    a = ap.parse_args()
    print(json.dumps(build(a.scene, a.scenery, a.base, a.out, set(a.valid_photos),
                           scene_zoom_first=not a.scene_distance_first), indent=1))


if __name__ == "__main__":
    main()
