"""Run every (model x case x strategy) and write a side-by-side comparison.

  photo-ai bench --models smolvlm2-500m qwen2.5-vl-3b-4bit
  photo-ai report --bench <bench_id>

Greedy runs (temperature 0) give one comparable output per cell. Consistency is
measured separately: N sampled runs (temperature > 0, different seeds) of one
strategy per model/case, compared by validity rate and text overlap.
Benchmark manifests live in runs/benchmarks/<bench_id>/.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path

from .backends import make_backend
from .cases import Case, load_case
from .evaluation import CATEGORY_KEYS, MAX_TOTAL, load_scores
from .metrics import composition_text, evaluate_result, pairwise_similarity
from .pipeline import STRATEGIES, RunConfig, analyze
from .storage import DEFAULT_RUNS_DIR


def run_benchmark(
    models: list[str],
    cases: list[Case],
    strategies: list[str] = list(STRATEGIES),
    consistency_strategy: str | None = "two_stage",
    consistency_samples: int = 3,
    consistency_temperature: float = 0.7,
    runs_dir: Path | None = None,
    bench_id: str | None = None,
    log=print,
) -> dict:
    runs_dir = Path(runs_dir or DEFAULT_RUNS_DIR)
    bench_id = bench_id or datetime.now().strftime("bench-%Y%m%d-%H%M%S")
    bdir = runs_dir / "benchmarks" / bench_id
    bdir.mkdir(parents=True, exist_ok=True)
    manifest_path = bdir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {
        "bench_id": bench_id, "created_at": datetime.now().isoformat(timespec="seconds"), "runs": []}
    done = {(r["model"], r["case"], r["strategy"], r["kind"], r["seed"]) for r in manifest["runs"]}

    def save():
        manifest_path.write_text(json.dumps(manifest, indent=2))

    for model in models:
        backend = make_backend(model)
        for case in cases:
            insp = [str(i.path) for i in case.inspiration]
            tgt = str(case.target.path)
            jobs = [(s, "greedy", 0, 0.0) for s in strategies]
            if consistency_strategy and consistency_samples:
                jobs += [(consistency_strategy, "sampled", seed, consistency_temperature)
                         for seed in range(1, consistency_samples + 1)]
            for strategy, kind, seed, temp in jobs:
                key = (backend.spec.key, case.id, strategy, kind, seed)
                if key in done:  # resumable
                    continue
                cfg = RunConfig(strategy=strategy, temperature=temp, seed=seed, subject=case.subject)
                rec = analyze(backend, insp, tgt, cfg, runs_dir, label=bench_id, case=case)
                manifest["runs"].append({"run_id": rec["run_id"], "model": backend.spec.key, "case": case.id,
                                         "strategy": strategy, "kind": kind, "seed": seed, "temperature": temp})
                save()
                log(f"{backend.spec.key:20} {case.id:26} {strategy:12} {kind:7} seed={seed} "
                    f"valid={rec['validation']['ok']!s:5} {rec['timing']['inference_s']:6.1f}s "
                    f"peak={rec['timing']['peak_memory_gb'] or 0:.2f}GB")
        backend.unload()
    save()
    return manifest


# ---------------------------------------------------------------------------------- report

def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.fmean(xs), 2) if xs else None


def _load_run(runs_dir: Path, run_id: str) -> dict:
    return json.loads((runs_dir / run_id / "run.json").read_text())


def summarize(manifest: dict, runs_dir: Path | None = None) -> dict:
    runs_dir = Path(runs_dir or DEFAULT_RUNS_DIR)
    scores = {}
    for e in load_scores(runs_dir):
        scores.setdefault(e["run_id"], []).append(e)
    case_cache: dict[str, Case | None] = {}

    def case_for(cid):
        if cid not in case_cache:
            try:
                case_cache[cid] = load_case(cid)
            except FileNotFoundError:
                case_cache[cid] = None
        return case_cache[cid]

    cells: dict[tuple[str, str], list[dict]] = {}
    samples: dict[tuple[str, str], list[dict]] = {}
    for r in manifest["runs"]:
        rec = _load_run(runs_dir, r["run_id"])
        rec["_scores"] = scores.get(r["run_id"], [])
        # recompute so metric fixes apply to old runs; result-less runs keep partial output
        rec["auto_metrics"] = evaluate_result(rec["result"] or rec.get("partial_result"), case_for(r["case"]))
        bucket = cells if r["kind"] == "greedy" else samples
        bucket.setdefault((r["model"], r["strategy"]), []).append(rec)
        if r["kind"] == "sampled":
            samples.setdefault((r["model"], "_by_case_" + r["case"]), []).append(rec)

    rows = []
    for (model, strategy), recs in sorted(cells.items()):
        am = [r["auto_metrics"] for r in recs]
        tr = [a.get("target_recall") or {} for a in am]
        insp_hits = [h for a in am for h in a.get("inspiration_primary_hits", [])]
        manual = [e for r in recs for e in r["_scores"]]
        row = {
            "model": model, "strategy": strategy, "runs": len(recs),
            "valid_rate": _mean([1.0 if r["validation"]["ok"] else 0.0 for r in recs]),
            "inference_s": _mean([r["timing"]["inference_s"] for r in recs]),
            "peak_memory_gb": max((r["timing"]["peak_memory_gb"] or 0) for r in recs),
            "model_calls": _mean([r["timing"].get("model_calls") for r in recs]),
            "inspiration_identified": _mean([1.0 if h else 0.0 for h in insp_hits]),
            "target_identified": _mean([1.0 if t.get("primary_hit") else 0.0 for t in tr if t]),
            "target_object_recall": _mean([t.get("object_recall") for t in tr if t]),
            "leaks": sum(len(a.get("leaks_in_target", [])) + len(a.get("leaks_in_compositions", [])) for a in am),
            "specific_cue_types": _mean([a.get("specific_cue_types_mean") for a in am]),
            "generic_phrases": sum(a.get("generic_phrases_total", 0) for a in am),
            "copied_prompt_examples": sum(a.get("copied_prompt_examples", 0) for a in am),
            "manual_total": _mean([e["total"] for e in manual]),
            "manual_by_category": {k: _mean([e["scores"][k] for e in manual]) for k in CATEGORY_KEYS},
            "manual_n": len(manual),
            "manual_raters": sorted({e["rater"] for e in manual}),
        }
        rows.append(row)

    consistency = []
    for (model, key), recs in sorted(samples.items()):
        if not key.startswith("_by_case_"):
            continue
        texts = ["\n".join(composition_text(c) for c in (r["result"] or {}).get("compositions", [])) for r in recs]
        valid_texts = [t for t, r in zip(texts, recs) if r["validation"]["ok"]]
        lat = [r["timing"]["inference_s"] for r in recs]
        consistency.append({
            "model": model, "case": key.removeprefix("_by_case_"), "strategy": recs[0]["config"]["strategy"],
            "samples": len(recs), "temperature": recs[0]["config"]["temperature"],
            "valid_rate": _mean([1.0 if r["validation"]["ok"] else 0.0 for r in recs]),
            "composition_text_similarity": pairwise_similarity(valid_texts),
            "latency_mean_s": _mean(lat), "latency_stdev_s": round(statistics.pstdev(lat), 2) if len(lat) > 1 else None,
        })
    return {"bench_id": manifest["bench_id"], "rows": rows, "consistency": consistency}


def _cell(v, pct=False):
    if v is None:
        return "—"
    if pct:
        return f"{v * 100:.0f}%"
    return str(v)


def report_markdown(summary: dict) -> str:
    out = [f"## Benchmark `{summary['bench_id']}`", "", "### Greedy runs (temperature 0), averaged over cases", ""]
    out.append("| model | strategy | valid | inference s | peak GB | calls | inspiration identified | target identified | target object recall | leaked inspiration objects | specific cue types / comp | generic or copied phrases | manual /25 (n) |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in summary["rows"]:
        out.append(
            f"| {r['model']} | {r['strategy']} | {_cell(r['valid_rate'], True)} | {_cell(r['inference_s'])} | "
            f"{r['peak_memory_gb']:.2f} | {_cell(r['model_calls'])} | {_cell(r['inspiration_identified'], True)} | "
            f"{_cell(r['target_identified'], True)} | {_cell(r['target_object_recall'])} | {r['leaks']} | "
            f"{_cell(r['specific_cue_types'])} | {r['generic_phrases']} ({r['copied_prompt_examples']} copied) | {_cell(r['manual_total'])} ({r['manual_n']}) |"
        )
    scored = [r for r in summary["rows"] if r["manual_n"]]
    if scored:
        out += ["", f"### Manual rubric (mean per category, 1-5; total out of {MAX_TOTAL})", ""]
        out.append("| model | strategy | raters | " + " | ".join(CATEGORY_KEYS) + " | total |")
        out.append("|---|---|---|" + "---|" * (len(CATEGORY_KEYS) + 1))
        for r in scored:
            out.append(f"| {r['model']} | {r['strategy']} | {', '.join(r['manual_raters'])} | "
                       + " | ".join(_cell(r["manual_by_category"][k]) for k in CATEGORY_KEYS)
                       + f" | {_cell(r['manual_total'])} |")
    if summary["consistency"]:
        out += ["", "### Consistency (sampled runs)", ""]
        out.append("| model | case | strategy | samples @ T | valid | composition text similarity | latency mean ± sd |")
        out.append("|---|---|---|---|---|---|---|")
        for c in summary["consistency"]:
            out.append(f"| {c['model']} | {c['case']} | {c['strategy']} | {c['samples']} @ {c['temperature']} | "
                       f"{_cell(c['valid_rate'], True)} | {_cell(c['composition_text_similarity'])} | "
                       f"{_cell(c['latency_mean_s'])} ± {_cell(c['latency_stdev_s'])} s |")
    out += ["", "Column notes: *identified* = the annotated main subject is named; *object recall* = share of "
            "annotated target objects mentioned in target_scene; *leaked* = inspiration-only objects that appear "
            "in the target description or compositions; *specific cue types* = how many of {height, angle, distance, "
            "frame position, movement, lens} a composition states concretely (max 6). Auto metrics are keyword "
            "checks against case annotations, not quality judgments."]
    return "\n".join(out)


def load_manifest(runs_dir: Path, bench_id: str) -> dict:
    return json.loads((Path(runs_dir) / "benchmarks" / bench_id / "manifest.json").read_text())


def latest_bench_id(runs_dir: Path) -> str | None:
    bdir = Path(runs_dir) / "benchmarks"
    ids = sorted(p.name for p in bdir.iterdir() if (p / "manifest.json").exists()) if bdir.exists() else []
    return ids[-1] if ids else None


__all__ = ["run_benchmark", "summarize", "report_markdown", "load_manifest", "latest_bench_id", "load_case"]
