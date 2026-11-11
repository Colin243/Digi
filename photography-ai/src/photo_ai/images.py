"""Image preparation: orient, downscale, strip metadata.

Downscaling matters for small VLMs: SmolVLM2 tiles large images into many
512px crops, so six full-resolution photos can overflow its context window.
Saving re-encoded copies also strips EXIF/GPS from anything stored in runs/.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageOps

try:  # HEIC from iPhone, if pillow-heif happens to be installed
    from pillow_heif import register_heif_opener  # type: ignore

    register_heif_opener()
except ImportError:  # pragma: no cover
    pass


@dataclass
class PreparedImage:
    role: str  # "inspiration" | "target"
    original_name: str
    saved_as: str  # prepared copy inside the run folder
    original_size: tuple[int, int]
    size: tuple[int, int]

    def to_dict(self) -> dict:
        return asdict(self)


def prepare(src: str | Path, dest: Path, role: str, max_side: int) -> PreparedImage:
    src = Path(src)
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        original = im.size
        im = im.convert("RGB")
        if max(im.size) > max_side:
            im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, "JPEG", quality=92)  # no exif= argument -> metadata dropped
        size = im.size
    return PreparedImage(role, src.name, str(dest), original, size)
