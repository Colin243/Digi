# ios-bench: on-device Qwen3-VL-2B benchmark (issue #7)

A small standalone iOS app that runs `mlx-community/Qwen3-VL-2B-Instruct-4bit` on the phone with [mlx-swift-lm](https://github.com/ml-explore/mlx-swift-lm) 3.32.3 (`MLXVLM`, `Qwen3VL.swift`). It uses the same decomposed prompts (v4, keys format) and the same test photos as the Mac benchmark. It does not touch the Digi app in `../../ios/`.

The method, budgets and go/no-go criteria are in [`../docs/iphone-benchmark.md`](../docs/iphone-benchmark.md).

## What it measures

For each run it writes one JSON file to the app's `Documents/results/` and saves it after every trial, so a jetsam kill still leaves the data:

- **Load:** cold load time, then a reload after unloading.
- **Every model call:** time to first token, prefill, decode and end-to-end time; prompt and generation tok/s; peak `phys_footprint` sampled every 25 ms; minimum `os_proc_available_memory`; MLX peak memory; thermal state before and after.
- **Camera:** around every trial, an `AVCaptureSession` (back camera, `.photo` preset) is stopped before inference and restarted after. It records the stop time, the `startRunning()` time and the time until the first video frame arrives (capture recovery).
- **Run context:** device model, iOS version and build, RAM, GPU, battery, Low Power Mode, uptime, and network status (unreachable means airplane mode). It also records exact package versions (from the bundled `Package.resolved`), the model revision and the prompt version.
- **Events:** thermal changes, memory warnings, camera interruptions and errors, and app backgrounding.

Failures are handled without crashing:

- A memory pre-check before loading.
- A load failure shows a fallback message instead of crashing.
- The first memory warning clears MLX's cache; a second one stops the run and unloads the model.
- Thermal state `critical` or the app moving to the background stops the run after the current call.
- If a report is still marked "running" at the next launch, it is marked `terminated`, which most likely means jetsam.

## Setup (Mac)

```sh
cd photography-ai
uv run photo-ai dataset fetch          # once: test photos into samples/ (git-ignored)
uv run --no-project --with pillow --with huggingface_hub \
    python ios-bench/scripts/prepare_assets.py
```

This writes `Resources/prompts.json` (committed), `Resources/BenchImages/` and `Resources/Model/` (both git-ignored). The model folder holds the pinned 1.8 GB snapshot `9c4f5209e57b`, the one Phase 3 used, taken from the HF cache or downloaded once. The app never uses the network.

If you have no `samples/`, pass `--samples /path/to/photography-ai/samples`.

## Build and install

You need Xcode 27 and the Metal Toolchain (`xcodebuild -downloadComponent MetalToolchain`, about 840 MB, needed to compile MLX's shaders). Then:

```sh
cd photography-ai/ios-bench
xcrun devicectl list devices            # phone must show "available (paired)"
xcodebuild -project IOSBench.xcodeproj -scheme IOSBench -configuration Release \
  -destination 'generic/platform=iOS' -derivedDataPath build/dd -allowProvisioningUpdates build
xcrun devicectl device install app --device <device-id> build/dd/Build/Products/Release-iphoneos/IOSBench.app
```

Or open `IOSBench.xcodeproj` in Xcode, select the phone and press Run. The shared scheme runs the **Release** configuration with no debugger attached, so the numbers aren't slowed down.

The app is about 1.7 GB, because the weights are inside the bundle. If you'd rather keep weights out of the app, copy `Resources/Model` to the app's `Documents/Qwen3-VL-2B-Instruct-4bit/` (with Finder's Files tab or `xcrun devicectl device copy to … --domain-type appDataContainer --domain-identifier com.colin.digit.iosbench`); a copy there takes precedence.

## Run (phone)

1. Charge to more than 50% and unplug. Close other apps. Let the phone cool down if it's warm.
2. Turn on **airplane mode**. Wi-Fi and Bluetooth must also be off.
3. Open **Digi Bench** and allow camera access. Keep the screen on and the app in the foreground.
4. Run **Quick**, then **Standard**, then **Soak**. Each run writes its own JSON.
5. Turn airplane mode off. Under Results, tap each file and AirDrop it to the Mac. Alternatively, use Finder → iPhone → Files → IOSBench → `results`.

## Summarize

```sh
python3 photography-ai/ios-bench/scripts/summarize.py ~/Downloads/bench-*.json
```

This prints the markdown tables and budget check for `docs/iphone-benchmark.md`.

## Mac check of the same Swift code

`MacSmoke/` is a command-line package that runs `ModelHost.swift` and `PromptKit.swift` (symlinked from `IOSBench/`) on a Mac:

```sh
cd photography-ai/ios-bench/MacSmoke
xcodebuild -scheme MacSmoke -destination 'platform=macOS,arch=arm64' -configuration Release \
  -clonedSourcePackagesDirPath ../build/spm -derivedDataPath ../build/dd-mac build
../build/dd-mac/Build/Products/Release/MacSmoke ../Resources 1024 2
```

## Files

| path | what |
|---|---|
| `IOSBench/BenchRunner.swift` | Run plan, trials, camera pause/resume, failure handling, JSON output |
| `IOSBench/ModelHost.swift` | Local-only model load, tokenizer adapter, one timed generation |
| `IOSBench/PromptKit.swift` | Loads `prompts.json` and the image manifest; fills in the decomposed prompts |
| `IOSBench/CameraProbe.swift` | Capture session with first-frame timing |
| `IOSBench/Probes.swift` | Memory (`task_vm_info`, `os_proc_available_memory`), thermal, network and device info |
| `IOSBench/Records.swift` | The JSON schema |
| `Config/IOSBench.entitlements` | `com.apple.developer.kernel.increased-memory-limit` |
| `scripts/prepare_assets.py` | Exports prompts, test images and pinned weights |
| `scripts/summarize.py` | Turns results JSON into the doc tables and budget check |
