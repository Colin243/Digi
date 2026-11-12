import Foundation
import MLX
import SwiftUI
import UIKit

enum Preset: String, CaseIterable, Identifiable {
    case quick, standard, soak
    var id: String { rawValue }

    var workloads: [String] {
        switch self {
        case .quick: ["image_notes", "target_scene"]
        case .standard, .soak: ["decomposed"]
        }
    }
    var sizes: [Int] { self == .soak ? [1024] : [768, 1024] }
    var defaultRepeats: Int {
        switch self { case .quick: 5; case .standard: 3; case .soak: 10 }
    }
    var blurb: String {
        switch self {
        case .quick: "Single calls (one photo's notes, target-scene JSON) at 768 and 1024 px. ~5 min."
        case .standard: "Full decomposed analysis (4 notes + target + aesthetic + 3 compositions = 7 calls) at 768 and 1024 px, interleaved. ~10-20 min."
        case .soak: "Full analysis at 1024 px back to back with no cooldown, to see thermal throttling."
        }
    }
}

private struct Abort: Error { let reason: String }

@MainActor
final class BenchRunner: ObservableObject {
    // UI state
    @Published var running = false
    @Published var status = "Idle"
    @Published var progress = ""
    @Published var fallback: String?
    @Published var log: [String] = []
    @Published var results: [URL] = []
    @Published var memoryLine = ""

    let camera = CameraProbe()
    private let host = ModelHost()
    private var report: BenchReport?
    private var reportURL: URL?
    private var runStart = now()
    private var task: Task<Void, Never>?
    private var cancelRequested = false
    private var memoryWarnings = 0
    private var trialMemoryWarnings = 0
    private var backgrounded = false
    private var observers: [NSObjectProtocol] = []

    /// MLX keeps freed GPU buffers in a cache; on iOS that cache counts against the app's
    /// footprint. 20 MB is what Apple's mlx-swift-examples use on device.
    static let mlxCacheLimit = 20 * 1024 * 1024
    /// Refuse to load unless this much is available on top of the weights (Mac peak was
    /// 3.05 GB for 1.8 GB of weights, so ~1.3 GB of activations, KV cache and vision tower).
    static let headroomOverWeights = 1_500_000_000

    static var resultsDir: URL {
        let d = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("results")
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }

    init() {
        Memory.cacheLimit = Self.mlxCacheLimit
        markStaleRunsTerminated()
        refreshResults()
        let nc = NotificationCenter.default
        observers.append(nc.addObserver(forName: UIApplication.didReceiveMemoryWarningNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.memoryWarning() }
        })
        observers.append(nc.addObserver(forName: ProcessInfo.thermalStateDidChangeNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.event("thermal", thermalNow) }
        })
        camera.onEvent = { [weak self] kind, detail in
            Task { @MainActor in self?.event(kind, detail) }
        }
        Task { [weak self] in
            await self?.camera.configure()
            guard let self else { return }
            if self.camera.configured { _ = await self.camera.start() } else {
                self.say("Camera unavailable: \(self.camera.configureError ?? "?"). Camera checks will be skipped.")
            }
        }
        Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated {
                self?.memoryLine = "footprint \(formatBytes(MemoryProbe.footprint)) · available \(formatBytes(MemoryProbe.available)) · \(thermalNow)"
            }
        }
    }

    // MARK: - Controls

    func start(preset: Preset, repeats: Int, cameraPauseResume: Bool, reloadTest: Bool, cooldown: Double) {
        guard !running else { return }
        running = true
        cancelRequested = false
        fallback = nil
        log.removeAll()
        task = Task {
            await run(preset: preset, repeats: repeats, cameraPauseResume: cameraPauseResume,
                      reloadTest: reloadTest, cooldown: cooldown)
            UIApplication.shared.isIdleTimerDisabled = false
            running = false
        }
    }

    func stop() {
        cancelRequested = true
        say("Stop requested: finishing the current call.")
    }

    func scenePhaseChanged(_ phase: ScenePhase) {
        let label = phase == .active ? "active" : phase == .inactive ? "inactive" : "background"
        if running { event("scene_phase", label) }
        backgrounded = phase == .background
    }

    // MARK: - Run

    private func run(preset: Preset, repeats: Int, cameraPauseResume: Bool, reloadTest: Bool, cooldown: Double) async {
        UIApplication.shared.isIdleTimerDisabled = true  // a locked screen suspends GPU work
        runStart = now()
        memoryWarnings = 0
        status = "Collecting device info"
        let id = "bench-" + Self.stamp() + "-\(preset.rawValue)"
        let device = await DeviceProbe.info()
        var pack: PromptPack?
        var manifest: (ImageManifest, URL)?
        var setupError: String?
        do {
            pack = try PromptPack.load()
            manifest = try ImageManifest.load()
        } catch {
            setupError = error.localizedDescription
        }
        let maxTokens = Dictionary(uniqueKeysWithValues: (pack?.stages ?? [:]).map { ($0.key, $0.value.maxTokens) })
        let found = ModelLocator.find()
        let modelInfo = found.map { ModelLocator.info(at: $0.url, location: $0.location) }
        let required = Int(modelInfo?.weightsBytes ?? 0) + Self.headroomOverWeights

        report = BenchReport(
            id: id, status: "running", startedAt: Date(), device: device,
            runtime: RuntimeInfo(
                appVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?",
                packages: DeviceProbe.packageVersions(), mlxCacheLimit: Memory.cacheLimit,
                mlxMemoryLimit: Memory.memoryLimit, promptVersion: pack?.promptVersion ?? "?", jsonFormat: pack?.jsonFormat ?? "?"),
            model: modelInfo,
            config: BenchConfig(
                preset: preset.rawValue, repeats: repeats, sizes: preset.sizes, workloads: preset.workloads,
                imageCase: manifest?.0.case ?? "?", cameraPauseResume: cameraPauseResume && camera.configured,
                cameraPreset: CameraProbe.presetName, reloadTest: reloadTest, cooldownSeconds: cooldown,
                maxTokens: maxTokens, temperature: 0, memoryPrecheckBytes: required))
        reportURL = Self.resultsDir.appendingPathComponent("\(id).json")
        save()
        say("\(device.modelName ?? device.machine) · iOS \(device.systemVersion) · \(formatBytes(device.physicalMemory)) RAM · available to app \(formatBytes(device.availableMemoryAtStart))")
        say("Network: \(device.networkAtStart.note)")

        if let setupError {
            return finish(status: "failed", reason: setupError, fallback: "Benchmark assets missing: \(setupError)")
        }
        guard let pack, let manifest else { return }
        let (images, imageDir) = manifest
        guard let found, let modelInfo else {
            return finish(status: "failed", reason: "model files not found",
                          fallback: "On-device model not installed (no config.json in the app bundle or Documents/\(ModelLocator.folderName)). The director feature stays off; the camera keeps working.")
        }

        // Memory pre-check: decline to load rather than get killed by jetsam.
        let avail = MemoryProbe.available
        say("Model: \(modelInfo.repoId) @ \(modelInfo.revision?.prefix(12) ?? "?") from \(modelInfo.location), \(formatBytes(modelInfo.weightsBytes))")
        if avail < required {
            return finish(status: "aborted", reason: "memory precheck: \(avail) available < \(required) required",
                          fallback: "Not enough memory for the on-device director (\(formatBytes(avail)) free, needs \(formatBytes(required))). It stays off; the camera keeps working. Close other apps or check the increased-memory-limit entitlement.")
        }

        // Cold load (camera keeps running, as it would on the camera screen).
        status = "Loading model (cold)"
        report?.load = await timedLoad(from: found.url, note: "camera running during load; systemUptime \(Int(device.systemUptimeAtStart)) s")
        save()
        guard report?.load?.ok == true else {
            return finish(status: "failed", reason: "model load failed: \(report?.load?.error ?? "?")",
                          fallback: "On-device model failed to load (\(report?.load?.error ?? "?")). The director feature is turned off for this session; the camera keeps working.")
        }
        say(String(format: "Cold load %.2f s, footprint %@", report?.load?.seconds ?? 0, formatBytes(report?.load?.footprintAfter ?? 0)))

        // Trials, sizes interleaved so thermal drift does not line up with image size.
        var plan: [(String, Int)] = []
        for _ in 0..<repeats { for s in preset.sizes { for w in preset.workloads { plan.append((w, s)) } } }
        var abortReason: String?
        for (i, (workload, size)) in plan.enumerated() {
            progress = "Trial \(i + 1)/\(plan.count): \(workload) @ \(size) px"
            status = progress
            if let r = abortCheck() { abortReason = r; break }
            let trial = await runTrial(index: i, workload: workload, size: size, first: i == 0, pack: pack,
                                       images: images, dir: imageDir, cameraPauseResume: cameraPauseResume)
            report?.trials.append(trial)
            let trialsSoFar = report?.trials ?? []
        report?.summary = Self.summarize(trialsSoFar)
            save()
            say(String(format: "#%d %@ @%d: %.1f s inference, peak %@, %@%@", i + 1, workload, size, trial.inferenceSeconds,
                       formatBytes(trial.peakFootprint), trial.thermalEnd,
                       trial.camera?.firstFrameSeconds.map { String(format: ", camera back in %.2f s", $0) } ?? ""))
            if let e = trial.error {
                if e.hasPrefix("abort:") { abortReason = String(e.dropFirst(6)); break }
                say("Trial error: \(e)")
            }
            if cooldown > 0, i < plan.count - 1 {
                status = "Cooldown \(Int(cooldown)) s"
                try? await Task.sleep(nanoseconds: UInt64(cooldown * 1e9))
            }
        }

        if abortReason == nil, reloadTest, !cancelRequested {
            status = "Reload test"
            host.unload()
            try? await Task.sleep(nanoseconds: 1_000_000_000)
            report?.reload = await timedLoad(from: found.url, note: "after unload() + Memory.clearCache(); footprint_before is the post-unload footprint")
            say(String(format: "Reload %.2f s (footprint after unload was %@)", report?.reload?.seconds ?? 0,
                       formatBytes(report?.reload?.footprintBefore ?? 0)))
        }
        host.unload()
        if let abortReason {
            finish(status: "aborted", reason: abortReason,
                   fallback: "Stopped early (\(abortReason)). Results so far are saved. In the product this is where the director would unload and show its \"try again\" state while the camera keeps working.")
        } else {
            finish(status: cancelRequested ? "aborted" : "finished", reason: cancelRequested ? "stopped by user" : nil, fallback: nil)
        }
    }

    private func timedLoad(from url: URL, note: String) async -> LoadRecord {
        let fb = MemoryProbe.footprint, ab = MemoryProbe.available
        Memory.peakMemory = 0
        let sampler = MemorySampler()
        sampler.start()
        let t0 = now()
        var err: String?
        do { try await host.load(from: url) } catch { err = String(describing: error) }
        let secs = now() - t0
        let (peak, minA) = sampler.stop()
        return LoadRecord(
            ok: err == nil, error: err, seconds: err == nil ? secs : nil,
            footprintBefore: fb, footprintAfter: MemoryProbe.footprint,
            availableBefore: ab, availableAfter: MemoryProbe.available,
            peakFootprint: peak, minAvailable: minA,
            mlxActiveAfter: Memory.activeMemory, mlxPeak: Memory.peakMemory,
            thermalState: thermalNow, camera: nil, note: note)
    }

    private func runTrial(index: Int, workload: String, size: Int, first: Bool, pack: PromptPack,
                          images: ImageManifest, dir: URL, cameraPauseResume: Bool) async -> Trial {
        var t = Trial(index: index, workload: workload, size: size, firstAfterLoad: first, startedAt: Date(),
                      thermalStart: thermalNow, thermalEnd: thermalNow)
        trialMemoryWarnings = 0
        let tStart = now()
        let useCamera = cameraPauseResume && camera.configured
        var cc = CameraCheck(available: camera.configured, error: camera.configureError)
        if useCamera {
            cc.availableWithCameraRunning = MemoryProbe.available
            cc.footprintWithCameraRunning = MemoryProbe.footprint
            cc.stopSeconds = await camera.stop()
        }

        func image(_ role: String, _ idx: Int) throws -> (URL, [Int]) {
            guard let v = images.variant(role: role, index: idx, size: size) else {
                throw AssetError.missing("no \(role)_\(idx) at \(size) px in BenchImages")
            }
            return (dir.appendingPathComponent(v.file), v.size)
        }

        do {
            switch workload {
            case "image_notes":
                t.calls.append(try await call("image_notes", pack: pack, prompt: try pack.stage("image_notes").prompt,
                                              image: try image("inspiration", 1), json: false))
            case "target_scene":
                t.calls.append(try await call("target_scene", pack: pack, prompt: try pack.stage("target_scene").prompt,
                                              image: try image("target", 1), json: true))
            default:  // decomposed, same order as pipeline._decomposed
                var notes: [String] = []
                for i in 1...images.inspirationCount {
                    let c = try await call("notes_inspiration\(i)", pack: pack, prompt: try pack.stage("image_notes").prompt,
                                           image: try image("inspiration", i), json: false, stageKey: "image_notes")
                    notes.append(c.output)
                    t.calls.append(c)
                }
                let target = try await call("target_scene", pack: pack, prompt: try pack.stage("target_scene").prompt,
                                            image: try image("target", 1), json: true)
                t.calls.append(target)
                let aesthetic = try await call("aesthetic_from_notes", pack: pack,
                                               prompt: try pack.aestheticPrompt(notes: notes), image: nil, json: true)
                t.calls.append(aesthetic)
                t.calls.append(try await call("compositions", pack: pack,
                                              prompt: try pack.compositionsPrompt(aestheticRaw: aesthetic.output, targetRaw: target.output),
                                              image: try image("target", 1), json: true))
            }
        } catch let a as Abort {
            t.error = "abort:" + a.reason
        } catch {
            t.error = String(describing: error)
        }

        if useCamera {
            let (callS, ff) = await camera.start()
            cc.startCallSeconds = callS
            cc.firstFrameSeconds = ff
            cc.recovered = ff != nil
            if ff == nil { event("camera_error", "no frame within 5 s of restart") }
        }
        t.camera = cc
        t.wallSeconds = now() - tStart
        t.thermalEnd = thermalNow
        t.inferenceSeconds = t.calls.reduce(0) { $0 + $1.e2eSeconds }
        t.peakFootprint = t.calls.map(\.peakFootprint).max() ?? 0
        t.minAvailable = t.calls.map(\.minAvailable).min() ?? MemoryProbe.available
        t.mlxPeak = t.calls.map(\.mlxPeak).max() ?? 0
        t.memoryWarnings = trialMemoryWarnings
        return t
    }

    private func call(_ stage: String, pack: PromptPack, prompt: String, image: (URL, [Int])?, json: Bool,
                      stageKey: String? = nil) async throws -> CallRecord {
        if let r = abortCheck() { throw Abort(reason: r) }
        let maxTokens = try pack.stage(stageKey ?? stage).maxTokens
        status = "\(progress) · \(stage)"
        Memory.peakMemory = 0
        let sampler = MemorySampler()
        sampler.start()
        let th0 = thermalNow
        let r: CallResult
        do {
            r = try await host.run(template: prompt, marker: pack.imageMarker, image: image?.0, maxTokens: maxTokens)
        } catch {
            _ = sampler.stop()
            throw error
        }
        let (peak, minA) = sampler.stop()
        return CallRecord(
            stage: stage, image: image?.0.lastPathComponent, imagePixels: image?.1,
            promptTokens: r.promptTokens, generatedTokens: r.generatedTokens, maxTokens: maxTokens,
            stopReason: r.stopReason, prepareSeconds: r.prepare, prefillSeconds: r.prefill,
            ttftSeconds: r.ttft, decodeSeconds: r.decode, e2eSeconds: r.e2e,
            promptTokensPerSecond: r.promptTPS, generationTokensPerSecond: r.genTPS,
            peakFootprint: peak, minAvailable: minA, mlxPeak: Memory.peakMemory,
            thermalStart: th0, thermalEnd: thermalNow,
            jsonValid: json ? JSONText.isValid(r.text) : nil, output: r.text)
    }

    // MARK: - Resource failures

    private func abortCheck() -> String? {
        if cancelRequested { return "stopped by user" }
        if backgrounded { return "app went to background (iOS does not allow GPU work in the background)" }
        if ProcessInfo.processInfo.thermalState == .critical { return "thermal state critical" }
        if memoryWarnings >= 2 { return "repeated memory warnings" }
        return nil
    }

    private func memoryWarning() {
        memoryWarnings += 1
        trialMemoryWarnings += 1
        // First response: give MLX's buffer cache back. A second warning stops the run and unloads.
        Memory.clearCache()
        event("memory_warning", "#\(memoryWarnings); cleared MLX cache")
    }

    // MARK: - Bookkeeping

    private func finish(status: String, reason: String?, fallback: String?) {
        report?.status = status
        report?.abortReason = reason
        report?.fallbackMessage = fallback
        report?.finishedAt = Date()
        let trialsSoFar = report?.trials ?? []
        report?.summary = Self.summarize(trialsSoFar)
        save()
        self.fallback = fallback
        self.status = "\(status.capitalized)\(reason.map { ": \($0)" } ?? "")"
        progress = ""
        say("Saved \(reportURL?.lastPathComponent ?? "?")")
        refreshResults()
    }

    private func event(_ kind: String, _ detail: String) {
        guard report != nil, running else { return }
        report?.events.append(EventRecord(at: Date(), secondsSinceStart: now() - runStart, kind: kind, detail: detail,
                                          footprint: MemoryProbe.footprint, available: MemoryProbe.available))
        say("[\(kind)] \(detail)")
    }

    private func say(_ s: String) {
        log.append(s)
        if log.count > 300 { log.removeFirst(log.count - 300) }
    }

    private func save() {
        guard let report, let reportURL else { return }
        do {
            try Self.encoder.encode(report).write(to: reportURL, options: .atomic)
        } catch {
            say("Could not save results: \(error.localizedDescription)")
        }
    }

    func refreshResults() {
        let files = (try? FileManager.default.contentsOfDirectory(at: Self.resultsDir, includingPropertiesForKeys: nil)) ?? []
        results = files.filter { $0.pathExtension == "json" }.sorted { $0.lastPathComponent > $1.lastPathComponent }
    }

    /// A report still marked "running" at launch means the app died mid-run, most likely
    /// jetsam (memory limit) or a crash. Keep the partial data and say so.
    private func markStaleRunsTerminated() {
        let files = (try? FileManager.default.contentsOfDirectory(at: Self.resultsDir, includingPropertiesForKeys: nil)) ?? []
        for f in files where f.pathExtension == "json" {
            guard let data = try? Data(contentsOf: f), var r = try? Self.decoder.decode(BenchReport.self, from: data),
                  r.status == "running" else { continue }
            r.status = "terminated"
            r.abortReason = "app was killed before the run finished (likely jetsam/memory limit or a crash); \(r.trials.count) trials were saved"
            try? Self.encoder.encode(r).write(to: f, options: .atomic)
        }
    }

    static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        e.dateEncodingStrategy = .iso8601
        e.outputFormatting = [.prettyPrinted, .sortedKeys]
        e.nonConformingFloatEncodingStrategy = .convertToString(positiveInfinity: "inf", negativeInfinity: "-inf", nan: "nan")
        return e
    }()

    static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        d.dateDecodingStrategy = .iso8601
        d.nonConformingFloatDecodingStrategy = .convertFromString(positiveInfinity: "inf", negativeInfinity: "-inf", nan: "nan")
        return d
    }()

    static func stamp() -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyyMMdd-HHmmss"
        return f.string(from: Date())
    }

    // MARK: - Summary

    static func summarize(_ trials: [Trial]) -> [SummaryRow] {
        func median(_ xs: [Double]) -> Double? {
            guard !xs.isEmpty else { return nil }
            let s = xs.sorted()
            return s.count % 2 == 1 ? s[s.count / 2] : (s[s.count / 2 - 1] + s[s.count / 2]) / 2
        }
        var keys: [(String, Int)] = []
        for t in trials where !keys.contains(where: { $0 == (t.workload, t.size) }) { keys.append((t.workload, t.size)) }
        return keys.map { w, s in
            let ts = trials.filter { $0.workload == w && $0.size == s && $0.error == nil }
            let warm = ts.filter { !$0.firstAfterLoad }
            let warmCalls = warm.flatMap(\.calls)
            let rec = ts.compactMap { $0.camera?.firstFrameSeconds }
            let jsonCalls = ts.flatMap(\.calls).compactMap(\.jsonValid)
            return SummaryRow(
                workload: w, size: s, n: ts.count,
                firstE2e: ts.first(where: \.firstAfterLoad)?.inferenceSeconds,
                warmE2eMedian: median(warm.map(\.inferenceSeconds)),
                warmE2eMax: warm.map(\.inferenceSeconds).max(),
                ttftMedian: median(warm.compactMap { $0.calls.first?.ttftSeconds }),
                genTokPerSecMedian: median(warmCalls.filter { $0.generatedTokens >= 16 }.map(\.generationTokensPerSecond)),
                promptTokPerSecMedian: median(warmCalls.map(\.promptTokensPerSecond)),
                peakFootprintMax: ts.map(\.peakFootprint).max() ?? 0,
                minAvailableMin: ts.map(\.minAvailable).min() ?? 0,
                cameraRecoveryMedian: median(rec), cameraRecoveryMax: rec.max(),
                jsonValid: "\(jsonCalls.filter { $0 }.count)/\(jsonCalls.count)")
        }
    }
}
