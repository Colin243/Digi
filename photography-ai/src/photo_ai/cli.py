"""photo-ai command line.

  photo-ai models
  photo-ai analyze -i a.jpg b.jpg c.jpg -t scene.jpg [--model smolvlm2-500m] [--strategy two_stage]
  photo-ai scene -t scene.jpg --style relaxed_candid      (Scene Director: one photo, no references)
  photo-ai scene-demo                                     (reproducible Scene Director demo run)
  photo-ai ui [--port 7860]
  photo-ai runs
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import prompts
from .backends import DEFAULT_MODEL, MODELS, SELECTED_MODEL, make_backend
from .pipeline import STRATEGIES, InputError, RunConfig, analyze
from .render import result_markdown, timing_markdown
from .storage import DEFAULT_RUNS_DIR, read_index


def _add_run_args(p: argparse.ArgumentParser) -> None:
    d = RunConfig()
    p.add_argument("--model", default=DEFAULT_MODEL, help="registry key or HF repo id (see `photo-ai models`)")
    p.add_argument("--strategy", choices=STRATEGIES, default=d.strategy)
    p.add_argument("--max-side", type=int, default=d.max_side, help="downscale images to this long edge (px)")
    p.add_argument("--max-tokens", type=int, default=d.max_tokens)
    p.add_argument("--temperature", type=float, default=d.temperature)
    p.add_argument("--repetition-penalty", type=float, default=None)
    p.add_argument("--seed", type=int, default=d.seed)
    p.add_argument("--json-retries", type=int, default=d.json_retries)
    p.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)


def _cfg(a: argparse.Namespace) -> RunConfig:
    return RunConfig(a.strategy, a.max_side, a.max_tokens, a.temperature, a.repetition_penalty, a.seed, a.json_retries,
                     shot_format=getattr(a, "shot_format", "v1"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="photo-ai", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("models", help="list registered models")

    an = sub.add_parser("analyze", help="run one analysis from the command line")
    an.add_argument("-i", "--inspiration", nargs="+", required=True, help="3-5 inspiration photos")
    an.add_argument("-t", "--target", required=True, help="target scene photo")
    an.add_argument("--label", help="free-text tag saved with the run")
    an.add_argument("--repeat", type=int, default=1, help="run N times with the model kept loaded (warm timings)")
    an.add_argument("--json", action="store_true", help="print the full run record as JSON")
    an.add_argument("--shot-format", choices=["v1", "v2"], default="v1",
                    help="v2 adds body pose, head/chin, gaze and an optional expression cue (decomposed strategy)")
    _add_run_args(an)

    sn = sub.add_parser("scene", help="Scene Director (experimental): one scene photo + a style brief -> 3 portrait looks")
    sn.add_argument("-t", "--target", required=True, help="the scene photo (with or without a person)")
    sn.add_argument("--style", choices=list(prompts.STYLE_BRIEFS), help="starter style brief")
    sn.add_argument("--brief", default="", help="extra style notes in your own words")
    sn.add_argument("--json-format", choices=["shape", "keys"], default="keys")
    sn.add_argument("--label", help="free-text tag saved with the run")
    sn.add_argument("--json", action="store_true", help="print the full run record as JSON")
    _add_run_args(sn)
    sn.set_defaults(model=SELECTED_MODEL)

    sd = sub.add_parser("scene-demo", help="reproducible Scene Director demo over fixed fixtures")
    sd.add_argument("--config", type=Path, default=None, help="default: configs/scene_demo.json")
    sd.add_argument("--model", default=SELECTED_MODEL)
    sd.add_argument("--demo-id")
    sd.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)

    ui = sub.add_parser("ui", help="launch the local upload interface")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=7860)
    ui.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)

    dg = sub.add_parser("diagnose", help="check image plumbing and perception on benchmark cases")
    dg.add_argument("--model", default=DEFAULT_MODEL)
    dg.add_argument("--case", nargs="*", help="case ids or json paths (default: all in cases/)")
    dg.add_argument("--max-side", type=int, default=1024)
    dg.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)

    bn = sub.add_parser("bench", help="run models x cases x strategies (resumable)")
    bn.add_argument("--models", nargs="+", default=[DEFAULT_MODEL])
    bn.add_argument("--case", nargs="*", help="case ids or json paths (default: all cases in the suite)")
    bn.add_argument("--suite", help="case suite folder, e.g. portrait_v1 (default: Phase 2 cases)")
    bn.add_argument("--strategies", nargs="+", choices=STRATEGIES, default=list(STRATEGIES))
    bn.add_argument("--consistency-strategy", choices=STRATEGIES, default="two_stage")
    bn.add_argument("--consistency-samples", type=int, default=3)
    bn.add_argument("--consistency-temperature", type=float, default=0.7)
    bn.add_argument("--bench-id", help="reuse an id to resume or extend a benchmark")
    bn.add_argument("--json-format", choices=["shape", "keys"], default="shape",
                    help="describe the expected JSON as a blank shape (default) or as a list of keys")
    bn.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)

    rp = sub.add_parser("report", help="side-by-side comparison for a benchmark")
    rp.add_argument("--bench", help="benchmark id (default: latest)")
    rp.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    rp.add_argument("--out", type=Path, help="also write the markdown here")

    sc = sub.add_parser("score", help="record a rubric score from the command line")
    sc.add_argument("--run", required=True, help="run id")
    sc.add_argument("--rater", required=True)
    sc.add_argument("--scores", type=int, nargs=6, required=True, metavar="1-5",
                    help="aesthetic_understanding scene_awareness aesthetic_transfer actionability "
                         "composition_quality shot_diversity")
    sc.add_argument("--hallucination", choices=["yes", "no"], help="output claims something not in the photos")
    sc.add_argument("--notes", default="")
    sc.add_argument("--not-blind", action="store_true", help="rater knew which model produced the run")
    sc.add_argument("--rater-kind", choices=["human", "ai"], help="default: inferred from the name (claude-* = ai)")
    sc.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)

    ds = sub.add_parser("dataset", help="download evaluation images listed in a manifest")
    ds.add_argument("action", choices=["fetch", "attribution"])
    ds.add_argument("--manifest", type=Path, default=None)

    pf = sub.add_parser("prefer", help="record a blind side-by-side preference for one benchmark case")
    pf.add_argument("--bench", required=True)
    pf.add_argument("--case", required=True)
    pf.add_argument("--rater", required=True)
    pf.add_argument("--set", dest="pref_set", help="preferred label (A, B, ...) as shown to this rater, or 'none'")
    pf.add_argument("--shot", help="preferred single composition, e.g. B2, or 'none'")
    pf.add_argument("--notes", default="")
    pf.add_argument("--show", action="store_true", help="print the blinded A/B/C order for this rater and exit")
    pf.add_argument("--strategy", default="decomposed")
    pf.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)

    cv = sub.add_parser("convert", help="quantize a registered MLX model to 4-bit into models/<key>-4bit")
    cv.add_argument("model")
    cv.add_argument("--bits", type=int, default=4)

    td = sub.add_parser("train-data", help="Phase 4 training data: pool, fetch, tags, examples, labels, export")
    td.add_argument("action", choices=["pool", "fetch", "status", "attribution", "assemble", "qa", "export",
                                       "import-tags", "import-labels", "draft", "import-review", "review-site"])
    td.add_argument("--reviewer", help="import-review: the human reviewer's name (default: the name in the file)")
    td.add_argument("--site", type=Path, help="import-review: the review page folder (or HTML file) the reviewer was "
                                               "sent; ties the review to the answer versions it showed")
    td.add_argument("--target", choices=["artifact", "vercel"], default="artifact", help="review-site: where it will be hosted")
    td.add_argument("--model", default="claude-opus-5-5", help="draft: reference model (Anthropic API)")
    td.add_argument("--dataset", default="train_v1")
    td.add_argument("--ids", nargs="*", help="limit fetch to these pool ids")
    td.add_argument("--file", type=Path, help="JSON file for import-tags / import-labels")
    td.add_argument("--source", default="ai-draft", help="provenance label for imported drafts")
    td.add_argument("--n-examples", type=int, default=24)
    td.add_argument("--reserve", action="store_true",
                    help="assemble: append a reserve batch from unused images instead of rebuilding examples.json")
    td.add_argument("--n-train", type=int, default=10, help="assemble --reserve: training examples to add")
    td.add_argument("--n-valid", type=int, default=3, help="assemble --reserve: validation examples to add")
    td.add_argument("--batch", type=int, help="assemble --reserve: new batch number (default 2); review-site: only this batch")
    td.add_argument("--include-unapproved", action="store_true",
                    help="export drafts too (ONLY for pipeline smoke tests; never for real training)")

    lr = sub.add_parser("lora", help="Phase 4 LoRA: smoke test or training run")
    lr.add_argument("action", choices=["smoke", "train"])
    lr.add_argument("--config", type=Path, required=True)
    lr.add_argument("--rows", type=int, default=4, help="smoke: rows to use")
    lr.add_argument("--steps", type=int, default=12, help="smoke: overfit steps")

    rn = sub.add_parser("runs", help="summarize saved runs")
    rn.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    rn.add_argument("--last", type=int, default=20)

    a = ap.parse_args(argv)

    if a.cmd == "models":
        for spec in MODELS.values():
            mark = " (default)" if spec.key == DEFAULT_MODEL else ""
            print(f"{spec.key:22} {spec.repo_id:50} {spec.notes}{mark}")
        return 0

    if a.cmd == "analyze":
        backend = make_backend(a.model)
        cfg = _cfg(a)
        for n in range(a.repeat):
            try:
                rec = analyze(backend, a.inspiration, a.target, cfg, a.runs_dir, a.label)
            except InputError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            if a.json:
                print(json.dumps(rec, indent=2))
            else:
                if n == 0:
                    print(result_markdown(rec), "\n")
                print(timing_markdown(rec), "\n")
        return 0

    if a.cmd == "scene":
        cfg = RunConfig(mode="scene", style=a.style, brief=a.brief, max_side=a.max_side, max_tokens=a.max_tokens,
                        temperature=a.temperature, repetition_penalty=a.repetition_penalty, seed=a.seed,
                        json_retries=a.json_retries, json_format=a.json_format)
        try:
            rec = analyze(make_backend(a.model), [], a.target, cfg, a.runs_dir, a.label)
        except InputError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(rec, indent=2, ensure_ascii=False) if a.json else f"{result_markdown(rec)}\n\n{timing_markdown(rec)}")
        return 0

    if a.cmd == "scene-demo":
        from .scene_demo import load_config, run_demo

        demo = run_demo(load_config(a.config), a.model, a.runs_dir, a.demo_id)
        print(f"{len(demo['rows'])} runs; report: {a.runs_dir / (demo['demo_id'] + '.md')}")
        return 0

    if a.cmd == "ui":
        from .app import launch

        launch(a.host, a.port, a.runs_dir)
        return 0

    if a.cmd == "diagnose":
        from .cases import all_cases, load_case
        from .diagnostics import run_diagnostics, summary_table

        cases = [load_case(c) for c in a.case] if a.case else all_cases()
        backend = make_backend(a.model)
        records = []
        for case in cases:
            if case.missing_files():
                print(f"skip {case.id}: missing {case.missing_files()}", file=sys.stderr)
                continue
            rec = run_diagnostics(backend, case, a.max_side, a.runs_dir)
            print(f"saved {rec['dir']}/diagnostics.json")
            records.append(rec)
        if records:
            print(summary_table(records))
        return 0

    if a.cmd == "bench":
        from .benchmark import run_benchmark
        from .cases import all_cases, load_case

        cases = [load_case(c) for c in a.case] if a.case else all_cases(a.suite)
        for c in [c for c in cases if c.missing_files()]:
            print(f"skip {c.id}: missing {c.missing_files()}", file=sys.stderr)
        cases = [c for c in cases if not c.missing_files()]
        m = run_benchmark(a.models, cases, a.strategies, a.consistency_strategy, a.consistency_samples,
                          a.consistency_temperature, a.runs_dir, a.bench_id, json_format=a.json_format)
        print(f"benchmark {m['bench_id']}: {len(m['runs'])} runs. Next: photo-ai report --bench {m['bench_id']}")
        return 0

    if a.cmd == "report":
        from .benchmark import latest_bench_id, load_manifest, report_markdown, summarize

        bid = a.bench or latest_bench_id(a.runs_dir)
        if not bid:
            print("no benchmarks found", file=sys.stderr)
            return 1
        md = report_markdown(summarize(load_manifest(a.runs_dir, bid), a.runs_dir))
        print(md)
        if a.out:
            a.out.write_text(md + "\n")
        return 0

    if a.cmd == "score":
        from .evaluation import CATEGORY_KEYS, make_entry, save_score

        try:
            hall = None if a.hallucination is None else a.hallucination == "yes"
            entry = make_entry(a.run, dict(zip(CATEGORY_KEYS, a.scores)), a.rater, a.notes, not a.not_blind, hall,
                               a.rater_kind)
            path = save_score(a.runs_dir, entry)
        except (ValueError, FileNotFoundError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"saved {entry['total']}/{entry['max_total']} -> {path}")
        return 0

    if a.cmd == "dataset":
        from .dataset import DEFAULT_MANIFEST, attribution_markdown, fetch, load_manifest

        path = a.manifest or DEFAULT_MANIFEST
        if a.action == "fetch":
            lock = fetch(path)
            print(f"{len(lock)} images present for {load_manifest(path)['dataset']}")
        else:
            print(attribution_markdown(load_manifest(path)))
        return 0

    if a.cmd == "prefer":
        from .benchmark import load_manifest
        from .comparison import LABELS, blind_order, candidates, make_preference, save_preference

        manifest = load_manifest(a.runs_dir, a.bench)
        shown = blind_order(candidates(manifest, a.case, a.strategy), a.rater, a.case, a.bench)
        label_to_run = {LABELS[i]: r["run_id"] for i, r in enumerate(shown)}
        if a.show or not (a.pref_set or a.shot):
            for lab, rid in label_to_run.items():
                print(f"{lab}: runs/{rid}")
            return 0
        try:
            pref_run = None if (a.pref_set or "none").lower() == "none" else label_to_run[a.pref_set.upper()]
            shot = None
            if a.shot and a.shot.lower() != "none":
                shot = (label_to_run[a.shot[0].upper()], int(a.shot[1:]))
            entry = make_preference(a.bench, a.case, a.rater, list(label_to_run.values()), pref_run, shot, a.notes)
        except (KeyError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"saved -> {save_preference(a.runs_dir, entry)}")
        return 0

    if a.cmd == "convert":
        import subprocess

        from .backends import resolve_spec
        from .cases import PROJECT_ROOT

        spec = resolve_spec(a.model)
        out = PROJECT_ROOT / "models" / f"{spec.key}-{a.bits}bit"
        if out.exists():
            print(f"{out} already exists")
            return 0
        cmd = [sys.executable, "-m", "mlx_vlm.convert", "--hf-path", spec.repo_id, "--mlx-path", str(out),
               "-q", "--q-bits", str(a.bits)]
        print(" ".join(cmd))
        return subprocess.call(cmd)

    if a.cmd == "train-data":
        from .training.cli import run_train_data

        return run_train_data(a)

    if a.cmd == "lora":
        from .training.lora import LoraConfig, train

        cfg = LoraConfig.load(a.config)
        if a.action == "smoke":
            from .training.smoke import run_smoke

            rep = run_smoke(cfg, a.rows, a.steps)
            print(f"smoke test {'PASSED' if rep['all_pass'] else 'FAILED'} -> {cfg.out_dir / 'smoke_report.json'}")
            return 0 if rep["all_pass"] else 1
        print(json.dumps(train(cfg), indent=1))
        return 0

    if a.cmd == "runs":
        rows = read_index(a.runs_dir)[-a.last :]
        if not rows:
            print(f"no runs in {a.runs_dir}")
            return 0
        print(f"{'run_id':42} {'strategy':12} {'valid':5} {'load_s':>7} {'infer_s':>8} {'peak_GB':>7}  label")
        for r in rows:
            f = lambda v, nd=1: "—" if v is None else f"{v:.{nd}f}"  # noqa: E731
            print(
                f"{r['run_id']:42} {r['strategy']:12} {str(r['valid']):5} {f(r['model_load_s']):>7} "
                f"{f(r['inference_s']):>8} {f(r['peak_memory_gb'], 2):>7}  {r.get('label') or ''}"
            )
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
