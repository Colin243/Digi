# G12 character: owner experiences translated into rendering tests

Research date: 15 September 2026. Complements the [dataset and regression study](2026-09-14-scene-conditioned-rendering.md). These findings guide experiments; they do not provide measured LUT coefficients. No renderer was changed in this research pass.

## Evidence and implications

| Observation | Source and evidence type | Proposed test for Digi |
| --- | --- | --- |
| Reds and greens can look rich, with selective hue shifts rather than uniform saturation. | [Imaging Resource's own color tests](https://www.imaging-resource.com/cameras/canon-g12-review/) describe stronger reds/greens/browns/blues but more subdued yellow/aqua/cyan, and shifts in cyan/red/yellow. | Fit hue-dependent color changes using neutral-controlled samples. Compare red fabric, foliage, sky and skin separately. Do not boost every color equally. |
| Skin rendering is not uniformly warm. | The same lab review reports slightly cool lighter skin and a warmer/yellowish result on darker skin in its test images. This is limited test-scene evidence, not a universal rule about skin. | Preserve the person's skin tone and test diverse complexions under each light. Do not encode different desired skin colors by demographic or apply blanket whitening. |
| Low-ISO output can be clean and detailed. | [DPReview's studio testing](https://www.dpreview.com/reviews/4522799364/canong12/) describes strong results through ISO 400, with noise/noise reduction becoming more evident at 800+. [PhotographyBlog's own review](https://www.photographyblog.com/reviews/canon_powershot_g12_review) similarly reports more noise and reduced color at higher ISO. | Make noise and fine-detail response depend on exposure and source-device behavior. Compare full-resolution low/high-ISO samples. Avoid constant film-grain overlays. Thresholds reported for G12 ISO do not transfer directly to iPhone ISO. |
| Enthusiasts value flash portraits. | A [G12 beach photographer](https://www.reddit.com/r/VintageDigitalCameras/comments/15uohdo) praises flash skin tones, while disclosing VSCO adjustments. The indexed post identifies Program mode and flash on; the full page could not be opened in this pass. | Keep this in the aesthetic-reference group, not default-JPEG calibration. Test real flash capture, subject/background exposure and highlight preservation together. |
| Strong flash and bright daylight are part of one owner's appeal; editing matters. | A [firsthand Weibo account dated 28 April 2025](https://weibo.com/6631077872/PpoJsC2tK) praises flash strength, clarity and sunny-day results, and explicitly emphasizes postprocessing. Their numerical claim about how many online pictures are edited is an opinion, not survey evidence. | Create a flash/ambient branch and assess sunny backlit portraits. A color LUT cannot reproduce different flash placement, power or physical shadows. |
| Some admired straight-out-of-camera colors use a specific preset. | The indexed [First day with Canon G12](https://www.reddit.com/r/VintageDigitalCameras/comments/15fw5tt) post identifies Positive Film. Full-page retrieval failed, so interpretation is limited to the indexed text. Canon's manual independently explains the preset. | Label target mode. Do not combine My Colors Off, Positive Film, custom settings and edited images into one supposedly default camera target. |
| The camera offers several distinct renderings. | [Canon G12 User Guide](https://gdlp01.c-wss.com/gds/1/0300004191/01/PSG12_CUG_EN.pdf), page 88, inspected in the locally downloaded manual: Positive Film emphasizes red/green/blue; Vivid and Neutral alter contrast/saturation; Custom Color controls include sharpness and skin tone. | Establish the default baseline first. Explore Positive Film as a separately named in-camera-style variant later. Its name is not evidence of actual film response or grain. |

The Imaging Resource observations above are directions to investigate, not enough data to derive numeric color transformations. Their white-balance tests also vary by setting and illuminant. A single universal yellow tint would discard this conditional behavior.

## Chinese-language and Xiaohongshu coverage

Chinese-language searches included G12 color, flash, straight-out-of-camera output and Xiaohongshu. They surfaced many reposts and shopping-page summaries claiming creamy skin, cool flash portraits or film-like color. Direct Xiaohongshu posts were not verified in this pass. Those secondhand summaries are discovery leads only: no platform-wide consensus, popularity count or exact camera-setting recipe is inferred from them.

The directly accessible Weibo owner account is useful independent testimony, but one account is not representative of all Chinese photographers. Its comments were not available as a complete discussion. Reported editing and settings should accompany any future example collected from social platforms.

## Rendering direction for the next experiment

The working target is clear low-ISO detail, selective color richness and lighting-dependent white balance, with a separate response for actual flash captures. This is our engineering interpretation of the evidence, subject to image comparison.

Keep three target categories in research metadata: default G12 JPEG, identified in-camera color mode, and edited G12-inspired aesthetic. These can share a future UI, but should not share indistinguishable training labels. The current verified CameraLabs originals have documented My Colours Off, so they remain useful anchors for the first category.

For the iPhone 17 Pro iteration:

1. Fit a restrained base color/tone candidate against verified references, treating unpaired comparisons as aesthetic evidence only. Retain identity as a baseline.
2. Compare scene-conditioned daylight, warm indoor, mixed light and actual flash candidates. Blend smoothly and avoid classifying a warm-colored background as proof of warm illumination.
3. Test rich greens and reds without oversaturating faces. Include neutral objects and multiple skin tones; reject hue discontinuities and clipping.
4. Assess highlights, shadow separation and fine detail before adding noise. Do not globally crush shadows to manufacture nostalgia, blur faces to manufacture softness, or add defects reported only on damaged cameras.
5. Use owner descriptions for human evaluation prompts: natural skin, convincing flash/ambient balance, appealing foliage/sky color, credible low-light texture. Keep these preference ratings separate from paired color-error measurements.

No trustworthy numerical saturation multiplier, skin-tone offset, noise strength or sensor-matching percentage can be extracted from these descriptions alone. Text supplies hypotheses and evaluation criteria; original images and controlled captures supply calibration evidence.

## What changes in our research plan

Add target color-mode and editing provenance to future reference intake. Prioritize flash portraits and indoor lighting over more near-duplicate outdoor scenes. Evaluate a camera-faithful baseline and an optional expressive aesthetic separately. Continue using the iPhone 17 Pro for the current iteration, while retaining iPhone 15 as an independent validation target for the gift build.
