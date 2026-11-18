"""Fetch a small set of CC0 scenery photos (no people) for testing the Director on views.

    uv run --no-sync python scripts/fetch_scenery.py

Source: Wikimedia Commons, Category:Images from Unsplash (published on Unsplash under CC0 before
June 2017), via the Commons API with a descriptive User-Agent and backoff on HTTP 429. Writes
samples/scenery_v1/<id>.jpg (git-ignored, 1600 px previews) and datasets/scenery_v1/SOURCES.md.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples" / "scenery_v1"
SOURCES = ROOT / "datasets" / "scenery_v1" / "SOURCES.md"
API = "https://commons.wikimedia.org/w/api.php"
UA = "photography-ai-eval/0.1 (local model evaluation; CC0 scenery test set)"

# id, search terms. One photo each; the ids describe the kind of view.
WANTED = [
    ("mountain-lake", "mountain lake"),
    ("forest-path", "forest path trees"),
    ("ocean-coast", "ocean coast cliff"),
    ("desert-dunes", "desert dunes"),
    ("waterfall", "waterfall"),
    ("city-skyline", "city skyline view"),
    ("snow-peaks", "snowy mountains"),
    ("field-sunset", "field sunset"),
]
PEOPLE = re.compile(r"\b(woman|women|man|men|girl|boy|portrait|people|person|couple|face|selfie|model|hiker|climber)\b", re.I)


def get(url: str) -> bytes:
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(2 ** attempt * 2)
    raise RuntimeError(f"gave up on {url}")


def search(terms: str) -> list[dict]:
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": "6", "gsrlimit": "30",
        "gsrsearch": f'incategory:"Images from Unsplash" {terms}',
        "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": "1600",
    }
    data = json.loads(get(API + "?" + urllib.parse.urlencode(params)))
    return list(data.get("query", {}).get("pages", {}).values())


def main() -> None:
    lines = [
        "# scenery_v1 sources", "",
        "Wikimedia Commons, Category:Images from Unsplash (photos originally published on Unsplash under CC0 "
        "before June 2017). Fetched via the Commons API. Scenery only, no people.", "",
        "Local model evaluation only. Images are NOT committed to git; run `scripts/fetch_scenery.py` to download "
        "them into samples/scenery_v1/ (1600 px previews).", "",
    ]
    for pid, terms in WANTED:
        pages = sorted(search(terms), key=lambda p: p.get("index", 0))
        chosen = None
        for p in pages:
            info = (p.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata", {})
            lic = meta.get("LicenseShortName", {}).get("value", "")
            title = p.get("title", "")
            desc = re.sub("<[^>]+>", "", meta.get("ImageDescription", {}).get("value", ""))
            if "CC0" not in lic and "public domain" not in lic.lower():
                continue
            if PEOPLE.search(title) or PEOPLE.search(desc) or info.get("width", 0) < 1600:
                continue
            chosen = (p, info, lic)
            break
        if not chosen:
            print(f"{pid}: nothing suitable for {terms!r}")
            continue
        p, info, lic = chosen
        (OUT / f"{pid}.jpg").write_bytes(get(info["thumburl"]))
        artist = re.sub("<[^>]+>", "", info["extmetadata"].get("Artist", {}).get("value", "unknown")).strip()
        page_url = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(p["title"].replace(" ", "_"), safe=":_(),")
        lines.append(f"- `{pid}.jpg` — [{p['title']}]({page_url}) by {artist}, {lic}")
        print(f"{pid}: {p['title']} ({(OUT / f'{pid}.jpg').stat().st_size // 1024} KB)")
        time.sleep(1)
    SOURCES.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
