# Flash pair evaluation: IMG_9767–9770

Four supplied, already styled 3024×4032 JPEGs were evaluated as one warm indoor session. Keep the session together in any evaluation split; these are not four independent lighting conditions.

| File | Subject | EXIF flash fired | EXIF ISO |
|---|---|---|---|
| IMG_9767 | Portrait | No (16) | 1000 |
| IMG_9768 | Portrait | Yes (9) | 64 |
| IMG_9769 | Room | No (16) | 800 |
| IMG_9770 | Room | Yes (9) | 160 |

## Findings

The portrait flash shot shows brighter frontal skin illumination, pronounced detail and a darker background relative to the subject. Warm/red highlights merit examination before stronger sharpening or smoothing. Capture sensitivity also changed substantially, so differences cannot be attributed solely to the flash or to a rendering algorithm. Framing differs; these images are not aligned pixelwise training pairs.

Face rectangles (NOT skin masks) contain at least one RGB channel ≥250 in approximately 6.45% of the ambient crop and 38.21% of the flash crop. Almost no pixels reach that threshold in all three channels. This suggests examining individual-channel saturation/color handling, not assuming widespread white clipping. Rectangles include non-skin content; these are diagnostic statistics, not skin accuracy metrics. No causal attribution to the LUT is possible without matching pre-style originals.

The room images are useful negative examples for future skin masks: warm walls and wood must remain unselected. No face was detected in either room image; that does not establish that a skin segmentation model would avoid false positives.

## Mask retrieval

None of the four JPEGs contains an embedded Apple skin matte. Retrieved Digi's MaskStudy folder from the connected phone: still the same nine historical captures, with no new diagnostic originals or masks for this session. Existing old masks must not be reused for these photos. A reliable study capture workflow remains necessary.

## Finishing experiment

Rendered baseline, chroma-only, highlight-only and combined variants for all four files at native resolution. No LUT was applied again. Visually inspected 100% portrait crops. The first candidate introduced colored speckles in very dark regions. Conservative gamut limiting alone did not eliminate them. A dark-pixel early bypass removed the visible speckles in the inspected comparison; this is a bounded mitigation, not a proven root cause or universal fix. The offline kernel also retains extended-range values until output conversion. Production would need a supported Metal implementation and broader validation.

The final changes remain subtle and do not establish better G12 matching. No mask-directed processing or app changes were deployed. The earlier texture report's measurements refer to the earlier kernel revision; they should not be mixed with this run.

Artifacts in ignored private output/flash-texture-session: report.json, session.json, flash-portrait-detail.jpg, and 16 native-size PNG renders. Reproduce using probe_texture_finishing.swift and evaluate_flash_session.py. Personal photos are not embedded in source files.

## Next implementation priority

Make diagnostic capture survive ordinary app reopening, clearly indicate whether a skin mask was actually saved, and preserve wide framing. Then gather aligned pre-style originals, saved results and masks with actual flash state. Only after coverage and highlight checks should local skin finishing be enabled. These samples support iPhone flash evaluation; they do not provide G12 ground truth.
