# G12 portrait research and database expansion

## Result and evidence status

Three requested sub-agents failed to start with backend HTTP 404; two retries also failed. Research continued in the main task. No findings are attributed to those agents.

Added a catalog of 46 G12 original-image candidates from Photography Blog. The publisher describes the full-size samples as unaltered; the first image download returned 403, so further downloads stopped. These are **46 discovered links, zero newly verified G12 files**, not training images. The separate flash portrait examples on that page are valuable viewing references but not equivalent to full-size originals.

Downloaded 50 review JPEGs from 9to5Mac: EXIF identifies 48 as iPhone 17 Pro and two as iPhone 16 Pro. Of the 48, 27 identify the main rear lens and 21 the telephoto lens. All 50 were visually screened in three contact sheets. They cover daylight and concert lighting, with crowds/performers rather than controlled face portraits. Keep them inspection-only: Standard style is publisher-declared, but web export and editing history are not fully verified and training permission is unestablished. Lens EXIF alone does not resolve digital cropping. These images do not constitute 50 independent scenes.

Audited the existing 33-image G12 fit manifest: buildings, landscapes and objects dominate, with no labeled human portrait. Existing local iPhone lighting labels identify six explicit portrait candidates, preserved in their existing train/evaluation/stress splits in ignored output/portrait-audit/. No new personal photos were uploaded. This is a label-based audit, not a claim that other images contain no people.

## History and style evidence

Canon dates the G12 to October 2010. Its 10MP CCD and DIGIC 4 processor form the hardware baseline; the 28–140mm-equivalent zoom means portrait framing can differ substantially from the iPhone main camera. The hardware description alone does not imply a universal warm cast or visible grain. [Canon museum](https://global.canon/en/c-museum/product/dcc596.html)

CameraLabs documents default My Colours off, auto white balance and Large Fine JPEG for its gallery, including a Program-plus-flash portrait at 140mm equivalent. That is a useful default-rendering reference with known capture context; its permission is personal evaluation, not unrestricted reuse. [Sample conditions](https://www.cameralabs.com/canon_powershot_g12/3/)

Photography Blog distinguishes Portrait mode, Positive Film, Lighter/Darker Skin Tone and other My Colors options. Its flash tests show separate on-flash and red-eye examples. Therefore social-media images with those settings should not all be pooled as one default G12 target. [Review and samples](https://www.photographyblog.com/reviews/canon_powershot_g12_review)

Photography Bay explicitly says its samples were developed from RAW and adjusted to the photographer's taste. They belong in an edited-look inspiration set, excluded from default JPEG response fitting. The review also discusses external/bounced flash, which must be separated from the built-in flash aesthetic. [Photographer's review](https://photographybay.com/2011/01/24/canon-powershot-g12-review/)

The iPhone source side also has multiple looks: Apple lists Smart HDR 5, Deep Fusion, Photonic Engine, adaptive flash and Photographic Styles. The review used Standard style, but that does not prove its output matches Digi's AVFoundation capture path. [Apple specifications](https://support.apple.com/en-nz/125090), [review capture context](https://9to5mac.com/2025/09/17/iphone-17-pro-review/)

## Portrait-specific direction — proposed, not yet fitted

1. Protect facial tonal gradients while allowing stronger background color. A global contrast increase can deepen facial shadows and push cheeks/lips excessively; evaluate face and background separately.
2. Preserve variation in observed skin lightness and color. Do not normalize every face to one orange, pink or pale target. Review varied complexions without inferring race or identity.
3. Separate daylight, warm indoor, mixed light and direct-flash references. Flash changes actual illumination, highlights and shadows; a color LUT cannot recreate missing flash geometry.
4. Preserve eyes, hair and skin texture. Compare sharpening halos and noise at equal output sizes before adding softening or grain. No face reshaping or beauty smoothing is needed.
5. Test close main-camera framing separately from longer-lens portraits. A crop cannot undo perspective differences caused by shooting distance.

## Next model experiment

First curate genuine G12 face references with documented settings and usable rights. Keep edited/social reference images as aesthetic targets, not neutral measurements. Retain group splits by photographer and session; do not let adjacent burst frames cross train/test boundaries.

Then compare identity, current fitted v1, Classic v2 and a bounded face-protected candidate on the existing private portraits. Measure clipping in face regions, chroma shifts, face/background exposure balance and processing latency; obtain preference judgments with labels hidden. Distribution distance alone is not a fidelity score. For unpaired data, scene composition remains a confounder.

A small network selecting weights among constrained LUTs is a relevant later architecture; image-adaptive 3D LUT research supports that form, including unpaired learning. It does not demonstrate recovery of a particular camera from arbitrary internet photos. Skin-focused research motivates local evaluation rather than global histogram matching. [Adaptive LUTs](https://arxiv.org/abs/2009.14468), [controllable portrait enhancement](https://arxiv.org/abs/2406.15848), [background-dependent skin correction](https://arxiv.org/abs/2105.09034)

No model was retrained or deployed in this research pass. The installed Classic v2 remains unchanged. The useful expansion is source provenance, verified iPhone reference files and a clearer portrait coverage gap, not a measured increase in Canon accuracy.
