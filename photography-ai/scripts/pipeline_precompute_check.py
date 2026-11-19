#!/usr/bin/env python3
"""Does preparing the inspiration notes + aesthetic ahead of time change the answer?

For every case of a suite it runs the normal decomposed plan, then prepare_references() + a plan that uses them
(greedy decoding, so the two should match exactly), compares aesthetic / target_scene / compositions, and writes
runs/pipeline-precompute-<date>.json, which the observatory's "Director pipeline" tab reads.

    .venv/bin/python scripts/pipeline_precompute_check.py --model models/q35-2b-v7-fused-q5 --suite portrait_v1
"""
import argparse
import json
import tempfile
from datetime import date
from pathlib import Path

from photo_ai import pipeline
from photo_ai.backends import make_backend
from photo_ai.cases import PROJECT_ROOT, all_cases

PREPARE = ("notes_inspiration", "aesthetic_from_notes")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--suite", default="portrait_v1")
    ap.add_argument("--shot-format", default="v7")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    cfg = lambda **k: pipeline.RunConfig(**{"mode": "inspiration", "strategy": "decomposed", "json_format": "keys",  # noqa: E731
                                            "shot_format": a.shot_format, **k})
    backend = make_backend(str(Path(a.model).resolve()))
    backend.load()
    runs = Path(tempfile.mkdtemp(prefix="precompute-check-"))
    out = []
    for c in all_cases(a.suite):
        ins, tgt = [str(i.path) for i in c.inspiration], str(c.target.path)
        full = pipeline.analyze(backend, ins, tgt, cfg(), runs)
        refs = pipeline.check_references(json.loads(json.dumps(pipeline.prepare_references(backend, ins, cfg(), runs))), backend, cfg())
        fast = pipeline.analyze(backend, [], tgt, cfg(references=refs), runs)
        ok = full["result"] is not None and fast["result"] is not None
        same = {k: ok and full["result"].get(k) == fast["result"].get(k) for k in ("aesthetic", "target_scene", "compositions")}
        prepare_s = round(sum(s["wall_s"] for s in full["timing"]["stages"] if s["name"].startswith(PREPARE)), 3)
        out.append({"case": c.id, "full_s": full["timing"]["inference_s"], "fast_s": fast["timing"]["inference_s"],
                    "prepare_s": prepare_s, "same": same})
        print(c.id, same, out[-1]["full_s"], "->", out[-1]["fast_s"], flush=True)
    path = Path(a.out) if a.out else PROJECT_ROOT / "runs" / f"pipeline-precompute-{date.today():%Y%m%d}.json"
    path.write_text(json.dumps({"model": Path(a.model).name, "suite": a.suite, "shot_format": a.shot_format, "cases": out}, indent=1))
    print("wrote", path)


if __name__ == "__main__":
    main()
