# Still-photo quality investigation

## Applied change

Digi now sets the photo output's maximum quality prioritization and each photo request's quality prioritization to `.quality`. This asks AVFoundation to favor image quality over capture delivery speed. It adds no filters or analysis to the preview. Actual capture latency, resource contention and image improvement require physical-device testing; this setting is not a promise of better results than Apple Camera.

## Capture/render audit

Current pipeline: processed JPEG capture, full-resolution Core Image color LUT, JPEG export at 0.96 quality. Only the live preview is reduced to 960 pixels. The saved photo does not use that reduced preview. There is no existing super-resolution or detail reconstruction pass. JPEG decoding/re-encoding is another quality consideration; a future pixel-buffer or RAW path could reduce intermediate losses, but changes color-pipeline assumptions and needs a separate profile validation.

Resolution is unchanged in this update. Xcode's installed AVFoundation headers state that 5712×4284 (24 MP) delivery requires opting into deferred photo delivery. That is not a drop-in change for a pipeline which must finish custom styling before saving. The alternative of full supported high-resolution output needs memory and latency measurements with the existing full-image renderer; do not assume more pixels improves dim-light results. Do not enable deferred delivery without handling its proxy callback and defining how the final styled asset is produced.

## Lens and target quality

Canon documents a 10 MP CCD with a 28–140 mm equivalent f/2.8–4.5 zoom lens. Apple's iPhone 17 Pro main camera is 48 MP with a 24 mm equivalent f/1.78 lens. Aperture affects exposure and depth of field; identical f-numbers on different sensor formats do not imply matching depth of field. Digi cannot physically stop down the iPhone lens. Any future depth-based blur should be described as simulated, and should not be confused with higher captured detail.

The goal is natural, well-resolved photographs with the desired G12 rendering, not maximum sharpening or softness. A G12-inspired profile need not deliberately reduce the output to 10 MP.

## Next finishing experiment

Use the saved-photo queue, preserving the lightweight preview. Compare current output against candidates using limited noise reduction and edge-aware detail enhancement, adapting conservatively to noise/exposure evidence. Protect facial texture and consistent face/neck/arm rendering. Do not generatively invent eyes, hair, text or skin detail. A soft image with lost detail cannot be reliably reconstructed from one JPEG.

Hold out scenes across daylight people, backlit people, warm indoor light, flash portraits, fine fabric/hair and dim light. Inspect equal-size images and 100% crops for halos, waxy skin, noise, clipping and detail loss. Measure shutter-to-save duration, memory and frame delivery during capture. Repeated Apple Camera comparisons must match viewpoint, lighting and subject movement as closely as possible. Do not claim superior quality until the comparisons support it.

## Sources

- https://developer.apple.com/documentation/avfoundation/avcapturephotosettings/photoqualityprioritization
- https://developer.apple.com/documentation/avfoundation/avcapturephotooutput/maxphotodimensions
- Installed iPhoneOS SDK: AVFoundation/AVCapturePhotoOutput.h, maxPhotoDimensions and deferred-delivery requirements.
- https://www.usa.canon.com/support/p/powershot-g12
- https://my.canon/media/migration/local/my/stage/press_room/canon_news_10/dec/chip.pdf
- https://www.apple.com/ie/iphone-17-pro/specs/

No denoising, upscaling, synthetic aperture, new regression fit, or physical-device evaluation was performed in this update.
