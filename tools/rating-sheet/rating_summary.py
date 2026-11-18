#!/usr/bin/env python3
"""Turn the downloaded ratings file into a quality-vs-speed table.

    python3 tools/rating-sheet/rating_summary.py ~/Downloads/portrait_v1_ratings.json
"""
import json, statistics as st, sys
from collections import defaultdict

d = json.load(open(sys.argv[1]))
rows = defaultdict(list)
for r in d["ratings"]:
    rows[r["candidate"]].append(r)
scenarios = {r["scenario"] for r in d["ratings"]}
rated = {s for s in scenarios if all(r["score"] for r in d["ratings"] if r["scenario"] == s)}
print(f"{len(rated)} of {len(scenarios)} scenarios fully rated\n")
print("| Candidate | Mean score | Scores 4-5 | Invented detail | Unsafe | Picked best | Median s | Valid |")
print("|---|---|---|---|---|---|---|---|")
for k, rs in sorted(rows.items(), key=lambda kv: -(st.mean([r["score"] for r in kv[1] if r["score"]] or [0]))):
    rs = [r for r in rs if r["scenario"] in rated]
    if not rs:
        continue
    sc = [r["score"] for r in rs]
    wins = sum(r["picked_best"] for r in rs)
    print(f"| {d['names'][k]} | {st.mean(sc):.2f} | {sum(s >= 4 for s in sc)}/{len(sc)} | {sum(r['invented'] for r in rs)}/{len(rs)} | "
          f"{sum(r['unsafe'] for r in rs)}/{len(rs)} | {wins}/{len(rs)} | {st.median([r['seconds'] for r in rs if r['seconds']]):.1f} | "
          f"{sum(r['valid'] for r in rs)}/{len(rs)} |")
n_tie = len({r["scenario"] for r in d["ratings"] if r["tie"]})
print(f"\nScenarios marked as a tie: {n_tie}. Scores are 1-5 per answer (a set of 3 looks); 5 means you would use all of them.")
