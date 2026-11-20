#!/usr/bin/env python3
"""Build a blind side-by-side rating sheet for the three leading portrait_v1 candidates.

    photography-ai/.venv/bin/python tools/rating-sheet/build.py

Reads the benchmark runs (runs/*/run.json), embeds small copies of each scenario's photos and the three candidates'
looks into ONE self-contained HTML file (tools/rating-sheet/out/, git-ignored because it holds your photos), and
leaves the order of A/B/C shuffled per scenario so you rate without knowing which model wrote what.
Ratings save in the browser as you go; "Download ratings" gives a JSON file that rating_summary.py turns into a table.
"""
import base64, glob, io, json, random, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PHOTO = Path("/Users/colin/Documents/ChatGPT/DIgit/photography-ai")
sys.path.insert(0, str(PHOTO / "src"))
from PIL import Image  # noqa: E402
from photo_ai.cases import all_cases  # noqa: E402

CANDIDATES = {  # key -> (bench label, shown to you only after you finish)
    "q5": ("fuse-v7-q5-20261118", "Fused q5 (Qwen3.5 + v7 adapter)"),
    "q35mix": ("clean-q35-mix-v4-20261118", "Qwen3.5 + mix adapter, unfused (v4)"),
    "qvlmix": ("clean-qvl-mix-v4-20261118", "Qwen3-VL + mix adapter, unfused (v4)"),
}
SEED = 20261118
OUT = Path(__file__).parent / "out" / "portrait_v1_rating_sheet.html"


def thumb(path, side):
    im = Image.open(path).convert("RGB")
    im.thumbnail((side, side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=78)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


runs = {}
for f in glob.glob(str(PHOTO / "runs/202611*/run.json")):
    j = json.load(open(f))
    for key, (label, _) in CANDIDATES.items():
        if j.get("label") == label:
            runs[(key, j["case"] if isinstance(j["case"], str) else j["case"]["id"])] = j

rng = random.Random(SEED)
scenarios = []
for case in all_cases("portrait_v1"):
    cands = {}
    for key in CANDIDATES:
        j = runs.get((key, case.id))
        res = (j or {}).get("result") or {}
        cands[key] = {"valid": bool(j and j["validation"]["ok"]), "looks": (res.get("compositions") or [])[:3],
                      "seconds": (j or {}).get("timing", {}).get("inference_s")}
    order = list(CANDIDATES)
    rng.shuffle(order)
    scenarios.append({"id": case.id, "subject": case.subject, "target": thumb(case.target.path, 720),
                      "inspiration": [thumb(i.path, 240) for i in case.inspiration],
                      "order": order, "cands": cands})

data = {"scenarios": scenarios, "names": {k: v[1] for k, v in CANDIDATES.items()}, "built": "2026-11-18"}
html = (Path(__file__).parent / "template.html").read_text().replace(
    "/*DATA*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(html, encoding="utf-8")
print(f"{OUT}  ({OUT.stat().st_size / 1e6:.1f} MB, {len(scenarios)} scenarios)")
missing = [(k, s["id"]) for s in scenarios for k, c in s["cands"].items() if not c["looks"]]
if missing:
    print("WARNING: no looks for", missing)
