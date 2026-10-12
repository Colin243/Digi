# Depth-induced framing regression

The new diagnostic originals recorded a 100mm-equivalent focal length, compared with 24mm in the previous physical-wide captures. The change followed enabling depth delivery on the selected dual camera. The installed SDK documents that depth delivery constrains available zoom factors. No user zoom control or renderer crop was introduced.

Removed depth opt-in from both the capability probe and live study session; explicitly reset study-camera zoom to 1 (bounded by the available minimum). Skin mattes remain requested when advertised. Prior on-device reports advertised skin support before depth was enabled, but actual delivery without depth still requires testing.

The retrieved dual-camera session contains four new captures: two with skin mattes and two without. One delivered mask was visually inspected: it broadly covers the close-up face/neck and excludes the mouth and much of the background. Close framing prevents meaningful arm coverage assessment. No numerical segmentation accuracy claim is justified.

Verification: signed device build succeeded; 25 existing Python regression tests passed. Those tests do not test AVFoundation zoom behavior. Installation succeeded. Launch failed because iOS reported the phone locked. A subsequently retrieved capability file may belong to the prior launch and is not evidence that the fix ran. Physical framing and matte delivery remain pending an unlocked test.

No new skin color processing was enabled. The experiment remains available only through the `--mask-study` launch argument; an ordinary launch uses the physical-wide camera.
