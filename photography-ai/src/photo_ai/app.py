"""Local Gradio interface: upload 3-5 inspiration photos + 1 target, get 3 compositions.

Binds to 127.0.0.1 only; nothing is shared or uploaded off the machine.
"""

from __future__ import annotations

from pathlib import Path

import gradio as gr

from .backends import DEFAULT_MODEL, MODELS, VLMBackend, make_backend
from .pipeline import MAX_INSPIRATION, MIN_INSPIRATION, STRATEGIES, InputError, RunConfig, analyze
from .render import result_markdown, timing_markdown

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


def build(runs_dir: Path) -> gr.Blocks:
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

    with gr.Blocks(title="Digi · Photography AI baseline") as demo:
        gr.Markdown(
            "## Photography AI baseline\n"
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
                    max_tokens = gr.Slider(200, 2000, value=d.max_tokens, step=50, label="Max new tokens")
                    temperature = gr.Slider(0.0, 1.0, value=d.temperature, step=0.05, label="Temperature")
                    label = gr.Textbox(label="Run label (optional)", placeholder="e.g. kitchen-window test")
                go = gr.Button("Analyze", variant="primary")
            with gr.Column(scale=1):
                result_md = gr.Markdown()
                timing_md = gr.Markdown()
                with gr.Accordion("Full run record (JSON)", open=False):
                    record = gr.JSON()

        files.change(lambda f: _paths(f), files, gallery)
        go.click(
            run,
            [files, target, model, strategy, max_side, max_tokens, temperature, label],
            [result_md, timing_md, record],
            concurrency_limit=1,  # one generation at a time on the GPU
        )
    return demo


def launch(host: str, port: int, runs_dir: Path) -> None:
    build(runs_dir).queue().launch(server_name=host, server_port=port, share=False, inbrowser=True)
