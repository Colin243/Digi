# Expanded private iPhone 17 Pro lighting study

Exported 96 original photo assets through Photos' supported automation interface. Photos rejected its scripted date filter; collection instead sampled 96 evenly spaced positions among 25,095 still-image filenames, then filtered by ImageIO camera/lens metadata. This did not rearrange or modify the user's library. Live Photo exports also produced companion files; the analysis counts still images only. No photos were uploaded.

## Verified sample inventory

Of the 96 stills, 66 report an iPhone model, including 31 iPhone 17 Pro and two iPhone 15 Pro. Eighteen new photos identify the 17 Pro main rear lens. Two photographed displays were excluded from camera-style fitting. Sixteen new usable main-camera photos plus nine existing ones provide 25 usable photos:

| Visually reviewed condition | Photos |
| --- | ---: |
| Daylight: sun, overcast, shade, backlight, outdoors | 9 |
| Indoor: warm artificial, window light, mixed light, dim interiors | 12 |
| Colored illumination/concert | 3 |
| Night street | 1 |

These labels are visual inferences, not measured illuminants. All selected source photos report flash off. The two 15 Pro files are retained separately for future inspection; they are not enough for a validated 15 Pro profile. Other lenses/models and photos of displays are excluded from this fit.

## Splits and new fit

Sixteen source photos are used for fitting: seven daylight and nine indoor. Five photos from separate capture dates form an evaluation set: two outdoor scenes, two indoor scenes and the previously supplied bedroom-library scene. No date/session identifier overlaps between fitting and evaluation. Repeated scenes across different days remain a possible limitation. Three colored-light photos and one night photo are reserved for stress checks; they are not used to fit unsupported lighting branches.

Fit separate daylight and indoor tone/color candidates using the existing bounded regression. G12 targets are separated by reviewed lighting and actual flash-fired EXIF; flashed targets are excluded because no source flash examples exist. Daylight uses 16 target groups; indoor uses four. The light label is supplied manually for this experiment. No automatic scene classifier or white-balance estimator was trained or installed.

| Evaluation scene | Installed-profile diagnostic | Lighting-candidate diagnostic |
| --- | ---: | ---: |
| Restaurant meal | 0.082683 | 0.082651 |
| Backlit city | 0.142518 | 0.143998 |
| Sun/cloud landscape | 0.128406 | 0.129154 |
| Window-lit portrait | 0.130495 | 0.128917 |
| Backlit bedroom | 0.112199 | 0.111064 |

This is an unpaired centered-tone plus saturation-feature diagnostic, not G12 accuracy or a perceptual preference score. Indoor changes are small; daylight changes do not improve the metric. No candidate is promoted to the app. The expanded set is useful for iteration but remains small and uneven, especially for night, flash and G12 indoor targets.

The city, landscape and portrait comparisons were visually inspected. Differences remain modest; scene-specific color factors alone do not reproduce flash or remove the original iPhone processing pipeline. The two remaining indoor comparisons use the same deterministic transform. All images remain private ignored outputs.

## Reproducible local artifacts

- `output/lighting-samples/export.applescript`: actual export procedure, using bulk Photos filename/reference reads.
- `output/lighting-samples/analysis/manifest.json`: decoded source metadata, with no GPS fields selected.
- `output/lighting-samples/labeled.json`: reviewed labels, lens selection and date/session split.
- `research/regression/fit_lighting_study.py`: fits branches and renders evaluations without modifying the installed profile.
- `output/lighting-samples/lighting-study.json`: coefficients, sample counts, diagnostics and limitations.
- `output/lighting-samples/evaluation-0.jpg` through `evaluation-4.jpg`: original / installed / candidate comparisons.

Eleven existing processing/research tests pass. The new study asserts disjoint fitting/evaluation dates. Source manifests and derived images are ignored by git; the installed model hash is unchanged. No app code changed, so native build/UI tests were not repeated.
