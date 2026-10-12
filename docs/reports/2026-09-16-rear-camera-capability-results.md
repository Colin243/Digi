# iPhone 17 Pro native skin-mask capability result

Built, signed, installed and launched Digi with `--mask-study` on the user's iPhone 17 Pro. Retrieved the actual device capability report at `output/mask-capabilities.json`.

| Camera configuration | Depth supported | Skin type advertised | Flash hardware |
| --- | --- | --- | --- |
| Physical wide | No | No | Yes |
| Dual | Yes | Yes | Yes |
| Dual wide | Yes | Yes | Yes |
| Triple | Yes | Yes | Yes |

Each probe used the photo preset and a connected video output. The three virtual configurations advertised skin mattes even before enabling depth. The experiment selected the first compatible camera with flash hardware: rear dual. Capture requests now request enabled depth and skin delivery in study mode. A missing matte continues to be recorded rather than treated as successful segmentation.

Normal launches retain the physical-wide configuration and existing rendering. Study mode probes once during startup, requests optional masks and exports diagnostic captures; it does not alter skin color or add segmentation work to preview frames. Capability probing and extra capture processing may affect startup/capture latency and require measurement.

Verification: signed device build succeeded; 25 existing Python regression tests passed; installation and launch succeeded; capability report was copied back from the device. These tests do not validate native mask geometry. Actual skin delivery, alignment, neck/arm coverage, false-positive behavior, flash interaction and image quality remain unverified until new captures are inspected. No G12 color accuracy improvement is claimed.

Next test: keep this launched session open and take a portrait with neck/arms visible, a no-person scene and an additional flash portrait. Retrieve the new original/mask/metadata bundles. Verify masks before enabling any skin treatment. Force-quitting/reopening the app normally removes the study launch argument; relaunch from the development tools to resume diagnostics.
