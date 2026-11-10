"""Held-out Scene Director evaluation (issue #21).

  photo-ai scene-eval validate                 check the manifest (fields, licences, coverage, split hygiene)
  photo-ai scene-eval fetch [--lock]           download fixtures to samples/scene_eval_v1/, verify sha256
  photo-ai scene-eval audit --pool <pool.json> overlap with training data: title, file hash, photographer,
                                               location and near-duplicate image (dHash)
  photo-ai scene-eval run --split heldout      one model, every fixture in the split, greedy; writes
                                               runs/scene-eval/<eval id>/{eval.json, report.md}
  photo-ai scene-eval report --eval <id>       rebuild report.md from eval.json

The fixture set is datasets/scene_eval_v1/manifest.json (images are downloaded, never committed) and
the scoring and decision rules are datasets/scene_eval_v1/criteria.json, declared before any run.
Scene Director only: Inspiration Director results live in the portrait_v1 benchmark and are never
mixed in here. The blind review package is built by scene_review.py.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from . import metrics, prompts
from .backends import make_backend
from .cases import PROJECT_ROOT, REPO_ROOT, Case, CaseImage
from .pipeline import RunConfig, analyze

DATASET = "scene_eval_v1"
DATASET_DIR = PROJECT_ROOT / "datasets" / DATASET
MANIFEST = DATASET_DIR / "manifest.json"
CRITERIA = DATASET_DIR / "criteria.json"
SAMPLES_DIR = PROJECT_ROOT / "samples" / DATASET

GROUPS = ("xhs_aligned", "ordinary")
SPLITS = ("heldout", "dev")
TAG_VALUES = {
    "setting": {"indoor", "outdoor"},
    "occupancy": {"empty", "occupied"},
    "posing_space": {"open", "limited", "ambiguous"},
}
SOURCES = {"wikimedia_commons", "private_album"}
_FREE = re.compile(r"^(cc0|public domain|pd\b|cc by(-sa)? \d(\.\d)?)", re.I)
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")

# Frozen generation settings. Changing any of them makes runs incomparable with earlier ones.
SETTINGS = {"max_side": 1024, "json_format": "keys", "temperature": 0.0, "seed": 0, "json_retries": 1,
            "repetition_penalty": None, "max_tokens": RunConfig().max_tokens}

# Fields that carry directions (where unsafe wording matters); evidence/on-site checks are observations.
DIRECTION_TEXT_FIELDS = ("camera_position", "subject_position", "body_pose", "head_direction", "gaze", "steps",
                         "lighting_tip", "distance_and_framing")
# A sentence that warns against the hazard ("stay well back from the yellow line") is not a direction into it.
_SAFETY_ADVICE = re.compile(r"\b(away from|back from|clear of|behind the yellow|do not|don't|never|avoid|stay off|"
                            r"keep off|keep clear|not on|instead of)\b")


# --- manifest -----------------------------------------------------------------------------------

def load_manifest(path: Path | None = None) -> dict:
    return json.loads(Path(path or MANIFEST).read_text())


def load_criteria(path: Path | None = None) -> dict:
    return json.loads(Path(path or CRITERIA).read_text())


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fixtures(manifest: dict, split: str | None = None, group: str | None = None) -> list[dict]:
    return [f for f in manifest["fixtures"]
            if (split is None or f["split"] == split) and (group is None or f["group"] == group)]


def image_path(fx: dict, samples_dir: Path | None = None) -> Path:
    return Path(samples_dir or SAMPLES_DIR) / fx["file"]


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w ,]", " ", (s or "").lower())).strip()


def location_of(prov: dict) -> str | None:
    """Commons 'description' of these Unsplash uploads is usually the place ("Toronto, Canada"); when it is
    just the photographer's name and a date there is no location."""
    desc = _norm(prov.get("description"))
    author = _norm(prov.get("author"))
    if not desc or (author and desc.split(" ")[0] == author.split(" ")[0]):
        return None
    if re.fullmatch(r"[\w ]*\b(19|20)\d\d\b[\w ,]*", desc) and "," not in desc:
        return None
    return desc


def city_of(location: str | None) -> str | None:
    """'Heritage Hill, Grand Rapids, United States' -> 'grand rapids'; 'Toronto, Canada' -> 'toronto'."""
    if not location:
        return None
    parts = [p.strip() for p in location.split(",") if p.strip()]
    return (parts[-2] if len(parts) >= 3 else parts[0]) or None


def is_specific_location(location: str | None) -> bool:
    """A place you could stand in (venue/street + city), not just 'City, Country'. Only a specific
    location identifies a shared shooting location; a shared city is reported as a warning."""
    if not location:
        return False
    return len([p for p in location.split(",") if p.strip()]) >= 3 or bool(re.search(r"\d", location))


def _coverage_errors(fxs: list[dict], label: str) -> list[str]:
    errs = []
    occ = {f["tags"]["occupancy"] for f in fxs}
    if occ != TAG_VALUES["occupancy"]:
        errs.append(f"{label}: needs both empty and occupied scenes (has {sorted(occ)})")
    if {f["tags"]["setting"] for f in fxs} != TAG_VALUES["setting"]:
        errs.append(f"{label}: needs both indoor and outdoor scenes")
    if not any(f["tags"]["posing_space"] in ("limited", "ambiguous") for f in fxs):
        errs.append(f"{label}: needs at least one limited or ambiguous posing space")
    if not any(f["tags"]["light"].startswith(("low", "night")) for f in fxs):
        errs.append(f"{label}: needs at least one low-light or night scene")
    if len({f["tags"]["light"] for f in fxs}) < 3:
        errs.append(f"{label}: needs at least three kinds of light")
    return errs


def validate_manifest(manifest: dict, samples_dir: Path | None = None, check_files: bool = False) -> list[str]:
    """Return a list of problems (empty = valid)."""
    errs: list[str] = []
    for k in ("dataset", "version", "groups", "splits", "fixtures"):
        if k not in manifest:
            errs.append(f"manifest: missing {k!r}")
    if errs:
        return errs
    seen: set[str] = set()
    for f in manifest["fixtures"]:
        fid = f.get("id", "?")
        where = f"fixture {fid}"
        if not _ID.match(fid):
            errs.append(f"{where}: id must be lowercase letters, digits and dashes")
        if fid in seen:
            errs.append(f"{where}: duplicate id")
        seen.add(fid)
        if f.get("group") not in GROUPS:
            errs.append(f"{where}: group must be one of {GROUPS}")
        if f.get("split") not in SPLITS:
            errs.append(f"{where}: split must be one of {SPLITS}")
        if f.get("style") not in prompts.STYLE_BRIEFS:
            errs.append(f"{where}: style must be one of {tuple(prompts.STYLE_BRIEFS)}")
        if not f.get("file"):
            errs.append(f"{where}: missing file")
        tags = f.get("tags") or {}
        for k, allowed in TAG_VALUES.items():
            if tags.get(k) not in allowed:
                errs.append(f"{where}: tags.{k} must be one of {sorted(allowed)}")
        if not tags.get("light"):
            errs.append(f"{where}: tags.light is required")
        a = f.get("annotations") or {}
        if not a.get("primary"):
            errs.append(f"{where}: annotations.primary is empty")
        objs = a.get("objects") or []
        if len(objs) < 3 or any(not isinstance(g, list) or not g for g in objs):
            errs.append(f"{where}: annotations.objects needs at least 3 non-empty synonym groups")
        if tags.get("occupancy") == "empty" and "person" not in a.get("absent", []):
            errs.append(f"{where}: an empty scene must list 'person' in annotations.absent")
        for pat in a.get("unsafe_terms", []):
            try:
                re.compile(pat)
            except re.error as exc:
                errs.append(f"{where}: bad unsafe_terms regex {pat!r}: {exc}")
        errs += _provenance_errors(f.get("provenance") or {}, where)
        if check_files:
            p = image_path(f, samples_dir)
            if not p.is_file():
                errs.append(f"{where}: image missing at {p} (run `photo-ai scene-eval fetch`)")
            elif f.get("sha256") and file_sha256(p) != f["sha256"]:
                errs.append(f"{where}: sha256 mismatch for {p}; the image changed since the set was frozen")
    for split in SPLITS:
        for group in GROUPS:
            fxs = fixtures(manifest, split, group)
            if split == "heldout":
                errs += _coverage_errors(fxs, f"heldout/{group}")
            elif not fxs:
                errs.append(f"dev/{group}: needs at least one fixture")
    errs += _split_hygiene_errors(manifest)
    return errs


def _provenance_errors(prov: dict, where: str) -> list[str]:
    src = prov.get("source")
    if src not in SOURCES:
        return [f"{where}: provenance.source must be one of {sorted(SOURCES)}"]
    if src == "wikimedia_commons":
        missing = [k for k in ("title", "page_url", "license", "author") if not prov.get(k)]
        errs = [f"{where}: provenance.{k} is required" for k in missing]
        if prov.get("license") and not _FREE.match(prov["license"]):
            errs.append(f"{where}: licence {prov['license']!r} is not a free licence")
        return errs
    consent = prov.get("consent") or {}
    errs = [f"{where}: private_album photos need consent.{k}" for k in ("owner", "date", "scope") if not consent.get(k)]
    if consent.get("scope") and "evaluation" not in consent["scope"]:
        errs.append(f"{where}: consent.scope must include 'evaluation'")
    return errs


def _split_hygiene_errors(manifest: dict) -> list[str]:
    """dev and held-out must not share a photographer (shoot) or a location."""
    errs = []
    by = {s: fixtures(manifest, s) for s in SPLITS}
    dev_authors = {_norm(f["provenance"].get("author")): f["id"] for f in by["dev"] if f["provenance"].get("author")}
    dev_locs = {location_of(f["provenance"]): f["id"] for f in by["dev"] if is_specific_location(location_of(f["provenance"]))}
    for f in by["heldout"]:
        a, loc = _norm(f["provenance"].get("author")), location_of(f["provenance"])
        if a and a in dev_authors:
            errs.append(f"fixture {f['id']}: same photographer as dev fixture {dev_authors[a]}")
        if loc and loc in dev_locs:
            errs.append(f"fixture {f['id']}: same location as dev fixture {dev_locs[loc]}")
    return errs


# --- fetch ----------------------------------------------------------------------------------------

def fetch(manifest_path: Path | None = None, samples_dir: Path | None = None, lock: bool = False,
          log=print, pause_s: float = 0.5, download=None) -> dict:
    """Download missing images; verify sha256. `lock=True` records sha256 + dHash into the manifest
    (only for fixtures that have none yet; a mismatch is always an error)."""
    from .training.pool import FINE_SIZE, dhash

    path = Path(manifest_path or MANIFEST)
    manifest = load_manifest(path)
    root = Path(samples_dir or SAMPLES_DIR)
    root.mkdir(parents=True, exist_ok=True)
    if download is None:
        from .commons import _get as download
    changed, problems = False, []
    for f in manifest["fixtures"]:
        dest = root / f["file"]
        if not dest.exists():
            if f["provenance"]["source"] != "wikimedia_commons":
                problems.append(f"{f['id']}: private-album image must be placed at {dest} by hand")
                continue
            dest.write_bytes(download(f["provenance"]["download_url"]))
            log(f"fetched {f['id']}")
            time.sleep(pause_s)
        sha = file_sha256(dest)
        if f.get("sha256") and f["sha256"] != sha:
            problems.append(f"{f['id']}: sha256 mismatch (expected {f['sha256'][:12]}, got {sha[:12]})")
        elif not f.get("sha256") and lock:
            f["sha256"] = sha
            f["dhash"] = f"{dhash(dest):016x}"
            f["dhash_fine"] = f"{dhash(dest, FINE_SIZE):064x}"
            changed = True
    if changed:
        path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    return {"fixtures": len(manifest["fixtures"]), "locked": changed, "problems": problems}


# --- overlap audit --------------------------------------------------------------------------------

def training_reference(pool_path: Path) -> dict:
    """The LoRA training pool (data/<dataset>/pool.json): every searched image counts for title, photographer
    and location; downloaded ones also for near-duplicate pixels."""
    pool_path = Path(pool_path)
    pool = json.loads(pool_path.read_text())
    repo_root = pool_path.resolve().parents[3]  # <repo>/photography-ai/data/<dataset>/pool.json
    items = []
    for it in pool["images"]:
        p = repo_root / it["file"] if it.get("file") else None
        items.append({"ref": it["id"], "title": it["title"], "author": it.get("author"),
                      "description": it.get("description"), "sha1_original": it.get("sha1_original"),
                      "path": p if p and p.is_file() else None})
    return {"name": pool.get("dataset", pool_path.parent.name), "kind": "training", "items": items}


def manifest_reference(manifest_path: Path, samples_root: Path | None = None) -> dict:
    """A held-out evaluation manifest (e.g. portrait_v1). Overlap with it is reported, not a failure."""
    man = json.loads(Path(manifest_path).read_text())
    root = Path(samples_root or PROJECT_ROOT / "samples" / man["dataset"])
    items = [{"ref": i["file"], "title": i["title"], "author": i.get("author"), "description": i.get("description"),
              "sha1_original": i.get("sha1_original"), "path": (root / i["file"]) if (root / i["file"]).is_file() else None}
             for s in man["scenarios"] for i in s["images"]]
    return {"name": man["dataset"], "kind": "evaluation", "items": items}


def audit_overlap(manifest: dict, references: list[dict], samples_dir: Path | None = None,
                  coarse_threshold: int = 6) -> dict:
    """Per fixture and reference: same Commons title, same original file (sha1), same photographer
    (the best available proxy for 'same shoot'), same location string, same city, and near-duplicate
    pixels (two-stage dHash, as for the training pool). Training overlaps on anything but city fail."""
    from .training.pool import FINE_SIZE, dhash, is_near_duplicate

    hashes: dict[str, tuple[int, int]] = {}

    def h(path: Path) -> tuple[int, int]:
        key = str(path)
        if key not in hashes:
            hashes[key] = (dhash(path), dhash(path, FINE_SIZE))
        return hashes[key]

    out = {"dataset": manifest["dataset"], "version": manifest["version"], "references": [], "fixtures": []}
    for ref in references:
        out["references"].append({"name": ref["name"], "kind": ref["kind"], "items": len(ref["items"]),
                                  "with_pixels": sum(1 for i in ref["items"] if i["path"])})
    fx_paths = {f["id"]: image_path(f, samples_dir) for f in manifest["fixtures"]}
    for f in manifest["fixtures"]:
        prov = f["provenance"]
        loc, author = location_of(prov), _norm(prov.get("author"))
        fpath = fx_paths[f["id"]] if fx_paths[f["id"]].is_file() else None
        row = {"id": f["id"], "split": f["split"], "group": f["group"], "location": loc,
               "pixels_checked": bool(fpath), "hits": [], "warnings": []}
        for ref in references:
            for it in ref["items"]:
                why = []
                if it["title"] == prov.get("title"):
                    why.append("same_title")
                if prov.get("sha1_original") and it.get("sha1_original") == prov["sha1_original"]:
                    why.append("same_file")
                if author and _norm(it.get("author")) == author:
                    why.append("same_photographer")
                iloc = location_of(it)
                if loc and iloc == loc and is_specific_location(loc):
                    why.append("same_location")
                if fpath and it["path"]:
                    (a1, a2), (b1, b2) = h(fpath), h(it["path"])
                    if is_near_duplicate(a1, b1, a2, b2, coarse_threshold):
                        why.append("near_duplicate")
                if why:
                    row["hits"].append({"reference": ref["name"], "kind": ref["kind"], "item": it["ref"],
                                        "title": it["title"], "why": why})
                elif loc and iloc and city_of(loc) == city_of(iloc):
                    row["warnings"].append({"reference": ref["name"], "item": it["ref"], "why": "same_city",
                                            "city": city_of(loc)})
        # inside the set itself: near-duplicate fixtures
        for g in manifest["fixtures"]:
            if g["id"] <= f["id"] or not fpath or not fx_paths[g["id"]].is_file():
                continue
            (a1, a2), (b1, b2) = h(fpath), h(fx_paths[g["id"]])
            if is_near_duplicate(a1, b1, a2, b2, coarse_threshold):
                row["hits"].append({"reference": manifest["dataset"], "kind": "self", "item": g["id"],
                                    "title": g["provenance"].get("title"), "why": ["near_duplicate"]})
        bad = [x for x in row["hits"] if x["kind"] in ("training", "self")]
        row["status"] = "fail" if bad else ("warn" if row["hits"] or row["warnings"] else "ok")
        out["fixtures"].append(row)
    out["summary"] = {
        "fixtures": len(out["fixtures"]),
        "fail": sum(r["status"] == "fail" for r in out["fixtures"]),
        "warn": sum(r["status"] == "warn" for r in out["fixtures"]),
        "pixels_checked": sum(r["pixels_checked"] for r in out["fixtures"]),
    }
    return out


def overlap_markdown(audit: dict) -> str:
    s = audit["summary"]
    lines = [f"# Overlap audit: {audit['dataset']} v{audit['version']}", "",
             f"{s['fixtures']} fixtures, {s['pixels_checked']} with pixels checked. "
             f"**{s['fail']} fail**, {s['warn']} warn.", "", "| reference | kind | items | with pixels |", "|---|---|---|---|"]
    lines += [f"| {r['name']} | {r['kind']} | {r['items']} | {r['with_pixels']} |" for r in audit["references"]]
    lines += ["", "| fixture | split | status | hits | warnings |", "|---|---|---|---|---|"]
    for r in audit["fixtures"]:
        hits = "; ".join(f"{h['reference']}:{h['item']} ({', '.join(h['why'])})" for h in r["hits"]) or "—"
        warns = "; ".join(f"{w['reference']} same city {w['city']}" for w in r["warnings"][:3]) or "—"
        if len(r["warnings"]) > 3:
            warns += f" (+{len(r['warnings']) - 3})"
        lines.append(f"| {r['id']} | {r['split']} | {r['status']} | {hits} | {warns} |")
    return "\n".join(lines) + "\n"


# --- automated checks -----------------------------------------------------------------------------

def fixture_case(fx: dict, samples_dir: Path | None = None) -> Case:
    a = fx["annotations"]
    return Case(id=fx["id"], description=fx.get("scene_note", ""), subject=prompts.DEFAULT_SUBJECT,
                inspiration=[], target=CaseImage(str(image_path(fx, samples_dir)), a["primary"], a["objects"]),
                leak_terms=[], suite=DATASET, category=fx["group"], target_absent=a["absent"])


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.;!?\n])\s*", text) if s.strip()]


def unsafe_hits(text: str, extra_patterns: list[str]) -> list[str]:
    """Unsafe wording in a direction text: the shared pattern plus the fixture's own hazards.
    Sentences that warn against the hazard are skipped."""
    hits = []
    pats = [metrics._UNSAFE, *(re.compile(p) for p in extra_patterns)]
    for s in _sentences(text.lower()):
        if _SAFETY_ADVICE.search(s):
            continue
        hits += [m.group(0) for p in pats for m in p.finditer(s)]
    return hits


def auto_checks(fx: dict, record: dict) -> dict:
    """Automated checks for one run (see criteria.json 'automated'). Flags are failures until a human
    marks them false positives."""
    result = record.get("result") or record.get("partial_result") or {}
    comps = result.get("compositions") or []
    ts = result.get("target_scene") or {}
    a = fx["annotations"]
    flags = []
    claimed = "\n".join([str(ts.get("description", "")), *[str(x) for x in ts.get("key_elements", [])],
                         str(ts.get("people_in_frame", ""))])
    for term in metrics.present_mentions(claimed, a["absent"]):
        flags.append({"type": "invented_scene_detail", "look": None, "term": term, "where": "scene reading"})
    for i, c in enumerate(comps, 1):
        ev = "\n".join(str(e) for e in c.get("visible_evidence", []))
        for term in metrics.present_mentions(ev, a["absent"]):
            flags.append({"type": "invented_scene_detail", "look": i, "term": term, "where": "visible_evidence"})
        text = "\n".join(metrics.composition_text({k: c.get(k) for k in DIRECTION_TEXT_FIELDS if c.get(k)}).split("\n"))
        for hit in unsafe_hits(text, a.get("unsafe_terms", [])):
            flags.append({"type": "unsafe_direction", "look": i, "term": hit, "where": "directions"})
        for m in metrics._EMOTION_INFERENCE.finditer(metrics.composition_text(c).lower()):
            flags.append({"type": "emotion_inference", "look": i, "term": m.group(0), "where": "look"})
    for m in metrics._EMOTION_INFERENCE.finditer(str(ts.get("people_in_frame", "")).lower()):
        flags.append({"type": "emotion_inference", "look": None, "term": m.group(0), "where": "people_in_frame"})
    am = record.get("auto_metrics") or {}
    div = metrics.diversity(comps) if len(comps) >= 2 else {}
    titles = {metrics._normalize(str(c.get("title", ""))) for c in comps}
    filled = {f: sum(bool(c.get(f)) for c in comps) for f in ("body_pose", "head_direction", "gaze", "expression_cue")}
    return {
        "fixture": fx["id"], "group": fx["group"], "split": fx["split"], "style": fx["style"],
        "tags": fx["tags"], "run_id": record["run_id"],
        "schema_valid": bool(record["validation"]["ok"]), "errors": record["validation"]["errors"],
        "n_looks": len(comps),
        "flags": flags,
        "direction_complete": len(comps) == 3 and all(filled[f] == 3 for f in ("body_pose", "head_direction", "gaze")),
        "fields_filled": filled,
        "gaze_specific": sum(bool(metrics._GAZE_TARGET.search(str(c.get("gaze", "")).lower())) for c in comps),
        "distinct_fields": div.get("field_distinct"),
        "distinct_titles": len(titles - {""}),
        "scene_recall": (am.get("target_recall") or {}).get("object_recall"),
        "evidence_grounded_rate": am.get("evidence_grounded_rate"),
        "people_in_frame": ts.get("people_in_frame"),
        "inference_s": record["timing"]["inference_s"],
        "peak_memory_gb": record["timing"]["peak_memory_gb"],
        "generation_tokens": record["timing"]["generation_tokens"],
        "model_calls": record["timing"]["model_calls"],
    }


# --- run --------------------------------------------------------------------------------------------

def model_revision(repo_id: str) -> dict:
    """The exact weights used: the Hugging Face cache commit for a hub model, or the local path."""
    p = Path(repo_id).expanduser()
    if p.exists():
        cfg = p / "config.json"
        return {"local_path": str(p), "config_sha256": file_sha256(cfg) if cfg.exists() else None}
    try:
        from huggingface_hub import scan_cache_dir

        for repo in scan_cache_dir().repos:
            if repo.repo_id == repo_id and repo.repo_type == "model":
                revs = sorted(repo.revisions, key=lambda r: r.last_modified, reverse=True)
                main = next((r for r in revs if "main" in r.refs), revs[0] if revs else None)
                if main:
                    return {"hf_commit": main.commit_hash, "refs": sorted(main.refs), "size_gb": round(main.size_on_disk / 1e9, 2)}
    except Exception as exc:  # noqa: BLE001 - informational
        return {"error": repr(exc)}
    return {"hf_commit": None}


def git_state() -> dict:
    def g(*args: str) -> str | None:
        try:
            return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:  # noqa: BLE001
            return None
    return {"commit": g("rev-parse", "HEAD"), "branch": g("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty_files": [ln[3:] for ln in (g("status", "--porcelain", "--", "photography-ai") or "").splitlines()]}


def eval_dir(runs_dir: Path, eval_id: str) -> Path:
    return Path(runs_dir) / "scene-eval" / eval_id


def run_eval(split: str, model: str, runs_dir: Path, eval_id: str | None = None, manifest_path: Path | None = None,
             samples_dir: Path | None = None, only: list[str] | None = None, backend=None, log=print) -> dict:
    manifest_path = Path(manifest_path or MANIFEST)
    manifest = load_manifest(manifest_path)
    problems = validate_manifest(manifest, samples_dir, check_files=True)
    if problems:
        raise ValueError("manifest problems:\n  " + "\n  ".join(problems))
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}")
    fxs = [f for f in fixtures(manifest, split) if not only or f["id"] in only]
    eval_id = eval_id or f"{split}-{datetime.now():%Y%m%d-%H%M%S}"
    out = eval_dir(runs_dir, eval_id)
    if (out / "eval.json").exists():
        raise FileExistsError(f"{out}/eval.json exists; pick another --eval-id")
    out.mkdir(parents=True, exist_ok=True)
    backend = backend or make_backend(model)
    load_s = backend.load()
    log(f"loaded {backend.spec.key} in {load_s:.1f}s; {len(fxs)} {split} fixtures")
    rows = []
    for fx in fxs:
        cfg = RunConfig(mode="scene", style=fx["style"], max_side=SETTINGS["max_side"], max_tokens=SETTINGS["max_tokens"],
                        temperature=SETTINGS["temperature"], repetition_penalty=SETTINGS["repetition_penalty"],
                        seed=SETTINGS["seed"], json_retries=SETTINGS["json_retries"], json_format=SETTINGS["json_format"])
        rec = analyze(backend, [], str(image_path(fx, samples_dir)), cfg, runs_dir, label=f"scene-eval:{eval_id}",
                      case=fixture_case(fx, samples_dir))
        row = auto_checks(fx, rec)
        rows.append(row)
        log(f"{fx['id']:28} {fx['group']:12} valid={row['schema_valid']!s:5} flags={len(row['flags'])} "
            f"{row['inference_s']:5.1f}s")
    backend.unload()
    criteria_path = CRITERIA
    doc = {
        "eval_id": eval_id, "created_at": datetime.now().isoformat(timespec="seconds"),
        "director": "scene", "split": split, "only": only or None,
        "dataset": manifest["dataset"], "dataset_version": manifest["version"],
        "manifest_sha256": file_sha256(manifest_path),
        "criteria_version": load_criteria(criteria_path)["criteria_version"],
        "criteria_sha256": file_sha256(criteria_path),
        "model": {"key": backend.spec.key, "repo_id": backend.spec.repo_id, "adapter_path": backend.spec.adapter_path,
                  "revision": model_revision(backend.spec.repo_id) if backend.spec.backend == "mlx" else None},
        "model_load_s": round(load_s, 2),
        "prompt_version": prompts.version_for("scene", "v2"),
        "prompts_sha256": file_sha256(Path(prompts.__file__)),
        "settings": SETTINGS,
        "run_config_example": asdict(RunConfig(mode="scene", **{k: v for k, v in SETTINGS.items()})),
        "environment": {"python": platform.python_version(), "platform": platform.platform(), **backend.runtime_info()},
        "git": git_state(),
        "rerun_command": (f"cd photography-ai && uv run photo-ai scene-eval run --split {split} --model {model}"
                          + (f" --only {' '.join(only)}" if only else "") + " --eval-id <new id>"),
        "rows": rows,
    }
    (out / "eval.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    (out / "report.md").write_text(report_markdown(doc))
    if split == "heldout":  # every look at the held-out split is logged, so repeated peeking is visible
        with open(Path(runs_dir) / "scene-eval" / "heldout_ledger.jsonl", "a") as fh:
            fh.write(json.dumps({"eval_id": eval_id, "created_at": doc["created_at"], "model": doc["model"]["key"],
                                 "prompt_version": doc["prompt_version"], "prompts_sha256": doc["prompts_sha256"],
                                 "manifest_sha256": doc["manifest_sha256"]}) + "\n")
    return doc


def load_eval(runs_dir: Path, eval_id: str) -> dict:
    return json.loads((eval_dir(runs_dir, eval_id) / "eval.json").read_text())


# --- report -----------------------------------------------------------------------------------------

FLAG_TYPES = ("invented_scene_detail", "unsafe_direction", "emotion_inference")


def _mean(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    valid = [r for r in rows if r["schema_valid"]]
    s = {"fixtures": n, "schema_valid": len(valid)}
    for t in FLAG_TYPES:
        s[f"runs_flagged_{t}"] = sum(any(f["type"] == t for f in r["flags"]) for r in rows)
    s["runs_with_any_flag"] = sum(bool(r["flags"]) for r in rows)
    s["direction_complete"] = sum(r["direction_complete"] for r in valid)
    s["gaze_specific_mean"] = _mean([r["gaze_specific"] for r in valid])
    s["distinct_fields_mean"] = _mean([r["distinct_fields"] for r in valid])
    s["distinct_titles_mean"] = _mean([r["distinct_titles"] for r in valid])
    s["scene_recall_mean"] = _mean([r["scene_recall"] for r in rows])
    s["evidence_grounded_mean"] = _mean([r["evidence_grounded_rate"] for r in valid])
    s["inference_s_mean"] = _mean([r["inference_s"] for r in rows])
    s["peak_memory_gb_max"] = max((r["peak_memory_gb"] or 0 for r in rows), default=None)
    return s


def _fmt(v, nd=2) -> str:
    if v is None:
        return "—"
    return f"{v:.{nd}f}" if isinstance(v, float) else str(v)


def _summary_table(by: dict[str, dict]) -> list[str]:
    keys = list(by)
    rows = [("schema-valid runs", lambda s: f"{s['schema_valid']}/{s['fixtures']}"),
            ("runs flagged: invented scene detail", lambda s: f"{s['runs_flagged_invented_scene_detail']}/{s['fixtures']}"),
            ("runs flagged: unsafe direction", lambda s: f"{s['runs_flagged_unsafe_direction']}/{s['fixtures']}"),
            ("runs flagged: emotion inference", lambda s: f"{s['runs_flagged_emotion_inference']}/{s['fixtures']}"),
            ("pose/head/gaze filled on all 3 looks", lambda s: f"{s['direction_complete']}/{s['schema_valid']}"),
            ("gaze names a target (mean of 3)", lambda s: _fmt(s["gaze_specific_mean"])),
            ("look distinctness, fields (0-1)", lambda s: _fmt(s["distinct_fields_mean"])),
            ("distinct titles (mean of 3)", lambda s: _fmt(s["distinct_titles_mean"])),
            ("scene recall (annotated objects named)", lambda s: _fmt(s["scene_recall_mean"])),
            ("evidence grounded rate", lambda s: _fmt(s["evidence_grounded_mean"])),
            ("seconds per scene (mean)", lambda s: _fmt(s["inference_s_mean"], 1)),
            ("peak memory GB (max)", lambda s: _fmt(s["peak_memory_gb_max"]))]
    out = ["| automated measure | " + " | ".join(keys) + " |", "|---|" + "---|" * len(keys)]
    out += [f"| {name} | " + " | ".join(f(by[k]) for k in keys) + " |" for name, f in rows]
    return out


def report_markdown(doc: dict) -> str:
    rows = doc["rows"]
    by = {g: summarize([r for r in rows if r["group"] == g]) for g in GROUPS if any(r["group"] == g for r in rows)}
    by["all"] = summarize(rows)
    rev = (doc["model"].get("revision") or {})
    lines = [
        f"# Scene Director evaluation `{doc['eval_id']}` ({doc['split']} split)", "",
        "Automated checks only. Quality (grounding, style fit, practicality, safety) is decided by the blind human "
        "review; see `photo-ai scene-eval pack`.", "",
        "| | |", "|---|---|",
        f"| director | {doc['director']} (Scene Director only; Inspiration Director results are reported elsewhere) |",
        f"| model | `{doc['model']['key']}` (`{doc['model']['repo_id']}`"
        + (f", adapter `{doc['model']['adapter_path']}`" if doc["model"].get("adapter_path") else "") + ") |",
        f"| model revision | `{rev.get('hf_commit') or rev.get('local_path') or '—'}` |",
        f"| prompt version | `{doc['prompt_version']}` (prompts.py sha256 `{doc['prompts_sha256'][:12]}`) |",
        f"| settings | {', '.join(f'{k}={v}' for k, v in doc['settings'].items())} |",
        f"| fixtures | `{doc['dataset']}` v{doc['dataset_version']} (manifest sha256 `{doc['manifest_sha256'][:12]}`), "
        f"{len(rows)} {doc['split']} fixtures |",
        f"| criteria | `{doc['criteria_version']}` (sha256 `{doc['criteria_sha256'][:12]}`) |",
        f"| code | `{(doc['git'].get('commit') or '?')[:12]}` on `{doc['git'].get('branch')}`"
        + (f", {len(doc['git']['dirty_files'])} uncommitted file(s)" if doc["git"].get("dirty_files") else "") + " |",
        f"| machine | {doc['environment'].get('device_name') or doc['environment'].get('platform')}, "
        f"mlx-vlm {doc['environment'].get('mlx_vlm') or '—'} |",
        f"| rerun | `{doc['rerun_command']}` |", "",
        "## By background group", "",
        *_summary_table(by), "",
        "Groups are reported separately; `all` is shown last and is not a headline number.", "",
    ]
    for g in GROUPS:
        grows = [r for r in rows if r["group"] == g]
        if not grows:
            continue
        lines += [f"## {g}", "", "| fixture | style | space | occupancy | light | valid | flags | gaze /3 | distinct | titles | recall | s |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in grows:
            flags = ", ".join(f"{f['type'].split('_')[0]}{'@' + str(f['look']) if f['look'] else ''}: {f['term']}"
                              for f in r["flags"]) or "—"
            lines.append(f"| {r['fixture']} | {prompts.style_label(r['style'])} | {r['tags']['posing_space']} | "
                         f"{r['tags']['occupancy']} | {r['tags']['light']} | {'yes' if r['schema_valid'] else '**NO**'} | "
                         f"{flags} | {r['gaze_specific']} | {_fmt(r['distinct_fields'])} | {r['distinct_titles']} | "
                         f"{_fmt(r['scene_recall'])} | {_fmt(r['inference_s'], 1)} |")
        lines.append("")
    invalid = [r for r in rows if not r["schema_valid"]]
    if invalid:
        lines += ["## Schema failures", ""] + [f"- `{r['fixture']}`: {'; '.join(r['errors'])[:300]}" for r in invalid] + [""]
    return "\n".join(lines)
