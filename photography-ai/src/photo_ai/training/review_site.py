"""Build the "Shot Review" page: a shareable review of AI-drafted labels for a creative director.

  photo-ai train-data review-site        -> data/<dataset>/review_site/{shot-review.html, img/*.jpg}

The page template lives in review_site/ (committed). Its data (the drafted answers) and the
downscaled CC0 photos are generated into the git-ignored data/ folder and published as a
private claude.ai artifact with the photos as files beside the page. Reviews come back with
`photo-ai train-data import-review --file <export.json>`.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageOps

from ..cases import PROJECT_ROOT, REPO_ROOT
from .assemble import load_examples
from .labels import load_label
from .pool import data_dir, load_pool

TEMPLATE = PROJECT_ROOT / "review_site"


VERCEL_JSON = {"headers": [{"source": "/(.*)", "headers": [{"key": "X-Robots-Tag", "value": "noindex, nofollow"}]}]}


def build(dataset: str = "train_v1", max_side: int = 900, target: str = "artifact") -> dict:
    """target "artifact": a claude.ai page (the publish adds the document skeleton; answers go to its db).
    target "vercel": a standalone static site (full HTML document + vercel.json, not indexed); answers stay in
    the reviewer's browser and come back as a downloaded or copied JSON file."""
    out = data_dir(dataset) / ("review_site" if target == "artifact" else "review_site_vercel")
    (out / "img").mkdir(parents=True, exist_ok=True)
    pool = {i["id"]: i for i in load_pool(dataset)["images"]}

    def img(pid: str) -> dict:
        dst = out / "img" / f"{pid}.jpg"
        if not dst.exists():
            im = ImageOps.exif_transpose(Image.open(REPO_ROOT / pool[pid]["file"])).convert("RGB")
            im.thumbnail((max_side, max_side))
            im.save(dst, "JPEG", quality=80, optimize=True)
        it = pool[pid]
        return {"src": f"img/{pid}.jpg", "credit": f"{it.get('author') or 'Unknown'} · {it['license']}", "page": it["page_url"]}

    examples = []
    for e in load_examples(dataset):
        lab = load_label(dataset, e["example_id"])
        if lab is None:
            continue
        notes = []
        for h in lab["history"]:
            if not h.get("note") or h["action"] == "creative-review":
                continue
            if h["action"] == "draft-imported":
                notes.append({"who": "Claude (drafted this)", "note": h["note"].split("\n\n> ")[0]})
            else:
                notes.append({"who": "Codex (AI review)" if "codex" in h["by"] else h["by"], "note": h["note"]})
        examples.append({"id": e["example_id"], "short": e["example_id"].split("-")[1], "split": e["split"],
                         "technique": e["technique"]["description"], "inspiration": [img(p) for p in e["inspiration"]],
                         "target": img(e["target"]), "answer": lab["answer"], "ai_notes": notes})
    data = json.dumps(examples, ensure_ascii=False).replace("</", "<\\/")
    page = ((TEMPLATE / "page_head.html").read_text() + (TEMPLATE / "page_body.html").read_text()
            + f'<script type="application/json" id="data">{data}</script>\n<script>\n'
            + (TEMPLATE / "page_script.js").read_text() + "</script>\n")
    if target == "vercel":
        page = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
                '<meta name="robots" content="noindex,nofollow">'
                '<style>body{margin:0}img{max-width:100%}</style></head><body>' + page + "</body></html>\n")
        (out / "vercel.json").write_text(json.dumps(VERCEL_JSON, indent=1))
        name = "index.html"
    else:
        name = "shot-review.html"
    (out / name).write_text(page)
    return {"page": str(out / name), "examples": len(examples), "images": len(list((out / "img").glob("*.jpg")))}
