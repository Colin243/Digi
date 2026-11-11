"""Human-readable views of a run record (shared by CLI and UI)."""

from __future__ import annotations


def _fmt(v, unit="", nd=2) -> str:
    return "—" if v is None else f"{v:.{nd}f}{unit}" if isinstance(v, float) else f"{v}{unit}"


def timing_markdown(rec: dict) -> str:
    t = rec["timing"]
    load = "already loaded (warm)" if t["model_was_warm"] else _fmt(t["model_load_s"], " s")
    lines = [
        f"**Run** `{rec['run_id']}` · model `{rec['model']['repo_id']}` · strategy `{rec['config']['strategy']}`"
        + (f" · shot format `{rec.get('shot_format', 'v1')}`" if rec.get("shot_format") else ""),
        f"**Model load:** {load} · **Inference:** {_fmt(t['inference_s'], ' s')} · "
        f"**Peak memory:** {_fmt(t['peak_memory_gb'], ' GB')} · **Model calls:** {t.get('model_calls', '—')}",
    ]
    for s in rec["stages"]:
        for a in s["attempts"]:
            lines.append(
                f"- {s['name']} attempt {a['attempt']}: {_fmt(a['wall_s'], ' s')}, "
                f"{_fmt(a['prompt_tokens'])} prompt tok @ {_fmt(a['prompt_tps'], ' tok/s', 0)}, "
                f"{_fmt(a['generation_tokens'])} gen tok @ {_fmt(a['generation_tps'], ' tok/s', 1)}, "
                f"parse={a['parse_method']}, finish={a['finish_reason']}"
                + (f", errors: {'; '.join(a['errors'])}" if a["errors"] else "")
            )
    lines.append(f"\nSaved to `{rec['run_dir']}`")
    return "\n".join(lines)


def _bullets(pairs, d: dict) -> list[str]:
    out = []
    for label, key in pairs:
        v = d.get(key)
        if isinstance(v, list) and v:
            out.append(f"- **{label}:** " + "; ".join(map(str, v)))
        elif v and not isinstance(v, list):
            out.append(f"- **{label}:** {v}")
    return out


def result_markdown(rec: dict) -> str:
    res = rec["result"] or rec.get("partial_result")
    if not res:
        errs = "\n".join(f"- {e}" for e in rec["validation"]["errors"])
        return f"### No valid structured output\n{errs}\n\nRaw model text is in the run's `raw/` folder."
    out = []
    if not rec["validation"]["ok"]:
        out.append("> **Partial result** — a later stage failed validation:\n> " + "; ".join(rec["validation"]["errors"]))
    if res.get("mode") == "scene":
        st = res.get("style") or {}
        out.append(f"### Scene Director (experimental) · {st.get('label') or 'custom brief'}")
        out.append("> Experimental: check every look on site. The base model can direct people who are already in "
                   "the photo, or suggest a spot that isn't safe; never ask strangers to pose, and skip any direction "
                   "involving traffic, ledges, railings or water.")
        d = (rec.get("auto_metrics") or {}).get("direction") or {}
        warn = [f"{n} look(s) may direct someone already in the photo" for n in [d.get("directs_people_in_frame")] if n]
        warn += [f"possible unsafe direction: {', '.join(d['unsafe_directions'])}"] if d.get("unsafe_directions") else []
        warn += [f"wording that guesses feelings: {', '.join(d['emotion_inferences'])}"] if d.get("emotion_inferences") else []
        if warn:
            out.append("> **Automated checks flagged:** " + "; ".join(warn))
        if st.get("brief"):
            out.append(f"*Brief:* {st['brief']}")
    a = res.get("aesthetic")
    if a:
        out.append("### Inspiration aesthetic")
        out.append(a.get("summary", ""))
        if a.get("per_image"):
            out.append("\n".join(f"{i}. {line}" for i, line in enumerate(a["per_image"], 1)))
        out += _bullets([("Transferable principles", "principles"), ("Palette", "color_palette"),
                         ("Patterns", "composition_patterns"), ("Lighting", "lighting"), ("Mood", "mood"),
                         ("Subjects", "subject_treatment")], a)
    ts = res.get("target_scene")
    if ts:
        out.append("### Target scene")
        out.append(ts.get("description", ""))
        out += _bullets([("Use", "key_elements"), ("Watch out for", "constraints"), ("People in frame", "people_in_frame")], ts)
    for i, c in enumerate(res.get("compositions", []), 1):
        out.append(f"### {i}. {c.get('title', '')}")
        meta = " · ".join(x for x in (c.get("distance_and_framing") or c.get("framing"), c.get("orientation"), c.get("zoom_or_lens")) if x)
        if meta:
            out.append(f"*{meta}*")
        out += _bullets([
            ("Transfers", "uses_principle"), ("Stand", "camera_position"), ("Camera height", "camera_height"),
            ("Angle", "camera_angle"), ("Subject", "subject_position"), ("Pose", "body_pose"),
            ("Head / chin", "head_direction"), ("Gaze", "gaze"), ("Expression (optional)", "expression_cue"),
            ("Light", "lighting_tip"),
            ("Seen in photo", "visible_evidence"), ("Check on site", "needs_on_site_check"),
            ("Why", "why_it_matches"),
        ], c)
        if c.get("steps"):
            out.append("\n**Steps:**\n" + "\n".join(f"{n}. {s}" for n, s in enumerate(c["steps"], 1)))
    return "\n".join(out)
