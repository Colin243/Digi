# G12 portrait and flash reference audit

Target: default G12 camera JPEG rendering, for an iPhone 17 Pro capture pipeline. Research only; no model or installed app changed.

## Most useful new leads

| Source | Useful evidence | Admission limit |
| --- | --- | --- |
| [Câmera versus Câmera](https://www.cameraversuscamera.com.br/cameras/cg12/ck_cg12_2.htm) | Dedicated window-light, household-light and built-in-flash comparisons; separate white-balance examples. | Search-index text accessible; direct fetch failed. Mostly mannequins plus a hand sample, not a diverse human portrait set. Nondefault My Colors/WB demonstrations must remain separate. |
| [Photo Review](https://www.photoreview.com.au/reviews/advanced-compact-cameras/fixed-lens/canon-powershot-g12/) | Labeled flash ISO series, incandescent/fluorescent AWB examples and JPEG color-test figures. | Direct page 403; originals and real-skin coverage unverified. An ISO1600 filename has an ISO800 caption: resolve against original metadata. Charts are not a measured iPhone-to-G12 transform. |
| [ZOL](https://detail.zol.com.cn/255/254746/sample.shtml) | Index lists 35 portrait entries, a promising source of additional subjects. | Search lead only; not 35 verified originals. Need actual camera model, settings, editing history and flash status. |
| [DCFever comparison](https://www.dcfever.com/news/readnews.php?id=4651) | Accessible original links with AWB/ISO labels; useful environmental lighting comparisons. | Mixed-camera page. Select only labeled G12 originals. Default My Colors and portrait/flash coverage not established. |

## Existing sources still worth prioritizing

- [CameraLabs](https://www.cameralabs.com/canon_powershot_g12/3/) explicitly documents AWB, Large Fine JPEG and My Colours Off. Its labeled flash portrait is more valuable for our target than an unlabeled social post, but that portrait original has not been recovered into the local fitting set.
- [Photography Blog](https://www.photographyblog.com/reviews/canon_powershot_g12_review) provides built-in-flash portraits and describes unaltered full-size JPEG samples. Its image host previously denied retrieval; the original portraits are still not admitted.
- [Imaging Resource](https://www.imaging-resource.com/cameras/canon-g12-review/exposure/) has controlled skin/exposure and flash observations in indexed text, while direct access remains blocked. Its reported indoor auto-flash example used ISO250 and 1/25 second: G12 flash does not always imply a black background.
- [DPReview](https://www.dpreview.com/reviews/4522799364/canong12/) documents default studio methods, but the old comparison scene is unavailable. The described 25-image gallery needs original-file verification. Its developed RAW illustrations are a separate target.

## What this changes about the fitting strategy

These references support investigating lighting-dependent behavior; they do not yet supply a reliable numerical skin-color fit. Câmera versus Câmera reports different casts under window light, household lighting and flash. Its mannequin results cannot be generalized to human skin reflectance.

1. Admit originals only after recording camera model, JPEG/RAW origin, WB, My Colors, flash-fired status and editing certainty. Keep unknown fields unknown. EXIF alone does not prove an image is unedited.
2. Separate daylight/shade, warm indoor, mixed light, daytime fill flash and low-light flash. Do not infer flash use from appearance alone.
3. Label actual exposed skin on face, neck and arms; exclude lips, eyes, hair, clothing, background and clipped highlights. Include a range of observed complexions without inferring ethnicity.
4. Fit bounded color and tone adjustments within each sufficiently supported group. Use flash-fired capture metadata for the flash branch. Preserve natural complexion rather than impose a common pale target.
5. Hold out entire subjects, sessions and sources. Compare skin hue/chroma, clipping, texture and subject/background brightness separately. Similar distributions across unrelated scenes are supporting evidence, not a camera-matching accuracy score.
6. Validate on originals captured through Digi on iPhone 17 Pro. Apple Camera samples have a different processing path. Without matched scenes, report the result as a constrained approximation, not calibrated sensor equivalence.

## Rejected shortcut

The inspected [SampleShots G12 page](https://www.sampleshots.com/cameras/canon-powershot-g12/?sort=-popularity_score&tag=human) contained inconsistent Sony model naming and nonhuman results under its human filter. Its labels are insufficient for automatic ingestion. Verify each originating file independently before using any item.

Outcome: six additional catalog entries, zero newly admitted training images. The useful next acquisition targets are the documented CameraLabs/Photography Blog human flash originals, followed by individually verified ZOL portraits. The new controlled lighting references can guide evaluation while that gap remains.
