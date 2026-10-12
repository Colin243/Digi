"""Descriptive output checks, not ground-truth noise or G12 accuracy scores."""
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path('output/texture-finishing-study')
rows = json.loads((ROOT / 'report.json').read_text())
metrics = []
board = Image.new('RGB', (1260, 3 * 470), '#eeeeeb')
draw = ImageDraw.Draw(board)

def luminance(rgb):
    v = rgb / 255.0
    linear = np.where(v <= .04045, v / 12.92, ((v + .055) / 1.055) ** 2.4)
    return linear @ np.array([.2126, .7152, .0722], dtype=np.float32)

for i, row in enumerate(rows):
    stem = row['stem']
    base = np.asarray(Image.open(ROOT / f'{stem}-baseline.png').convert('RGB'), dtype=np.float32)
    face = row['faces'][0]
    cx = int((face['x'] + face['width'] / 2) * row['width'])
    cy = int((1 - face['y'] - face['height'] / 2) * row['height'])
    crop = (cx - 210, cy - 210, cx + 210, cy + 210)
    ybase = luminance(base)
    for j, variant in enumerate(['baseline', 'chroma', 'combined']):
        im = Image.open(ROOT / f'{stem}-{variant}.png').convert('RGB')
        board.paste(im.crop(crop), (420 * j, 470 * i + 40))
        draw.text((420 * j + 8, 470 * i + 12), f'{stem} | {variant} | 100% crop', fill='black')
    for variant in ['chroma', 'highlights', 'combined']:
        arr = np.asarray(Image.open(ROOT / f'{stem}-{variant}.png').convert('RGB'), dtype=np.float32)
        assert arr.shape == base.shape == (4032, 3024, 3)
        y = luminance(arr)
        x0, y0, x1, y1 = crop
        a, b = ybase[y0:y1, x0:x1], y[y0:y1, x0:x1]
        gradient = lambda z: (np.abs(np.diff(z, axis=0)).mean() + np.abs(np.diff(z, axis=1)).mean()) / 2
        metrics.append(dict(stem=stem, variant=variant, rgb_mean_absolute_change=float(np.abs(arr-base).mean()),
                            linear_luminance_mean_absolute_change=float(np.abs(y-ybase).mean()),
                            face_crop_gradient_ratio=float(gradient(b)/gradient(a)),
                            warning='Gradient includes noise; not a measure of recovered texture or G12 fidelity.'))
board.save(ROOT / 'texture-comparison.jpg', quality=95)
(ROOT / 'metrics.json').write_text(json.dumps(metrics, indent=2))
print(json.dumps(metrics, indent=2))
