# ExploreCams audit and portrait lighting simulations

## Source audit

[ExploreCams G12 index](https://explorecams.com/photos/model/canon-powershot-g12) is useful for discovering contributors and source pages. It links to Pexels and Pixabay, including a beach-friends photograph. Attempts to open selected Pexels originals failed; no new original was admitted to fitting.

The [Homa detail page](https://explorecams.com/photos/wcgomzR8OS?model=canon-powershot-g12) reports Program AE, ISO80, 1/1250, f5.6 and flash not fired. A [sea/fishing example](https://explorecams.com/photos/NQCubzPZLp?model=canon-powershot-g12) also reports flash not fired. These are useful scene-selection fields, but site metadata does not verify My Colors Off, white balance or an unedited camera JPEG. Recorded three catalog entries as unadmitted candidates.

## Simulation executed

Ran frozen existing processing on six local iPhone 17 Pro portrait originals: four outdoor/daylight examples, one window-lit indoor portrait and one night street portrait. Compared original, Classic, prior face-protection experiment and default-JPEG tone candidate. No new training or app profile replacement.

Artifacts: `output/portrait-lighting-study/`; repeat using its `run.py` from repository root. All originals loaded successfully, orientation and embedded color profiles handled by the existing reader. Evaluation images were reduced to a maximum 1600px edge. Face-context crops are enlarged for comparison, not full-resolution texture validation.

| Portrait | Scene | Classic change | Face-protected change | Default tone change |
| --- | --- | ---: | ---: | ---: |
| IMG_5109 | Overcast outdoor | 16.55 | 6.79 | 1.38 |
| IMG_7459 | Field | 13.29 | 6.32 | 1.50 |
| IMG_9077 | Window light | 12.96 | 6.64 | 0.70 |
| IMG_5066 | Overcast outdoor | 17.24 | 6.98 | 1.33 |
| IMG_9913 | Street daylight | 12.18 | 4.91 | 1.16 |

Numbers are mean absolute RGB change from the iPhone original on a 0–255 scale, inside the existing face ellipse. They are NOT skin-specific color error or G12 similarity scores. The ellipse includes non-skin pixels. Night IMG_9969 has detection confidence 0.688, below the existing 0.7 threshold, so no face-region metric is reported and face protection is inactive. Night uses the indoor tone candidate only as a stress test.

## Visual findings and next changes to investigate

Inspected the six-image contact sheet and enlarged field/window-light face crops. Classic visibly brightens faces and increases scene contrast; face protection moderates that effect locally. The default tone candidate remains close to the original. None establishes closer G12 skin rendering without corresponding target evidence.

The window-lit scene is currently labeled indoor, revealing an overly coarse lighting taxonomy. Future labels should distinguish window daylight, overcast/open shade, direct sun, warm artificial light, mixed light and night. These are observed scene labels, not measured illuminant spectra. Do not relabel all indoor scenes as artificial light.

The next skin evaluation needs reviewed masks covering face, neck and exposed arms consistently. Evaluate color and highlight clipping separately from background styling; do not use a whole-person mask that includes clothing. Low-confidence detections need a conservative fallback rather than forced skin correction. Current samples do not provide a broad independent complexion/subject evaluation; training examples in this run are diagnostics, not held-out proof.

Verification: 20 existing regression tests passed. All six simulation outputs were finite and bounded; app profile hashes were unchanged. No native application code changed, so no new iOS build or installation was performed.
