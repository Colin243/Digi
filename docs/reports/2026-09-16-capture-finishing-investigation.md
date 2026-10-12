# Capture finishing investigation and installation

## Installed

The signed build in `output/ios-device/Build/Products/Debug-iphoneos/Digi.app` installed successfully on the user's iPhone 17 Pro on September 16. It contains the camera picker, always-enabled available G12 profile, focus, flash modes and quality-prioritized capture. Launch was denied because the phone was locked. No experimental portrait mask or finishing filter was deployed.

## New local experiment

Ran `research/regression/probe_person_masks.swift` on the six previously selected private portrait samples, entirely locally. Apple's Vision accurate person segmentation produced six masks. First request: 2.36 seconds. Subsequent requests: 0.067–0.100 seconds on this Mac. Those timings cover Vision processing, not PNG export or end-to-end capture, and are not iPhone benchmarks. Outputs and measurements are in `output/portrait-segmentation/`.

Visually inspected the held-out window-light source and mask plus the night mask. The window-light mask covers the head, torso, arms and legs, improving spatial coverage over the previous face ellipse. However, it also includes much of the dog held by the subject and all clothing. It is therefore unsuitable as a skin mask. The night example produces a nonempty person silhouette even though the prior face detector confidence was below its cutoff. This is a useful fallback observation, not an accuracy score. No annotated segmentation ground truth exists for these samples.

## Proposed saved-photo pipeline

1. Capture quality-prioritized image and actual exposure/flash metadata. Prefer retaining the processed pixel buffer for the next prototype to avoid an initial lossy JPEG round trip; inspect pixel color space and orientation explicitly. Do not switch input pipelines without rechecking the existing LUT.
2. Probe `availableSemanticSegmentationMatteTypes` on the actual rear-camera configuration. Request skin/hair mattes only when supported, configuring the output before session startup. The current single-wide camera path is not proven to support them. Capture can return no matte even when requested. Missing or suspect mattes must fall back safely.
3. Estimate scene class conservatively from capture metadata and image evidence: daylight, warm/mixed ambient and fired flash. Do not infer illumination from average image color alone: a blue wall is not proof of cool light. Mixed light may need local rather than whole-image correction.
4. Apply an evidence-backed color/tone profile with bounded scene adjustments. Skin-specific adjustments use an actual skin mask, protecting individual complexion and highlights. A person mask can constrain the region but cannot by itself distinguish skin, clothing, hair or held objects. Avoid fixed hue-threshold skin detection as the sole solution.
5. Evaluate a mild, bounded noise/detail finishing pass. `CINoiseReduction` exposes noise and sharpness controls; its availability does not mean its default settings are appropriate for already processed iPhone images. Compare no-op, mild noise reduction, and noise reduction with restrained sharpening. Use skin and hair masks to avoid waxy skin and haloed hair, not to reshape faces.
6. Export once at full captured dimensions with valid orientation and metadata; auto-save only the finished image. Keep heavy analysis on the existing photo-render queue. Measure preview frame delivery during rendering because background work can still compete for GPU/memory.

This sequence is a proposed experiment, not a newly fitted model. Parameter values must be selected using held-out comparisons rather than arbitrary strong settings. A finishing pass is not super-resolution and cannot restore clipped highlights or missing fine detail reliably.

## Flash and color implications

The flash branch must follow resolved `isFlashEnabled`, not the requested Auto/On state. Subject distance, ambient exposure and specular clipping need repeatable device samples. Person-background separation can help assess brightness balance, but darkening every background or whitening every face would be an aesthetic effect, not G12 calibration. The iPhone's flash timing, energy and illumination pattern cannot be assumed equivalent to Canon's.

Image-adaptive LUT research supports selecting/blending small color transforms efficiently. It does not supply G12 coefficients or separate camera rendering from lighting and editing in arbitrary web photos. Keep default G12, Portrait scene, My Colors variants and edited social examples labeled separately. Avoid training all of them toward one average skin hue.

## Acceptance before shipping

- Review face/neck/arm consistency across skin tones and lighting, including multiple people, small faces, occlusion, pets, warm walls and skin-colored clothing.
- Compare equal-size images and detail crops for noise reduction versus real texture loss; reject sharpening halos and invented detail.
- Check portrait/landscape mask alignment, mirrored/oriented images and empty-mask fallback.
- Measure warm/cold shutter-to-save time, peak memory and preview delivery on iPhone 17 Pro, then independently on the gift iPhone 15 Pro.
- Retain scene/photographer-separated evaluation; repeated crops from one portrait do not expand independent evidence.

## Primary sources

- Apple photo segmentation overview: https://developer.apple.com/videos/play/wwdc2019/260/
- Person segmentation: https://developer.apple.com/documentation/vision/vngeneratepersonsegmentationrequest
- Noise/detail filter: https://developer.apple.com/documentation/coreimage/cinoisereduction
- Flash result: https://developer.apple.com/documentation/avfoundation/avcaptureresolvedphotosettings/isflashenabled
- Adaptive LUT paper: https://arxiv.org/abs/2009.14468
- Canon G12 modes and custom color controls: https://www.usa.canon.com/support/p/powershot-g12
- Installed Xcode AVFoundation headers verified that segmentation support varies with configuration, may return nil, and may add significant capture processing time.
