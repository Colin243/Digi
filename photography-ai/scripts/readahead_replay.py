#!/usr/bin/env python3
"""Replay the app's read-ahead on a fixed timeline, so the numbers do not depend on how fast anyone taps.

The app reads each photo as it is picked (scene for the target, notes per inspiration photo, then the style step
and the prompt prefix), one call at a time, and when Plan is pressed it lets the call in progress finish, starts
no new one, and plans with whatever is ready. This script does the same with the real model in ONE thread:

  picks   target at 0 s, inspiration photo k at k * GAP s (GAP 0 = all picked at once)
  press   Plan 1 s after the last pick ("now": the call the app just started is still running), or WAIT seconds after it
  metric  seconds from the press to the first shot, and to the last shot (includes finishing the call in progress)

"none" is the baseline: no read-ahead, Plan with all photos at the press.

    .venv/bin/python scripts/readahead_replay.py --model models/q35-2b-v7-fused-q5 --cases 3

Writes runs/readahead-replay-<date>.json and prints a table. Run it with the API server stopped (one model at a time).
"""
import argparse
import json
import statistics as st
import tempfile
import time
from datetime import datetime
from pathlib import Path

from photo_ai import pipeline
from photo_ai.backends import make_backend
from photo_ai.cases import PROJECT_ROOT, all_cases


def log(*a):
    print(*a, flush=True)


class Replay:
    def __init__(self, backend, cfg_fn, runs: Path, shot_format: str):
        self.backend, self.cfg_fn, self.runs, self.shot_format = backend, cfg_fn, runs, shot_format

    def run_timeline(self, target: str, insp: list[str], gap: float, wait: float | None) -> dict:
        """wait None = the baseline with no read-ahead. Otherwise picks at the given gap and Plan after `wait`."""
        b, cfg_fn, runs = self.backend, self.cfg_fn, self.runs
        pipeline._SCENE_CACHE.clear()
        n = len(insp)
        t0 = time.perf_counter()
        picks = [0.0] + [k * gap for k in range(1, n + 1)]  # target, then each inspiration photo
        press_at = (picks[-1] + wait) if wait is not None else picks[-1]
        scene = None
        notes: list[dict | None] = [None] * n
        refs = None
        prefix = None
        done_jobs: list[tuple[str, float, float]] = []

        def now():
            return time.perf_counter() - t0

        def next_job():
            if wait is None:
                return None
            if scene is None and picks[0] <= now():
                return "scene"
            for k in range(n):
                if notes[k] is None and picks[k + 1] <= now():
                    return f"note{k}"
            if all(x is not None for x in notes) and picks[-1] <= now() and refs is None:
                return "refs"
            if refs is not None and scene is not None and prefix is None and not self_prefix_failed[0]:
                return "prefix"
            return None

        self_prefix_failed = [False]
        while now() < press_at:
            job = next_job()
            if job is None:
                due = [p for p in picks if p > now()]
                time.sleep(max(0.0, min([press_at] + due) - now()))
                continue
            s = now()
            if job == "scene":
                scene = pipeline.prepare_target_scene(b, target, cfg_fn(), runs)
            elif job.startswith("note"):
                k = int(job[4:])
                notes[k] = pipeline.prepare_note(b, insp[k], cfg_fn(), runs)
            elif job == "refs":
                texts = pipeline.check_notes(json.loads(json.dumps(notes)), b, cfg_fn())
                refs = pipeline.prepare_references_from_notes(b, texts, cfg_fn(), runs)
            elif job == "prefix":
                rc = pipeline.check_references(json.loads(json.dumps(refs)), b, cfg_fn())
                sc = pipeline.check_target_scene(json.loads(json.dumps(scene)), target, b, cfg_fn())
                prefix = pipeline.prepare_compositions_prefix(b, rc, sc, target, cfg_fn(), runs)
                if prefix is None:
                    self_prefix_failed[0] = True
            done_jobs.append((job, round(s, 1), round(now(), 1)))
        # Plan pressed at press_at; the call in progress (if any) already finished above. Plan with what is ready.
        started = now()
        cfg_kwargs = {}
        plan_insp = insp
        if scene is not None:
            cfg_kwargs["target_scene"] = pipeline.check_target_scene(json.loads(json.dumps(scene)), target, b, cfg_fn())
        if refs is not None:
            cfg_kwargs["references"] = pipeline.check_references(json.loads(json.dumps(refs)), b, cfg_fn())
            plan_insp = []
        elif any(x is not None for x in notes):
            cfg_kwargs["prepared_notes"] = pipeline.check_partial_notes(json.loads(json.dumps(notes)), n, b, cfg_fn())
        first = [None]

        def sink(e):
            if e.get("type") == "shot" and first[0] is None:
                first[0] = now()

        tok = pipeline.set_event_sink(sink)
        ptok = pipeline.set_compositions_prefix(prefix)
        try:
            rec = pipeline.analyze(b, plan_insp, target, cfg_fn(**cfg_kwargs), runs)
        finally:
            pipeline.reset_compositions_prefix(ptok)
            pipeline.reset_event_sink(tok)
        end = now()
        return {"press_s": round(press_at, 1), "plan_started_after_press_s": round(started - press_at, 1),
                "first_shot_after_press_s": round((first[0] if first[0] is not None else end) - press_at, 2),
                "done_after_press_s": round(end - press_at, 2), "valid": bool(rec["validation"]["ok"]),
                "notes_ready": sum(x is not None for x in notes), "refs_ready": refs is not None,
                "prefix_used": any(s.get("prefix_cached") for s in rec["stages"]), "jobs": done_jobs}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--suite", default="portrait_v1")
    ap.add_argument("--cases", type=int, default=3, help="how many cases of the suite to replay")
    ap.add_argument("--shot-format", default="v7")
    ap.add_argument("--gaps", type=float, nargs="+", default=[0.0, 5.0], help="seconds between picks")
    ap.add_argument("--wait", type=float, default=40.0, help="seconds after the last pick for the 'waited' press")
    ap.add_argument("--samples-root", help="folder that holds samples/ if the cases' photos are not under this checkout")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    def cfg_fn(**k):
        return pipeline.RunConfig(**{"mode": "inspiration", "strategy": "decomposed", "json_format": "keys",
                                     "shot_format": a.shot_format, **k})

    backend = make_backend(str(Path(a.model).resolve()))
    backend.load()
    runs = Path(tempfile.mkdtemp(prefix="readahead-replay-"))
    rp = Replay(backend, cfg_fn, runs, a.shot_format)

    def path(p) -> str:
        s = str(p)
        if a.samples_root:
            s = s.replace(str(PROJECT_ROOT), a.samples_root)
        return s

    _ = pipeline.prepare_note(backend, path(all_cases(a.suite)[0].target.path), cfg_fn(), runs)  # warm the model first
    timelines = [("none", 0.0, None)] + [(f"gap{g:g}-now", g, 1.0) for g in a.gaps] + \
                [(f"gap{g:g}-wait{a.wait:g}", g, a.wait) for g in a.gaps]
    results = []
    for c in all_cases(a.suite)[: a.cases]:
        target, insp = path(c.target.path), [path(i.path) for i in c.inspiration]
        for name, gap, wait in timelines:
            r = rp.run_timeline(target, insp, gap, wait)
            r.update({"case": c.id, "timeline": name})
            results.append(r)
            log(f"{c.id:26s} {name:16s} first shot {r['first_shot_after_press_s']:5.1f}s  done {r['done_after_press_s']:5.1f}s  "
                f"notes {r['notes_ready']}/{len(insp)} refs {r['refs_ready']} prefix {r['prefix_used']} valid {r['valid']}")
    log("\ntimeline            first shot after press (mean, s)   done after press (mean, s)")
    for name, _, _ in timelines:
        rs = [r for r in results if r["timeline"] == name]
        log(f"{name:18s} {st.mean(r['first_shot_after_press_s'] for r in rs):10.1f} {st.mean(r['done_after_press_s'] for r in rs):28.1f}")
    out = Path(a.out) if a.out else PROJECT_ROOT / "runs" / f"readahead-replay-{datetime.now():%Y%m%d-%H%M}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"model": Path(a.model).name, "shot_format": a.shot_format, "wait": a.wait, "results": results}, indent=1))
    log("wrote", out)


if __name__ == "__main__":
    main()
