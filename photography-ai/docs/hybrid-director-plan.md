# Hybrid Director: online when connected, on-device always

Status (2026-11-14): **Phase 1 is built** (`ios/DirectorKit`, 24 passing tests). **Phase 2's server half is built** (`photo-ai server`, tested against the real model). The Swift `OnlineEngine` client is built too (tests only, no live run yet). The on-device engine and the UI are not started.

## Principles
- **One contract, two engines.** Both return shot-v3 shots through `DirectorEngine`, as a stream, so the UI never knows which engine answered and shot 1 can appear while the rest generates.
- **Online first when allowed**, with a first-shot deadline (6 s) and a total deadline (15 s). Any failure falls back to the phone and tells the UI to clear shown shots (`engineSwitched`).
- **The offline model must be strong enough that falling back is not a downgrade.** That is the job of the LoRA work (#5/#6), not of the router.
- **Photos reach the online model.** That matches what the model is trained on and gives the best results.

## Upload policy
Photos go out by default, with no prompt. A user can choose, in a later Settings screen:

| setting (`UserEnginePreference`) | online request carries |
|---|---|
| `automatic` (default) | the photos |
| `textOnly` (privacy option) | only the on-device scene reading (text) |
| `offlineOnly` | nothing; the phone does everything |

The local server does not serve `textOnly` yet (it answers 422 and the app falls back to the phone). That is deliberately left for the Settings work.

## Routing rules (`Router`, pure and tested)
- Connected: `[online, offline]`. Low Data Mode: `[offline, online]`.
- No connection or offline-only: `[offline]`, nothing uploaded.
- Thermal `critical` or free memory below weights + 1.5 GB: skip the phone. If online is also unavailable, show a plain message.
- Thermal `serious` or Low Power Mode: offline profile shrinks to 768 px, 450 compositions tokens, optional stages skipped.

## Phases
1. **Shared interface (done):** `Shot`, `DirectorEngine`, `DirectorRequest`, `Router`, `HybridDirector`, `SystemConditionsProvider`, tests with fake engines.
2. **Online engine:**
   - **Server (done):** `photo-ai server serve` runs the Scene and Inspiration Directors on this Mac behind our own API key. Keys are made with `server keygen` and only their hash is stored. It allows one analysis at a time, caps each key per hour, deletes uploaded photos after every request, and streams one JSON event per shot (NDJSON, same shape as `DirectorEvent`). Run the identical command on a cloud box later.
   - **App client (next):** a Swift `OnlineEngine` that posts the multipart request and decodes the stream.
   - **Then:** HTTPS for the phone (ATS blocks plain http except for local networking), and measuring latency, failure rate and cost.
3. **Offline engine and hardening (#8, #9):** wrap the benchmarked mlx-swift-lm path as an `OfflineEngine`. Cap compositions at 600 tokens, cache inspiration prep, stream tokens (not text) for JSON stages, fuse and re-quantize the adapter, download weights over Wi-Fi with a checksum, persist finished stages.
4. **Quality (#2, #4, #5, #6, #21):** human-approved labels, the real LoRA run, and a blind eval that scores base, adapter and the online model on the same held-out scenes.
5. **Product UI (#10):** reference picker, streamed shot cards, an online/on-device badge, the offline-only setting. Live guidance (#11-16) needs no model.

## Targets
| | online | offline |
|---|---|---|
| First shot visible | under 5 s | under 10 s |
| Full set | under 10 s | under 30 s (measured on site: 25-37 s, depending on heat) |

## Where Phase 1 lives
`ios/DirectorKit` is a Swift package with no MLX or network dependency. Run `cd ios/DirectorKit && swift test`. It is linked into `ios/Digi.xcodeproj` as a local package. The app has a wand button in the camera header that opens the Director screen (`DirectorView.swift`): pick a place photo (and 3-5 inspiration photos for inspiration mode), choose a style, and watch shots stream in. Server address and client key live in that screen's settings (key in the Keychain). The on-device engine is still a stub (`OfflineEngineUnavailable`), so with no reachable server the screen reports that clearly.

## Where the online client lives
`ios/DirectorKit/Sources/DirectorKit/OnlineEngine.swift` (+ `MultipartBody.swift`): `OnlineEngine(configuration:client:)` POSTs multipart to `<baseURL>/v1/plan` with `Authorization: Bearer <client key>` and maps the NDJSON stream to `DirectorEvent`s (`.online`). The app supplies the base URL and the key from `photo-ai server keygen` (kept in the Keychain; not implemented in the package). Only `upload=photos` is sent; `sceneTextOnly`/`none` throw `onlineUnavailable` without touching the network, so the router falls back to the phone. HTTP errors, `error` lines and streams that end without `finished` also become `onlineUnavailable`. The transport is injectable (`StreamingHTTPClient`; default `URLSession.bytes`), and the tests use a fake. An opt-in live test runs with `DIGI_LIVE_URL`, `DIGI_LIVE_KEY` and `DIGI_LIVE_JPEG` set.

## Running the local server
```bash
cd photography-ai
uv run photo-ai server keygen --label colin-iphone     # copy the key now; it is never shown again
uv run photo-ai server serve --host 0.0.0.0 --port 8787 [--model "qwen3-vl-2b-4bit+adapter=data/adapters/<run>"]
```
Test on the Mac with `curl -N -H "Authorization: Bearer <key>" -F mode=scene -F style=relaxed_candid -F target=@photo.jpg localhost:8787/v1/plan`. A phone on the same Wi-Fi reaches it at `http://<Mac IP>:8787`; for anything beyond that, put it behind a tunnel with HTTPS (Tailscale or Cloudflare Tunnel) rather than opening a router port.

**Honest speed note.** A real scene request took about 59 s end to end on this busy Mac (earlier demo runs: 28-35 s). The Mac runs the 2B model only about 1.6x faster than the phone, so this server proves the plumbing, not the "online is fast" target. That target needs a larger model on a cloud GPU.

## After the LoRA training finishes (2026-11-14)
The 4B reasoning run (`bootstrap-r16-reasoning-4B-UNREVIEWED`) was at step 79 of 120 and needs about 2 more hours. Its queue then runs a portrait_v1 benchmark and a `bootstrap_eval` on its own (`bench exit` in `data/adapters/chain-rerun-then-4B.log` marks the end). Do these in order, once the Mac is free:

1. **Read the 4B result.** Check validation loss, then compare it with the 2B adapters on the same benchmark and held-out scenes. All of these adapters are `UNREVIEWED`, so this says whether a bigger model helps, not whether the output is good.
2. **Decide where the 4B belongs.** It will not meet the phone budgets (2B already misses latency at 1.8 GB). If it is clearly better, it becomes the Mac/cloud model for the online engine, and the 2B stays the offline model. Measure its Mac speed before deciding.
3. **Real-model smoke test.** Start `photo-ai server serve --host 0.0.0.0 --model <best adapter>`, run the DirectorKit live test against it, then try one request from the phone on the same Wi-Fi. Record time to first shot, total time, and whether the fallback fires when the Mac is unreachable.
4. **Blind comparison (#21/#6).** Score base, best 2B adapter and the 4B (online) on the 20 held-out scenes.
5. **Fuse the chosen 2B adapter** (Swift's `fuse(with:)` can do it; the step below confirms it) and re-measure speed, since the unfused adapter runs at about 55% of base speed.
6. **Verify the Swift runtime loads our adapters.** Convert an adapter with `ios-bench/scripts/prepare_adapter.py`, compile `MacSmoke` (it may need a small fix: `import MLXNN` is not a declared dependency), and run it with `ADAPTER=<converted dir>`, then again with `ADAPTER_FUSE=1`. Checks: it applies to the 4-bit base without error, fused speed returns to base speed, and the output is close to the Python result. Ship language-only adapters to the phone; the vision-tower part of a vision adapter cannot load in Swift (merge it into the base weights only if a later run shows vision training clearly helps).
7. **Build the on-device `OfflineEngine`** (Phase 3) with the fused 2B, replacing the stub in the app.

Still the real blocker for quality claims: human-approved labels (#2/#4). Nothing above changes that.

## Offline model: does the Swift runtime load our adapters? (2026-11-14)
Read from mlx-swift-lm 3.32.3 (the version the phone harness pins):
- **Yes in principle.** `Qwen3VL` conforms to `LoRAModel` (`loraLayers` = the 28 language decoder layers). `LoRAContainer.from(directory:)` reads mlx-lm style `adapter_config.json` + `adapters.safetensors`, `load(into:)` applies it unfused, and `fuse(with:)` bakes it into the weights (including quantized layers).
- **Our adapter files need converting first:** the Swift loader matches `keys` relative to each layer ("self_attn.q_proj"), but mlx-vlm writes absolute paths; `num_layers: -1` would trap in Swift; and only language-model layers are adaptable, so vision-tower LoRA tensors are rejected. `ios-bench/scripts/prepare_adapter.py <adapter dir> <out dir>` does the conversion (tested on the reasoning and vision-reasoning adapters: 392 language tensors kept, 64 vision tensors dropped and reported). A vision-trained adapter's vision part must be merged into the base weights separately.
- **Not yet verified by running it.** `MacSmoke` now takes `ADAPTER=<converted dir>` (and `ADAPTER_FUSE=1`) and runs the same greedy target-scene call before and after, reporting layers applied, speed, JSON validity and whether the output changed. It has not been compiled or run: building MLX and loading the model would compete with the 4B training for memory.
- **Open questions the run answers:** does the adapter apply to the 4-bit base without an error; does fused decode speed return to base speed; is the fused output close to the Python result.
