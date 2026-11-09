"""Human rubric scoring. Scores are stored next to the model output they judge.

runs/<run_id>/scores.json   list of score entries for that run (append-only)
runs/scores.jsonl           one line per entry across all runs (for reports)

Each entry scores the run's whole recommendation set (aesthetic + target reading
+ 3 compositions) from 1-5 in five categories, 25 points total. A model's own
opinion of its output is never recorded here.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

RUBRIC = [
    ("aesthetic_understanding", "Aesthetic understanding",
     "Does it correctly interpret the inspiration images (each photo and the style they share)?"),
    ("scene_awareness", "Scene awareness",
     "Does it accurately identify and use elements actually present in the target environment?"),
    ("aesthetic_transfer", "Aesthetic transfer",
     "Does it apply the inspiration's photographic principles to the new place without copying the original backgrounds?"),
    ("actionability", "Actionability",
     "Concrete camera height, angle, distance, framing and subject position you could follow on the spot?"),
    ("composition_quality", "Composition quality",
     "Are the suggested shots visually coherent and right for the requested aesthetic?"),
]
CATEGORY_KEYS = [k for k, _, _ in RUBRIC]
MAX_TOTAL = 5 * len(RUBRIC)


def make_entry(run_id: str, scores: dict[str, int], rater: str, notes: str = "", blind: bool = True) -> dict:
    missing = [k for k in CATEGORY_KEYS if k not in scores]
    if missing:
        raise ValueError(f"missing categories: {missing}")
    for k in CATEGORY_KEYS:
        v = scores[k]
        if not isinstance(v, int) or not 1 <= v <= 5:
            raise ValueError(f"{k} must be an integer 1-5, got {v!r}")
    if not rater.strip():
        raise ValueError("rater name is required")
    return {
        "run_id": run_id,
        "rater": rater.strip(),
        "scored_at": datetime.now().isoformat(timespec="seconds"),
        "blind": blind,
        "scores": {k: scores[k] for k in CATEGORY_KEYS},
        "total": sum(scores[k] for k in CATEGORY_KEYS),
        "max_total": MAX_TOTAL,
        "notes": notes.strip(),
    }


def save_score(runs_dir: Path, entry: dict) -> Path:
    run_dir = Path(runs_dir) / entry["run_id"]
    if not (run_dir / "run.json").exists():
        raise FileNotFoundError(f"no run.json for {entry['run_id']}")
    path = run_dir / "scores.json"
    existing = json.loads(path.read_text()) if path.exists() else []
    existing.append(entry)
    path.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    with open(Path(runs_dir) / "scores.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


def load_scores(runs_dir: Path, run_id: str | None = None) -> list[dict]:
    """Latest entry per (run, rater) wins, so re-scoring replaces an earlier score."""
    if run_id:
        p = Path(runs_dir) / run_id / "scores.json"
        entries = json.loads(p.read_text()) if p.exists() else []
    else:
        p = Path(runs_dir) / "scores.jsonl"
        entries = [json.loads(line) for line in p.read_text().splitlines() if line.strip()] if p.exists() else []
    latest: dict[tuple[str, str], dict] = {}
    for e in entries:
        latest[(e["run_id"], e["rater"])] = e
    return list(latest.values())
