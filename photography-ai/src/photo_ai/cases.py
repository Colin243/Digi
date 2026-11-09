"""Benchmark cases: fixed inspiration/target sets with hand-written ground truth.

A case JSON lists each image with
  primary: synonyms for the main subject (did the model identify the image at all?)
  objects: synonym groups for visible things (how much of the image did it mention?)
and `leak_terms`: things that exist only in the inspiration photos. If those show up
in the target description or compositions, the model copied the inspiration instead
of looking at the target.

Image paths are relative to the Digi repository root.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parent
CASES_DIR = PROJECT_ROOT / "cases"


@dataclass
class CaseImage:
    file: str
    primary: list[str]
    objects: list[list[str]] = field(default_factory=list)

    @property
    def path(self) -> Path:
        p = Path(self.file)
        return p if p.is_absolute() else REPO_ROOT / p


@dataclass
class Case:
    id: str
    description: str
    subject: str
    inspiration: list[CaseImage]
    target: CaseImage
    leak_terms: list[str]
    source: str = ""

    def missing_files(self) -> list[str]:
        return [str(i.path) for i in [*self.inspiration, self.target] if not i.path.is_file()]


def _img(d: dict) -> CaseImage:
    return CaseImage(d["file"], d["primary"], d.get("objects", []))


def load_case(path_or_id: str | Path) -> Case:
    p = Path(path_or_id)
    if not p.suffix:
        p = CASES_DIR / f"{path_or_id}.json"
    d = json.loads(p.read_text())
    return Case(
        id=d["id"],
        description=d.get("description", ""),
        subject=d.get("subject", "a person posing in the scene"),
        inspiration=[_img(x) for x in d["inspiration"]],
        target=_img(d["target"]),
        leak_terms=d.get("leak_terms", []),
        source=str(p),
    )


def all_cases() -> list[Case]:
    return [load_case(p) for p in sorted(CASES_DIR.glob("*.json"))]
