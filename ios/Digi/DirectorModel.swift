import Foundation
import SwiftUI
import UIKit
import DirectorKit

@MainActor
final class DirectorModel: ObservableObject {
    /// Lives as long as the app, so the Director keeps its photos and shots when its sheet is closed.
    static let shared = DirectorModel()

    // What the person chose, kept across closing and reopening the Director.
    @Published var mode: DirectorMode = .scene
    @Published var style: DirectorStyle = .relaxedCandid
    @Published var brief = ""
    @Published var targetImage: UIImage?
    @Published var inspirationImages: [UIImage] = []
    enum Phase: Equatable { case idle, running, done, failed(String) }

    @Published var phase: Phase = .idle
    @Published var stageText = ""
    @Published private(set) var deck = ShotDeck()
    var shots: [Shot] { deck.shots }
    /// The request behind the shots on screen, so a refresh asks for the same place and style again.
    private var lastRequest: DirectorRequest?
    @Published var engineUsed: EngineKind?
    @Published var notice: String?
    /// Inspiration Director: whether the server is reading the chosen photos ahead of the plan.
    @Published private(set) var prepStatus: PlanPreparer.Status = .idle

    private var task: Task<Void, Never>?

    // MARK: checking the server when the app opens

    enum ServerState: Equatable { case unknown, checking, reachable, unreachable }
    /// Whether the saved Director server answered the last check. Stays `.unknown` when no server is set up.
    @Published private(set) var serverState: ServerState = .unknown

    /// Asks the saved server if it is there (the health check sends no photos and needs no key). Called when the
    /// app opens and comes back to the front, so a wrong or unreachable address shows before a plan fails on it.
    func checkServer() {
        guard let cfg = DirectorDefaults.configuration() else { serverState = .unknown; return }
        serverState = .checking
        let url = cfg.baseURL.appendingPathComponent("v1/health")
        Task { [weak self] in
            var request = URLRequest(url: url); request.timeoutInterval = 6
            let ok = ((try? await URLSession.shared.data(for: request).1 as? HTTPURLResponse)?.statusCode == 200)
            self?.serverState = ok ? .reachable : .unreachable
        }
    }

    // MARK: reading photos ahead (Inspiration Director, online only)

    /// Each photo is turned into a JPEG once and that exact `Data` is used for preparing and for the plan:
    /// the server ties prepared work to the photo's bytes.
    private var jpegCache: [ObjectIdentifier: (image: UIImage, jpeg: Data)] = [:]
    private var preparer: PlanPreparer?
    private var preparerServer: (url: URL, key: String)?
    private var prepTask: Task<Void, Never>?

    private func jpegData(_ image: UIImage) -> Data? {
        if let hit = jpegCache[ObjectIdentifier(image)], hit.image === image { return hit.jpeg }
        guard let data = Self.jpeg(image) else { return nil }
        jpegCache[ObjectIdentifier(image)] = (image, data)
        return data
    }

    /// Call when the mode or any photo changes. In Inspiration mode, with online use allowed, the server starts
    /// reading the photos straight away so the plan has less left to do.
    func inputsChanged(mode: DirectorMode, target: UIImage?, inspiration: [UIImage], inspirationComplete: Bool = true,
                       after delay: Double = 0) {
        let keep = Set(([target].compactMap { $0 } + inspiration).map(ObjectIdentifier.init))
        jpegCache = jpegCache.filter { keep.contains($0.key) }
        let targetJPEG = mode == .inspiration ? target.flatMap(jpegData) : nil
        let inspirationJPEGs = mode == .inspiration ? inspiration.compactMap(jpegData) : []
        prepTask?.cancel()
        prepTask = Task { [weak self] in
            guard let self else { return }
            if delay > 0 { try? await Task.sleep(for: .seconds(delay)) }
            guard !Task.isCancelled else { return }
            let allowed = await Self.onlinePreparationAllowed()
            guard !Task.isCancelled else { return }
            if allowed, let preparer = self.currentPreparer() {
                await preparer.update(target: targetJPEG, inspiration: inspirationJPEGs, inspirationComplete: inspirationComplete)
            } else {
                await self.preparer?.update(target: nil, inspiration: [])
            }
        }
    }

    /// Only when the photos would go online for the plan anyway: a server is set up and the router would try it first.
    private static func onlinePreparationAllowed() async -> Bool {
        guard DirectorDefaults.configuration() != nil else { return false }
        let config = DirectorConfig.make(preference: DirectorDefaults.userPreference(), priority: DirectorDefaults.userPriority())
        guard let route = try? Router.route(conditions: await conditions.current(), config: config) else { return false }
        return route.upload == .photos && route.order.first == .online
    }

    /// The preparer only if it reads ahead on the server the plan will use; one made for an old address has nothing
    /// the new server can take (its work failed or lives on the other server).
    private func preparerForCurrentServer() -> PlanPreparer? {
        guard let cfg = DirectorDefaults.configuration(), let preparer, let s = preparerServer,
              s.url == cfg.baseURL, s.key == cfg.apiKey else { return nil }
        return preparer
    }

    private func currentPreparer() -> PlanPreparer? {
        guard let cfg = DirectorDefaults.configuration() else { preparer = nil; return nil }
        if let preparer, let s = preparerServer, s.url == cfg.baseURL, s.key == cfg.apiKey { return preparer }
        let p = PlanPreparer(service: OnlineEngine(configuration: cfg), onStatus: { [weak self] status in
            Task { @MainActor in self?.prepStatus = status }
        })
        preparer = p; preparerServer = (cfg.baseURL, cfg.apiKey); prepStatus = .idle
        return p
    }

    init() {
        _ = Self.conditions  // start the network monitor now, so it has a reading before the first photo is picked
        #if DEBUG
        // Debug only: `-digiDebugShots YES` shows sample results so the shot cards can be reviewed without a server.
        if UserDefaults.standard.bool(forKey: "digiDebugShots") {
            for i in 0..<3 { var shot = PinnedShotStore.debugSampleShot; shot.title += " \(i + 1)"; deck.append(shot) }
            engineUsed = .online; phase = .done
        }
        #endif
    }

    /// Builds the director from the current Settings each time, so edits apply to the next request.
    private func makeDirector() -> HybridDirector {
        // Best results by default: the online model writes better shots, so it gets time to finish.
        // Waiting limits come from the user's priority (see DirectorPriority).
        let config = DirectorConfig.make(preference: DirectorDefaults.userPreference(), priority: DirectorDefaults.userPriority())
        let online = DirectorDefaults.configuration().map { OnlineEngine(configuration: $0) }
        return HybridDirector(online: online, offline: OfflineEngine(generator: OnDeviceGenerator.shared),
                              conditions: Self.conditions, config: { config })
    }

    /// One long-lived monitor: a fresh NWPathMonitor reports "no connection" until its first update arrives,
    /// which made a just-created one route everything to the phone.
    private static let conditions = SystemConditionsProvider()

    func run(mode: DirectorMode, style: DirectorStyle, brief: String, target: UIImage?, inspiration: [UIImage]) {
        guard let target, let targetJPEG = jpegData(target) else {
            phase = .failed("Add a photo of the place you will shoot."); return
        }
        var images = [DirectorImage(role: .target, jpeg: targetJPEG)]
        if mode == .inspiration {
            images += inspiration.compactMap { jpegData($0) }.map { DirectorImage(role: .inspiration, jpeg: $0) }
        }
        let request = DirectorRequest(mode: mode, style: mode == .scene ? style : nil,
                                      brief: brief.isEmpty ? nil : brief, images: images)
        cancel()
        lastRequest = request
        deck.clear()
        start(request, refreshing: false)
    }

    /// Keeps the starred shots and rewrites the rest, steering the engine away from every look seen so far.
    func refresh() {
        guard phase != .running, let base = lastRequest, let seen = deck.beginRefresh() else { return }
        // The notes and scene read earlier still hold; a refresh has a brief, so the prepared prompt would not match.
        var prepared = base.prepared
        prepared?.planToken = nil
        let request = DirectorRequest(mode: base.mode, style: base.style,
                                      brief: ShotDeck.briefAvoiding(seen, base: base.brief), images: base.images,
                                      prepared: prepared)
        start(request, refreshing: true)
    }

    func toggleKeep(_ shot: Shot) {
        deck.toggleKeep(shot)
        if let id = currentRun { let kept = deck.keptCount; RunLogStore.update(id) { $0.keptCount = kept } }
    }

    /// The person pinned a shot to the camera: the strongest sign the run was useful.
    func markUsed() { if let id = currentRun { RunLogStore.update(id) { $0.usedShot = true } } }

    private var currentRun: UUID?

    private func start(_ request: DirectorRequest, refreshing: Bool) {
        task?.cancel(); task = nil  // not cancel(): that would end the refresh that was just begun
        engineUsed = nil; notice = nil; stageText = refreshing ? "Rewriting" : "Starting"; phase = .running
        let director = makeDirector()
        let priority = DirectorDefaults.userPriority()
        let started = Date()
        var firstShotAt: Date?, shotCount = 0, fellBack = false
        let preparer = request.mode == .inspiration && request.prepared == nil ? self.preparerForCurrentServer() : nil
        task = Task { [weak self] in
            var request = request
            var prepWait: Double?
            if let preparer {
                // Let the read-ahead call in progress finish (the server would make the plan queue behind it anyway),
                // start no new one, and take whatever is ready for these photos.
                if await preparer.currentStatus == .working { self?.stageText = "Finishing reading your photos" }
                prepWait = await preparer.finishCurrent()
                let target = request.images.first { $0.role == .target }?.jpeg
                let inspiration = request.images.filter { $0.role == .inspiration }.map(\.jpeg)
                if let target {
                    let ready = await preparer.prepared(target: target, inspiration: inspiration)
                    if !ready.isEmpty { request.prepared = ready }
                }
                if !refreshing, let self { var kept = request; kept.prepared?.planToken = nil; self.lastRequest = kept }
            }
            /// Writes the run to the log once it ends with at least one shot.
            @MainActor func record() {
                guard let self, shotCount > 0 else { return }
                let p = request.prepared
                let preparedParts = [p?.references != nil ? "references" : nil, p?.targetScene != nil ? "scene" : nil,
                                     p?.planToken != nil ? "token" : nil].compactMap { $0 }
                let r = RunRecord(engine: self.engineUsed ?? .offline, priority: priority,
                                  firstShotSeconds: firstShotAt.map { $0.timeIntervalSince(started) },
                                  totalSeconds: Date().timeIntervalSince(started), shotCount: shotCount, fellBack: fellBack,
                                  mode: request.mode.rawValue,
                                  prepared: preparedParts.isEmpty ? "none" : preparedParts.joined(separator: "+"),
                                  prepWaitSeconds: prepWait)
                self.currentRun = r.id
                RunLogStore.append(r)
            }
            do {
                for try await event in director.plan(request) {
                    guard let self else { return }
                    switch event {
                    case .stage(let stage, let engine):
                        self.engineUsed = engine
                        self.stageText = Self.describe(stage, engine)
                    case .shot(let rawShot, let engine):
                        // Zoom and distance come from a rule, not from the model (it kept writing 2x looks with 1x distances).
                        let shot = ZoomPlan.resolved(rawShot)
                        self.engineUsed = engine
                        shotCount += 1; if firstShotAt == nil { firstShotAt = Date() }
                        if refreshing {
                            // Every waiting slot filled: stop early, the rest of the answer is not needed.
                            if self.deck.fill(shot) { self.phase = .done; record(); self.task?.cancel(); return }
                        } else {
                            self.deck.append(shot)
                        }
                    case .engineSwitched(_, let to, let reason):
                        fellBack = true
                        if !refreshing { self.deck.resetKeepingFavorites() }
                        self.engineUsed = to
                        self.notice = "Switched to \(to == .offline ? "the phone" : "online"): \(reason)."
                    case .finished(let engine):
                        self.engineUsed = engine; self.phase = .done
                    }
                }
                if self?.phase == .running { self?.phase = .done }
                record()
                self?.deck.endRefresh()
            } catch is CancellationError {
                self?.deck.endRefresh()
            } catch {
                self?.deck.endRefresh()
                self?.phase = .failed(Self.message(for: error))
            }
        }
    }

    func cancel() { task?.cancel(); task = nil; deck.endRefresh(); if phase == .running { phase = .idle } }

    // MARK: helpers

    private static func describe(_ stage: DirectorStage, _ engine: EngineKind) -> String {
        let where_ = engine == .online ? "online" : "on this phone"
        switch stage {
        case .preparing: return "Preparing (\(where_))"
        case .readingScene: return "Reading the scene (\(where_))"
        case .writingShots: return "Writing shots (\(where_))"
        }
    }

    static func message(for error: Error) -> String {
        guard let e = error as? DirectorError else { return error.localizedDescription }
        switch e {
        case .timedOut: return "That took too long."
        case .offlineUnavailable(let m), .onlineUnavailable(let m), .noEngineAvailable(let m),
             .invalidOutput(let m), .invalidRequest(let m): return m
        }
    }

    /// Long edge about 1024 px, as the server and the on-device model expect.
    static func jpeg(_ image: UIImage, longEdge: CGFloat = 1024) -> Data? {
        let size = image.size
        let scale = min(1, longEdge / max(size.width, size.height))
        let target = CGSize(width: (size.width * scale).rounded(), height: (size.height * scale).rounded())
        let format = UIGraphicsImageRendererFormat(); format.scale = 1
        let resized = UIGraphicsImageRenderer(size: target, format: format).image { _ in image.draw(in: CGRect(origin: .zero, size: target)) }
        return resized.jpegData(compressionQuality: 0.92)
    }
}

extension DirectorStyle {
    var label: String {
        switch self {
        case .relaxedCandid: return "松弛感 Relaxed candid"
        case .dreamyAtmospheric: return "氛围感 Dreamy"
        case .coolEditorial: return "清冷感 Cool editorial"
        case .vintageCCD: return "复古 Vintage CCD"
        }
    }
}

// MARK: - Pinned shot (Director -> camera)

/// The shot the user chose in the Director. It stays on the camera screen until they clear it, and
/// survives relaunch. Live guidance (tilt, framing) will later compare the camera against this shot.
@MainActor
final class PinnedShotStore: ObservableObject {
    static let shared = PinnedShotStore()
    private static let storageKey = "digi.pinnedShot"

    @Published private(set) var shot: Shot?
    @Published var stepIndex = 0
    @Published var expanded = true
    /// Showing the subject's cue cards (what to tell the person) instead of the camera setup.
    @Published var directing = false
    @Published var cueIndex = 0

    private init() {
        if let data = UserDefaults.standard.data(forKey: Self.storageKey),
           let saved = try? JSONDecoder().decode(Shot.self, from: data) { shot = saved }
        #if DEBUG
        // Debug only: `simctl launch … -digiDebugPinShot YES` pins a sample shot so the pinned-shot UI
        // can be seen without a Director engine (the simulator has none).
        if UserDefaults.standard.bool(forKey: "digiDebugPinShot") { shot = Self.debugSampleShot; expanded = false }
        #endif
    }

    #if DEBUG
    static let debugSampleShot = Shot(
        title: "Warm backlit walk", cameraPosition: "Stand about 3 m back, slightly left of the path",
        cameraHeight: "Chest height", cameraAngle: "Level, tilted slightly up",
        subjectPosition: "On the path, left third of the frame", steps: ["Crouch a little", "Wait for light between the trees", "Shoot"],
        bodyPose: "Walk slowly away from the camera, hands relaxed",
        headDirection: "Turn your head slightly to the right, chin level", gaze: "Look at the light ahead",
        expressionCue: "Soft smile, as if you just noticed something nice")
    #endif

    func pin(_ shot: Shot) {
        self.shot = shot; stepIndex = 0; expanded = false; directing = false; cueIndex = 0
        if let data = try? JSONEncoder().encode(shot) { UserDefaults.standard.set(data, forKey: Self.storageKey) }
    }

    func clear() {
        shot = nil; stepIndex = 0
        UserDefaults.standard.removeObject(forKey: Self.storageKey)
    }

    func nextStep() { if let n = shot?.steps.count, n > 0 { stepIndex = min(stepIndex + 1, n - 1) } }
    func previousStep() { stepIndex = max(stepIndex - 1, 0) }

    /// What to tell the person being photographed, one card each, in the order you'd say it.
    static func subjectCues(_ shot: Shot) -> [(label: String, text: String)] {
        [("Where to be", shot.subjectPosition), ("Pose", shot.bodyPose), ("Head", shot.headDirection),
         ("Eyes", shot.gaze), ("Expression", shot.expressionCue)]
            .filter { !$0.1.trimmingCharacters(in: .whitespaces).isEmpty }
    }
}

/// The card over the viewfinder that tells the user how to take the pinned shot.
struct PinnedShotCard: View {
    @ObservedObject var store: PinnedShotStore
    @ObservedObject private var live = LiveGuidance.shared
    @ObservedObject private var settings = GuidanceSettings.shared
    @Environment(\.guidanceTheme) private var theme
    /// The card's highlight colour follows the look: gold in Full info, pink in Soft, white in Minimal.
    private var accent: Color { theme.hint ?? theme.accent }
    /// Soft and Minimal keep the card small: just the title, with the live hint floating lower.
    private var compact: Bool { settings.prefs.style != .full }
    @Environment(\.deviceScale) private var scale
    private var cardRadius: CGFloat { theme.style == .soft ? 20 : theme.style == .minimal ? 14 : 12 }
    private var cardStroke: Double { theme.style == .minimal ? 0.3 : theme.style == .soft ? 0.35 : 0.45 }
    var body: some View {
        if let shot = store.shot, compact, !store.expanded {
            // Soft and Minimal: just a small circle that opens the shot guide.
            HStack {
                Button { withAnimation(.easeOut(duration: 0.15)) { store.expanded = true } } label: {
                    Image(systemName: "scope").font(.system(size: 17 * scale)).foregroundStyle(accent)
                        .frame(width: 40 * scale, height: 40 * scale)
                        .background(.black.opacity(0.5), in: Circle())
                }
                .accessibilityLabel("Open shot guide: \(shot.title)")
                .accessibilityIdentifier("pinned-shot-toggle")
                Spacer()
            }.padding(8).foregroundStyle(.white).accessibilityIdentifier("pinned-shot-card")
        } else if let shot = store.shot {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 10) {
                    Image(systemName: "scope").foregroundStyle(accent)
                    Text(shot.title).font(.subheadline.weight(.semibold)).lineLimit(1)
                    Spacer()
                    Button { withAnimation(.easeOut(duration: 0.15)) { store.expanded.toggle() } } label: {
                        Image(systemName: store.expanded ? "chevron.up" : "chevron.down").frame(width: 32, height: 32)
                    }.accessibilityLabel(store.expanded ? "Collapse shot guide" : "Expand shot guide")
                        .accessibilityIdentifier("pinned-shot-toggle")
                    Button { store.clear() } label: {
                        Image(systemName: "xmark").frame(width: 32, height: 32)
                    }.accessibilityLabel("Remove pinned shot").accessibilityIdentifier("pinned-shot-clear")
                }
                if !compact { LiveCueRow(live: LiveGuidance.shared, accent: accent, style: settings.display.cueRow) }
                if store.expanded { controls }
                if store.expanded && store.directing {
                    subjectCards(shot)
                } else if store.expanded {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 5) {
                            line("Stand", shot.cameraPosition); line("Height", shot.cameraHeight); line("Angle", shot.cameraAngle)
                            line("Subject", shot.subjectPosition); line("Framing", shot.distanceAndFraming)
                            line("Lens", shot.zoomOrLens); line("Light", shot.lightingTip)
                            line("Pose", shot.bodyPose); line("Head", shot.headDirection); line("Gaze", shot.gaze)
                            line("Expression", shot.expressionCue)
                        }
                    }.frame(maxHeight: 175)
                    if !shot.steps.isEmpty {
                        let i = min(store.stepIndex, shot.steps.count - 1)
                        HStack(alignment: .top, spacing: 8) {
                            Button { store.previousStep() } label: { Image(systemName: "chevron.left") }
                                .disabled(i == 0).accessibilityLabel("Previous step")
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Step \(i + 1) of \(shot.steps.count)").font(.caption2.weight(.semibold)).foregroundStyle(accent)
                                Text(shot.steps[i]).font(.footnote).fixedSize(horizontal: false, vertical: true)
                            }.frame(maxWidth: .infinity, alignment: .leading)
                            Button { store.nextStep() } label: { Image(systemName: "chevron.right") }
                                .disabled(i == shot.steps.count - 1).accessibilityLabel("Next step")
                        }.padding(8).background(.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
                    }
                    if settings.prefs.style == .full {
                        Toggle("Show detection boxes", isOn: settings.detectionBoxes).font(.caption).tint(accent)
                            .accessibilityIdentifier("guidance-debug-toggle")
                    }
                }
            }
            .font(.footnote).foregroundStyle(.white)
            .fontDesign(theme.cueDesign)
            .padding(compact ? 12 : 8)
            .background(.black.opacity(store.expanded ? 0.72 : 0.55), in: RoundedRectangle(cornerRadius: cardRadius))
            .overlay { RoundedRectangle(cornerRadius: cardRadius).stroke(accent.opacity(cardStroke), lineWidth: theme.style == .minimal ? 0.5 : 1) }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(8)
            .accessibilityIdentifier("pinned-shot-card")
        }
    }

    /// Camera / Subject switch. Choosing who to direct is a tap on the person in the viewfinder.
    private var controls: some View {
        HStack(spacing: 8) {
            Picker("Guide", selection: $store.directing) {
                Text("Camera").tag(false)
                Text("Subject").tag(true)
            }
            .pickerStyle(.segmented).frame(maxWidth: 170)
            .onChange(of: store.directing) { _, on in if on { store.expanded = true } }
            .accessibilityIdentifier("pinned-shot-mode")
            Spacer()
        }
    }

    /// Live check of the subject's head against the shot (when the experimental toggle is on).
    @ViewBuilder private var liveHeadStatus: some View {
        let g = live.guidance
        let head = live.targets?.head ?? HeadTargets()
        if live.subjectCuesEnabled && !head.isEmpty {
            VStack(alignment: .leading, spacing: 3) {
                if g.subjectSatisfied {
                    Label(GuidanceWording.text(.headRight, style: settings.prefs.style), systemImage: "checkmark.circle.fill").foregroundStyle(.green)
                } else if g.subjectCues.isEmpty {
                    Label(GuidanceWording.text(.watchingHead, style: settings.prefs.style), systemImage: "eye").foregroundStyle(.white.opacity(0.6))
                } else {
                    ForEach(Array(g.subjectCues.enumerated()), id: \.offset) { _, c in
                        Label(GuidanceWording.text(for: c, style: settings.prefs.style), systemImage: c.symbol).foregroundStyle(.cyan)
                    }
                }
            }
            .font(.footnote.weight(.semibold))
            .accessibilityIdentifier("subject-live-status")
        } else if live.subjectCuesEnabled {
            Text(GuidanceWording.text(.noHeadChecks, style: settings.prefs.style)).font(.caption).foregroundStyle(.white.opacity(0.6))
        }
    }

    /// Big, read-aloud cards for directing the person: where to be, pose, head, eyes, expression.
    @ViewBuilder private func subjectCards(_ shot: Shot) -> some View {
        Toggle(isOn: settings.headCues) {
            Label("Live head cues (experimental)", systemImage: "face.smiling").font(.caption)
        }
        .tint(.cyan).accessibilityIdentifier("live-subject-toggle")
        let cues = PinnedShotStore.subjectCues(shot)
        if cues.isEmpty {
            Text("This shot has no directions for the subject.").font(.footnote).foregroundStyle(.white.opacity(0.7))
        } else {
            let i = min(store.cueIndex, cues.count - 1)
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("Tell your subject · \(cues[i].label)").font(.caption.weight(.semibold)).foregroundStyle(accent)
                    Spacer()
                    Text("\(i + 1) of \(cues.count)").font(.caption2).foregroundStyle(.white.opacity(0.6))
                }
                Text(cues[i].text).font(.title3.weight(.semibold)).fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, minHeight: 64, alignment: .topLeading)
                    .accessibilityIdentifier("subject-cue-text")
                if ["Head", "Eyes"].contains(cues[i].label) { liveHeadStatus }
                HStack {
                    Button { store.cueIndex = max(i - 1, 0) } label: { Label("Back", systemImage: "chevron.left") }
                        .disabled(i == 0)
                    Spacer()
                    HStack(spacing: 5) { ForEach(0..<cues.count, id: \.self) { Circle().fill($0 == i ? accent : .white.opacity(0.3)).frame(width: 6, height: 6) } }
                    Spacer()
                    Button { store.cueIndex = min(i + 1, cues.count - 1) } label: { Label("Next", systemImage: "chevron.right").labelStyle(.titleAndIcon) }
                        .disabled(i == cues.count - 1).accessibilityIdentifier("subject-cue-next")
                }.font(.subheadline)
            }
            .padding(10).background(.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 10))
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 30).onEnded { v in
                if v.translation.width < -30 { store.cueIndex = min(i + 1, cues.count - 1) }
                else if v.translation.width > 30 { store.cueIndex = max(i - 1, 0) }
            })
        }
    }

    @ViewBuilder private func line(_ label: String, _ text: String) -> some View {
        if !text.isEmpty {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(label).font(.caption2.weight(.semibold)).foregroundStyle(accent).frame(width: 64, alignment: .leading)
                Text(text).font(.footnote).fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}
