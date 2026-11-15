"""Compare benchmark runs on the phone setups and on projected iPhone time.

    python -m photo_ai.training.bootstrap_eval <bench_id> [<bench_id> ...]

For each model in the given benchmarks: schema validity, how many looks frame a person with one of the
three setups (photo_ai/framing.py), how many of that setup's cues they state, wrong-tilt contradictions,
generated tokens, and the iPhone 17 Pro time projected from those tokens (photo_ai/phone_projection.py).

Informational only. Setup cues are wording checks, not photographic quality; quality is the blind human
review (docs/phase4-finetuning.md §7). The projection is an estimate, not a device run.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

from .. import framing, phone_projection
from ..cases import PROJECT_ROOT

RUNS = PROJECT_ROOT / "runs"


def _med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else None


def model_rows(bench_ids: list[str], runs_dir: Path = RUNS) -> dict[str, dict]:
    by_model: dict[str, list[dict]] = {}
    for bid in bench_ids:
        manifest = json.loads((runs_dir / "benchmarks" / bid / "manifest.json").read_text())
        for r in manifest["runs"]:
            if r.get("strategy") != "decomposed" or r.get("kind") != "greedy":
                continue
            rec = json.loads((runs_dir / r["run_id"] / "run.json").read_text())
            by_model.setdefault(r["model"], []).append(rec)
    out = {}
    for model, recs in by_model.items():
        comps = [c for rec in recs for c in ((rec.get("result") or {}).get("compositions") or [])]
        fit = framing.summarize_fit(comps)
        proj = [phone_projection.project_run(rec["stages"]) for rec in recs]
        proj = [p for p in proj if p]
        comp_tokens = [p["generated_tokens"].get("compositions") for p in proj]
        out[model] = {
            "runs": len(recs),
            "valid": sum(bool(rec["validation"]["ok"]) for rec in recs),
            "max_side": sorted({rec["config"].get("max_side") for rec in recs}),
            **fit,
            "compositions_tokens_median": _med(comp_tokens),
            "generated_tokens_median": _med([sum(p["generated_tokens"].values()) for p in proj]),
            "phone_full_s_median": _med([p["full_s"] for p in proj]),
            "phone_on_site_s_median": _med([p["on_site_s"] for p in proj]),
            "mac_s_median": _med([rec["timing"].get("inference_s") for rec in recs]),
        }
    return out


def markdown(rows: dict[str, dict]) -> str:
    keys = list(rows)
    lines = [("runs schema-valid", lambda r: f"{r['valid']}/{r['runs']}"),
             ("looks framing a person with a setup", lambda r: f"{r['with_setup']}/{r['looks']} "
              f"(half {r['by_setup']['half_body']}, full {r['by_setup']['full_body']}, seated {r['by_setup']['seated']})"),
             ("setup cues stated, mean (0-1)", lambda r: str(r["setup_cue_score_mean"])),
             ("setup contradictions (wrong tilt)", lambda r: str(r["setup_conflicts"])),
             ("compositions tokens, median", lambda r: str(r["compositions_tokens_median"])),
             ("generated tokens per analysis, median", lambda r: str(r["generated_tokens_median"])),
             ("projected iPhone full analysis s, median (budget 60)", lambda r: str(r["phone_full_s_median"])),
             ("projected iPhone on-site s, median (budget 30)", lambda r: str(r["phone_on_site_s_median"])),
             ("Mac seconds per analysis, median", lambda r: str(r["mac_s_median"]))]
    out = ["| measure | " + " | ".join(f"`{k}`" for k in keys) + " |", "|---|" + "---|" * len(keys)]
    out += [f"| {name} | " + " | ".join(f(rows[k]) for k in keys) + " |" for name, f in lines]
    return "\n".join(out)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    print(markdown(model_rows(sys.argv[1:])))
