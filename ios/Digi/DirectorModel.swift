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
        let config = DirectorConfig(preference: DirectorDefaults.userPreference())
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
