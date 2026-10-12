# G12 portrait reference follow-up — September 16, 2026

## Findings and source quality

Seven source/lead records added to `research/portrait-sources.json`. No new original JPEGs authenticated or admitted to training. No model weights or installed app changed in this research pass.

- [honeypnd on Lemon8](https://www.lemon8-app.com/@honeypnd/7379987734275998209?region=th): accessible main caption identifies G12 and describes adjusting flash with conditions; carousel descriptions identify Program plus flash at night. Author links Instagram @honeypnd. Instagram profile could not be opened; original pixels/EXIF and editing history were not verified. This is a useful social portrait direction, not a camera calibration target. Do not attribute the site's extended search-oriented prose to the author without further verification.
- [Gman80918 self portrait](https://www.flickr.com/photos/30341494@N07/8711896515/): owner labels G12, taken May 5, 2013. Outdoor portrait candidate; flash, EXIF and editing unknown. All rights reserved.
- [Doug Jackson G12 sample](https://www.flickr.com/photos/dougweb1000/5602667498): owner explicitly discloses ST-E2 wireless triggering and external Canon flash. Useful lighting comparison, unsuitable as evidence of the built-in flash alone.
- [Rocco's Lab self portrait](https://www.flickr.com/photos/roccoslab/6548586723/): search lead only; page/metadata unavailable.
- [Salisawangs Lemon8](https://www.lemon8-app.com/@salisawangs_/7316800074581852673?region=th): search lead only; page unavailable. No settings admitted from expanded search prose.
- [CameraLabs](https://www.cameralabs.com/canon_powershot_g12/3/): strongest existing controlled portrait lead. Publisher labels Program + flash, ISO 200, 1/1000, f/4.5 at 140 mm equivalent, with AWB and My Colours Off. Treat its portrait as one scene, not several independent samples from crops. Files are offered for personal evaluation, with republication restricted.
- [PhotographyBlog](https://www.photographyblog.com/reviews/canon_powershot_g12_review): explicit flash and red-eye portrait comparisons. Previously encountered image-host denial remains; no bypass attempted.

Direct image links in this pass did not render successfully. Conclusions above are based on source captions/documentation, not a fresh pixel-level visual comparison.

## What this changes about the model direction

[Canon specifications](https://www.usa.canon.com/support/p/powershot-g12) describe facial brightness in exposure/flash metering and facial color in white balance under Face AiAF. [Canon's scene-mode instructions](https://asia.canon/en/support/8200922600) separately describe a soft portrait effect. These establish behaviors to investigate; they do not specify numerical color curves or prove our current face-mask blend is faithful.

1. Separate default daylight, indoor ambient, and direct-flash portraits. Keep external-flash, edited social posts and Portrait/My Colors settings separately labeled. Do not average all of them into one global curve.
2. Extend the experimental face treatment coherently to visible neck and arms, with person/skin masks and feathered boundaries. Preserve individual skin tone; do not drive every face toward a common peach or lighter target. Low-confidence detection should fall back safely.
3. Evaluate subject-to-background brightness, highlight clipping, skin hue/chroma, texture and sharpening separately. Current face-only contrast protection cannot recreate the lighting of a real flash.
4. Use captured flash state and exposure metadata to select processing. Test physical iPhone flash at several subject distances; its light cannot be assumed equivalent to G12 flash or replaced by a global brightness change.
5. Fit small, regularized adjustments per lighting group only after original candidates are verified. For unpaired photos, compare matched lighting and subject regions; whole-image histogram matching will confuse backgrounds and subject composition with camera response. Keep authors/shoots disjoint between fitting and evaluation.
6. Evaluate on held-out iPhone 17 Pro people in daylight, window light, warm indoor light and flash; check face/neck/arm consistency and failure cases. Existing six portraits are a small starting set, not representative validation. There are no verified local flash examples yet.
7. Keep segmentation off the per-frame critical path: first validate saved-photo output, then low-resolution asynchronous preview masks with tracking and time smoothing. Measure actual device frame delivery before shipping.

## Accuracy boundary

Public reference photos can help match a portrait aesthetic. Unpaired images with unknown edits cannot identify an exact iPhone-to-G12 color transform or justify a percentage accuracy claim. More independent verified portrait sessions are more valuable than hundreds of reposts of one shoot. Neither pixel error nor skin-color differences across different people are valid camera-fidelity scores.
