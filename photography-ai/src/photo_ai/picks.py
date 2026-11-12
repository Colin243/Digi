"""Tap-to-pick review for the creative director: choose a theme, see each scene with three looks as a few short
notes plus an example photo, and tap the one she likes best. Her picks become preference data (chosen vs the
other looks) and approved training rows for the chosen look.

  photo-ai picks generate      run the Scene Director on scene x theme (configs/picks_v1.json)
  photo-ai picks site          build the static page (data/<dataset>/picks/<pick_id>/site/)
  photo-ai picks import --file her-picks.json --site <that site folder>
  photo-ai picks export        preference pairs + SFT rows for chosen looks (approved picks only)

Scenes come from the training split of the CC0 pool, so nothing here touches the held-out sets.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from . import prompts
from .cases import PROJECT_ROOT, REPO_ROOT
from .training.pool import data_dir, load_pool

DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "picks_v1.json"


def load_config(path: Path | None = None) -> dict:
    return json.loads(Path(path or DEFAULT_CONFIG).read_text())


def pick_dir(cfg: dict) -> Path:
    d = data_dir(cfg["dataset"]) / "picks" / cfg["pick_id"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def generate(cfg: dict, model: str, runs_dir: Path, log=print) -> dict:
    """One Scene Director run per scene x theme; resumable (runs already recorded are skipped)."""
    from .backends import make_backend
    from .pipeline import RunConfig, analyze

    out = pick_dir(cfg) / "runs.json"
    done = json.loads(out.read_text()) if out.exists() else {"pick_id": cfg["pick_id"], "runs": []}
    have = {(r["scene"], r["theme"]) for r in done["runs"]}
    pool = {i["id"]: i for i in load_pool(cfg["dataset"])["images"]}
    backend = make_backend(model)
    for scene in cfg["scenes"]:
        for theme in cfg["themes"]:
            if (scene, theme) in have:
                continue
            rc = RunConfig(mode="scene", style=theme, max_side=cfg.get("max_side", 1024), json_format="keys",
                           n_looks=cfg.get("n_looks", 3))
            rec = analyze(backend, [], str(REPO_ROOT / pool[scene]["file"]), rc, runs_dir, label=cfg["pick_id"])
            done["runs"].append({"scene": scene, "theme": theme, "run_id": rec["run_id"], "valid": rec["validation"]["ok"],
                                 "run_dir": rec["run_dir"]})
            out.write_text(json.dumps(done, indent=1))
            log(f"{scene} {theme:20} valid={rec['validation']['ok']} {rec['timing']['inference_s']:.0f}s")
    backend.unload()
    return done


# --------------------------------------------------------------------------- short notes ("chips")

def _has(text: str, *words: str) -> bool:
    return any(re.search(rf"\b{w}", text) for w in words)


def _clause(text: str, n: int = 7) -> str:
    first = re.split(r"[,;.]| with | while | and then ", text.strip(), maxsplit=1)[0].strip()
    words = first.split()
    out = " ".join(words[:n]) + ("…" if len(words) > n else "")
    return out[:1].upper() + out[1:]


def look_traits(look: dict) -> dict:
    """Coarse angle / framing / pose / gaze read from a shot-v2 look, for notes and for matching example photos."""
    cam = f"{look.get('camera_height', '')} {look.get('camera_angle', '')}".lower()
    frm = f"{look.get('distance_and_framing', '')} {look.get('title', '')}".lower()
    pose = str(look.get("body_pose", "")).lower()
    gaze = str(look.get("gaze", "")).lower()
    angle = ("low" if _has(cam, "low", "knee", "crouch", "kneel", "ground", "below", "tilt(?:ed|s)? up", "looking up")
             else "high" if _has(cam, "high", "above", "overhead", "tilt(?:ed|s)? down", "looking down") else "eye")
    framing = ("close-up" if _has(frm, "close", "head and shoulders", "head-and-shoulders", "headshot", "portrait crop")
               else "half-body" if _has(frm, "waist", "half", "three-quarter", "medium", "chest")
               else "environmental" if _has(frm, "wide", "small in", "environment", "far")
               else "full-body")
    p = ("sitting" if _has(pose, "sit", "seated", "perch") else "leaning" if _has(pose, "lean")
         else "walking" if _has(pose, "walk", "step", "stroll") else "standing")
    facing = ("camera" if _has(gaze, "lens", "camera", "viewer") else "away")
    return {"camera_angle": angle, "framing": framing, "pose": p, "facing": facing}


def look_notes(look: dict) -> list[str]:
    """3-5 short notes instead of paragraphs."""
    t = look_traits(look)
    light = f"{look.get('lighting_tip', '')}".lower()
    notes = [{"close-up": "Close-up", "half-body": "Waist up", "full-body": "Full body",
              "environmental": "Wide, small in frame"}[t["framing"]],
             {"low": "Shot from low", "high": "Shot from above", "eye": "Eye level"}[t["camera_angle"]]]
    if look.get("body_pose"):
        notes.append(_clause(look["body_pose"]))
    gaze = str(look.get("gaze", "")).lower()
    notes.append("Eyes to camera" if t["facing"] == "camera" else "Eyes closed" if "closed" in gaze
                 else "Looking down" if _has(gaze, "down", "floor", "ground") else "Looking away")
    for words, label in ((("flash",), "Phone flash"), (("backlight", "behind (?:her|him|them|the subject)", "rim"), "Backlit"),
                         (("window",), "Window light"), (("neon", "lamp", "street ?light", "sign"), "Lamp / neon light"),
                         (("shade", "overcast", "diffuse", "soft"), "Soft light")):
        if _has(light, *words):
            notes.append(label)
            break
    expr = str(look.get("expression_cue", "")).strip()
    if expr and len(expr.split()) <= 6:
        notes.append(expr[:1].upper() + expr[1:])
    return notes


def example_photo(look: dict, dataset: str, avoid: set[str]) -> str | None:
    """A CC0 pool photo of a person shot roughly the same way (angle, framing, pose, facing)."""
    from .training.pool import usable
    from .training.tags import load_tags

    t = look_traits(look)
    pool = {i["id"]: i for i in usable(load_pool(dataset))}
    best, best_score = None, -1
    for pid, rec in sorted(load_tags(dataset).items()):
        g = rec["tags"]
        if pid not in pool or pid in avoid or g.get("role") != "person" or not g.get("usable", True) or g.get("n_people", 1) > 1:
            continue
        score = (2 * (g.get("camera_angle") == t["camera_angle"]) + 2 * (g.get("framing") == t["framing"])
                 + 2 * (g.get("pose") == t["pose"]) + (("camera" if g.get("facing") == "camera" else "away") == t["facing"]))
        if score > best_score:
            best, best_score = pid, score
    return best


# --------------------------------------------------------------------------- page

TEMPLATE = PROJECT_ROOT / "review_site" / "picks_page.html"


def _looks(run_dir: str) -> list[dict] | None:
    rec = json.loads((Path(run_dir) / "run.json").read_text())
    return (rec.get("result") or {}).get("compositions") if rec["validation"]["ok"] else None


def look_sha(look: dict) -> str:
    from .training.labels import answer_sha

    return answer_sha(look)


def build_site(cfg: dict, max_side: int = 900, example_side: int = 480) -> dict:
    from PIL import Image, ImageOps

    runs = json.loads((pick_dir(cfg) / "runs.json").read_text())["runs"]
    pool = {i["id"]: i for i in load_pool(cfg["dataset"])["images"]}
    out = pick_dir(cfg) / "site"
    (out / "img").mkdir(parents=True, exist_ok=True)

    def img(pid: str, side: int) -> str:
        dst = out / "img" / f"{pid}-{side}.jpg"
        if not dst.exists():
            im = ImageOps.exif_transpose(Image.open(REPO_ROOT / pool[pid]["file"])).convert("RGB")
            im.thumbnail((side, side))
            im.save(dst, "JPEG", quality=78, optimize=True)
        return f"img/{dst.name}"

    items, shown = [], {}
    for r in runs:
        looks = _looks(r["run_dir"]) if r["valid"] else None
        if not looks:
            continue
        avoid: set[str] = set()
        cards = []
        for lk in looks:
            ex = example_photo(lk, cfg["dataset"], avoid)
            if ex:
                avoid.add(ex)
            cards.append({"notes": look_notes(lk), "example": img(ex, example_side) if ex else None, "sha": look_sha(lk)})
        items.append({"scene": r["scene"], "theme": r["theme"], "run_id": r["run_id"],
                      "scene_img": img(r["scene"], max_side), "looks": cards})
        shown[f"{r['scene']}|{r['theme']}"] = {"run_id": r["run_id"], "look_sha": [c["sha"] for c in cards]}
    themes = [{"key": t, "zh": prompts.STYLE_BRIEFS[t]["zh"], "en": prompts.STYLE_BRIEFS[t]["en"]} for t in cfg["themes"]]
    data = json.dumps({"pick_id": cfg["pick_id"], "themes": themes, "items": items}, ensure_ascii=False).replace("</", "<\\/")
    (out / "index.html").write_text(TEMPLATE.read_text().replace("/*PICKS_DATA*/null", data))
    api = out / "api"
    api.mkdir(exist_ok=True)
    for f in (PROJECT_ROOT / "review_site" / "picks_api").glob("*.js"):
        (api / f.name).write_text(f.read_text())
    (out / "vercel.json").write_text(json.dumps({"headers": [{"source": "/(.*)", "headers": [
        {"key": "X-Robots-Tag", "value": "noindex, nofollow"}]}]}, indent=1))
    (out / "manifest.json").write_text(json.dumps({"pick_id": cfg["pick_id"], "built_at": datetime.now().isoformat(timespec="seconds"),
                                                   "shown": shown}, indent=1))
    return {"page": str(out / "index.html"), "items": len(items), "images": len(list((out / "img").glob("*.jpg")))}


# --------------------------------------------------------------------------- import / export

def prefs_path(cfg: dict) -> Path:
    return pick_dir(cfg) / "preferences.json"


def import_picks(cfg: dict, doc: dict, site: Path | None = None, reviewer: str | None = None) -> dict:
    """Store her picks. A pick counts only if the looks it names are exactly the looks the page showed and the
    run still has (fingerprints match); 'none' records that no look was good enough."""
    from collections import Counter

    from .training.labels import _require_human

    who = _require_human(reviewer or doc.get("name", ""))
    if doc.get("pick_id") not in (None, cfg["pick_id"]):
        raise ValueError(f"these picks are for {doc.get('pick_id')}, not {cfg['pick_id']}")
    shown = json.loads((Path(site or pick_dir(cfg) / "site") / "manifest.json").read_text())["shown"]
    runs = {r["run_id"]: r for r in json.loads((pick_dir(cfg) / "runs.json").read_text())["runs"]}
    prefs = json.loads(prefs_path(cfg).read_text()) if prefs_path(cfg).exists() else {}
    counts = Counter()
    for k, p in (doc.get("picks") or {}).items():
        page = shown.get(k)
        if not page or p.get("run_id") != page["run_id"]:
            counts["unknown_item"] += 1
            continue
        looks = _looks(runs[page["run_id"]]["run_dir"]) or []
        current = [look_sha(lk) for lk in looks]
        if p.get("look_sha") != page["look_sha"] or current != page["look_sha"]:
            counts["stale"] += 1
            continue
        scene, theme = k.split("|")
        choices = _choices(p, len(current))
        none = p.get("none") is True or p.get("choice") == "none"
        if not choices and not none:
            counts["no_answer"] += 1
            continue
        prefs[f"{k}|{who}"] = {"scene": scene, "theme": theme, "run_id": page["run_id"], "reviewer": who,
                               "choices": [] if none else choices, "none": none, "why": p.get("why") or [],
                               "look_sha": current, "picked_at": p.get("at"),
                               "imported_at": datetime.now().isoformat(timespec="seconds")}
        counts["none_of_these" if none else "picked"] += 1
    prefs_path(cfg).write_text(json.dumps(prefs, indent=1, ensure_ascii=False))
    return dict(counts)


def _choices(p: dict, n: int) -> list[int]:
    """Chosen look indices: the page's multi-select `choices`, or v1's single `choice`."""
    raw = p.get("choices")
    if raw is None:
        raw = [p["choice"]] if isinstance(p.get("choice"), int) else []
    return sorted({int(c) for c in raw if isinstance(c, int) and 0 <= c < n})


def pull(cfg: dict, base_url: str, read_key: str, site: Path | None = None) -> dict:
    """Fetch every submission stored by the live page (/api/picks) and import each one."""
    import urllib.request

    req = urllib.request.Request(base_url.rstrip("/") + "/api/picks", headers={"x-read-key": read_key})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    (pick_dir(cfg) / "pulled.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
    results = {}
    for sub in data.get("submissions", []):
        label = f"{sub.get('name')} ({sub.get('client_id')}, {len(sub.get('picks') or {})} places)"
        try:
            results[label] = import_picks(cfg, sub, site)
        except ValueError as exc:
            results[label] = {"refused": str(exc)}
    return {"submissions": len(data.get("submissions", [])), "imported": results}


def delete_submission(base_url: str, read_key: str, slot: str) -> dict:
    """Remove one stored submission (e.g. a test) from the live page's storage."""
    import urllib.parse
    import urllib.request

    url = base_url.rstrip("/") + "/api/picks?slot=" + urllib.parse.quote(slot)
    req = urllib.request.Request(url, method="DELETE", headers={"x-read-key": read_key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def status(cfg: dict) -> dict:
    from collections import Counter

    prefs = json.loads(prefs_path(cfg).read_text()) if prefs_path(cfg).exists() else {}
    return {"picks": len(prefs), "by_theme": dict(Counter(p["theme"] for p in prefs.values())),
            "chosen_look_position": dict(Counter(str(c) for p in prefs.values() for c in _choices(p, 99))),
            "none_of_these": sum(bool(p.get("none") or p.get("choice") == "none") for p in prefs.values()),
            "why": dict(Counter(w for p in prefs.values() for w in p["why"]))}


def export(cfg: dict) -> dict:
    """SFT rows for each chosen look (her pick is the approval) + preference records (chosen vs the other looks)."""
    from .training.export import _j, _row

    runs = {r["run_id"]: r for r in json.loads((pick_dir(cfg) / "runs.json").read_text())["runs"]}
    pool = {i["id"]: i for i in load_pool(cfg["dataset"])["images"]}
    prefs = json.loads(prefs_path(cfg).read_text()) if prefs_path(cfg).exists() else {}
    out = pick_dir(cfg) / "export"
    out.mkdir(exist_ok=True)
    sft, pairs = [], []
    with prompts.json_format("keys"):
        for p in prefs.values():
            rec = json.loads((Path(runs[p["run_id"]]["run_dir"]) / "run.json").read_text())
            looks, scene = rec["result"]["compositions"], rec["result"]["target_scene"]
            chosen = _choices(p, len(looks))
            if not chosen or [look_sha(lk) for lk in looks] != p["look_sha"]:
                continue
            for c in chosen:
                prompt = prompts.scene_look(scene, p["theme"], "", prompts.DEFAULT_SUBJECT, c + 1, looks[:c], len(looks))
                meta = {"pick_id": cfg["pick_id"], "scene": p["scene"], "theme": p["theme"], "reviewer": p["reviewer"],
                        "stage": f"look{c + 1}", "why": p["why"]}
                sft.append(_row(prompt, [str(REPO_ROOT / pool[p["scene"]]["file"])], _j(looks[c]), meta))
                pairs += [{"scene": p["scene"], "theme": p["theme"], "reviewer": p["reviewer"], "chosen": looks[c],
                           "rejected": lk, "why": p["why"]} for k, lk in enumerate(looks) if k not in chosen]
    (out / "sft_chosen.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in sft))
    (out / "preference_pairs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in pairs))
    return {"out_dir": str(out), "sft_rows": len(sft), "preference_pairs": len(pairs), "prompt_version": prompts.version_for("scene", "v2")}
