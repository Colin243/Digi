#!/usr/bin/env python3
"""Compositions cap/streaming numbers from ios-bench results JSON (docs/iphone-benchmark.md section 8).

    python3 photography-ai/ios-bench/scripts/streaming_summary.py ~/Downloads/bench-*.json
"""
import json
import statistics
import sys
from pathlib import Path


def fmt(x, unit=" s"):
    return "—" if x is None else f"{x:.2f}{unit}"


def main(paths):
    print("| file | cap | px | n warm | compositions TTFT median | shot 1 median / max | target + shot 1 median "
          "| compositions e2e median | tokens median | shots complete (min) | repaired | JSON valid |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for p in paths:
        r = json.loads(Path(p).read_text())
        cap = r["config"]["max_tokens"].get("compositions")
        for size in r["config"]["sizes"]:
            trials = [t for t in r["trials"] if t["size"] == size and t["workload"] == "decomposed"
                      and not t.get("error") and not t["first_after_load"]]
            comps = [c for t in trials for c in t["calls"] if c["stage"] == "compositions"]
            if not comps:
                continue
            med = lambda xs: statistics.median(xs) if xs else None
            shot1 = [c["first_shot_seconds"] for c in comps if c.get("first_shot_seconds") is not None]
            on_site = []
            for t in trials:
                tgt = next((c for c in t["calls"] if c["stage"] == "target_scene"), None)
                cmp_ = next((c for c in t["calls"] if c["stage"] == "compositions"), None)
                if tgt and cmp_ and cmp_.get("first_shot_seconds") is not None:
                    on_site.append(tgt["e2e_seconds"] + cmp_["first_shot_seconds"])
            shots = [c.get("shots_complete") for c in comps if c.get("shots_complete") is not None]
            print(f"| {Path(p).name} | {cap} | {size} | {len(comps)} | {fmt(med([c['ttft_seconds'] for c in comps]))} "
                  f"| {fmt(med(shot1))} / {fmt(max(shot1) if shot1 else None)} | {fmt(med(on_site))} "
                  f"| {fmt(med([c['e2e_seconds'] for c in comps]))} "
                  f"| {med([c['generated_tokens'] for c in comps])} | {min(shots) if shots else '—'} "
                  f"| {sum(1 for c in comps if c.get('repaired_after_cap'))}/{len(comps)} "
                  f"| {sum(1 for c in comps if c.get('json_valid'))}/{len(comps)} |")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
