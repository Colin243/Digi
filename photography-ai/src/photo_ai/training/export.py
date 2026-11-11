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
from collections import Counter
from pathlib import Path

from .. import prompts
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
                 stages=STAGES) -> list[dict]:
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
            p = prompts.compositions_from_parts(answer["aesthetic"], answer["target_scene"], example.get("subject", prompts.DEFAULT_SUBJECT))
            rows.append(_row(p, [tgt], _j({"compositions": answer["compositions"]}), {**meta, "stage": "compositions"}))
    return rows


def export_sft(dataset: str = "train_v1", out_dir: Path | None = None, json_format: str = "keys",
               include_unapproved: bool = False, example_ids: list[str] | None = None) -> dict:
    pool = {i["id"]: i for i in load_pool(dataset)["images"]}
    examples = {e["example_id"]: e for e in load_examples(dataset)}
    labels = load_labels(dataset)
    if example_ids:
        labels = [lab for lab in labels if lab["example_id"] in example_ids]
    chosen = [lab for lab in labels if lab["status"] == "approved" or
              (include_unapproved and lab["status"] == "draft" and not lab.get("schema_errors"))]
    out_dir = Path(out_dir or data_dir(dataset) / ("sft-UNREVIEWED-smoke" if include_unapproved else "sft"))
    out_dir.mkdir(parents=True, exist_ok=True)

    def image_path(pid):
        return str((REPO_ROOT / pool[pid]["file"]).resolve())

    rows = {"train": [], "valid": []}
    for lab in chosen:
        ex = examples[lab["example_id"]]
        for r in example_rows(ex, lab["answer"], image_path, json_format):
            r["meta"]["label_status"] = lab["status"]
            r["meta"]["approved_by"] = lab["provenance"]["approved_by"]
            rows[ex["split"]].append(r)
    for split, rs in rows.items():
        (out_dir / f"{split}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rs))
    info = {
        "out_dir": str(out_dir),
        "json_format": json_format,
        "prompt_version": prompts.PROMPT_VERSION,
        "examples": dict(Counter(examples[lab["example_id"]]["split"] for lab in chosen)),
        "rows": {k: len(v) for k, v in rows.items()},
        "rows_by_stage": dict(Counter(r["meta"]["stage"] for v in rows.values() for r in v)),
        "includes_unapproved_drafts": include_unapproved,
    }
    (out_dir / "export_info.json").write_text(json.dumps(info, indent=1))
    return info
