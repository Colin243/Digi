from pathlib import Path

import pytest
from PIL import Image


@pytest.fixture
def photos(tmp_path: Path):
    def make(n: int, size=(2400, 1600)) -> list[str]:
        out = []
        for i in range(n):
            p = tmp_path / f"img{i}.png"
            Image.new("RGB", size, (40 * i % 255, 120, 200)).save(p)
            out.append(str(p))
        return out

    return make
