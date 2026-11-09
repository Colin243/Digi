"""photo-ai command line.

  photo-ai models
  photo-ai analyze -i a.jpg b.jpg c.jpg -t scene.jpg [--model smolvlm2-500m] [--strategy two_stage]
  photo-ai ui [--port 7860]
  photo-ai runs
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .backends import DEFAULT_MODEL, MODELS, make_backend
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
    return RunConfig(a.strategy, a.max_side, a.max_tokens, a.temperature, a.repetition_penalty, a.seed, a.json_retries)


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
    _add_run_args(an)

    ui = sub.add_parser("ui", help="launch the local upload interface")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=7860)
    ui.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)

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

    if a.cmd == "ui":
        from .app import launch

        launch(a.host, a.port, a.runs_dir)
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
