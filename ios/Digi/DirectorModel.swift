import Foundation
import SwiftUI
import UIKit
import DirectorKit

/// Stand-in until the on-device engine (mlx-swift-lm) is wrapped as a DirectorEngine. It always
/// declines, so HybridDirector reports a clear error instead of crashing when the server is unreachable.
struct OfflineEngineUnavailable: DirectorEngine {
    let kind: EngineKind = .offline
    func plan(_ request: DirectorRequest) -> AsyncThrowingStream<DirectorEvent, Error> {
        AsyncThrowingStream { $0.finish(throwing: DirectorError.offlineUnavailable("The on-device director is not installed yet.")) }
    }
}

@MainActor
final class DirectorModel: ObservableObject {
    enum Phase: Equatable { case idle, running, done, failed(String) }

    @Published var phase: Phase = .idle
    @Published var stageText = ""
    @Published var shots: [Shot] = []
    @Published var engineUsed: EngineKind?
    @Published var notice: String?

    private var task: Task<Void, Never>?

    /// Builds the director from the current Settings each time, so edits apply to the next request.
    private func makeDirector() -> HybridDirector {
        // The Mac-hosted server needs ~12 s for a first shot and 30-60 s overall; the package defaults
        // (6 s / 15 s) are for a cloud GPU. Tighten these again when the server moves to the cloud.
        let config = DirectorConfig(preference: DirectorDefaults.userPreference(),
                                    onlineFirstShotDeadline: 40, onlineTotalDeadline: 120)
        let online = DirectorDefaults.configuration().map { OnlineEngine(configuration: $0) }
        return HybridDirector(online: online, offline: OfflineEngineUnavailable(),
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
        shots = []; engineUsed = nil; notice = nil; stageText = "Starting"; phase = .running
        let director = makeDirector()
        task = Task { [weak self] in
            do {
                for try await event in director.plan(request) {
                    guard let self else { return }
                    switch event {
                    case .stage(let stage, let engine):
                        self.engineUsed = engine
                        self.stageText = Self.describe(stage, engine)
                    case .shot(let shot, let engine):
                        self.engineUsed = engine
                        self.shots.append(shot)
                    case .engineSwitched(_, let to, let reason):
                        self.shots = []; self.engineUsed = to
                        self.notice = "Switched to \(to == .offline ? "the phone" : "online"): \(reason)."
                    case .finished(let engine):
                        self.engineUsed = engine; self.phase = .done
                    }
                }
                if self?.phase == .running { self?.phase = .done }
            } catch is CancellationError {
            } catch {
                self?.phase = .failed(Self.message(for: error))
            }
        }
    }

    func cancel() { task?.cancel(); task = nil; if phase == .running { phase = .idle } }

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
    }

    func pin(_ shot: Shot) {
        self.shot = shot; stepIndex = 0; expanded = true; directing = false; cueIndex = 0
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
    @AppStorage("digi.guidanceDebug") private var debugBoxes = false
    private let accent = Color(red: 1.0, green: 0.78, blue: 0.2)

    var body: some View {
        if let shot = store.shot {
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
                LiveCueRow(live: LiveGuidance.shared, accent: accent)
                controls
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
                    }.frame(maxHeight: 190)
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
                    Toggle("Show detection boxes", isOn: $debugBoxes).font(.caption).tint(accent)
                        .accessibilityIdentifier("guidance-debug-toggle")
                }
            }
            .font(.footnote).foregroundStyle(.white)
            .padding(10)
            .background(.black.opacity(0.72), in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(accent.opacity(0.45), lineWidth: 1))
            .padding(8)
            .accessibilityIdentifier("pinned-shot-card")
        }
    }

    /// Camera / Subject switch, plus choosing who to direct.
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
            if live.detections.locked {
                Button { live.clearSubject() } label: {
                    Label("Subject", systemImage: "xmark.circle.fill").font(.caption.weight(.semibold))
                }.tint(.green).accessibilityLabel("Stop following the chosen subject")
                    .accessibilityIdentifier("subject-clear")
            } else {
                Button { live.choosingSubject.toggle() } label: {
                    Label(live.choosingSubject ? "Cancel" : "Choose", systemImage: "person.crop.rectangle").font(.caption.weight(.semibold))
                }.tint(accent).disabled(!live.running)
                    .accessibilityLabel(live.choosingSubject ? "Cancel choosing a subject" : "Choose who to direct")
                    .accessibilityIdentifier("subject-choose")
            }
        }
    }

    /// Live check of the subject's head against the shot (when the experimental toggle is on).
    @ViewBuilder private var liveHeadStatus: some View {
        let g = live.guidance
        let head = live.targets?.head ?? HeadTargets()
        if live.subjectCuesEnabled && !head.isEmpty {
            VStack(alignment: .leading, spacing: 3) {
                if g.subjectSatisfied {
                    Label("Head looks right", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
                } else if g.subjectCues.isEmpty {
                    Label("Watching their head…", systemImage: "eye").foregroundStyle(.white.opacity(0.6))
                } else {
                    ForEach(Array(g.subjectCues.enumerated()), id: \.offset) { _, c in
                        Label(c.text, systemImage: c.symbol).foregroundStyle(.cyan)
                    }
                }
            }
            .font(.footnote.weight(.semibold))
            .accessibilityIdentifier("subject-live-status")
        } else if live.subjectCuesEnabled {
            Text("Nothing in this direction the camera can check.").font(.caption).foregroundStyle(.white.opacity(0.6))
        }
    }

    /// Big, read-aloud cards for directing the person: where to be, pose, head, eyes, expression.
    @ViewBuilder private func subjectCards(_ shot: Shot) -> some View {
        Toggle(isOn: $live.subjectCuesEnabled) {
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
