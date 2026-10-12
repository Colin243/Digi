"""Scene-grouped unpaired tone diagnostic, never a camera-fidelity score.
Run on EXIF-verified references and local sources. No downloads or app mutation.
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path
import numpy as np
from fit_tone import load_srgb, tone, fit, curve


def checked_quantiles(rgb):
    if not np.isfinite(rgb).all() or np.ptp(rgb) < 1 / 255:
        raise ValueError('Blank/invalid analysis image; inspect decoding before fitting')
    return np.quantile(tone(rgb), np.linspace(.02, .98, 97))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, action='append', required=True)
    p.add_argument('--manifest', type=Path, default=Path('research/g12/collection/manifest.json'))
    p.add_argument('--output', type=Path, default=Path('output/dataset/grouped-regression.json'))
    args = p.parse_args()
    def quantiles(path):
        image, _ = load_srgb(path)
        return checked_quantiles(np.asarray(image, dtype=float) / 255)
    sources = np.array([quantiles(path) for path in args.source])
    groups = defaultdict(list)
    rows = json.loads(args.manifest.read_text())
    for row in rows:
        if row['camera_model'] != 'Canon PowerShot G12':
            raise ValueError('Unexpected reference model')
        groups[row['scene_group']].append(quantiles(row['file']))
    if len(groups) < 3:
        raise ValueError('At least three independent reference groups required')
    targets = np.array([np.mean(v, axis=0) for v in groups.values()])
    results = {}
    for penalty in [None, .01, .1, 1., 10.]:
        scores = []
        for held in range(len(targets)):
            train = np.delete(targets, held, axis=0).mean(axis=0)
            per_source = []
            for src in sources:
                if penalty is None:
                    prediction = src
                else:
                    x, y = curve(fit(src, train, penalty))
                    prediction = np.interp(src, x, y)
                per_source.append(float(np.mean(np.abs(prediction - targets[held]))))
            scores.append(float(np.mean(per_source)))
        results['identity' if penalty is None else str(penalty)] = {'mean': float(np.mean(scores)), 'fold_scores': scores}
    report = {'source_count': len(sources), 'reference_count': len(rows), 'reference_scene_groups': len(groups), 'groups': list(groups), 'results': results, 'limitations': ['Unpaired encoded-sRGB luma-distribution distance, NOT color accuracy or camera fidelity.', 'Every source is reused across target-group folds. No held-out source/session evaluation.', 'Each curve is fitted to its source distribution; this is not a reusable scene predictor.', 'Scene groups receive equal weight; this reduces duplicate-scene bias but does not remove publisher/scene-content confounding.', 'No model selected or installed in Digi.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v['mean'] for k, v in results.items()}, indent=2))


if __name__ == '__main__':
    main()
