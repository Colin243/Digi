"""Run folders and the run index.

runs/
  index.jsonl                       one summary line per run (append-only)
  20261109-153012_smolvlm2-500m/
    inputs/inspiration_1.jpg ...    downscaled, metadata-stripped copies
    inputs/target.jpg
    raw/<stage>_attempt<n>.txt      exact model text
    run.json                        everything: config, timings, parsed result, errors
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

DEFAULT_RUNS_DIR = Path(os.environ.get("PHOTO_AI_RUNS_DIR", Path(__file__).resolve().parents[2] / "runs"))


def new_run_dir(runs_dir: Path, model_key: str) -> tuple[str, Path]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"{stamp}_{model_key}"
    path = runs_dir / run_id
    n = 1
    while path.exists():
        n += 1
        run_id = f"{stamp}-{n}_{model_key}"
        path = runs_dir / run_id
    (path / "inputs").mkdir(parents=True)
    (path / "raw").mkdir()
    return run_id, path


def write_raw(run_dir: Path, name: str, text: str) -> str:
    p = run_dir / "raw" / f"{name}.txt"
    p.write_text(text, encoding="utf-8")
    return str(p.relative_to(run_dir))


def save_run(run_dir: Path, record: dict, runs_dir: Path) -> Path:
    out = run_dir / "run.json"
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = {
        "run_id": record["run_id"],
        "created_at": record["created_at"],
        "model": record["model"]["key"],
        "strategy": record["config"]["strategy"],
        "prompt_version": record["prompt_version"],
        "n_inspiration": len(record["inputs"]["inspiration"]),
        "valid": record["validation"]["ok"],
        "model_load_s": record["timing"]["model_load_s"],
        "inference_s": record["timing"]["inference_s"],
        "peak_memory_gb": record["timing"]["peak_memory_gb"],
        "label": record.get("label"),
        "case": record.get("case"),
        "temperature": record["config"].get("temperature"),
        "seed": record["config"].get("seed"),
    }
    with open(runs_dir / "index.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(summary) + "\n")
    return out


def read_index(runs_dir: Path) -> list[dict]:
    idx = runs_dir / "index.jsonl"
    if not idx.exists():
        return []
    return [json.loads(line) for line in idx.read_text().splitlines() if line.strip()]
