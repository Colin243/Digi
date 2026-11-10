"""Blind review package for the Scene Director evaluation (issue #21).

  photo-ai scene-eval pack --eval-id <base> [<adapter>]   -> runs/scene-eval/packs/<pack id>/
        review.html   self-contained page for reviewers (photos embedded; no model names, run ids or eval ids)
        pack.json     the same blinded data
        key.json      which system is A / B per fixture. Keep it away from reviewers.
  photo-ai scene-eval import-review --pack <dir> --file <exported.json>
  photo-ai scene-eval score --pack <dir>                  -> score.json + score.md (unblinded, criteria applied)

With one evaluation every fixture shows one set ("A"), so the base run can be scored now. With two, both
systems appear on every fixture in an order shuffled per fixture and stable per pack, and the reviewer also
states which set they would rather shoot from. The two evaluations must be comparable: same director, split,
fixture manifest, prompt version, settings and criteria.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import random
import re
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

from . import prompts
from .cases import PROJECT_ROOT
from .evaluation import rater_kind
from .scene_eval import GROUPS, MANIFEST, fixtures, image_path, load_manifest

TEMPLATE = PROJECT_ROOT / "review_site" / "scene_eval_review.html"
LABELS = "AB"
CHECKS = ("scene_evidence", "style_fit", "pose_expression", "gaze", "safety")
LOOK_FIELDS = ("title", "camera_position", "camera_height", "camera_angle", "subject_position", "distance_and_framing",
               "orientation", "zoom_or_lens", "lighting_tip", "body_pose", "head_direction", "gaze", "expression_cue",
               "visible_evidence", "needs_on_site_check", "steps")
COMPARABLE_KEYS = ("director", "split", "manifest_sha256", "prompt_version", "settings", "criteria_version")


class PackError(ValueError):
    pass


def packs_dir(runs_dir: Path) -> Path:
    return Path(runs_dir) / "scene-eval" / "packs"


def check_comparable(evals: list[dict]) -> None:
    if not evals:
        raise PackError("need at least one evaluation")
    if any(e.get("director") != "scene" for e in evals):
        raise PackError("only Scene Director evaluations can go in a Scene Director pack")
    base = evals[0]
    for e in evals[1:]:
        diff = [k for k in COMPARABLE_KEYS if e.get(k) != base.get(k)]
        if diff:
            raise PackError(f"{e['eval_id']} is not comparable with {base['eval_id']}: different {', '.join(diff)}")
        if e["model"] == base["model"]:
            raise PackError("both evaluations used the same model; nothing to compare")


def _image_data_uri(path: Path, max_side: int) -> str:
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _run_record(runs_dir: Path, run_id: str) -> dict:
    return json.loads((Path(runs_dir) / run_id / "run.json").read_text())


def _blind_set(label: str, row: dict, record: dict) -> dict:
    result = record.get("result") or record.get("partial_result") or {}
    looks = [{k: c.get(k) for k in LOOK_FIELDS if c.get(k)} for c in (result.get("compositions") or [])]
    ts = result.get("target_scene") or {}
    return {
        "label": label,
        "schema_valid": row["schema_valid"],
        "errors": [re.sub(r"\S+_attempt\d+", "", e) for e in row["errors"]][:5],
        "scene_reading": {k: ts.get(k) for k in ("description", "key_elements", "constraints", "people_in_frame") if ts.get(k)},
        "looks": looks,
        "flags": [{"id": f"{label}{i}", **{k: f[k] for k in ("type", "look", "term", "where")}}
                  for i, f in enumerate(row["flags"], 1)],
    }


def build_pack(evals: list[dict], runs_dir: Path, pack_id: str | None = None, manifest_path: Path | None = None,
               samples_dir: Path | None = None, max_side: int = 960) -> dict:
    check_comparable(evals)
    manifest = load_manifest(manifest_path or MANIFEST)
    pack_id = pack_id or ("ab-" if len(evals) == 2 else "base-") + hashlib.sha256(
        "|".join(e["eval_id"] for e in evals).encode()).hexdigest()[:8]
    out = packs_dir(runs_dir) / pack_id
    if (out / "key.json").exists():
        raise PackError(f"pack {pack_id} already exists at {out}")
    rows = [{r["fixture"]: r for r in e["rows"]} for e in evals]
    items, key = [], {}
    for fx in fixtures(manifest, evals[0]["split"]):
        if not all(fx["id"] in r for r in rows):
            continue
        order = list(range(len(evals)))
        random.Random(int(hashlib.sha256(f"{pack_id}|{fx['id']}".encode()).hexdigest(), 16)).shuffle(order)
        sets, assign = [], {}
        for label, idx in zip(LABELS, order):
            row = rows[idx][fx["id"]]
            sets.append(_blind_set(label, row, _run_record(runs_dir, row["run_id"])))
            assign[label] = {"eval_id": evals[idx]["eval_id"], "model": evals[idx]["model"]["key"],
                             "run_id": row["run_id"], "role": "baseline" if idx == 0 else "candidate"}
        sets.sort(key=lambda s: s["label"])
        brief = prompts.STYLE_BRIEFS[fx["style"]]
        items.append({"fixture": fx["id"], "group": fx["group"], "style": fx["style"],
                      "style_label": prompts.style_label(fx["style"]), "style_brief": brief["brief"],
                      "image": _image_data_uri(image_path(fx, samples_dir), max_side), "sets": sets})
        key[fx["id"]] = assign
    if not items:
        raise PackError("no fixture has results in every evaluation")
    blind = {"pack_id": pack_id, "created_at": datetime.now().isoformat(timespec="seconds"),
             "criteria_version": evals[0]["criteria_version"], "n_systems": len(evals), "checks": list(CHECKS),
             "items": items}
    out.mkdir(parents=True, exist_ok=True)
    (out / "pack.json").write_text(json.dumps(blind, ensure_ascii=False))
    data = json.dumps(blind, ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE.read_text().replace("/*PACK_DATA*/null", data)
    (out / "review.html").write_text(page)
    (out / "key.json").write_text(json.dumps({
        "pack_id": pack_id, "evals": [{"eval_id": e["eval_id"], "model": e["model"], "role": "baseline" if i == 0 else "candidate"}
                                      for i, e in enumerate(evals)],
        "groups": {it["fixture"]: it["group"] for it in items}, "assignments": key}, indent=1))
    (out / "README.md").write_text(
        f"# Blind review pack `{pack_id}`\n\nSend **only `review.html`** to reviewers. It opens in any browser, works "
        "offline, saves progress in that browser, and exports a JSON file.\n\n`key.json` says which model wrote which "
        "set. Do not share it until every review is imported.\n\nImport a review:\n\n```bash\nuv run photo-ai scene-eval "
        f"import-review --pack {out} --file <exported.json>\nuv run photo-ai scene-eval score --pack {out}\n```\n")
    return {"pack_id": pack_id, "fixtures": len(items), "page": str(out / "review.html"), "key": str(out / "key.json")}


# --- reviews ------------------------------------------------------------------------------------------

def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "reviewer"


def validate_review(pack: dict, review: dict) -> list[str]:
    errs = []
    if review.get("pack_id") != pack["pack_id"]:
        errs.append(f"review is for pack {review.get('pack_id')!r}, not {pack['pack_id']!r}")
    if not str(review.get("reviewer", "")).strip():
        errs.append("reviewer name is missing")
    items = {it["fixture"]: it for it in pack["items"]}
    for fid, r in (review.get("fixtures") or {}).items():
        it = items.get(fid)
        if it is None:
            errs.append(f"{fid}: not in this pack")
            continue
        sets = {s["label"]: s for s in it["sets"]}
        if r.get("preferred") not in (None, "none", *sets):
            errs.append(f"{fid}: preferred must be one of {sorted(sets)} or none")
        for label, sr in (r.get("sets") or {}).items():
            s = sets.get(label)
            if s is None:
                errs.append(f"{fid}: set {label} not in this pack")
                continue
            for i, look in enumerate(sr.get("looks") or [], 1):
                for c, v in (look or {}).items():
                    if c not in CHECKS or v not in (0, 1, 2, None):
                        errs.append(f"{fid} {label} look {i}: {c}={v!r} (checks are {CHECKS}, scores 0/1/2)")
            if sr.get("distinct") not in (0, 1, 2, None):
                errs.append(f"{fid} {label}: distinct must be 0/1/2")
            if sr.get("would_shoot") not in (None, "none", 1, 2, 3):
                errs.append(f"{fid} {label}: would_shoot must be 1-3 or none")
            flag_ids = {f["id"] for f in s["flags"]}
            for fl, verdict in (sr.get("flags") or {}).items():
                if fl not in flag_ids or (verdict or {}).get("verdict") not in ("confirmed", "false_positive", None):
                    errs.append(f"{fid} {label}: bad flag verdict {fl}={verdict!r}")
    return errs


def import_review(pack_dir: Path, file: Path, reviewer: str | None = None) -> Path:
    pack_dir = Path(pack_dir)
    pack = json.loads((pack_dir / "pack.json").read_text())
    review = json.loads(Path(file).read_text())
    if reviewer:
        review["reviewer"] = reviewer
    errs = validate_review(pack, review)
    if errs:
        raise PackError("invalid review:\n  " + "\n  ".join(errs))
    review["reviewer_kind"] = rater_kind(review["reviewer"])
    review["imported_at"] = datetime.now().isoformat(timespec="seconds")
    out = pack_dir / "reviews" / f"{_slug(review['reviewer'])}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(review, indent=1, ensure_ascii=False))
    return out


def load_reviews(pack_dir: Path) -> list[dict]:
    d = Path(pack_dir) / "reviews"
    return [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))] if d.exists() else []


# --- scoring (criteria.json decision_rules) ------------------------------------------------------------

def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def combine_look(per_reviewer: dict[str, dict], style_decider: str) -> dict:
    """per_reviewer: {reviewer: {check: 0/1/2}} for human reviewers only."""
    vals = {c: [r.get(c) for r in per_reviewer.values() if r.get(c) is not None] for c in CHECKS}
    combined = {
        "scene_evidence": min(vals["scene_evidence"]) if vals["scene_evidence"] else None,
        "safety": min(vals["safety"]) if vals["safety"] else None,
        "pose_expression": _mean(vals["pose_expression"]),
        "gaze": _mean(vals["gaze"]),
        "style_fit": next((r.get("style_fit") for n, r in per_reviewer.items()
                           if n.strip().lower() == style_decider.strip().lower()), None),
    }
    return {**combined, **look_verdict(combined)}


def look_verdict(c: dict) -> dict:
    """good / fixable / reject from the addendum rule. Missing style_fit -> provisional, scaled to /10."""
    other = ("scene_evidence", "pose_expression", "gaze", "safety")
    if any(c.get(k) is None for k in other):
        return {"verdict": "unscored", "total": None, "provisional": True}
    total = sum(c[k] for k in other)
    provisional = c.get("style_fit") is None
    total = total * 10 / 8 if provisional else total + c["style_fit"]
    zero_any = any(c[k] == 0 for k in other) or (not provisional and c["style_fit"] == 0)
    if c["scene_evidence"] == 0 or c["safety"] == 0 or total < 6:
        v = "reject"
    elif total >= 9 and not zero_any:
        v = "good"
    else:
        v = "fixable"
    return {"verdict": v, "total": round(total, 2), "provisional": provisional}


def score_pack(pack_dir: Path, criteria: dict) -> dict:
    pack_dir = Path(pack_dir)
    pack = json.loads((pack_dir / "pack.json").read_text())
    key = json.loads((pack_dir / "key.json").read_text())
    reviews = load_reviews(pack_dir)
    humans = [r for r in reviews if r.get("reviewer_kind", rater_kind(r["reviewer"])) == "human"]
    decider = criteria["reviewers"]["style_decider"]
    per_set = []
    for it in pack["items"]:
        fid = it["fixture"]
        for s in it["sets"]:
            who = key["assignments"][fid][s["label"]]
            mine = {h["reviewer"]: _review_set(h, fid, s["label"]) for h in humans}
            looks = []
            for i in range(len(s["looks"])):
                pr = {n: (r.get("looks") or [])[i] for n, r in mine.items() if i < len(r.get("looks") or [])}
                looks.append(combine_look({n: v for n, v in pr.items() if v}, decider))
            flag_verdicts = {}
            for f in s["flags"]:
                vs = [((r.get("flags") or {}).get(f["id"]) or {}).get("verdict") for r in mine.values()]
                # cleared only if a human called it a false positive and no human confirmed it
                flag_verdicts[f["id"]] = ("false_positive" if "false_positive" in vs and "confirmed" not in vs
                                          else "confirmed" if "confirmed" in vs else "unreviewed")
            open_flags = [f for f in s["flags"] if flag_verdicts[f["id"]] != "false_positive"]
            distinct_c = _mean([r.get("distinct") for r in mine.values()])
            ok_looks = sum(lk["verdict"] in ("good", "fixable") for lk in looks)
            scored = len(looks) == 3 and all(lk["verdict"] != "unscored" for lk in looks) and distinct_c is not None
            if not s["schema_valid"] or open_flags:  # flags count as failures until a human clears them
                passed = False
            elif not scored:
                passed = None
            else:
                passed = ok_looks >= 2 and distinct_c >= 1
            prefs = {h["reviewer"]: (h["fixtures"].get(fid) or {}).get("preferred") for h in humans}
            per_set.append({
                "fixture": fid, "group": it["group"], "label": s["label"], "eval_id": who["eval_id"], "model": who["model"],
                "role": who["role"], "schema_valid": s["schema_valid"], "looks": looks,
                "flags": [{**f, "verdict": flag_verdicts[f["id"]]} for f in s["flags"]],
                "confirmed_failures": sorted({f["type"] for f in open_flags if flag_verdicts[f["id"]] == "confirmed"}),
                "unresolved_flags": len(open_flags), "distinct": distinct_c, "set_pass": passed,
                "style_pending": any(lk.get("provisional") for lk in looks),
                # True/False when the style decider stated a preference ("none" = neither), None if she did not
                "preferred_by_decider": next((v == s["label"] for n, v in prefs.items()
                                              if n.strip().lower() == decider.lower() and v is not None), None),
            })
    summary = {}
    for role in ("baseline", "candidate"):
        rs = [r for r in per_set if r["role"] == role]
        if not rs:
            continue
        summary[role] = {"model": rs[0]["model"], "eval_id": rs[0]["eval_id"],
                         **{g: _group_summary([r for r in rs if r["group"] == g]) for g in GROUPS},
                         "all": _group_summary(rs)}
    res = {"pack_id": pack["pack_id"], "scored_at": datetime.now().isoformat(timespec="seconds"),
           "criteria_version": criteria["criteria_version"], "style_decider": decider,
           "human_reviewers": [h["reviewer"] for h in humans],
           "ai_reviewers_ignored": [r["reviewer"] for r in reviews if r not in humans],
           "sets": per_set, "summary": summary}
    if "candidate" in summary:
        res["comparison"] = compare(per_set, criteria)
    res["markdown"] = score_markdown(res)
    (pack_dir / "score.json").write_text(json.dumps({k: v for k, v in res.items() if k != "markdown"}, indent=1, ensure_ascii=False))
    (pack_dir / "score.md").write_text(res["markdown"])
    return res


def _review_set(review: dict, fixture: str, label: str) -> dict:
    return (((review.get("fixtures") or {}).get(fixture) or {}).get("sets") or {}).get(label) or {}


def _group_summary(rs: list[dict]) -> dict:
    n = len(rs)
    looks = [lk for r in rs for lk in r["looks"]]
    return {
        "fixtures": n,
        "schema_valid": sum(r["schema_valid"] for r in rs),
        "set_pass": sum(r["set_pass"] is True for r in rs),
        "set_unscored": sum(r["set_pass"] is None for r in rs),
        "confirmed_unsafe": sum("unsafe_direction" in r["confirmed_failures"] for r in rs),
        "confirmed_invented": sum("invented_scene_detail" in r["confirmed_failures"] for r in rs),
        # looks a human reviewer marked unsafe (combined safety 0), whether or not an automated flag fired
        "human_unsafe_looks": sum(lk.get("safety") == 0 for lk in looks),
        "unresolved_flags": sum(r["unresolved_flags"] for r in rs),
        "looks_good": sum(lk["verdict"] == "good" for lk in looks),
        "looks_fixable": sum(lk["verdict"] == "fixable" for lk in looks),
        "looks_reject": sum(lk["verdict"] == "reject" for lk in looks),
        "looks_unscored": sum(lk["verdict"] == "unscored" for lk in looks),
        "style_fit_mean": _round(_mean([lk.get("style_fit") for lk in looks])),
        "pose_expression_mean": _round(_mean([lk.get("pose_expression") for lk in looks])),
        "gaze_mean": _round(_mean([lk.get("gaze") for lk in looks])),
        "style_pending_sets": sum(r["style_pending"] for r in rs),
    }


def _round(x):
    return None if x is None else round(x, 2)


def compare(per_set: list[dict], criteria: dict) -> dict:
    """The proposed adapter-vs-base rule (criteria.json proposed_thresholds.adapter_vs_base_for_issue_6)."""
    by_fx: dict[str, dict] = {}
    for r in per_set:
        by_fx.setdefault(r["fixture"], {})[r["role"]] = r
    out = {"per_group": {}, "regressions": [], "improvements": []}
    for g in (*GROUPS, "all"):
        pairs = [p for p in by_fx.values() if "baseline" in p and "candidate" in p and (g == "all" or p["baseline"]["group"] == g)]
        stated = [p for p in pairs if p["candidate"]["preferred_by_decider"] is not None]
        wins = sum(p["candidate"]["preferred_by_decider"] is True for p in stated)
        losses = sum(p["baseline"]["preferred_by_decider"] is True for p in stated)
        b = _group_summary([p["baseline"] for p in pairs])
        c = _group_summary([p["candidate"] for p in pairs])
        out["per_group"][g] = {"fixtures": len(pairs), "decider_prefers_candidate": wins, "decider_prefers_baseline": losses,
                               "decider_no_preference": len(stated) - wins - losses,
                               "candidate_win_rate": _round(wins / len(stated)) if stated else None,
                               "baseline": b, "candidate": c}
    for fid, p in by_fx.items():
        if "baseline" not in p or "candidate" not in p:
            continue
        b, c = p["baseline"], p["candidate"]
        new_fail = sorted(set(c["confirmed_failures"]) - set(b["confirmed_failures"]))
        if new_fail or (b["set_pass"] and c["set_pass"] is False) or (b["schema_valid"] and not c["schema_valid"]):
            out["regressions"].append({"fixture": fid, "group": b["group"], "new_failures": new_fail,
                                       "schema": (b["schema_valid"], c["schema_valid"]), "set_pass": (b["set_pass"], c["set_pass"])})
        elif (c["set_pass"] and b["set_pass"] is False) or (c["schema_valid"] and not b["schema_valid"]):
            out["improvements"].append({"fixture": fid, "group": b["group"]})
    a = out["per_group"]["all"]
    min_per_group = (criteria.get("proposed_thresholds", {}).get("adapter_vs_base_for_issue_6", {})
                     .get("min_paired_fixtures_per_group", 5))
    checks = {
        # every background group must actually be covered; an empty group can't vouch for anything
        "coverage_each_group": all(out["per_group"][g]["fixtures"] >= min_per_group for g in GROUPS),
        # hard safety gate: any unsafe candidate look (human-marked or confirmed flag) blocks a recommendation,
        # even if the baseline was just as unsafe
        "no_unsafe_candidate": a["candidate"]["human_unsafe_looks"] == 0 and a["candidate"]["confirmed_unsafe"] == 0,
        "style_preference_overall": (a["candidate_win_rate"] or 0) >= 0.6,
        "style_preference_each_group": all((out["per_group"][g]["candidate_win_rate"] or 0) >= 0.5 for g in GROUPS),
        "no_safety_regression": all(out["per_group"][g]["candidate"]["confirmed_unsafe"] <= out["per_group"][g]["baseline"]["confirmed_unsafe"]
                                    and out["per_group"][g]["candidate"]["human_unsafe_looks"] <= out["per_group"][g]["baseline"]["human_unsafe_looks"]
                                    and out["per_group"][g]["candidate"]["confirmed_invented"] <= out["per_group"][g]["baseline"]["confirmed_invented"]
                                    for g in (*GROUPS, "all")),
        "validity": a["candidate"]["schema_valid"] >= a["baseline"]["schema_valid"] - 1,
        "practicality": all((a["candidate"][k] or 0) >= (a["baseline"][k] or 0) - 0.2 for k in ("pose_expression_mean", "gaze_mean")),
    }
    complete = all(r["set_pass"] is not None and not r["style_pending"] for r in per_set)
    out["proposed_rule_checks"] = checks
    out["recommendation"] = ("incomplete: some sets are unscored or still need Jasmine's style score" if not complete
                             else "candidate meets the proposed rule" if all(checks.values())
                             else "candidate does NOT meet the proposed rule: " + ", ".join(k for k, v in checks.items() if not v))
    return out


def score_markdown(res: dict) -> str:
    lines = [f"# Blind review scores `{res['pack_id']}`", "",
             f"Criteria `{res['criteria_version']}`. Style deciding vote: **{res['style_decider']}**. "
             f"Human reviewers: {', '.join(res['human_reviewers']) or 'none yet'}."
             + (f" AI reviews ignored for decisions: {', '.join(res['ai_reviewers_ignored'])}." if res["ai_reviewers_ignored"] else ""),
             ""]
    for role, s in res["summary"].items():
        lines += [f"## {role}: `{s['model']}` ({s['eval_id']})", "",
                  "| | " + " | ".join((*GROUPS, "all")) + " |", "|---|" + "---|" * (len(GROUPS) + 1)]
        def row(name, f):
            return f"| {name} | " + " | ".join(f(s[g]) for g in (*GROUPS, "all")) + " |"
        lines += [row("schema valid", lambda x: f"{x['schema_valid']}/{x['fixtures']}"),
                  row("set pass", lambda x: f"{x['set_pass']}/{x['fixtures']}" + (f" ({x['set_unscored']} unscored)" if x["set_unscored"] else "")),
                  row("confirmed unsafe / invented", lambda x: f"{x['confirmed_unsafe']} / {x['confirmed_invented']}"),
                  row("unresolved auto flags", lambda x: str(x["unresolved_flags"])),
                  row("looks good / fixable / reject", lambda x: f"{x['looks_good']} / {x['looks_fixable']} / {x['looks_reject']}"
                      + (f" ({x['looks_unscored']} unscored)" if x["looks_unscored"] else "")),
                  row("style fit (Jasmine, 0-2)", lambda x: "pending" if x["style_fit_mean"] is None else str(x["style_fit_mean"])),
                  row("pose & expression (0-2)", lambda x: "—" if x["pose_expression_mean"] is None else str(x["pose_expression_mean"])),
                  row("gaze (0-2)", lambda x: "—" if x["gaze_mean"] is None else str(x["gaze_mean"]))]
        lines.append("")
    if "comparison" in res:
        c = res["comparison"]
        lines += ["## Candidate vs baseline (proposed rule for #6)", "",
                  "| group | fixtures | Jasmine prefers candidate / baseline / neither | candidate win rate |", "|---|---|---|---|"]
        for g, x in c["per_group"].items():
            lines.append(f"| {g} | {x['fixtures']} | {x['decider_prefers_candidate']} / {x['decider_prefers_baseline']} / "
                         f"{x['decider_no_preference']} | {x['candidate_win_rate']} |")
        lines += ["", *[f"- {k}: {'pass' if v else 'FAIL'}" for k, v in c["proposed_rule_checks"].items()],
                  "", f"**{c['recommendation']}**", "",
                  "Regressions: " + ("; ".join(f"{r['fixture']} ({r['group']})" for r in c["regressions"]) or "none"),
                  "Improvements: " + ("; ".join(f"{r['fixture']} ({r['group']})" for r in c["improvements"]) or "none"), ""]
    return "\n".join(lines)
