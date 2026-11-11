"""Human rubric scoring. Scores are stored next to the model output they judge.

runs/<run_id>/scores.json   list of score entries for that run (append-only)
runs/scores.jsonl           one line per entry across all runs (for reports)

Each entry scores the run's whole recommendation set (aesthetic + target reading
+ 3 compositions) from 1-5 per category. A model's own opinion of its output is never
recorded here.

Rubric v1 (Phase 2): five categories, 25 points.
Rubric v2 (Phase 3): the same five plus shot_diversity, 30 points. Reports show the
five-category "core /25" for every entry so v1 and v2 scores stay comparable, and
diversity separately. An entry may also flag `hallucination` (the rater saw something
claimed in the output that is not in the photos).

Rater kinds (Phase 4): every entry carries `rater_kind` = "human" or "ai". Entries written
before Phase 4 have no field; they are classified by name (`claude-*` raters are AI
reviewers). Reports and the UI keep the two kinds apart, and decisions should rest on
human scores; AI reviewer scores are a provisional second opinion.
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
    ("shot_diversity", "Shot diversity",
     "Are the three shots genuinely different (position, height, angle, framing), not one idea repeated?"),
]
RUBRIC_VERSION = 2
CATEGORY_KEYS = [k for k, _, _ in RUBRIC]
CORE_KEYS = CATEGORY_KEYS[:5]  # rubric v1 categories
MAX_TOTAL = 5 * len(RUBRIC)
MAX_CORE = 5 * len(CORE_KEYS)


RATER_KINDS = ("human", "ai")
AI_RATER_PREFIXES = ("claude", "ai-", "gpt", "model-")


def rater_kind(entry_or_name: dict | str) -> str:
    """'human' or 'ai'. Uses the stored field when present, else the rater name."""
    if isinstance(entry_or_name, dict):
        if entry_or_name.get("rater_kind") in RATER_KINDS:
            return entry_or_name["rater_kind"]
        name = entry_or_name.get("rater", "")
    else:
        name = entry_or_name
    return "ai" if name.strip().lower().startswith(AI_RATER_PREFIXES) else "human"


def core_total(entry: dict) -> int:
    return sum(entry["scores"][k] for k in CORE_KEYS)


def make_entry(run_id: str, scores: dict[str, int], rater: str, notes: str = "", blind: bool = True,
               hallucination: bool | None = None, kind: str | None = None) -> dict:
    missing = [k for k in CATEGORY_KEYS if k not in scores]
    if missing:
        raise ValueError(f"missing categories: {missing}")
    for k in CATEGORY_KEYS:
        v = scores[k]
        if not isinstance(v, int) or not 1 <= v <= 5:
            raise ValueError(f"{k} must be an integer 1-5, got {v!r}")
    if not rater.strip():
        raise ValueError("rater name is required")
    kind = kind or rater_kind(rater)
    if kind not in RATER_KINDS:
        raise ValueError(f"rater kind must be one of {RATER_KINDS}")
    if kind == "human" and rater_kind(rater) == "ai":
        raise ValueError(f"{rater!r} is reserved for AI reviewers; choose another name for human ratings")
    return {
        "run_id": run_id,
        "rater": rater.strip(),
        "rater_kind": kind,
        "scored_at": datetime.now().isoformat(timespec="seconds"),
        "blind": blind,
        "scores": {k: scores[k] for k in CATEGORY_KEYS},
        "total": sum(scores[k] for k in CATEGORY_KEYS),
        "max_total": MAX_TOTAL,
        "core_total": sum(scores[k] for k in CORE_KEYS),
        "rubric_version": RUBRIC_VERSION,
        "hallucination": hallucination,
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
