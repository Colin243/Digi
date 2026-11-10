"""`photo-ai train-data <action>` dispatcher (kept separate so cli.py stays small)."""

from __future__ import annotations

import json
import sys
from collections import Counter


def run_train_data(a) -> int:
    from . import pool as P

    if a.action == "pool":
        doc = P.build_pool(a.dataset)
        print(f"{len(doc['images'])} candidate images -> {P.data_dir(a.dataset) / 'pool.json'}")
        return 0
    if a.action == "fetch":
        doc = P.fetch_pool(a.dataset, a.ids)
        ok = P.usable(doc)
        print(f"usable {len(ok)}; excluded {sum(1 for i in doc['images'] if i.get('excluded'))}; "
              f"held-out images checked {doc.get('heldout_images_checked')}")
        print("split:", dict(Counter(i["split"] for i in ok)), "role:", dict(Counter(i["role_hint"] for i in ok)))
        return 0
    if a.action == "attribution":
        print(P.attribution_markdown(P.load_pool(a.dataset)))
        return 0
    if a.action == "status":
        from .labels import status_summary

        print(json.dumps(status_summary(a.dataset), indent=1))
        return 0
    if a.action == "import-tags":
        from .tags import import_tags

        n = import_tags(a.dataset, json.loads(a.file.read_text()), a.source)
        print(f"imported {n} tag records as {a.source!r} (provisional until reviewed)")
        return 0
    if a.action == "assemble":
        from .assemble import assemble

        ex = assemble(a.dataset, a.n_examples)
        print(f"{len(ex)} example skeletons; splits {dict(Counter(e['split'] for e in ex))}")
        return 0
    if a.action == "import-labels":
        from .labels import import_drafts

        n = import_drafts(a.dataset, json.loads(a.file.read_text()), a.source)
        print(f"imported {n} draft labels as {a.source!r}; status=draft until a human approves")
        return 0
    if a.action == "draft":
        from .draft_api import draft_examples

        if not a.ids:
            print("pass --ids <example ids>; drafting calls a paid API, so do a few at a time", file=sys.stderr)
            return 2
        print(json.dumps(draft_examples(a.dataset, a.ids, a.model), indent=1))
        return 0
    if a.action == "review-site":
        from .review_site import build

        print(json.dumps(build(a.dataset), indent=1))
        return 0
    if a.action == "import-review":
        from .labels import import_creative_review

        raw = json.loads(a.file.read_text())
        doc = raw.get("data", raw) if isinstance(raw, dict) else raw  # shared-store export or "Copy my review" text
        print(json.dumps(import_creative_review(a.dataset, doc, a.reviewer), indent=1))
        return 0
    if a.action == "qa":
        from .labels import load_labels
        from .qa import check_label

        for lab in load_labels(a.dataset):
            issues = check_label(lab)
            print(f"{lab['example_id']:14} {lab['status']:9} {len(issues)} issue(s): " + "; ".join(issues[:4]))
        return 0
    if a.action == "export":
        from .export import export_sft

        info = export_sft(a.dataset, include_unapproved=a.include_unapproved)
        print(json.dumps(info, indent=1))
        return 0
    print(f"unknown action {a.action}", file=sys.stderr)
    return 2
