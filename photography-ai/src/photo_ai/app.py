"""Local Gradio interface. Binds to 127.0.0.1 only; nothing is shared or uploaded off the machine.

Tab "Analyze":  upload 3-5 inspiration photos + 1 target, get 3 compositions.
Tab "Evaluate": view any saved run (inspiration, target, recommendations) and score it
                with the 6-category rubric. Blind by default: the model and strategy are
                hidden until you save, so scores aren't biased by knowing which model wrote it.
Tab "Compare":  for one benchmark case, every model's recommendations side by side as
                Set A / B / C in a per-rater shuffled order; pick the set and the single shot
                you would actually take. Model names appear only after saving.
"""

from __future__ import annotations

import json
from pathlib import Path

import gradio as gr

from .backends import DEFAULT_MODEL, MODELS, VLMBackend, make_backend
from .comparison import LABELS, blind_order, candidates, load_preferences, make_preference, save_preference
from .evaluation import RUBRIC, load_scores, make_entry, save_score
from .pipeline import MAX_INSPIRATION, MIN_INSPIRATION, STRATEGIES, InputError, RunConfig, analyze
from .render import result_markdown, timing_markdown
from .storage import read_index

_current: dict[str, VLMBackend] = {}


def _backend(name: str) -> VLMBackend:
    """Keep one model resident; switching models unloads the previous one."""
    if name not in _current:
        for old in _current.values():
            old.unload()
        _current.clear()
        _current[name] = make_backend(name)
    return _current[name]


def _paths(files) -> list[str]:
    if not files:
        return []
    return [f if isinstance(f, str) else getattr(f, "name", str(f)) for f in files]


# ------------------------------------------------------------------ evaluation helpers

def _run_choices(runs_dir: Path, bench: str, rater: str, only_unscored: bool, blind: bool) -> list[tuple[str, str]]:
    rows = [r for r in read_index(runs_dir) if (runs_dir / r["run_id"] / "run.json").exists()]
    if bench and bench != "all runs":
        rows = [r for r in rows if r.get("label") == bench]
    scored = {e["run_id"] for e in load_scores(runs_dir) if e["rater"] == rater.strip()} if rater.strip() else set()
    if only_unscored:
        rows = [r for r in rows if r["run_id"] not in scored]
    choices = []
    for i, r in enumerate(rows, 1):
        mark = "✓ " if r["run_id"] in scored else ""
        case = r.get("case") or "custom"
        if blind:
            label = f"{mark}#{i} · {case}"
        else:
            label = f"{mark}#{i} · {case} · {r['model']} · {r['strategy']} · T={r.get('temperature', 0)}"
        choices.append((label, r["run_id"]))
    return choices


def _bench_choices(runs_dir: Path) -> list[str]:
    labels = sorted({r.get("label") for r in read_index(runs_dir) if r.get("label")})
    return ["all runs", *labels]


def _load(runs_dir: Path, run_id: str) -> dict:
    return json.loads((runs_dir / run_id / "run.json").read_text())


def build(runs_dir: Path) -> gr.Blocks:
    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    d = RunConfig()

    def run(files, target, model, strategy, max_side, max_tokens, temperature, label):
        inspiration = _paths(files)
        if not (MIN_INSPIRATION <= len(inspiration) <= MAX_INSPIRATION):
            raise gr.Error(f"Upload {MIN_INSPIRATION}-{MAX_INSPIRATION} inspiration photos (you have {len(inspiration)}).")
        if not target:
            raise gr.Error("Upload a target scene photo.")
        cfg = RunConfig(strategy=strategy, max_side=int(max_side), max_tokens=int(max_tokens), temperature=float(temperature))
        try:
            rec = analyze(_backend(model), inspiration, target, cfg, runs_dir, label or None)
        except InputError as exc:
            raise gr.Error(str(exc)) from exc
        return result_markdown(rec), timing_markdown(rec), rec

    # ---- evaluate callbacks
    def refresh(bench, rater, only_unscored, blind):
        choices = _run_choices(runs_dir, bench, rater, only_unscored, blind)
        return gr.update(choices=choices, value=choices[0][1] if choices else None), gr.update(choices=_bench_choices(runs_dir))

    def show(run_id, rater, blind):
        empty = [None] * len(RUBRIC)
        if not run_id:
            return [], None, "Pick a run.", "", "", *empty, "", False
        rec = _load(runs_dir, run_id)
        def img(p: dict) -> str:  # Phase-1 runs used the key "path"
            return p.get("saved_as") or p.get("path")

        gallery = [img(p) for p in rec["inputs"]["inspiration"]]
        target = img(rec["inputs"]["target"])
        identity = "*Model and strategy hidden until you save (blind mode).*" if blind else (
            f"**{rec['model']['key']}** · strategy `{rec['config']['strategy']}` · T={rec['config']['temperature']}")
        auto = "```json\n" + json.dumps(rec.get("auto_metrics", {}), indent=1)[:3000] + "\n```"
        prev = [e for e in load_scores(runs_dir, run_id) if e["rater"] == rater.strip()]
        vals = [prev[0]["scores"].get(k) for k, _, _ in RUBRIC] if prev else empty
        notes = prev[0]["notes"] if prev else ""
        hall = bool(prev[0].get("hallucination")) if prev else False
        return gallery, target, result_markdown(rec), identity, auto, *vals, notes, hall

    def save(run_id, rater, blind, notes, hall, *vals):
        if not run_id:
            raise gr.Error("Pick a run first.")
        if any(v is None for v in vals):
            raise gr.Error(f"Score all {len(RUBRIC)} categories before saving.")
        try:
            entry = make_entry(run_id, {k: int(v) for (k, _, _), v in zip(RUBRIC, vals)}, rater, notes, blind, bool(hall))
        except ValueError as exc:
            raise gr.Error(str(exc)) from exc
        save_score(runs_dir, entry)
        rec = _load(runs_dir, run_id)
        return (f"Saved **{entry['total']}/{entry['max_total']}** for `{run_id}` → "
                f"`runs/{run_id}/scores.json`. This was **{rec['model']['key']}** · `{rec['config']['strategy']}`.")

    with gr.Blocks(title="Digi · Photography AI") as demo:
        gr.Markdown("## Photography AI · local experiments")
        with gr.Tabs():
            with gr.Tab("Analyze"):
                gr.Markdown(
                    "Upload 3-5 **inspiration** photos and one **target scene**. The model describes the "
                    "inspiration aesthetic and recommends three compositions. Runs locally with MLX; every "
                    "run is saved under `runs/`. First use of a model downloads its weights."
                )
                with gr.Row():
                    with gr.Column(scale=1):
                        files = gr.File(label="Inspiration photos (3-5)", file_count="multiple", file_types=["image"])
                        gallery = gr.Gallery(label="Inspiration preview", columns=5, height=160, interactive=False)
                        target = gr.Image(label="Target scene", type="filepath", height=280)
                        model = gr.Dropdown(list(MODELS), value=DEFAULT_MODEL, label="Model")
                        strategy = gr.Radio(list(STRATEGIES), value=d.strategy, label="Strategy")
                        with gr.Accordion("Generation settings", open=False):
                            max_side = gr.Slider(384, 2048, value=d.max_side, step=64, label="Max image side (px)")
                            max_tokens = gr.Slider(200, 3000, value=d.max_tokens, step=50, label="Max new tokens")
                            temperature = gr.Slider(0.0, 1.0, value=d.temperature, step=0.05, label="Temperature")
                            label = gr.Textbox(label="Run label (optional)", placeholder="e.g. kitchen-window test")
                        go = gr.Button("Analyze", variant="primary")
                    with gr.Column(scale=1):
                        result_md = gr.Markdown()
                        timing_md = gr.Markdown()
                        with gr.Accordion("Full run record (JSON)", open=False):
                            record = gr.JSON()
                files.change(lambda f: _paths(f), files, gallery)
                go.click(run, [files, target, model, strategy, max_side, max_tokens, temperature, label],
                         [result_md, timing_md, record], concurrency_limit=1)

            with gr.Tab("Evaluate"):
                gr.Markdown(
                    "Score a saved run from 1 (poor) to 5 (excellent) in each category; 25 points total. "
                    "Scores are saved to `runs/<run>/scores.json` and `runs/scores.jsonl`. "
                    "Saving again as the same rater replaces your earlier score for that run."
                )
                with gr.Row():
                    rater = gr.Textbox(label="Your name (rater)", value="colin", scale=1)
                    bench = gr.Dropdown(_bench_choices(runs_dir), value="all runs", label="Benchmark / label", scale=1)
                    only_unscored = gr.Checkbox(label="Only runs I haven't scored", value=False, scale=1)
                    blind = gr.Checkbox(label="Blind (hide model)", value=True, scale=1)
                    refresh_btn = gr.Button("Refresh list", scale=0)
                run_pick = gr.Dropdown(label="Run", choices=[], interactive=True)
                with gr.Row():
                    with gr.Column(scale=1):
                        ev_gallery = gr.Gallery(label="Inspiration photos", columns=5, height=200, interactive=False)
                        ev_target = gr.Image(label="Target scene", height=320, interactive=False)
                        identity = gr.Markdown()
                        with gr.Accordion("Automatic checks (keyword-based)", open=False):
                            auto_md = gr.Markdown()
                    with gr.Column(scale=1):
                        ev_result = gr.Markdown()
                gr.Markdown("### Rubric")
                radios = []
                with gr.Row():
                    for key, title, desc in RUBRIC:
                        radios.append(gr.Radio([1, 2, 3, 4, 5], label=title, info=desc, elem_id=f"score-{key}"))
                hall = gr.Checkbox(label="Hallucination: the output claims something that is not in the photos")
                notes = gr.Textbox(label="Notes (optional)", lines=2)
                save_btn = gr.Button("Save score", variant="primary")
                status = gr.Markdown()

                list_inputs = [bench, rater, only_unscored, blind]
                refresh_btn.click(refresh, list_inputs, [run_pick, bench])
                for comp in (bench, only_unscored, blind):
                    comp.change(refresh, list_inputs, [run_pick, bench])
                demo.load(refresh, list_inputs, [run_pick, bench])
                run_pick.change(show, [run_pick, rater, blind],
                                [ev_gallery, ev_target, ev_result, identity, auto_md, *radios, notes, hall])
                save_btn.click(save, [run_pick, rater, blind, notes, hall, *radios], status)

            with gr.Tab("Compare"):
                _compare_tab(runs_dir, demo)
            with gr.Tab("Label"):
                _label_tab(demo)
    return demo


def _answer_markdown(answer: dict) -> str:
    """Readable preview of a training label, reusing the run renderer."""
    fake = {"result": {"aesthetic": answer.get("aesthetic"), "target_scene": answer.get("target_scene"),
                       "compositions": answer.get("compositions", [])},
            "validation": {"ok": True, "errors": []}}
    notes = "\n".join(f"{i}. {n}" for i, n in enumerate(answer.get("inspiration_notes", []), 1))
    return f"### Inspiration notes\n{notes}\n\n" + result_markdown(fake)


def _label_tab(demo: gr.Blocks, dataset: str = "train_v1") -> None:
    """Review AI-drafted training labels: inspect, edit, approve or reject (human reviewers only)."""
    from .cases import REPO_ROOT
    from .training import labels as L
    from .training.assemble import load_examples
    from .training.pool import data_dir, load_pool
    from .training.qa import check_label

    gr.Markdown(
        "Training labels are **provisional AI drafts** until a human approves them. Check every claim against the "
        "photos, edit the JSON if needed (**Save edits**), then **Approve** or **Reject**. Only approved labels are "
        "exported for LoRA training. Guide: `docs/annotation-guide.md`."
    )
    if not (data_dir(dataset) / "examples.json").exists():
        gr.Markdown(f"_No training examples yet. Run `photo-ai train-data assemble` (dataset `{dataset}`)._")
        return
    with gr.Row():
        reviewer = gr.Textbox(label="Your name (reviewer)", value="colin")
        status_filter = gr.Dropdown(["all", "draft", "approved", "rejected", "unlabeled"], value="draft",
                                    label="Show")
        pick = gr.Dropdown([], label="Example")
        refresh = gr.Button("Refresh", scale=0)
    summary = gr.Markdown()
    with gr.Row():
        insp = gr.Gallery(label="Inspiration photos", columns=4, height=220, interactive=False, scale=3)
        tgt = gr.Image(label="Target place", height=240, interactive=False, scale=2)
    info = gr.Markdown()
    qa_md = gr.Markdown()
    with gr.Row():
        with gr.Column(scale=1):
            editor = gr.Code(label="Answer JSON (editable)", language="json", interactive=True, lines=30)
        with gr.Column(scale=1):
            preview = gr.Markdown()
    note = gr.Textbox(label="Review note (why you edited, approved or rejected)", lines=2)
    with gr.Row():
        save_btn = gr.Button("Save edits")
        approve_btn = gr.Button("Approve as training data", variant="primary")
        reject_btn = gr.Button("Reject")
        draft_btn = gr.Button("Back to draft")
    status = gr.Markdown()

    def paths():
        pool = {i["id"]: i for i in load_pool(dataset)["images"]}
        return lambda pid: str(REPO_ROOT / pool[pid]["file"])

    def listing(filt):
        labels = {lab["example_id"]: lab for lab in L.load_labels(dataset)}
        out = []
        for e in load_examples(dataset):
            st = labels[e["example_id"]]["status"] if e["example_id"] in labels else "unlabeled"
            if filt in ("all", st):
                out.append((f"{e['example_id']} · {e['split']} · {st} · {e['technique']['description']}", e["example_id"]))
        s = L.status_summary(dataset)
        text = (f"**{s['examples']} examples** · labels {s['labels']} · approved by a human: **{s['approved_human']}** · "
                f"by split {s['by_split_status']}")
        return gr.update(choices=out, value=out[0][1] if out else None), text

    def show(eid):
        if not eid:
            return [], None, "", "", "", ""
        p = paths()
        ex = {e["example_id"]: e for e in load_examples(dataset)}[eid]
        lab = L.load_label(dataset, eid)
        head = (f"**{eid}** ({ex['split']}) — shared technique: *{ex['technique']['description']}* — subject: {ex['subject']}")
        if not lab:
            return [p(x) for x in ex["inspiration"]], p(ex["target"]), head, "_No draft yet._", "", ""
        prov = lab["provenance"]
        head += (f"\n\nStatus **{lab['status']}** · drafted by `{prov['drafted_by']}` · edited by {prov['edited_by'] or '—'} · "
                 f"approved by {prov['approved_by'] or '—'}")
        drafter_notes = [h["note"] for h in lab.get("history", []) if h.get("note") and h["action"] == "draft-imported"]
        if drafter_notes:
            head += f"\n\n> **Drafter's note to the reviewer:** {drafter_notes[-1]}"
        issues = check_label(lab, dataset)
        qa = ("**Heuristic warnings** (not a verdict; check the photos):\n" + "\n".join(f"- {i}" for i in issues)
              if issues else "_No heuristic warnings — still verify every claim against the photos._")
        return ([p(x) for x in ex["inspiration"]], p(ex["target"]), head, qa,
                json.dumps(lab["answer"], indent=2, ensure_ascii=False), _answer_markdown(lab["answer"]))

    def act(eid, who, text, nt, action):
        if not eid:
            raise gr.Error("Pick an example.")
        try:
            if action in ("save", "approve"):
                try:
                    answer = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise gr.Error(f"Answer is not valid JSON: {exc}") from exc
                if answer != L.load_label(dataset, eid)["answer"]:
                    L.edit_answer(dataset, eid, answer, who, nt)
            if action == "approve":
                L.set_status(dataset, eid, "approved", who, nt)
            elif action in ("rejected", "draft"):
                L.set_status(dataset, eid, action, who, nt)
        except ValueError as exc:
            raise gr.Error(str(exc)) from exc
        lab = L.load_label(dataset, eid)
        return f"Saved. **{eid}** is now **{lab['status']}**" + (f" (approved by {lab['provenance']['approved_by']})"
                                                                  if lab["status"] == "approved" else "")

    outs = [insp, tgt, info, qa_md, editor, preview]
    for c in (status_filter,):
        c.change(listing, status_filter, [pick, summary])
    refresh.click(listing, status_filter, [pick, summary])
    demo.load(listing, status_filter, [pick, summary])
    pick.change(show, pick, outs)
    save_btn.click(lambda *a: act(*a, "save"), [pick, reviewer, editor, note], status).then(show, pick, outs)
    approve_btn.click(lambda *a: act(*a, "approve"), [pick, reviewer, editor, note], status).then(show, pick, outs)
    reject_btn.click(lambda *a: act(*a, "rejected"), [pick, reviewer, editor, note], status).then(show, pick, outs)
    draft_btn.click(lambda *a: act(*a, "draft"), [pick, reviewer, editor, note], status).then(show, pick, outs)


MAX_SETS = 4


def _benchmarks(runs_dir: Path) -> list[str]:
    bdir = runs_dir / "benchmarks"
    return sorted((p.name for p in bdir.iterdir() if (p / "manifest.json").exists()), reverse=True) if bdir.exists() else []


def _manifest(runs_dir: Path, bench: str) -> dict:
    return json.loads((runs_dir / "benchmarks" / bench / "manifest.json").read_text())


def _compare_tab(runs_dir: Path, demo: gr.Blocks) -> None:
    gr.Markdown(
        "Every model's recommendations for the same case, side by side. Labels A/B/C are shuffled per rater "
        "and case, and model names are revealed only after you save. Choose the set you prefer overall and the "
        "single composition you would actually shoot. Saved to `runs/benchmarks/<bench>/preferences.jsonl`."
    )
    benches = _benchmarks(runs_dir)
    with gr.Row():
        c_rater = gr.Textbox(label="Your name (rater)", value="colin")
        c_bench = gr.Dropdown(benches, value=benches[0] if benches else None, label="Benchmark")
        c_strategy = gr.Dropdown(["decomposed", "two_stage", "single_pass"], value="decomposed", label="Strategy")
        c_case = gr.Dropdown([], label="Case")
    with gr.Row():
        c_gallery = gr.Gallery(label="Inspiration photos", columns=5, height=200, interactive=False, scale=3)
        c_target = gr.Image(label="Target scene", height=240, interactive=False, scale=2)
    cols, mds = [], []
    with gr.Row(equal_height=False):
        for i in range(MAX_SETS):
            with gr.Column(visible=False, min_width=260) as col:
                mds.append(gr.Markdown())
            cols.append(col)
    pref_set = gr.Radio([], label="Which set would you use?")
    pref_shot = gr.Radio([], label="Which single composition would you actually shoot?")
    c_notes = gr.Textbox(label="Notes (optional)", lines=2)
    c_save = gr.Button("Save preference", variant="primary")
    c_status = gr.Markdown()
    state = gr.State({})

    def cases_for(bench, strategy, rater):
        if not bench:
            return gr.update(choices=[], value=None)
        m = _manifest(runs_dir, bench)
        done = {p["case"] for p in load_preferences(runs_dir, bench) if p["rater"] == rater.strip()}
        ids = sorted({r["case"] for r in m["runs"] if r["kind"] == "greedy" and r["strategy"] == strategy})
        choices = [(("✓ " if c in done else "") + c, c) for c in ids]
        return gr.update(choices=choices, value=ids[0] if ids else None)

    def show(bench, strategy, case, rater):
        hidden = [gr.update(visible=False)] * MAX_SETS
        if not (bench and case):
            return [], None, *hidden, *[""] * MAX_SETS, gr.update(choices=[]), gr.update(choices=[]), {}, ""
        m = _manifest(runs_dir, bench)
        shown = blind_order(candidates(m, case, strategy), rater, case, bench)[:MAX_SETS]
        recs = [_load(runs_dir, r["run_id"]) for r in shown]
        first = recs[0]["inputs"] if recs else {"inspiration": [], "target": {}}
        gallery = [p["saved_as"] for p in first["inspiration"]]
        vis = [gr.update(visible=i < len(recs)) for i in range(MAX_SETS)]
        texts = []
        shot_choices = []
        for i in range(MAX_SETS):
            if i >= len(recs):
                texts.append("")
                continue
            lab = LABELS[i]
            comps = (recs[i]["result"] or recs[i].get("partial_result") or {}).get("compositions") or []
            body = result_markdown(recs[i])
            for n in range(1, 4):  # number the shots so they can be picked
                body = body.replace(f"### {n}. ", f"### {lab}{n}. ", 1)
            texts.append(f"## Set {lab}\n\n" + body)
            shot_choices += [f"{lab}{n}" for n in range(1, len(comps) + 1)]
        prev = [p for p in load_preferences(runs_dir, bench) if p["rater"] == rater.strip() and p["case"] == case]
        st = {"bench": bench, "case": case, "order": [r["run_id"] for r in shown]}
        note = "*You already saved a preference for this case; saving again replaces it.*" if prev else ""
        return (gallery, first["target"].get("saved_as"), *vis, *texts,
                gr.update(choices=[f"Set {LABELS[i]}" for i in range(len(recs))] + ["No preference"], value=None),
                gr.update(choices=shot_choices + ["None of them"], value=None), st, note)

    def save(st, rater, pset, pshot, notes):
        if not st:
            raise gr.Error("Pick a benchmark and case first.")
        if pset is None or pshot is None:
            raise gr.Error("Choose a set and a single composition (or the 'No preference' / 'None' options).")
        order = st["order"]
        run = None if pset == "No preference" else order[LABELS.index(pset.split()[-1])]
        shot = None if pshot == "None of them" else (order[LABELS.index(pshot[0])], int(pshot[1:]))
        try:
            entry = make_preference(st["bench"], st["case"], rater, order, run, shot, notes)
        except ValueError as exc:
            raise gr.Error(str(exc)) from exc
        save_preference(runs_dir, entry)
        model_of = {r["run_id"]: r["model"] for r in _manifest(runs_dir, st["bench"])["runs"]}
        reveal = ", ".join(f"**{LABELS[i]}** = {model_of.get(rid, '?')}" for i, rid in enumerate(order))
        return f"Saved. {reveal}"

    for comp in (c_bench, c_strategy):
        comp.change(cases_for, [c_bench, c_strategy, c_rater], c_case)
    c_case.change(show, [c_bench, c_strategy, c_case, c_rater],
                  [c_gallery, c_target, *cols, *mds, pref_set, pref_shot, state, c_status])
    c_save.click(save, [state, c_rater, pref_set, pref_shot, c_notes], c_status)
    demo.load(cases_for, [c_bench, c_strategy, c_rater], c_case)


def launch(host: str, port: int, runs_dir: Path) -> None:
    build(runs_dir).queue().launch(
        server_name=host, server_port=port, share=False, inbrowser=True, allowed_paths=[str(runs_dir)]
    )
