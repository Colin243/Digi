# Skin matte validation, first pass

`research/regression/validate_skin_mask.py` reads one private MaskStudy capture
folder. It rotates `original.jpg` to its displayed EXIF orientation, checks
that `skin.png` is upright and has the same aspect ratio, then scales the matte
to the photo. It writes `overlay.jpg`, `mask_aligned.png`, and `report.json` to
the requested output folder. When the matte is absent or has a mismatched
aspect ratio, it writes only a report. Source captures are not changed.

Run with the bundled Python environment that contains Pillow and NumPy:

```sh
python research/regression/validate_skin_mask.py \
  output/device-mask-study-latest/<capture-id> \
  --output output/mask-validation/<capture-id>
```

The report includes delivery status, photo and mask dimensions, selected area,
mean mask confidence, a selected bounding box, and border selection. These
metrics show unusual behavior and help choose photos for review. They do not
measure correctness. If a hand-labeled upright, full-resolution binary skin
annotation is supplied with `--ground-truth`, the tool also calculates
precision, recall, intersection-over-union, and false-positive background
fraction at a fixed 50% mask threshold. Label quality and thresholds must be
recorded when comparing sessions.

## Existing phone captures

Two old virtual-camera captures produced aligned overlays at 3024 × 4032:

| Capture | Mask selected | Border selected | Visual inspection |
| --- | ---: | ---: | --- |
| `EDBA1565…` | 62.2% | 57.1% | Face and bare shoulder/torso selected; eyes, hair, mouth and window mostly excluded. |
| `C0F47E03…` | 86.0% | 75.5% | Face and torso selected; eyes, hair, mouth and window mostly excluded. |

Both portraits came from the earlier **overzoomed, blurry** diagnostic camera
configuration. They show that an oriented mask can align, but cannot validate
wide framing, fine edges, skin tone or flash behavior. The large coverage is
expected from a face and torso filling most of the frame; it is not a quality
score. An empty-room capture `B37043E6…` correctly reports `mask_missing` and
metadata `skin_delivered=false`. A missing mask in a scene with no person is
not a failure by itself.

Next validation needs wide-framed, sharp portraits with a delivered mask,
including neck and arms, flash on/off, and negative scenes without people.
Hand-label representative skin and non-skin regions before deriving an error
rate or changing color through the mask. The recent exported JPG pairs have no
matching matte and cannot supply this ground truth automatically.
