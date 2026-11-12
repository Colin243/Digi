# Selected-subject replay (#11)

A dependency-free browser experiment for following **one explicitly selected subject** in a recorded clip. No VLM, training labels, face recognition, camera permission, phone or network service is used.

Open `tracking-replay/index.html` directly in a current desktop browser, or serve it:

```sh
python3 -m http.server 8776 --bind 127.0.0.1 --directory tracking-replay
```

Then open `http://127.0.0.1:8776`.

1. Click **Run synthetic crossing** for a complete demo. It selects the red torso, follows it towards the blue figure, and stops with **LOST** when the blue figure occludes it. There is no automatic reacquisition when they separate.
2. To use a real recording, choose a local video (H.264 MP4 is a useful starting point), pause at a clear frame, and drag a tight box around the selected person's torso. Press **Play**.
3. The box follows a local appearance match. A missing match, sufficiently similar competing match, a seek, or a playback gap over 0.3 seconds clears the box and reports **LOST** with a reason. Only a new explicit box selection resumes tracking. Restart removes the selection.
4. **Export events** downloads JSON containing the source kind (`synthetic` or `recorded`), local filename for recorded clips, coordinate dimensions, explicit selections, loss transitions and every sampled result with its replay timestamp. Clips and pixels are not included in the export.

The file chooser and exported filename are local to the page; the demo makes no network requests. Video pixels are downscaled with their original aspect ratio (long edge 320 px). Boxes are expressed in that downscaled coordinate space. Processing runs at approximately 10 updates per second; slow decoding or processing can produce a conservative loss.

## What the prototype does

`tracker.cjs` freezes an 8 × 12 RGB sample of the original selected box. Each update searches nearby boxes at the same scale. It accepts a low-error match only when there is no similarly plausible spatially separated rival. The template never adapts, so it cannot learn an occluder as its new appearance. `session.cjs` owns explicit selection, sticky loss and timestamp discontinuities. The browser draws the overlay only when a current match exists.

**This is appearance tracking, not a guarantee of identity continuity.** Similar clothing, complete overlap followed by a different lookalike, abrupt motion, zoom, lighting changes, and scale changes can still produce an incorrect match or early loss. It deliberately prefers losing over guessing, but cannot detect every identity substitution. Thresholds are prototype constants, not calibrated confidence scores. There is no automatic subject selection or identity recovery.

## Verification and remaining work

```sh
node --test tracking-replay/*.test.cjs
```

The 22 regressions cover selected appearance, distinct and similar-color crossings, disappearance, occluders, sticky loss, reselection, reset, invalid frame data, resolution changes, seeks, frame gaps, export isolation, and the actual browser controller's synthetic run and portrait dimensions through a minimal DOM/canvas harness.

The built-in figures are **synthetic raster fixtures**, not recorded people or real-person accuracy evidence. No real-person clips are bundled or evaluated. The DOM/canvas harness verifies controller wiring; it does not verify browser video decoding or visual layout. Before considering camera integration, replay consenting real-person clips with two people crossing, temporary occlusion, matching clothes, portrait/landscape framing, lighting/scale changes, and leaving/re-entering frame. Review exported timelines against the original selected person. Record any silent switches as failures, and measure lost-track rate separately. Detector/reidentification integration and live iPhone tracking are outside this replay prototype.
