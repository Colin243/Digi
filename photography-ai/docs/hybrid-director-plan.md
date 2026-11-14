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
