import Foundation

/// The model seam for the on-device engine. The app implements it with mlx-swift-lm; tests use a
/// fake. One call is one prompt with at most one image (the prompt carries the image marker where
/// the image goes), greedy, capped at `maxTokens`.
public protocol OfflineTextGenerator: Sendable {
    /// `maxImageSide` is the long edge the model should see (the app downscales the JPEG to it).
    func generate(prompt: String, image: Data?, maxImageSide: Int, maxTokens: Int) async throws -> String
}

/// The on-device half of the hybrid Photography Director. Same stages and prompts as the server's
/// `photo-ai` pipeline (scene mode: read the scene, then one call per look; inspiration mode:
/// notes per photo, aesthetic, target scene, compositions), with the phone's token caps.
/// Shots are emitted one at a time as they finish, so the first one shows well before the last.
public final class OfflineEngine: DirectorEngine {
    public let kind: EngineKind = .offline
    private let generator: any OfflineTextGenerator

    /// Output budgets per stage (the pipeline's, except where the phone profile lowers them).
    enum Budget {
        static let note = 200, target = 500, aesthetic = 900, scene = 600
    }

    public init(generator: any OfflineTextGenerator) { self.generator = generator }

    public func plan(_ request: DirectorRequest) -> AsyncThrowingStream<DirectorEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    try request.validate()
                    continuation.yield(.stage(.preparing, .offline))
                    switch request.mode {
                    case .scene: try await self.scene(request, continuation)
                    case .scenery: try await self.scenery(request, continuation)
                    case .inspiration: try await self.inspiration(request, continuation)
                    }
                    continuation.yield(.finished(.offline))
                    continuation.finish()
                } catch is CancellationError {
                    continuation.finish(throwing: CancellationError())
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    // MARK: scene mode

    private func scene(_ request: DirectorRequest, _ out: AsyncThrowingStream<DirectorEvent, Error>.Continuation) async throws {
        let target = request.images.first { $0.role == .target }!.jpeg
        let profile = request.offlineProfile
        out.yield(.stage(.readingScene, .offline))
        let sceneObj = try await jsonObject(prompt: OfflinePromptData.sceneReading, image: target, profile: profile,
                                            maxTokens: Budget.scene, stage: "scene reading")
        out.yield(.stage(.writingShots, .offline))
        var shots: [Shot] = []
        for look in 1...min(max(request.shotCount, 1), OfflinePromptData.sceneLooks.count) {
            try Task.checkCancellation()
            let prompt = OfflinePrompts.sceneLook(scene: sceneObj, style: request.style, brief: request.brief,
                                                  look: look, previous: shots)
            let obj = try await jsonObject(prompt: prompt, image: target, profile: profile,
                                           maxTokens: lookTokens(profile), stage: "look \(look)")
            let shot = try Self.decodeShot(obj)
            guard shot.isActionable else {
                throw DirectorError.invalidOutput("The on-device director wrote an incomplete shot.")
            }
            shots.append(shot)
            out.yield(.shot(shot, .offline))
        }
    }

    // MARK: scenery mode

    private func scenery(_ request: DirectorRequest, _ out: AsyncThrowingStream<DirectorEvent, Error>.Continuation) async throws {
        let target = request.images.first { $0.role == .target }!.jpeg
        let profile = request.offlineProfile
        out.yield(.stage(.readingScene, .offline))
        let sceneObj = try await jsonObject(prompt: OfflinePromptData.scenerySceneReading, image: target, profile: profile,
                                            maxTokens: Budget.scene, stage: "scene reading")
        out.yield(.stage(.writingShots, .offline))
        var shots: [Shot] = []
        for look in 1...min(max(request.shotCount, 1), OfflinePromptData.sceneryLooks.count) {
            try Task.checkCancellation()
            let prompt = OfflinePrompts.sceneryLook(scene: sceneObj, brief: request.brief, look: look, previous: shots)
            let obj = try await jsonObject(prompt: prompt, image: target, profile: profile,
                                           maxTokens: lookTokens(profile), stage: "look \(look)")
            let shot = try Self.decodeShot(obj)
            guard shot.isActionable else {
                throw DirectorError.invalidOutput("The on-device director wrote an incomplete shot.")
            }
            shots.append(shot)
            out.yield(.shot(shot, .offline))
        }
    }

    /// One look is about 450-650 tokens on the Mac, more when the photo has people in it. Match the
    /// server's 900 (the profile's cap plus 300 when the phone is running reduced); a look that still
    /// gets cut off is repaired when its core fields are done.
    func lookTokens(_ profile: OfflineProfile) -> Int { profile.maxCompositionTokens + 300 }

    // MARK: inspiration mode

    private func inspiration(_ request: DirectorRequest, _ out: AsyncThrowingStream<DirectorEvent, Error>.Continuation) async throws {
        let profile = request.offlineProfile
        let target = request.images.first { $0.role == .target }!.jpeg
        var references = request.images.filter { $0.role == .inspiration }
        if profile.skipOptionalStages { references = Array(references.prefix(3)) }  // fewer notes when the phone is hot

        // The notes and the aesthetic do not depend on the target photo, so a later version can run them
        // before the user reaches the place.
        out.yield(.stage(.readingScene, .offline))
        var notes: [String] = []
        for ref in references {
            try Task.checkCancellation()
            let text = try await generator.generate(prompt: OfflinePromptData.imageNotes, image: ref.jpeg,
                                                    maxImageSide: profile.maxImageSide, maxTokens: Budget.note)
            notes.append(text.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        let aesthetic = try await jsonObject(prompt: OfflinePrompts.aesthetic(notes: notes), image: nil, profile: profile,
                                             maxTokens: Budget.aesthetic, stage: "aesthetic")
        let targetObj = try await jsonObject(prompt: OfflinePromptData.targetScene, image: target, profile: profile,
                                             maxTokens: Budget.target, stage: "target scene")

        out.yield(.stage(.writingShots, .offline))
        let prompt = OfflinePrompts.photographerAsks(OfflinePrompts.compositions(aesthetic: aesthetic, target: targetObj), brief: request.brief)
        // Three shots with reasoning fields run well past the profile's single-look cap; a cut-off answer
        // still yields its finished shots, so the budget bounds time rather than validity.
        let budget = profile.maxCompositionTokens * 2
        var shots = try await shotsFrom(prompt: prompt, image: target, profile: profile, maxTokens: budget)
        if shots.isEmpty {  // one retry, as the server does
            shots = try await shotsFrom(prompt: prompt + OfflinePromptData.retrySuffix, image: target, profile: profile, maxTokens: budget)
        }
        guard !shots.isEmpty else { throw DirectorError.invalidOutput("The on-device director could not write shots from these photos.") }
        for shot in shots.prefix(max(request.shotCount, 1)) { out.yield(.shot(shot, .offline)) }
    }

    private func shotsFrom(prompt: String, image: Data, profile: OfflineProfile, maxTokens: Int) async throws -> [Shot] {
        try Task.checkCancellation()
        let text = try await generator.generate(prompt: prompt, image: image, maxImageSide: profile.maxImageSide, maxTokens: maxTokens)
        return PromptJSON.objects(inArray: "compositions", in: text).compactMap { try? Self.decodeShot($0) }.filter(\.isActionable)
    }

    // MARK: shared

    /// Runs one JSON stage; on invalid output retries once with the pipeline's retry suffix.
    private func jsonObject(prompt: String, image: Data?, profile: OfflineProfile, maxTokens: Int,
                            stage: String) async throws -> [String: Any] {
        for attempt in 0..<2 {
            try Task.checkCancellation()
            let text = try await generator.generate(prompt: attempt == 0 ? prompt : prompt + OfflinePromptData.retrySuffix,
                                                    image: image, maxImageSide: profile.maxImageSide, maxTokens: maxTokens)
            if let obj = PromptJSON.objectAllowingTruncation(in: text) { return obj }
        }
        throw DirectorError.invalidOutput("The on-device director could not read the \(stage).")
    }

    static func decodeShot(_ obj: [String: Any]) throws -> Shot {
        let data = try JSONSerialization.data(withJSONObject: obj)
        return try JSONDecoder().decode(Shot.self, from: data)
    }
}
