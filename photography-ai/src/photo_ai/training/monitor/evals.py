"""Speed-versus-quality results for the observatory's comparison tab.

Reads files that already exist: held-out Scene Director reports (runs/scene-eval/spd-*), the eight-photo scenery
runs (runs/scenery/<name>.json) and the mood-cue runs (runs/scenery/mood-<name>.json). Automated measurements
only: nothing here is a human quality judgement.
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from pathlib import Path

SCENE_MEASURES = {
    "valid": "schema-valid runs",
    "invented": "runs flagged: invented scene detail",
    "unsafe": "runs flagged: unsafe direction",
    "distinct": "look distinctness, fields (0-1)",
    "titles": "distinct titles (mean of 3)",
    "recall": "scene recall (annotated objects named)",
    "grounded": "evidence grounded rate",
    "tilts": "setup contradictions (wrong tilt)",
    "seconds": "seconds per scene (mean)",
    "memory": "peak memory GB (max)",
}


def _num(cell: str):
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", cell or "")
    return float(m.group(1)) if m else None


def _ratio(cell: str):
    m = re.match(r"\s*(\d+)\s*/\s*(\d+)", cell or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _label(eval_json: dict) -> str:
    model = eval_json.get("model") or {}
    repo = (model.get("repo_id") or model.get("key") or "model").split("/")[-1]
    ad = model.get("adapter_path")
    return f"{repo} + {Path(ad).name.replace('bootstrap-r16-', '').replace('-UNREVIEWED', '')}" if ad else repo


def _family(label: str) -> str:
    return "Qwen3.5" if "Qwen3.5" in label or "qwen3.5" in label else "Qwen3-VL"


def scene_results(runs: Path) -> list[dict]:
    out = []
    for d in sorted((runs / "scene-eval").glob("spd-*")):
        try:
            ev = json.loads((d / "eval.json").read_text())
            text = (d / "report.md").read_text()
        except (OSError, ValueError):
            continue
        row = {"id": d.name, "label": _label(ev)}
        row["family"] = _family(row["label"])
        for key, name in SCENE_MEASURES.items():
            m = re.search(r"\|\s*" + re.escape(name) + r"\s*\|([^\n]*)", text)
            cells = [c.strip() for c in m.group(1).split("|") if c.strip()] if m else []
            row[key] = cells[-1] if cells else None
        v = _ratio(row.get("valid") or "")
        row["valid_share"] = v[0] / v[1] if v and v[1] else None
        for k in ("distinct", "titles", "recall", "grounded", "tilts", "seconds", "memory"):
            row[k] = _num(row.get(k) or "")
        out.append(row)
    return out


def scenery_results(runs: Path) -> list[dict]:
    out = []
    for f in sorted((runs / "scenery").glob("*.json")):
        if f.name.startswith(("mood-", "fakecheck")):
            continue
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        rows = d.get("rows") or []
        same = sum(1 for r in rows if len({str(l.get("camera_position")).strip().lower() for l in r.get("looks", [])}) == 1)
        out.append({"name": d.get("name", f.stem), "model": d.get("model"), "valid": d.get("valid"), "photos": d.get("photos"),
                    "median_s": d.get("median_s"), "max_s": d.get("max_s"), "same_position": same,
                    "family": _family(str(d.get("model")))})
    return out


def mood_results(runs: Path) -> list[dict]:
    out = []
    for f in sorted((runs / "scenery").glob("mood-*.json")):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        by = defaultdict(dict)
        for r in d.get("rows", []):
            by[r["photo"]][r["mood"]] = r
        light = height = 0
        for moods in by.values():
            if len(moods) < 3:
                continue
            L = {" | ".join(str(l.get("lighting_tip")) for l in m["looks"]) for m in moods.values()}
            H = {" | ".join(f"{l.get('camera_height')}/{l.get('camera_angle')}" for l in m["looks"]) for m in moods.values()}
            light += len(L) == 3
            height += len(H) == 3
        out.append({"name": d.get("name", f.stem), "model": d.get("model"), "runs": d.get("runs"), "valid": d.get("valid"),
                    "median_s": d.get("median_s"), "photos": len(by), "lighting_differs": light, "height_differs": height,
                    "family": _family(str(d.get("model")))})
    return out


def phone_results(runs: Path) -> list:
    out = []
    for f in sorted((runs / "swift-smoke").glob("*.json")):
        try: out += json.loads(f.read_text())
        except Exception: pass
    return out


def collect(runs: Path) -> dict:
    return {"generated": time.time(), "scene": scene_results(runs), "scenery": scenery_results(runs), "mood": mood_results(runs), "phone": phone_results(runs),
            "note": "Automated checks only. The blind human review has not been done; none of this is a quality judgement."}
