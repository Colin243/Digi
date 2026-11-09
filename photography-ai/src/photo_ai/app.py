"""Local Gradio interface. Binds to 127.0.0.1 only; nothing is shared or uploaded off the machine.

Tab "Analyze":  upload 3-5 inspiration photos + 1 target, get 3 compositions.
Tab "Evaluate": view any saved run (inspiration, target, recommendations) and score it
                with the 5-category rubric. Blind by default: the model and strategy are
                hidden until you save, so scores aren't biased by knowing which model wrote it.
"""

from __future__ import annotations

import json
from pathlib import Path

import gradio as gr

from .backends import DEFAULT_MODEL, MODELS, VLMBackend, make_backend
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
            return [], None, "Pick a run.", "", "", *empty, ""
        rec = _load(runs_dir, run_id)
        def img(p: dict) -> str:  # Phase-1 runs used the key "path"
            return p.get("saved_as") or p.get("path")

        gallery = [img(p) for p in rec["inputs"]["inspiration"]]
        target = img(rec["inputs"]["target"])
        identity = "*Model and strategy hidden until you save (blind mode).*" if blind else (
            f"**{rec['model']['key']}** · strategy `{rec['config']['strategy']}` · T={rec['config']['temperature']}")
        auto = "```json\n" + json.dumps(rec.get("auto_metrics", {}), indent=1)[:3000] + "\n```"
        prev = [e for e in load_scores(runs_dir, run_id) if e["rater"] == rater.strip()]
        vals = [prev[0]["scores"][k] for k, _, _ in RUBRIC] if prev else empty
        notes = prev[0]["notes"] if prev else ""
        return gallery, target, result_markdown(rec), identity, auto, *vals, notes

    def save(run_id, rater, blind, notes, *vals):
        if not run_id:
            raise gr.Error("Pick a run first.")
        if any(v is None for v in vals):
            raise gr.Error("Score all five categories before saving.")
        try:
            entry = make_entry(run_id, {k: int(v) for (k, _, _), v in zip(RUBRIC, vals)}, rater, notes, blind)
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
                notes = gr.Textbox(label="Notes (optional)", lines=2)
                save_btn = gr.Button("Save score", variant="primary")
                status = gr.Markdown()

                list_inputs = [bench, rater, only_unscored, blind]
                refresh_btn.click(refresh, list_inputs, [run_pick, bench])
                for comp in (bench, only_unscored, blind):
                    comp.change(refresh, list_inputs, [run_pick, bench])
                demo.load(refresh, list_inputs, [run_pick, bench])
                run_pick.change(show, [run_pick, rater, blind],
                                [ev_gallery, ev_target, ev_result, identity, auto_md, *radios, notes])
                save_btn.click(save, [run_pick, rater, blind, notes, *radios], status)
    return demo


def launch(host: str, port: int, runs_dir: Path) -> None:
    build(runs_dir).queue().launch(
        server_name=host, server_port=port, share=False, inbrowser=True, allowed_paths=[str(runs_dir)]
    )
