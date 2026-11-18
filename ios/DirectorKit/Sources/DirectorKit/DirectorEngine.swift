import Foundation

/// The four starter styles from photography-ai prompts.STYLE_BRIEFS.
public enum DirectorStyle: String, Codable, Sendable, CaseIterable {
    case relaxedCandid = "relaxed_candid"
    case dreamyAtmospheric = "dreamy_atmospheric"
    case coolEditorial = "cool_editorial"
    case vintageCCD = "vintage_ccd"
}

public enum ImageRole: String, Codable, Sendable { case inspiration, target }

/// A photo already downscaled by the app (long edge about 1024 px, JPEG). Engines never resize.
public struct DirectorImage: Equatable, Sendable {
    public let role: ImageRole
    public let jpeg: Data
    public init(role: ImageRole, jpeg: Data) { self.role = role; self.jpeg = jpeg }
}

public enum DirectorMode: String, Codable, Sendable {
    /// 3-5 inspiration photos plus a target (Inspiration Director).
    case inspiration
    /// One scene photo plus a style brief (Scene Director).
    case scene
    /// One photo of a view, no person to pose (Scenery Director). Style is not used; a note is optional.
    case scenery
}

/// What an engine is allowed to send off the phone. The router resolves this; engines obey it.
public enum UploadMode: String, Codable, Sendable {
    /// Photos go with the request. Best quality: matches what the model is trained on.
    case photos
    /// Only the on-device scene reading (text) goes. No pixels leave the phone.
    case sceneTextOnly
    /// Nothing leaves the phone.
    case none
}

public struct DirectorRequest: Sendable {
    public let mode: DirectorMode
    public let style: DirectorStyle?
    public let brief: String?
    public let images: [DirectorImage]
    public let shotFormat: ShotFormat
    public let shotCount: Int
    /// Set by HybridDirector from the policy. Engines must not exceed it.
    public var upload: UploadMode
    /// Set by HybridDirector from device state. Only the offline engine reads it.
    public var offlineProfile: OfflineProfile

    public init(
        mode: DirectorMode, style: DirectorStyle? = nil, brief: String? = nil,
        images: [DirectorImage], shotFormat: ShotFormat = .v3, shotCount: Int = 3,
        upload: UploadMode = .none, offlineProfile: OfflineProfile = .standard
    ) {
        self.mode = mode; self.style = style; self.brief = brief; self.images = images
        self.shotFormat = shotFormat; self.shotCount = shotCount
        self.upload = upload; self.offlineProfile = offlineProfile
    }
}

extension DirectorRequest {
    /// Both functions share one request. Scene Director: one target photo and a style or brief.
    /// Inspiration Director: 3-5 inspiration photos plus one target.
    public func validate() throws {
        let insp = images.filter { $0.role == .inspiration }.count
        let tgt = images.filter { $0.role == .target }.count
        guard tgt == 1 else { throw DirectorError.invalidRequest("Add exactly one photo of the place you will shoot.") }
        switch mode {
        case .scene:
            guard insp == 0 else { throw DirectorError.invalidRequest("Scene mode takes one photo and no references.") }
            guard style != nil || !(brief ?? "").trimmingCharacters(in: .whitespaces).isEmpty else {
                throw DirectorError.invalidRequest("Choose a style or write a short brief.")
            }
        case .scenery:
            guard insp == 0 else { throw DirectorError.invalidRequest("Scenery mode takes one photo and no references.") }
        case .inspiration:
            guard (3...5).contains(insp) else { throw DirectorError.invalidRequest("Add 3 to 5 inspiration photos.") }
        }
        guard shotCount >= 1 else { throw DirectorError.invalidRequest("Ask for at least one shot.") }
    }
}

/// Offline tuning chosen from device state (iphone-benchmark.md section 6, fallback 4).
public struct OfflineProfile: Equatable, Sendable {
    public var maxImageSide: Int
    public var maxCompositionTokens: Int
    public var skipOptionalStages: Bool

    public static let standard = OfflineProfile(maxImageSide: 1024, maxCompositionTokens: 600, skipOptionalStages: false)
    /// Used at thermal `serious` or in Low Power Mode.
    public static let reduced = OfflineProfile(maxImageSide: 768, maxCompositionTokens: 450, skipOptionalStages: true)
}

public enum EngineKind: String, Codable, Sendable { case online, offline }

public enum DirectorStage: String, Codable, Sendable {
    case preparing, readingScene, writingShots
}

public enum DirectorEvent: Equatable, Sendable {
    /// Coarse progress for the UI.
    case stage(DirectorStage, EngineKind)
    /// A finished shot. Shots arrive one at a time, in order.
    case shot(Shot, EngineKind)
    /// The online engine was abandoned. Clear any shown shots; the offline engine starts over.
    case engineSwitched(from: EngineKind, to: EngineKind, reason: String)
    case finished(EngineKind)
}

public enum DirectorError: Error, Equatable, Sendable {
    case timedOut
    case offlineUnavailable(String)
    case onlineUnavailable(String)
    case noEngineAvailable(String)
    case invalidOutput(String)
    case invalidRequest(String)
}

/// The one contract both engines implement. A stream, so shot 1 can appear while the rest generates.
public protocol DirectorEngine: Sendable {
    var kind: EngineKind { get }
    func plan(_ request: DirectorRequest) -> AsyncThrowingStream<DirectorEvent, Error>
}
