# Preview frame-timing correction

User reported lag and supplied Digi IMG_9715 3.JPG and stock Camera IMG_9716 3.JPG. Visual comparison shows deeper Digi shadows and stronger contrast; framing differs and these are separate exposures, so pixel differences cannot isolate the filter. No new Canon accuracy conclusion is justified.

The filtered preview required each incoming timestamp to be at least 1/24 second after the last accepted frame. At a regular 30 fps input, adjacent frames are only 1/30 second apart: alternate frames were rejected, limiting delivery to 15 fps. A deterministic ten-second timestamp simulation confirmed 15 fps at 30 fps input and 20 fps at 60 fps input. These are scheduling results, not measured physical-device FPS.

Removed the timestamp limiter. The serial preview queue, alwaysDiscardsLateVideoFrames, and single outstanding main-thread frame semaphore still bound work and prevent an unbounded backlog. Render size and the photo profile are unchanged. The preview can now accept each available input frame when rendering and presentation keep up.

Signed device build passed, all 14 processing tests passed, whitespace checks passed. Actual frame delivery, thermal impact and perceived motion on the device still need measurement. Remaining preview costs include Core Image CGImage materialization and per-frame published SwiftUI updates; direct GPU presentation is a potential later improvement if profiling shows those costs matter. This change does not promise 30 or 60 fps under every light level.
