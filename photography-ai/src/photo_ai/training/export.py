"""Approved labels -> supervised fine-tuning rows, rendered with the exact inference prompts.

The deployed pipeline is the `decomposed` strategy (pipeline.py): per-image notes, target scene,
aesthetic from notes (text only), compositions. Each approved example therefore becomes four
kinds of rows, one per call the model makes at inference time:

  stage           user turn (same function as inference)       assistant turn (the label)
  notes           prompts.image_notes() + 1 inspiration photo  answer.inspiration_notes[i]
  target_scene    prompts.target_scene_only() + target photo   answer.target_scene (JSON)
  aesthetic       prompts.aesthetic_from_notes(notes)           answer.aesthetic (JSON)
  compositions    prompts.compositions_from_parts(...)+target  {"compositions": [...]} (JSON)

Prompts are rendered under the chosen json_format so training and inference text match
byte for byte. Rows: data/<dataset>/sft/{train,valid}.jsonl, each
  {"messages": [user, assistant], "images": [abs paths], "meta": {...}}
(the "messages"/"images" keys are also what `mlx_vlm.train` reads).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .. import framing, prompts
from ..backends.mlx_backend import build_messages
from ..cases import REPO_ROOT
from .assemble import load_examples
from .labels import load_labels
from .pool import data_dir, load_pool

STAGES = ("notes", "target_scene", "aesthetic", "compositions")


def _row(prompt: str, images: list[str], answer_text: str, meta: dict) -> dict:
    user = build_messages(prompt, len(images))[0]
    return {
        "messages": [user, {"role": "assistant", "content": [{"type": "text", "text": answer_text}]}],
        "images": images,
        "meta": meta,
    }


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def example_rows(example: dict, answer: dict, image_path, json_format: str = "keys",
                 stages=STAGES, shot_format: str = "v1") -> list[dict]:
    meta = {"example_id": example["example_id"], "split": example["split"]}
    rows = []
    with prompts.json_format(json_format):
        if "notes" in stages:
            for i, (pid, note) in enumerate(zip(example["inspiration"], answer["inspiration_notes"]), 1):
                rows.append(_row(prompts.image_notes(), [image_path(pid)], note, {**meta, "stage": "notes", "index": i}))
        tgt = image_path(example["target"])
        if "target_scene" in stages:
            rows.append(_row(prompts.target_scene_only(), [tgt], _j(answer["target_scene"]), {**meta, "stage": "target_scene"}))
        if "aesthetic" in stages:
            rows.append(_row(prompts.aesthetic_from_notes(answer["inspiration_notes"]), [], _j(answer["aesthetic"]),
                             {**meta, "stage": "aesthetic"}))
        if "compositions" in stages:
            p = prompts.compositions_from_parts(answer["aesthetic"], answer["target_scene"],
                                                example.get("subject", prompts.DEFAULT_SUBJECT), shot_format)
            comps = [_ordered(c, shot_format) for c in answer["compositions"]]
            if shot_format in ("v5", "v6", "v7"):
                comps = [_zoom_first(c, name_zoom=shot_format != "v6") for c in comps]
            if shot_format == "v7":
                comps = [{k: v for k, v in c.items() if k not in prompts.DROPPED_V7} for c in comps]
            rows.append(_row(p, [tgt], _j({"compositions": comps}),
                             {**meta, "stage": "compositions", "shot_format": shot_format}))
    return rows


def _ordered(comp: dict, shot_format: str) -> dict:
    """shot-v3 targets put the reasoning keys first, in prompt order, so the model learns to reason first."""
    if shot_format not in ("v3", "v4", "v5", "v6", "v7"):
        return comp
    first = [k.removesuffix("[]") for k in prompts.REASONING_FIELDS]
    return {**{k: comp[k] for k in first if k in comp}, **{k: v for k, v in comp.items() if k not in first}}


_DIST = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:(?:-|–|to)\s*\d+(?:\.\d+)?\s*)?(?:m|metres?|meters?)\b")


def distance_with_zoom(look: dict) -> str:
    """shot-v5 wording: the first distance is followed by the zoom it is for ("About 4 m at 2x; ..."). Labels that
    already name an amount in distance_and_framing, or state no distance, are returned unchanged."""
    text = look.get("distance_and_framing") or ""
    amount = framing.zoom_fit(look)["amount"]
    m = _DIST.search(text)
    if amount is None or not m or re.search(r"\d(?:\.\d+)?\s*(?:x|×)(?![a-z])", text):
        return text
    end = m.end()
    if text[end:end + 5] == " away":  # "About 2.4 m away; ..." -> "About 2.4 m away at 2x; ..."
        end += 5
    return f"{text[:end]} at {amount:g}x{text[end:]}"


def _zoom_first(comp: dict, name_zoom: bool = True) -> dict:
    """shot-v5/v6 targets: zoom_or_lens directly ahead of distance_and_framing (v5 also names the zoom in the
    distance). Key order is generation order, so the model picks the zoom before it writes the distance for it."""
    out = {}
    for k, v in comp.items():
        if k == "zoom_or_lens":
            continue
        if k == "distance_and_framing" and "zoom_or_lens" in comp:
            out["zoom_or_lens"] = comp["zoom_or_lens"]
            v = distance_with_zoom(comp) if name_zoom else v
        out[k] = v
    if "zoom_or_lens" in comp and "zoom_or_lens" not in out:
        out["zoom_or_lens"] = comp["zoom_or_lens"]
    return out


def has_reasoning(answer: dict) -> bool:
    """Every composition carries the four shot-v3 reasoning fields, non-empty."""
    keys = [k.removesuffix("[]") for k in prompts.REASONING_FIELDS]
    return all(all(c.get(k) for k in keys) for c in answer.get("compositions") or [])


def has_zoom(answer: dict) -> bool:
    """Every composition states one zoom amount within 1-2x and gives a reason (shot-v4)."""
    fits = [framing.zoom_fit(c) for c in answer.get("compositions") or []]
    return bool(fits) and all(f["in_range"] and f["reason"] for f in fits)


def export_sft(dataset: str = "train_v1", out_dir: Path | None = None, json_format: str = "keys",
               include_unapproved: bool = False, example_ids: list[str] | None = None,
               shot_format: str = "v1") -> dict:
    """shot_format "v3": the compositions rows use the reasoning prompt; labels without reasoning are skipped.
    "v4": the zoom prompt (v11); labels also need every look's zoom_or_lens in 1-2x with a reason.
    "v5": as v4 with the v12 prompt; each look's zoom_or_lens is moved ahead of distance_and_framing and the
    distance names its zoom (the labels themselves are not changed). "v6": as v5 with the distance text as labelled.
    "v7": as v5 with uses_principle left out of the targets."""
    pool = {i["id"]: i for i in load_pool(dataset)["images"]}
    examples = {e["example_id"]: e for e in load_examples(dataset)}
    labels = load_labels(dataset)
    if example_ids:
        labels = [lab for lab in labels if lab["example_id"] in example_ids]
    chosen = [lab for lab in labels if lab["status"] == "approved" or
              (include_unapproved and lab["status"] == "draft" and not lab.get("schema_errors"))]
    skipped, skipped_zoom = [], []
    if shot_format in ("v3", "v4", "v5", "v6", "v7"):
        skipped = [lab["example_id"] for lab in chosen if not has_reasoning(lab["answer"])]
        chosen = [lab for lab in chosen if lab["example_id"] not in skipped]
    if shot_format in ("v4", "v5", "v6", "v7"):
        skipped_zoom = [lab["example_id"] for lab in chosen if not has_zoom(lab["answer"])]
        chosen = [lab for lab in chosen if lab["example_id"] not in skipped_zoom]
    out_dir = Path(out_dir or data_dir(dataset) / ("sft-UNREVIEWED-smoke" if include_unapproved else "sft"))
    out_dir.mkdir(parents=True, exist_ok=True)

    def image_path(pid):
        return str((REPO_ROOT / pool[pid]["file"]).resolve())

    rows = {"train": [], "valid": []}
    for lab in chosen:
        ex = examples[lab["example_id"]]
        for r in example_rows(ex, lab["answer"], image_path, json_format, shot_format=shot_format):
            r["meta"]["label_status"] = lab["status"]
            r["meta"]["approved_by"] = lab["provenance"]["approved_by"]
            rows[ex["split"]].append(r)
    for split, rs in rows.items():
        (out_dir / f"{split}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rs))
    info = {
        "out_dir": str(out_dir),
        "json_format": json_format,
        "prompt_version": prompts.version_for("inspiration", shot_format),
        "shot_format": shot_format,
        "skipped_without_reasoning": skipped,
        "skipped_without_zoom": skipped_zoom,
        "examples": dict(Counter(examples[lab["example_id"]]["split"] for lab in chosen)),
        "rows": {k: len(v) for k, v in rows.items()},
        "rows_by_stage": dict(Counter(r["meta"]["stage"] for v in rows.values() for r in v)),
        "includes_unapproved_drafts": include_unapproved,
    }
    (out_dir / "export_info.json").write_text(json.dumps(info, indent=1))
    return info
