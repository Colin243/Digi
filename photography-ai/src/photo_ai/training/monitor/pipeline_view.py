"""Data for the observatory's Director pipeline tab: real stage timings from benchmark runs, plus the check that
the "prepare ahead" path gives the same answers as the normal path.

Reads files that already exist and measures nothing itself:
- stage timings: runs/*/run.json whose label starts with PIPELINE_LABEL (the quiet fused-q5 benchmark);
- equality + precomputed timings: the newest runs/pipeline-precompute-*.json (written by scripts/pipeline_precompute_summary.py).
Anything missing comes back as None so the page can say "not measured" instead of inventing a number.
"""

from __future__ import annotations

import glob
import json
import statistics as st
from pathlib import Path

PIPELINE_LABEL = "fuse-v7-q5-quiet"
PREPARE_STAGES = ("notes_inspiration", "aesthetic_from_notes")  # the stages that do not need the target photo
FIELDS = ("aesthetic", "target_scene", "compositions")


def _med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 2) if xs else None


def _load(path: str):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def phase_of(stage_name: str) -> str:
    return "prepare" if stage_name.startswith(PREPARE_STAGES) else "plan"


def collect(runs_dir: Path) -> dict:
    runs = [r for r in (_load(f) for f in glob.glob(str(runs_dir / "*" / "run.json"))) if isinstance(r, dict)
            and str(r.get("label") or "").startswith(PIPELINE_LABEL) and r.get("stages")]
    by_stage: dict[str, list[dict]] = {}
    for r in runs:
        for s in r["stages"]:
            a = (s.get("attempts") or [{}])[-1]
            by_stage.setdefault(s["name"], []).append({
                "wall": s.get("wall_s"), "pt": a.get("prompt_tokens"), "gt": a.get("generation_tokens"),
                "ptps": a.get("prompt_tps"), "gtps": a.get("generation_tps")})
    stages = []
    for name in sorted(by_stage):
        rows = by_stage[name]
        pt, gt = _med([x["pt"] for x in rows]), _med([x["gt"] for x in rows])
        ptps, gtps = _med([x["ptps"] for x in rows]), _med([x["gtps"] for x in rows])
        stages.append({"name": name, "phase": phase_of(name), "cases": len(rows), "wall_s": _med([x["wall"] for x in rows]),
                       "prompt_tokens": pt, "generation_tokens": gt,
                       "prefill_s": round(pt / ptps, 2) if pt and ptps else None,
                       "decode_s": round(gt / gtps, 2) if gt and gtps else None})
    full_s = _med([r["timing"]["inference_s"] for r in runs])
    prepare_s = _med([sum(s.get("wall_s") or 0 for s in r["stages"] if phase_of(s["name"]) == "prepare") for r in runs])
    summary = None
    for f in sorted(glob.glob(str(runs_dir / "pipeline-precompute-*.json")), reverse=True):
        summary = _load(f)
        if isinstance(summary, dict) and summary.get("cases"):
            break
        summary = None
    equality = None
    if summary:
        cases = summary["cases"]
        equality = {"cases": len(cases), "all_identical": sum(all(c["same"].get(k) for k in FIELDS) for c in cases),
                    "identical": {k: sum(bool(c["same"].get(k)) for c in cases) for k in FIELDS},
                    "different": [c["case"] for c in cases if not all(c["same"].get(k) for k in FIELDS)],
                    "full_s": _med([c["full_s"] for c in cases]), "with_references_s": _med([c["fast_s"] for c in cases]),
                    "prepare_s": _med([c["prepare_s"] for c in cases]), "model": summary.get("model")}
    return {"model": (equality or {}).get("model") or "fused q5 (Qwen3.5-2B + v7 adapter)", "benchmark_cases": len(runs),
            "stages": stages, "totals": {"full_s": full_s, "prepare_s": prepare_s},
            "equality": equality}
