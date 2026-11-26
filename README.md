# Digi

**Digi turns a photo you love into step-by-step directions for recreating it with your own camera, wherever you are standing.** Pick 3 to 5 reference photos and a photo of your location, and Digi proposes three shots: where to stand, how high to hold the phone, the angle, the distance and zoom, and how to use the light. Pin one and the viewfinder coaches you live: level, tilt, framing, and when to step closer. It is an iPhone camera app with a G12-inspired digicam look.

## What works today

| Part | Status |
|---|---|
| Camera app (SwiftUI, iPhone 17 Pro tested) | Capture, Photos saving, G12-inspired look, portrait and landscape |
| Inspiration Director (reference photos to three shots) | Working end to end through a Director server on a Mac. With the photos read ahead, the first shot appears in about 5.5 s and all three in about 15 s |
| Portrait and Scenery modes | Working: one scene photo plus a style gives shots |
| Live guidance (level, tilt, subject framing, distance cue) | Partly built: person and face tracking, one cue at a time. Body pose, lighting cues and a target frame are not built |
| On-device (offline) Director | Prototype only. A 14 November run took about 40 s for three shots; the model is not bundled in the app |

## Status and limits (read this first)

- This is a one-developer prototype, not a released product. It has not been user-tested yet.
- Quality has been measured on 14 test scenes with automatic checks, plus an AI-assisted blind rating. Human-reviewed ratings and labels are still to come.
- The shot-planning model is a small fine-tuned vision-language model (Qwen3.5-2B family, run with MLX). Whether fine-tuning beats the base model or a hosted model has not been shown on human ratings.
- The Director server runs on a Mac. There is no hosted service.
- Privacy by design: live guidance analyses preview frames in memory and drops them. Photos sent to the Director server are deleted after each request, and API keys are stored hashed.
- No open-source license has been chosen. All rights reserved.

## How it works

1. The app reads each photo as you pick it, on the Director server: a short note per reference photo, a reading of your scene, then the shared style.
2. When you press Plan, the model writes three shots, streamed one at a time.
3. Zoom and distance are set by a rule in the app from the room you have to step back, so the advice fits the place.
4. A pinned shot becomes a guide card over the viewfinder, with live cues from the camera.

## Repository map

- `ios/`: the SwiftUI app and `DirectorKit`, the Swift package for shot planning, routing and live guidance.
- `photography-ai/`: the Director server, the benchmark and training tools, and the evaluation UI.
- `prototype/`, `tracking-replay/`, `research/`: browser study, tracking replay and research notes behind the camera look.
- `docs/`: design, plans and reports.

## Camera app foundation: what exists today

- Approved product design in `docs/superpowers/specs/2026-09-13-digicam-design.md`.
- Interactive browser study in `prototype/`, with an explicitly uncalibrated photo treatment and modeled save flow.
- Seventeen automated simulation tests and documented manual browser tests.
- Research audit and USB installation plan in `docs/reports/`.

The native iOS app lives in `ios/Digi.xcodeproj` and supports rear-camera capture, automatic Photos saving, portrait/landscape rotation, tap-to-focus and exposure lock, brightness adjustment, flash Off/Auto/On, and an opt-in local skin-mask capture study. The separate browser study simulates camera flows; its manual ISO and shutter controls are not yet implemented in the native app.

## Public source and private data

This repository contains the app source, bundled experimental color profile, browser prototype, tests, research scripts, and development notes. Personal photos, downloaded reference images, exported masks, device diagnostics, signing profiles, and compiled app builds are excluded. Research tools that depend on private samples require your own local inputs; the complete training/evaluation dataset is not distributed here.

Choose your own signing team and bundle identifier in Xcode before installing on a physical iPhone. The checked-in team identifier is local project configuration, not a signing certificate or credential. Free Personal Team installations require periodic provisioning renewal.

## Run the study

Requirements: Node.js and Python 3. No npm dependencies.

```sh
node --test tests/simulation.test.cjs
node prototype/build.cjs
python3 -m http.server 8765 --bind 127.0.0.1 --directory prototype
```

Open http://127.0.0.1:8765 in a browser. The viewfinder fills the phone; the bottom-right options button reveals exposure, white balance, and adaptive tone controls. The full-screen crop matches the simulated saved image. Comparison and synthetic sample-light tests sit outside the depicted phone. Auto WB and adaptive tone are untrained heuristics, not a learned Canon model. Captures disappear on reload. S95/G7 X are disabled roadmap entries, not implemented profiles.

Use Xcode for native builds and simulator/device testing; see `ios/README.md` for commands.

The default image is NASA's Eileen Collins portrait served by the pinned scikit-image v0.19.3 sample-data repository through jsDelivr. It is not a Canon reference image. If it cannot load, the preview uses labeled synthetic swatches. Local JPEG/PNG/WebP test images can be selected; their pixels remain in the browser. The sample loading itself requires network access.

Use VS Code's `Digi: Test simulation`, `Digi: Build study`, and `Digi: Preview study` tasks. These are browser-study tasks, not iPhone build tasks.

## UI audit checks

The September 14 [audit and plan](docs/plans/2026-09-14-ui-audit.md) records the preserve redesign and validation. Run lint with `npm exec --yes --package=eslint -- eslint prototype/core.js prototype/ui.js prototype/build.cjs tests/*.cjs`. Browser checks use `node tests/browser-flows.cjs` with Playwright available on the Node module path, Chrome installed, the preview server running on port 8765, `output/playwright` created, and the local research fixture `research/g12/references/dkamera-02.jpg`. Screenshots and Lighthouse output stay under `output/playwright`.

The browser study uses landscape framing (16:9), with capture controls on the right. The native app independently supports portrait and both landscape orientations; the user has confirmed correct saved orientation on iPhone 17 Pro.

## Native camera foundation

A native SwiftUI/AVFoundation target now exists at `ios/Digi.xcodeproj`. See [native setup and current limits](ios/README.md). It builds for iOS 18+ with portrait/landscape rear-camera capture and PhotoKit saving. The current iPhone 17 Pro build applies a G12-inspired profile in preview and saved photos; other physical models currently save original output until their profiles are validated. S95 and G7 X remain roadmap entries. Skin-mask validation and portrait/flash-specific fitting remain experimental. This is an aesthetic approximation, not a calibrated reproduction of Canon's rendering.
