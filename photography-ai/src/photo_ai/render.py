"""Human-readable views of a run record (shared by CLI and UI)."""

from __future__ import annotations


def _fmt(v, unit="", nd=2) -> str:
    return "—" if v is None else f"{v:.{nd}f}{unit}" if isinstance(v, float) else f"{v}{unit}"


def timing_markdown(rec: dict) -> str:
    t = rec["timing"]
    load = "already loaded (warm)" if t["model_was_warm"] else _fmt(t["model_load_s"], " s")
    lines = [
        f"**Run** `{rec['run_id']}` · model `{rec['model']['repo_id']}` · strategy `{rec['config']['strategy']}`",
        f"**Model load:** {load} · **Inference:** {_fmt(t['inference_s'], ' s')} · "
        f"**Peak memory:** {_fmt(t['peak_memory_gb'], ' GB')}",
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


def result_markdown(rec: dict) -> str:
    res = rec["result"] or rec.get("partial_result")
    if not res:
        errs = "\n".join(f"- {e}" for e in rec["validation"]["errors"])
        return f"### No valid structured output\n{errs}\n\nRaw model text is in the run's `raw/` folder."
    out = []
    if not rec["validation"]["ok"]:
        out.append("> **Partial result** — a later stage failed validation:\n> " + "; ".join(rec["validation"]["errors"]))
    a = res.get("aesthetic")
    if a:
        out.append("### Inspiration aesthetic")
        out.append(a["summary"])
        for label, key in [("Palette", "color_palette"), ("Patterns", "composition_patterns")]:
            if a.get(key):
                out.append(f"- **{label}:** {', '.join(a[key])}")
        for label, key in [("Lighting", "lighting"), ("Mood", "mood"), ("Subjects", "subject_treatment")]:
            if a.get(key):
                out.append(f"- **{label}:** {a[key]}")
    ts = res.get("target_scene")
    if ts:
        out.append("### Target scene")
        out.append(ts["description"])
        if ts.get("key_elements"):
            out.append(f"- **Use:** {', '.join(ts['key_elements'])}")
        if ts.get("constraints"):
            out.append(f"- **Watch out for:** {', '.join(ts['constraints'])}")
    for i, c in enumerate(res.get("compositions", []), 1):
        out.append(f"### {i}. {c['title']}")
        meta = " · ".join(x for x in (c.get("framing"), c.get("orientation"), c.get("zoom_or_lens")) if x)
        if meta:
            out.append(f"*{meta}*")
        for label, key in [
            ("Camera", "camera_position"),
            ("Subject", "subject_placement"),
            ("Light", "lighting_tip"),
            ("Why", "why_it_matches"),
        ]:
            if c.get(key):
                out.append(f"- **{label}:** {c[key]}")
        if c.get("steps"):
            out.append("\n**Steps:**\n" + "\n".join(f"{n}. {s}" for n, s in enumerate(c["steps"], 1)))
    return "\n".join(out)
