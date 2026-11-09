"""Blind side-by-side preferences.

For one benchmark case, the greedy run from each model is shown as "A", "B", "C"... in an
order that is shuffled per (rater, case) but stable, so reloading shows the same layout and
different raters see different layouts. The rater picks the set they prefer and the single
composition they would actually shoot. Model names are revealed only after saving.

runs/benchmarks/<bench>/preferences.jsonl   one line per saved choice (append-only;
                                            the latest per (rater, case) counts)
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime
from pathlib import Path

LABELS = "ABCDEFGH"


def candidates(manifest: dict, case_id: str, strategy: str | None = None) -> list[dict]:
    """Greedy runs for this case, one per model (first strategy found unless specified)."""
    out: dict[str, dict] = {}
    for r in manifest["runs"]:
        if r["case"] != case_id or r["kind"] != "greedy":
            continue
        if strategy and r["strategy"] != strategy:
            continue
        out.setdefault(r["model"], r)
    return list(out.values())


def blind_order(runs: list[dict], rater: str, case_id: str, bench_id: str) -> list[dict]:
    seed = int(hashlib.sha256(f"{bench_id}|{case_id}|{rater.strip().lower()}".encode()).hexdigest(), 16) % 2**32
    shuffled = list(runs)
    random.Random(seed).shuffle(shuffled)
    return shuffled


def make_preference(bench_id: str, case_id: str, rater: str, order: list[str], preferred_run: str | None,
                    preferred_shot: tuple[str, int] | None, notes: str = "") -> dict:
    if not rater.strip():
        raise ValueError("rater name is required")
    if preferred_run is not None and preferred_run not in order:
        raise ValueError("preferred run is not one of the shown runs")
    if preferred_shot is not None and (preferred_shot[0] not in order or preferred_shot[1] not in (1, 2, 3)):
        raise ValueError("preferred shot must be (shown run, 1-3)")
    return {
        "bench_id": bench_id,
        "case": case_id,
        "rater": rater.strip(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "shown_order": order,
        "preferred_run": preferred_run,  # None = no preference / all equally bad
        "preferred_shot": {"run_id": preferred_shot[0], "composition": preferred_shot[1]} if preferred_shot else None,
        "notes": notes.strip(),
    }


def save_preference(runs_dir: Path, entry: dict) -> Path:
    path = Path(runs_dir) / "benchmarks" / entry["bench_id"] / "preferences.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


def load_preferences(runs_dir: Path, bench_id: str) -> list[dict]:
    path = Path(runs_dir) / "benchmarks" / bench_id / "preferences.jsonl"
    if not path.exists():
        return []
    latest: dict[tuple[str, str], dict] = {}
    for line in path.read_text().splitlines():
        if line.strip():
            e = json.loads(line)
            latest[(e["rater"], e["case"])] = e
    return list(latest.values())


def summarize_preferences(manifest: dict, prefs: list[dict]) -> list[dict]:
    """Per model and rater: how often its set / one of its shots was preferred when shown."""
    model_of = {r["run_id"]: r["model"] for r in manifest["runs"]}
    stats: dict[tuple[str, str], dict] = {}
    for e in prefs:
        for rid in e["shown_order"]:
            key = (model_of.get(rid, "?"), e["rater"])
            s = stats.setdefault(key, {"model": key[0], "rater": key[1], "shown": 0, "set_wins": 0, "shot_wins": 0})
            s["shown"] += 1
            s["set_wins"] += int(e["preferred_run"] == rid)
            s["shot_wins"] += int(bool(e["preferred_shot"]) and e["preferred_shot"]["run_id"] == rid)
    for s in stats.values():
        s["set_win_rate"] = round(s["set_wins"] / s["shown"], 3) if s["shown"] else None
        s["shot_win_rate"] = round(s["shot_wins"] / s["shown"], 3) if s["shown"] else None
    return sorted(stats.values(), key=lambda s: (s["rater"], -(s["set_win_rate"] or 0)))
