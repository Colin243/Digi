import Foundation
import SwiftUI
import UIKit
import DirectorKit

@MainActor
final class DirectorModel: ObservableObject {
    enum Phase: Equatable { case idle, running, done, failed(String) }

    @Published var phase: Phase = .idle
    @Published var stageText = ""
    @Published private(set) var deck = ShotDeck()
    var shots: [Shot] { deck.shots }
    /// The request behind the shots on screen, so a refresh asks for the same place and style again.
    private var lastRequest: DirectorRequest?
    @Published var engineUsed: EngineKind?
    @Published var notice: String?

    private var task: Task<Void, Never>?

    #if DEBUG
    init() {
        // Debug only: `-digiDebugShots YES` shows sample results so the shot cards can be reviewed without a server.
        if UserDefaults.standard.bool(forKey: "digiDebugShots") {
            for i in 0..<3 { var shot = PinnedShotStore.debugSampleShot; shot.title += " \(i + 1)"; deck.append(shot) }
            engineUsed = .online; phase = .done
        }
    }
    #endif

    /// Builds the director from the current Settings each time, so edits apply to the next request.
    private func makeDirector() -> HybridDirector {
        // Best results by default: the online model writes better shots, so it gets time to finish.
        // Waiting limits come from the user's priority (see DirectorPriority).
        let config = DirectorConfig.make(preference: DirectorDefaults.userPreference(), priority: DirectorDefaults.userPriority())
        let online = DirectorDefaults.configuration().map { OnlineEngine(configuration: $0) }
        return HybridDirector(online: online, offline: OfflineEngine(generator: OnDeviceGenerator.shared),
                              conditions: SystemConditionsProvider(), config: { config })
    }

    func run(mode: DirectorMode, style: DirectorStyle, brief: String, target: UIImage?, inspiration: [UIImage]) {
        guard let target, let targetJPEG = Self.jpeg(target) else {
            phase = .failed("Add a photo of the place you will shoot."); return
        }
        var images = [DirectorImage(role: .target, jpeg: targetJPEG)]
        if mode == .inspiration {
            images += inspiration.compactMap { Self.jpeg($0) }.map { DirectorImage(role: .inspiration, jpeg: $0) }
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
        let request = DirectorRequest(mode: base.mode, style: base.style,
                                      brief: ShotDeck.briefAvoiding(seen, base: base.brief), images: base.images)
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
        task = Task { [weak self] in
            /// Writes the run to the log once it ends with at least one shot.
            @MainActor func record() {
                guard let self, shotCount > 0 else { return }
                let r = RunRecord(engine: self.engineUsed ?? .offline, priority: priority,
                                  firstShotSeconds: firstShotAt.map { $0.timeIntervalSince(started) },
                                  totalSeconds: Date().timeIntervalSince(started), shotCount: shotCount, fellBack: fellBack)
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
                    case .shot(let shot, let engine):
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
    private var accent: Color { theme.hint ?? Color(red: 1.0, green: 0.78, blue: 0.2) }
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
                    }.frame(maxHeight: 120)
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
