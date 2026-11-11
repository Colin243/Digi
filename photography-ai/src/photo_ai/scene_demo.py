"""Reproducible Scene Director demo: fixed fixtures x starter styles, greedy decoding, one model load.

  photo-ai scene-demo [--config configs/scene_demo.json] [--model qwen3-vl-2b-4bit]

Every run is saved under runs/ with label = the demo id, so the runs show up in the Evaluate tab
for blind scoring. The demo also writes runs/<demo id>.md: a table of validity, timing and the
automatic checks (scene grounding, hallucinated people, pose/gaze filled, emotion inference,
unsafe directions) per fixture. The fixtures reuse the CC0 portrait_v1 target photos
(`photo-ai dataset fetch` downloads them), so the case annotations double as grounding checks.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import prompts
from .backends import make_backend
from .cases import PROJECT_ROOT, load_case
from .pipeline import RunConfig, analyze

DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "scene_demo.json"


def load_config(path: Path | None = None) -> dict:
    return json.loads(Path(path or DEFAULT_CONFIG).read_text())


def _row(fx: dict, rec: dict) -> dict:
    m = rec.get("auto_metrics") or {}
    d = m.get("direction") or {}
    return {
        "fixture": fx["id"], "style": fx.get("style"), "tags": fx.get("tags", []), "run_id": rec["run_id"],
        "valid": rec["validation"]["ok"], "errors": rec["validation"]["errors"],
        "inference_s": rec["timing"]["inference_s"], "generation_tokens": rec["timing"]["generation_tokens"],
        "peak_memory_gb": rec["timing"]["peak_memory_gb"],
        "target_recall": (m.get("target_recall") or {}).get("object_recall"),
        "evidence_grounded_rate": m.get("evidence_grounded_rate"),
        "hallucinated_in_target": m.get("hallucinated_in_target"),
        "cue_types_mean": m.get("specific_cue_types_mean"),
        "field_distinct": (m.get("diversity") or {}).get("field_distinct"),
        "pose_gaze_filled": d.get("fields_filled"), "gaze_specific": d.get("gaze_specific"),
        "emotion_inferences": d.get("emotion_inferences"), "unsafe_directions": d.get("unsafe_directions"),
    }


def report_markdown(demo: dict) -> str:
    lines = [f"# Scene Director demo `{demo['demo_id']}`", "",
             f"Model `{demo['model']}` · prompt `{demo['prompt_version']}` · greedy (T=0) · "
             f"max_side {demo['max_side']} · {demo['created_at']}", "",
             "| fixture | style | valid | s | gen tok | peak GB | scene recall | evidence grounded | look diversity | "
             "hallucinated | pose/head/gaze filled | gaze specific | emotion inferred | unsafe |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in demo["rows"]:
        f = r.get("pose_gaze_filled") or {}
        filled = "/".join(str(f.get(k, "—")) for k in ("body_pose", "head_direction", "gaze"))
        lines.append(
            f"| {r['fixture']} | {prompts.style_label(r['style'])} | {'yes' if r['valid'] else 'NO'} | "
            f"{r['inference_s']:.1f} | {r['generation_tokens']} | {r['peak_memory_gb'] or 0:.2f} | "
            f"{r['target_recall'] if r['target_recall'] is not None else '—'} | "
            f"{r['evidence_grounded_rate'] if r['evidence_grounded_rate'] is not None else '—'} | "
            f"{r['field_distinct'] if r['field_distinct'] is not None else '—'} | "
            f"{', '.join(r['hallucinated_in_target'] or []) or '—'} | {filled} | {r['gaze_specific'] if r['gaze_specific'] is not None else '—'} | "
            f"{', '.join(r['emotion_inferences'] or []) or '—'} | {', '.join(r['unsafe_directions'] or []) or '—'} |")
    lines += ["", "Runs are labelled with the demo id; score them blind in the Evaluate tab (`photo-ai ui`)."]
    return "\n".join(lines) + "\n"


def run_demo(config: dict, model: str, runs_dir: Path, demo_id: str | None = None, log=print) -> dict:
    demo_id = demo_id or f"scene-demo-{datetime.now():%Y%m%d-%H%M%S}"
    backend = make_backend(model)
    load_s = backend.load()
    log(f"loaded {backend.spec.key} in {load_s:.1f}s")
    rows = []
    for fx in config["fixtures"]:
        case = load_case(fx["case"])
        if case.missing_files():
            log(f"skip {fx['id']}: missing {case.target.path} (run `photo-ai dataset fetch`)")
            continue
        cfg = RunConfig(mode="scene", style=fx.get("style"), brief=fx.get("brief", ""), subject=case.subject,
                        max_side=config.get("max_side", 1024), json_format=config.get("json_format", "keys"))
        rec = analyze(backend, [], str(case.target.path), cfg, runs_dir, label=demo_id, case=case)
        rows.append(_row(fx, rec))
        r = rows[-1]
        log(f"{fx['id']:26} {prompts.style_label(fx.get('style')):24} valid={r['valid']!s:5} "
            f"{r['inference_s']:5.1f}s peak={r['peak_memory_gb'] or 0:.2f}GB")
    backend.unload()
    demo = {"demo_id": demo_id, "created_at": datetime.now().isoformat(timespec="seconds"),
            "model": backend.spec.key, "model_load_s": round(load_s, 2),
            "prompt_version": prompts.version_for("scene", "v2"), "max_side": config.get("max_side", 1024),
            "config": config, "rows": rows}
    runs_dir = Path(runs_dir)
    (runs_dir / f"{demo_id}.json").write_text(json.dumps(demo, indent=1, ensure_ascii=False))
    (runs_dir / f"{demo_id}.md").write_text(report_markdown(demo))
    return demo
