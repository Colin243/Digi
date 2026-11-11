"""`photo-ai monitor <action>`: serve the dashboard, compare checkpoints, summarise overhead."""

from __future__ import annotations

import json
from pathlib import Path


def _train_log(run: Path) -> list[dict]:
    p = run / "train_log.jsonl" if run.is_dir() else run
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def overhead_report(off_dirs: list[Path], on_dirs: list[Path], warmup: int = 3) -> dict:
    """Pairs off[i] with on[i] (same config, same seed) and reports per-pair and pooled overhead."""
    from .runlog import read_events
    from .stats import median, step_overhead

    def rows(d):  # step_wall_s includes the monitor's own per-step work
        return [{**r, "step_s": r.get("step_wall_s", r.get("step_s"))} for r in _train_log(d) if r.get("step")]

    pairs = [step_overhead(rows(a), rows(b), warmup) for a, b in zip(off_dirs, on_dirs)]
    pooled_off = [r for d in off_dirs for r in rows(d)]
    pooled_on = [r for d in on_dirs for r in rows(d)]
    out = {"pairs": [{"off": str(a), "on": str(b), **p} for a, b, p in zip(off_dirs, on_dirs, pairs)],
           "median_of_pair_overheads_pct": median([p["overhead_median_paired_pct"] for p in pairs]),
           "pooled": step_overhead_pooled(pooled_off, pooled_on, warmup, median), "runs": {}}
    for d in off_dirs + on_dirs:
        s = json.loads((d / "summary.json").read_text()) if (d / "summary.json").exists() else {}
        mon = {}
        ev = read_events(d / "monitor" / "events.jsonl")["events"] if (d / "monitor" / "events.jsonl").exists() else []
        for e in ev:
            if e["kind"] == "summary":
                mon = {k: e.get(k) for k in ("peak_proc_footprint_gb", "swap_at_start_gb", "peak_swap_used_gb",
                                             "max_pressure", "layer_samples", "layer_sample_s_median",
                                             "dropped_total", "write_errors")}
        out["runs"][str(d)] = {"peak_mlx_gb": s.get("peak_memory_gb"), "steps": s.get("steps_done"), **mon}
    return out


def step_overhead_pooled(off, on, warmup, median):
    a = [r["step_s"] for r in off if r["step"] > warmup and "val_loss" not in r]
    b = [r["step_s"] for r in on if r["step"] > warmup and "val_loss" not in r]
    ma, mb = median(a), median(b)
    return {"median_step_s_off": ma, "median_step_s_on": mb,
            "overhead_ratio_of_medians_pct": None if not ma or mb is None else 100 * (mb / ma - 1)}


def run_monitor(a) -> int:
    if a.action == "serve":
        from .server import serve

        serve(a.host, a.port, runs=a.run)
        return 0
    if a.action == "compare":
        from .checkpoints import compare

        r = compare(a.a, a.b)
        if a.json:
            print(json.dumps(r, indent=1))
        else:
            c = r["compatibility"]
            print(("compatible" if c["compatible"] else "INCOMPATIBLE") + f"; {c['common_modules']} matched modules")
            for e in c["errors"]:
                print("  error:", e)
            for w in c["warnings"]:
                print("  warning:", w)
            if c["compatible"]:
                print(f"total effective ||dW||_F = {r['aggregate']['effective_delta_norm_total']}")
                for k in r["aggregate"]["top_modules_by_effective_delta"]:
                    print(f"  {k}: {r['modules'][k]['effective_delta_norm']:.4g}")
        return 0 if r["compatibility"]["compatible"] else 1
    if a.action == "overhead":
        rep = overhead_report(a.off, a.on, a.warmup)
        print(json.dumps(rep, indent=1, default=str))
        if a.out:
            a.out.write_text(json.dumps(rep, indent=1, default=str))
        return 0
    return 2
