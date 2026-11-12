# New portrait evaluation — 4 November 2026

## Data and retrieval

The iPhone app-container inventory contains 149 study folders. Comparison against the previously reviewed sessions identifies 83 new captures from 29–30 October: 74 delivered skin mattes, nine did not, and none recorded flash firing. Every new original/styled JPEG and delivered matte opens successfully locally. A first bulk export timed out; an interrupted retry was not treated as verification. The final remote directory inventory independently confirms zero missing new capture IDs.

Photos scripting access succeeds for the library count (30,469 items), but its recent-date query and last-item query time out. Therefore this evaluation uses Digi's actual paired capture studies, not an exhaustive review of all recent Photos assets. No Photos database or original library assets were modified. All personal image files remain under ignored output/ paths.

## Review

Reviewed five contact sheets covering all 83 originals. These include exposed arms, full-length and crouching poses, profile/back views, fur near the skin, red foliage, a window-lit interior, and a warm-lit restaurant. Many adjacent frames belong to one outdoor shoot; they must not be counted as independent sessions or randomly split across training and evaluation.

Eight varied matte-bearing captures were selected for a fixed-parameter stress test of the existing gentle/balanced skin-balance algorithm. Exported 16 full-resolution candidates without retuning parameters on this subject. Reviewed the eight aligned original-mask overlays and representative indoor/outdoor original/current/gentle/balanced comparisons.

The masks broadly cover exposed face/arm/hand regions, including profile and multiple-person restaurant cases, while excluding most clothing/fur/foliage at overview scale. Hair strands over faces, lips, fine edges and missing-mask poses still need independent labels. A matte's presence is not a correctness score. Back/profile poses sometimes have no matte; a future production path must fall back safely rather than hallucinate skin selection.

The adjustment remains subtle and rolls back part of the current rendering's extra skin contrast/chroma. It does not neutralize original complexion, makeup, or illumination. Warm restaurant lighting is not a flash test. Foreground skin/background brightness balance and foliage saturation remain material aesthetic differences in the current profile.

## Checks

- Eight capture pairs / 16 full-resolution candidate exports completed.
- Maximum floating-point change outside the final selected mask: zero for both variants across all selected captures.
- Interior luma-gradient ratios span 0.994883–1.000323. This describes gradient stability, including noise, not preserved true detail or Canon fidelity.
- All 35 Python regression tests were rerun; results recorded in this task.
- Digi's working native timer/button build was rebuilt and installed with valid signing through 11 November 2026 at 4:18 p.m. Eastern. The offline skin candidate remains outside the app; phone processing/memory performance has not been established.

## Artifacts and next evidence

Local inventory and contact sheets: output/study-2026-11-04/. Selected comparisons: output/skin-balance-new-subject-nov4/. These images are not committed or uploaded.

This is useful cross-subject/cross-lighting stress evidence, not paired G12 calibration. Prioritize labeled mask-edge/background checks and an experimental saved-photo-only phone implementation with no-matte fallback. Actual flash-on/off pairs and qualified G12 portrait originals remain necessary. No candidate was promoted solely because its export succeeded.
