# Social portrait evidence and first spatial candidate

## What was actually accessible

Direct XHS searches did not expose verifiable original posts or original files. Search-indexed SMZDM reposts attribute recipes to XHS, including flash and cooler/lighter skin styling. They are unverified secondary descriptions, not authenticated camera settings, a representative popularity survey, or calibration targets. We did not train on them or count them as new G12 portraits.

- XHS-attributed repost discovery: https://post.m.smzdm.com/zz/p/akolmv68/
- Recipe aggregation, full page unavailable: https://post.smzdm.com/p/a82l22k6/
- A first-person G12 beach post explicitly reports Program mode, flash on and VSCO adjustments: https://www.reddit.com/r/VintageDigitalCameras/comments/15uohdo
- Another G12 discussion describes exposing background and flash-lit subject separately, but supplies advice rather than controlled measurements: https://www.reddit.com/r/CanonCamera/comments/1wc0427/people_for_canon_g12/
- Canon confirms G12 white-balance presets and custom color/skin-tone controls: https://www.usa.canon.com/support/p/powershot-g12

Inference: the desired social portrait aesthetic combines lighting, selected camera settings and sometimes editing. Increasing global contrast cannot reproduce those causes. There is insufficient evidence here to estimate a unique G12 portrait color matrix or claim greater physical-camera accuracy.

## Implemented research change

`research/regression/portrait_look.py` adds spatial protection to the existing Classic model. Apple Vision detects normalized face rectangles locally via `detect_portrait_faces.swift`; detections below confidence 0.7 are ignored. Feathered elliptical masks blend between full Classic and its fitted base with only 25% of the additional designed layer. These parameters are design choices, not regression estimates from social images. No identity recognition, facial reshaping or fixed target skin color is used.

The experiment used six existing local portrait candidates, retaining their earlier splits: four train, one evaluation, one night stress. Five pass the confidence cutoff; the night image safely retains Classic. Six comparisons and the detection/measurement report are under ignored `output/portrait-model/`. Personal images remained local.

Seventeen processing tests pass, including no-face identity to Classic, locality, finite bounded output, confidence rejection and Vision-to-image vertical-coordinate conversion. The held-out window-lit portrait comparison was visually inspected. The global visual change is deliberately small because face regions occupy a small portion of the frame; global mean difference is not an accuracy metric.

## Why not deploy this prototype yet

The mask covers approximate face regions, not precise skin. Neck and arms still receive the stronger global look. On moving people, detection jitter and stale masks could cause visible transitions. Adding synchronous face detection to each preview frame would also undermine the just-fixed fluidity. This research candidate therefore does not replace the installed Classic profile.

Next implementation requirement: coherent exposed-skin protection within a person mask, with confidence fallback, asynchronous low-rate detection/tracking and temporal smoothing; evaluate hands/neck, multiple people, varied observed skin colors, profile/occluded faces and mixed/colored light. Flash-on capture needs separate testing because changing pixels cannot create the missing illumination geometry. A larger verified G12 portrait reference set remains necessary to assess style agreement.

The separate frame-timing correction was built, installed and launched on iPhone 17 Pro. It removes deterministic alternate-frame rejection; no physical-device FPS measurement has yet been made.
