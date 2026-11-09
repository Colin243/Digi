"""Backend interface. Anything that can turn (prompt, images) into text plugs in here."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

# Put this marker in a prompt where each image should go (one per image, in order).
# Without markers, images are placed before the text (the models' default layout).
IMAGE_MARKER = "<<image>>"


@dataclass(frozen=True)
class ModelSpec:
    key: str  # short name used in CLI/UI and run folders
    repo_id: str  # Hugging Face repo (or local path)
    backend: str  # "mlx" | "fake"
    notes: str = ""


@dataclass
class GenerationParams:
    max_tokens: int = 900
    temperature: float = 0.0
    repetition_penalty: float | None = None
    seed: int = 0


@dataclass
class Generation:
    text: str
    wall_seconds: float
    prompt_tokens: int | None = None
    generation_tokens: int | None = None
    prompt_tps: float | None = None
    generation_tps: float | None = None
    peak_memory_gb: float | None = None
    finish_reason: str | None = None
    extra: dict = field(default_factory=dict)


class VLMBackend(Protocol):
    spec: ModelSpec
    load_seconds: float | None

    @property
    def is_loaded(self) -> bool: ...

    def load(self) -> float:
        """Load weights; return seconds taken (0 if already loaded)."""

    def generate(self, prompt: str, images: list[str], params: GenerationParams) -> Generation: ...

    def unload(self) -> None: ...

    def inspect_inputs(self, prompt: str, images: list[str]) -> dict:
        """Tokenize without generating; report how images reached the model."""

    def runtime_info(self) -> dict: ...
