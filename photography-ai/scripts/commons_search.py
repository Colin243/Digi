"""Search Wikimedia Commons for freely licensed photos and build a numbered contact sheet.

Used to hand-pick evaluation images. Only free licenses are kept (CC0, public domain,
CC BY, CC BY-SA). Results (with author/license/source) go to <out>/<name>.json and a
contact sheet to <out>/<name>.jpg.

  uv run python scripts/commons_search.py "portrait woman cafe window" --name cafe --out /tmp/x
"""

from __future__ import annotations

import argparse
import io
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

API = "https://commons.wikimedia.org/w/api.php"
UA = "DigiPhotographyAI-eval/0.1 (local research tool; non-commercial evaluation)"
FREE = re.compile(r"^(cc0|public domain|pd\b|cc by(-sa)? \d(\.\d)?)", re.I)


def _get(url: str, tries: int = 5) -> bytes:
    """GET with Wikimedia-friendly User-Agent and backoff on HTTP 429."""
    import time
    import urllib.error

    for i in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or i == tries - 1:
                raise
            time.sleep(int(exc.headers.get("Retry-After") or 0) or 5 * (i + 1))
    raise RuntimeError("unreachable")


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def search(query: str, limit: int = 40, category: str | None = None) -> list[dict]:
    q = f"{query} filetype:bitmap" + (f' incategory:"{category}"' if category else "")
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": q, "gsrlimit": limit, "prop": "imageinfo",
        "iiprop": "url|extmetadata|size|mime|sha1", "iiurlwidth": 1280,
    }
    data = json.loads(_get(API + "?" + urllib.parse.urlencode(params)))
    out = []
    for page in sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0)):
        ii = (page.get("imageinfo") or [{}])[0]
        md = ii.get("extmetadata", {})
        lic = _strip_html(md.get("LicenseShortName", {}).get("value", ""))
        if not FREE.match(lic) or ii.get("mime") not in ("image/jpeg", "image/png"):
            continue
        out.append({
            "title": page["title"],
            "page_url": ii.get("descriptionurl"),
            "download_url": ii.get("thumburl") or ii.get("url"),
            "width": ii.get("width"), "height": ii.get("height"),
            "license": lic,
            "license_url": _strip_html(md.get("LicenseUrl", {}).get("value", "")),
            "author": _strip_html(md.get("Artist", {}).get("value", ""))[:200],
            "description": _strip_html(md.get("ImageDescription", {}).get("value", ""))[:300],
            "sha1_original": ii.get("sha1"),
        })
    return out


def contact_sheet(items: list[dict], path: Path, cell: int = 220, cols: int = 8) -> None:
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, max(rows, 1) * cell), "white")
    d = ImageDraw.Draw(sheet)
    for i, it in enumerate(items):
        try:
            url = it["download_url"].replace("/1280px-", "/330px-")
            im = Image.open(io.BytesIO(_get(url))).convert("RGB")
            im.thumbnail((cell - 6, cell - 18))
            x, y = (i % cols) * cell, (i // cols) * cell
            sheet.paste(im, (x + 3, y + 16))
            d.text((x + 3, y + 2), str(i), fill="red")
        except Exception as exc:  # noqa: BLE001
            print("thumb failed", i, exc)
    sheet.save(path, quality=80)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--category")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    items = search(a.query, a.limit, a.category)
    (a.out / f"{a.name}.json").write_text(json.dumps(items, indent=1, ensure_ascii=False))
    contact_sheet(items, a.out / f"{a.name}.jpg")
    print(f"{len(items)} free-licensed results -> {a.out / (a.name + '.jpg')}")


if __name__ == "__main__":
    main()
