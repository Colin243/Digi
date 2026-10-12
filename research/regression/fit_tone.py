"""Unpaired tone-distribution regression study. NOT a calibrated camera transform.
Run with numpy and Pillow. No network, neural inference, or changes to source files.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageCms, ImageDraw, ImageOps


def load_srgb(path):
    with Image.open(path) as opened:
        exif = opened.getexif()
        meta = {key: str(exif.get(tag, '')).replace('\x00', '').strip() or None for key, tag in [('make', 271), ('model', 272)]}
        profile = opened.info.get('icc_profile')
        image = ImageOps.exif_transpose(opened).convert('RGB')
        if profile:
            image = ImageCms.profileToProfile(image, ImageCms.ImageCmsProfile(io.BytesIO(profile)), ImageCms.createProfile('sRGB'), outputMode='RGB')
            meta['color_conversion'] = 'embedded ICC to sRGB'
        else:
            meta['color_conversion'] = 'assumed sRGB; no embedded ICC'
        image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    return image, meta


def tone(rgb):
    # Encoded-sRGB luma proxy, explicitly NOT linear/physical luminance.
    return rgb @ np.array([0.2126, 0.7152, 0.0722])


def design(x):
    return np.stack([x * (1 - x), x * (1 - x) * (2 * x - 1)], axis=-1)


def fit(source_quantiles, target_quantiles, penalty):
    x = design(source_quantiles)
    return np.linalg.solve(x.T @ x + penalty * np.eye(2), x.T @ (target_quantiles - source_quantiles))


def curve(coefficients):
    x = np.linspace(0, 1, 4097)
    # Explicit safety bound for this exploratory study, not measured Canon behavior.
    y = x + np.clip(design(x) @ coefficients, -0.08, 0.08)
    y = np.maximum.accumulate(np.clip(y, 0, 1))
    y[0], y[-1] = 0, 1
    return x, y


def apply(rgb, coefficients):
    x, lut = curve(coefficients)
    old = tone(rgb)
    new = np.interp(old, x, lut)
    chroma = rgb - old[..., None]
    # Preserve chroma direction; reduce magnitude only when needed for gamut safety.
    limit = np.ones_like(rgb)
    np.divide(1 - new[..., None], chroma, out=limit, where=chroma > 1e-9)
    np.divide(-new[..., None], chroma, out=limit, where=chroma < -1e-9)
    scale = np.minimum(1, np.min(limit, axis=-1))
    return np.clip(new[..., None] + chroma * scale[..., None], 0, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--references', type=Path, default=Path('research/g12/references'))
    parser.add_argument('--output', type=Path, default=Path('output/regression'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source, source_meta = load_srgb(args.source)
    rgb = np.asarray(source, dtype=float) / 255
    probabilities = np.linspace(0.02, 0.98, 97)
    source_quantiles = np.quantile(tone(rgb), probabilities)
    refs = sorted(args.references.glob('dkamera-*.jpg'))
    if len(refs) < 3:
        raise ValueError('This leave-one-reference-out study requires at least three references')
    targets, provenance = [], []
    for path in refs:
        image, meta = load_srgb(path)
        if meta['model'] != 'Canon PowerShot G12':
            raise ValueError(f'Unexpected reference model: {meta}')
        targets.append(np.quantile(tone(np.asarray(image, dtype=float) / 255), probabilities))
        provenance.append({'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), **meta})
    targets = np.array(targets)
    experiments = []
    for penalty in [0.01, 0.1, 1.0, 10.0]:
        folds = []
        for held in range(len(refs)):
            coeff = fit(source_quantiles, np.mean(np.delete(targets, held, axis=0), axis=0), penalty)
            xx, yy = curve(coeff)
            predicted = np.interp(source_quantiles, xx, yy)
            folds.append({'held_reference': refs[held].name, 'coefficients': coeff.tolist(),
                          'unpaired_quantile_mae': float(np.mean(abs(predicted - targets[held]))),
                          'identity_quantile_mae': float(np.mean(abs(source_quantiles - targets[held])))})
        experiments.append({'ridge_penalty': penalty, 'folds': folds})
    # Preselected conservative model; no tuning to a held-out source (none exists).
    coeff = fit(source_quantiles, targets.mean(axis=0), 1.0)
    rendered = apply(rgb, coeff)
    samples = [('Original iPhone photo', rgb), ('Pooled tone study (unvalidated)', rendered)]
    for i, path in enumerate(refs):
        individual = fit(source_quantiles, targets[i], 1.0)
        samples.append((f'Reference {path.stem.removeprefix("dkamera-")} tone fit', apply(rgb, individual)))
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    for label, values in samples:
        name = 'original' if label.startswith('Original') else 'pooled' if label.startswith('Pooled') else label.split()[1]
        Image.fromarray(np.uint8(np.round(values * 255))).save(args.output / f'{name}.jpg', quality=94, icc_profile=srgb)
    board = Image.new('RGB', (1500, 2 * 430), '#171a18')
    draw = ImageDraw.Draw(board)
    for i, (label, values) in enumerate(samples):
        tile = Image.fromarray(np.uint8(np.round(values * 255)))
        tile.thumbnail((480, 365), Image.Resampling.LANCZOS)
        col, row = i % 3, i // 3
        board.paste(tile, (col * 500 + 10, row * 430 + 38))
        draw.text((col * 500 + 10, row * 430 + 12), label, fill='#eeeeee', font_size=18)
    draw.multiline_text((1010, 475), 'EXPERIMENT ONLY\n\n1 iPhone image / 3 unpaired G12 images\nDifferent scenes confound the fit.\nNo camera-accuracy claim.\nNo app profile replaced.', fill='#dddddd', font_size=18, spacing=12)
    board.save(args.output / 'comparison.jpg', quality=94, icc_profile=srgb)
    xx, yy = curve(coeff)
    per_ref_curves = np.array([curve(fit(source_quantiles, t, 1.0))[1] for t in targets])
    report = {'status': 'exploratory-unpaired-not-for-production', 'source': {'path': str(args.source), 'sha256': hashlib.sha256(args.source.read_bytes()).hexdigest(), **source_meta}, 'references': provenance,
              'source_count': 1, 'target_count': len(refs), 'paired_examples': 0,
              'model': 'ridge regression on bounded quadratic/cubic residual tone basis',
              'working_space': 'encoded sRGB; luma proxy, not physical luminance',
              'coefficients': coeff.tolist(), 'ridge_penalty': 1.0,
              'maximum_allowed_tone_change': 0.08,
              'max_difference_between_reference_specific_curves': float(np.ptp(per_ref_curves, axis=0).max()),
              'measured_maximum_tone_change': float(np.max(abs(yy-xx))),
              'experiments': experiments,
              'limitations': ['No held-out iPhone scene or iPhone 15 sample', 'All targets from one publisher; not independent camera conditions', 'Reference scenes, ISO and flash differ', 'Quantile agreement is not camera fidelity', 'No learned color matrix, noise model, lighting adaptation or ML deployment', 'Reference training/reuse license not established; local exploratory study only']}
    (args.output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ['status', 'source', 'coefficients', 'max_difference_between_reference_specific_curves', 'measured_maximum_tone_change']}, indent=2))
    for exp in experiments:
        print('penalty', exp['ridge_penalty'], 'unpaired held-reference MAE', np.mean([f['unpaired_quantile_mae'] for f in exp['folds']]), 'identity', np.mean([f['identity_quantile_mae'] for f in exp['folds']]))


if __name__ == '__main__':
    main()
