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
from .comparison import load_preferences, summarize_preferences
from .evaluation import CATEGORY_KEYS, CORE_KEYS, MAX_CORE, load_scores, rater_kind
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
    json_format: str = "shape",
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
        load_s = backend.load()  # first use may include the weight download
        manifest.setdefault("models", {}).setdefault(backend.spec.key, {
            "repo_id": backend.spec.repo_id, "first_load_s": round(load_s, 2)})
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
                cfg = RunConfig(strategy=strategy, temperature=temp, seed=seed, subject=case.subject,
                                json_format=json_format)
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


def _core(e: dict) -> int:
    return sum(e["scores"][k] for k in CORE_KEYS)


def summarize(manifest: dict, runs_dir: Path | None = None) -> dict:
    """MEASURED numbers (timings, memory, validity, keyword checks) and HUMAN ratings, kept apart."""
    runs_dir = Path(runs_dir or DEFAULT_RUNS_DIR)
    scores: dict[str, list[dict]] = {}
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
        if r["kind"] == "greedy":
            cells.setdefault((r["model"], r["strategy"]), []).append(rec)
        else:
            samples.setdefault((r["model"], r["case"]), []).append(rec)

    rows = []
    for (model, strategy), recs in sorted(cells.items()):
        am = [r["auto_metrics"] for r in recs]
        tr = [a.get("target_recall") or {} for a in am]
        insp_hits = [h for a in am for h in a.get("inspiration_primary_hits", [])]
        div = [a.get("diversity") or {} for a in am]
        stage_peaks = [r["timing"]["peak_memory_gb"] or 0 for r in recs]
        rows.append({
            "model": model, "strategy": strategy, "runs": len(recs),
            "measured": {
                "valid_rate": _mean([1.0 if r["validation"]["ok"] else 0.0 for r in recs]),
                "inference_s_mean": _mean([r["timing"]["inference_s"] for r in recs]),
                "inference_s_max": max(r["timing"]["inference_s"] for r in recs),
                "peak_memory_gb": round(max(stage_peaks), 2),
                "model_calls": _mean([r["timing"].get("model_calls") for r in recs]),
                "generation_tokens": _mean([r["timing"].get("generation_tokens") for r in recs]),
            },
            "auto": {  # keyword checks against hand annotations; not quality judgments
                "inspiration_identified": _mean([1.0 if h else 0.0 for h in insp_hits]),
                "style_recall": _mean([a.get("style_recall") for a in am]),
                "target_identified": _mean([1.0 if t.get("primary_hit") else 0.0 for t in tr if t]),
                "target_object_recall": _mean([t.get("object_recall") for t in tr if t]),
                "leaked_inspiration_objects": sum(len(a.get("leaks_in_target", [])) + len(a.get("leaks_in_compositions", [])) for a in am),
                "hallucinated_in_target": sum(len(a.get("hallucinated_in_target", [])) for a in am),
                "runs_with_hallucination": sum(1 for a in am if a.get("hallucinated_in_target") or a.get("leaks_in_target")),
                "evidence_grounded_rate": _mean([a.get("evidence_grounded_rate") for a in am]),
                "specific_cue_types": _mean([a.get("specific_cue_types_mean") for a in am]),
                "generic_or_copied": sum(a.get("generic_phrases_total", 0) for a in am),
                "copied_prompt_examples": sum(a.get("copied_prompt_examples", 0) for a in am),
                "diversity_fields": _mean([d.get("field_distinct") for d in div]),
                "diversity_text": _mean([d.get("text_dissimilarity") for d in div]),
            },
            "human": _human([e for r in recs for e in r["_scores"]]),
        })

    consistency = []
    for (model, case_id), recs in sorted(samples.items()):
        texts = ["\n".join(composition_text(c) for c in (r["result"] or {}).get("compositions", [])) for r in recs]
        valid_texts = [t for t, r in zip(texts, recs) if r["validation"]["ok"]]
        lat = [r["timing"]["inference_s"] for r in recs]
        consistency.append({
            "model": model, "case": case_id, "strategy": recs[0]["config"]["strategy"],
            "samples": len(recs), "temperature": recs[0]["config"]["temperature"],
            "valid_rate": _mean([1.0 if r["validation"]["ok"] else 0.0 for r in recs]),
            "composition_text_similarity": pairwise_similarity(valid_texts),
            "latency_mean_s": _mean(lat), "latency_stdev_s": round(statistics.pstdev(lat), 2) if len(lat) > 1 else None,
        })
    prefs = load_preferences(runs_dir, manifest["bench_id"])
    return {"bench_id": manifest["bench_id"], "models": manifest.get("models", {}), "rows": rows,
            "consistency": consistency, "preferences": summarize_preferences(manifest, prefs),
            "n_preference_entries": len(prefs)}


def _human(entries: list[dict]) -> dict:
    by_rater: dict[str, list[dict]] = {}
    for e in entries:
        by_rater.setdefault(e["rater"], []).append(e)
    out = {}
    for rater, es in sorted(by_rater.items()):
        v2 = [e for e in es if "shot_diversity" in e["scores"]]
        flagged = [e for e in es if e.get("hallucination") is not None]
        out[rater] = {
            "kind": rater_kind(es[0]),
            "n": len(es),
            "blind": all(e.get("blind") for e in es),
            "core_25": _mean([_core(e) for e in es]),
            "by_category": {k: _mean([e["scores"][k] for e in es if k in e["scores"]]) for k in CATEGORY_KEYS},
            "shot_diversity": _mean([e["scores"]["shot_diversity"] for e in v2]),
            "hallucination_rate": _mean([1.0 if e["hallucination"] else 0.0 for e in flagged]),
        }
    return out


def _cell(v, pct=False):
    if v is None:
        return "—"
    if pct:
        return f"{v * 100:.0f}%"
    return str(v)


def report_markdown(summary: dict) -> str:
    out = [f"## Benchmark `{summary['bench_id']}`", ""]
    if summary.get("models"):
        out.append("First model load in this benchmark (includes download if it was the first use): " + ", ".join(
            f"{k} {v['first_load_s']} s" for k, v in summary["models"].items()))
        out.append("")
    out += ["### Measured (deterministic; greedy runs, temperature 0, mean over cases)", "",
            "| model | strategy | runs | valid | inference s (mean / max) | peak GB | model calls | gen tokens |",
            "|---|---|---|---|---|---|---|---|"]
    for r in summary["rows"]:
        m = r["measured"]
        out.append(f"| {r['model']} | {r['strategy']} | {r['runs']} | {_cell(m['valid_rate'], True)} | "
                   f"{_cell(m['inference_s_mean'])} / {_cell(m['inference_s_max'])} | {m['peak_memory_gb']:.2f} | "
                   f"{_cell(m['model_calls'])} | {_cell(m['generation_tokens'])} |")
    out += ["", "### Automatic checks (keyword matching against hand annotations; measured, but not quality)", "",
            "| model | strategy | inspiration identified | style recall | target identified | target object recall | "
            "invented objects in target (runs) | leaked inspiration objects | evidence grounded | concrete cue types / shot | "
            "generic or copied | diversity: fields / text |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in summary["rows"]:
        a = r["auto"]
        out.append(
            f"| {r['model']} | {r['strategy']} | {_cell(a['inspiration_identified'], True)} | {_cell(a['style_recall'])} | "
            f"{_cell(a['target_identified'], True)} | {_cell(a['target_object_recall'])} | "
            f"{a['hallucinated_in_target']} ({a['runs_with_hallucination']}) | {a['leaked_inspiration_objects']} | "
            f"{_cell(a['evidence_grounded_rate'])} | {_cell(a['specific_cue_types'])} | "
            f"{a['generic_or_copied']} ({a['copied_prompt_examples']} copied) | "
            f"{_cell(a['diversity_fields'])} / {_cell(a['diversity_text'])} |")
    rated = [(r, rater, h) for r in summary["rows"] for rater, h in r["human"].items()]
    for kind, title, empty in (
        ("human", "Your ratings (human raters; subjective)", "_No human scores yet. Use the UI's Evaluate tab or `photo-ai score`._"),
        ("ai", "AI reviewer ratings (model-made, subjective; provisional second opinion, not human judgment)", "_No AI reviewer scores._"),
    ):
        rows_k = [(r, rater, h) for r, rater, h in rated if h.get("kind", "human") == kind]
        out += ["", f"### {title} — rubric 1-5 per category, core = first five categories /{MAX_CORE}", ""]
        if not rows_k:
            out.append(empty)
            continue
        out.append("| model | strategy | rater | blind | n | " + " | ".join(CATEGORY_KEYS) + f" | core /{MAX_CORE} | rater-flagged hallucination |")
        out.append("|---|---|---|---|---|" + "---|" * (len(CATEGORY_KEYS) + 2))
        for r, rater, h in rows_k:
            out.append(f"| {r['model']} | {r['strategy']} | {rater} | {'yes' if h['blind'] else 'no'} | {h['n']} | "
                       + " | ".join(_cell(h["by_category"][k]) for k in CATEGORY_KEYS)
                       + f" | {_cell(h['core_25'])} | {_cell(h['hallucination_rate'], True)} |")
    out += ["", "### Blind side-by-side preferences (subjective)", ""]
    if summary["preferences"]:
        out.append("| rater | kind | model | times shown | preferred set | preferred single shot |")
        out.append("|---|---|---|---|---|---|")
        for p in summary["preferences"]:
            out.append(f"| {p['rater']} | {p.get('rater_kind', 'human')} | {p['model']} | {p['shown']} | {p['set_wins']} ({_cell(p['set_win_rate'], True)}) | "
                       f"{p['shot_wins']} ({_cell(p['shot_win_rate'], True)}) |")
    else:
        out.append("_No preferences yet. Use the UI's Compare tab or `photo-ai prefer`._")
    if summary["consistency"]:
        out += ["", "### Consistency (sampled runs; measured)", "",
                "| model | case | strategy | samples @ T | valid | composition text similarity | latency mean ± sd |",
                "|---|---|---|---|---|---|---|"]
        for c in summary["consistency"]:
            out.append(f"| {c['model']} | {c['case']} | {c['strategy']} | {c['samples']} @ {c['temperature']} | "
                       f"{_cell(c['valid_rate'], True)} | {_cell(c['composition_text_similarity'])} | "
                       f"{_cell(c['latency_mean_s'])} ± {_cell(c['latency_stdev_s'])} s |")
    out += ["", "Notes: *identified* = the annotated main subject is named. *style recall* = share of the case's "
            "expected style keyword groups mentioned in the aesthetic. *invented objects in target* = things annotated "
            "as absent (e.g. a person on an empty staircase) that the target description or visible_evidence claims "
            "are present; sentences with negations are ignored. *evidence grounded* = share of visible_evidence items "
            "naming an annotated target object. *concrete cue types* = how many of {height, angle, distance, frame "
            "position, movement, lens} a shot states (max 6). *diversity fields* = 0 when all three shots repeat the "
            "same camera position/height/angle/subject position/framing, 1 when all differ."]
    return "\n".join(out)


def load_manifest(runs_dir: Path, bench_id: str) -> dict:
    return json.loads((Path(runs_dir) / "benchmarks" / bench_id / "manifest.json").read_text())


def latest_bench_id(runs_dir: Path) -> str | None:
    bdir = Path(runs_dir) / "benchmarks"
    ids = sorted(p.name for p in bdir.iterdir() if (p / "manifest.json").exists()) if bdir.exists() else []
    return ids[-1] if ids else None


__all__ = ["run_benchmark", "summarize", "report_markdown", "load_manifest", "latest_bench_id", "load_case"]
