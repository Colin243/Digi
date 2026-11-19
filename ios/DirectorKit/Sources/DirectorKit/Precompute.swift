import CryptoKit
import Foundation

/// Work the server did before the plan request (photo-ai server: /v1/references, /v1/scene, /v1/prepare-plan).
/// Sent with an Inspiration Director plan so the server skips those stages. The JSON values are opaque here:
/// the server checks them (model, prompts, the photo they were read from) and refuses stale ones, in which case
/// the online engine retries once with the photos alone.
public struct PreparedInputs: Equatable, Sendable {
    /// Notes on each inspiration photo plus the aesthetic built from them (a JSON object).
    public var references: Data?
    /// The target photo's scene reading, tied to a hash of that photo (a JSON object).
    public var targetScene: Data?
    /// Single-use handle to the compositions prompt the server already read. Expires on the server after 10 minutes.
    public var planToken: String?

    public init(references: Data? = nil, targetScene: Data? = nil, planToken: String? = nil) {
        self.references = references; self.targetScene = targetScene; self.planToken = planToken
    }

    public var isEmpty: Bool { references == nil && targetScene == nil && planToken == nil }
}

/// The three server calls the preparer needs. `OnlineEngine` implements them; tests substitute a fake.
public protocol PrecomputeService: Sendable {
    func prepareReferences(_ inspiration: [Data]) async throws -> Data
    func prepareScene(_ target: Data) async throws -> Data
    /// Returns nil when the server has no prompt cache for this model.
    func preparePlan(target: Data, references: Data, targetScene: Data) async throws -> String?
}

/// Reads the photos ahead of time, while the person is still choosing them, one server call at a time.
///
/// Order: the target photo's scene as soon as it is picked, then the inspiration photos' references once there are
/// 3-5 of them, then the prompt prefix once both exist. Changing a photo drops only what depended on it. Results are
/// kept per exact photo bytes, so the plan must send the same JPEG `Data` that was prepared.
/// Calls run one at a time because the server runs one job at a time and turns away a third waiting request.
public actor PlanPreparer {
    public enum Status: Equatable, Sendable { case idle, working, ready }

    private struct Keyed<T: Sendable>: Sendable { let key: String; let value: T; let at: Date }

    private let service: any PrecomputeService
    private let now: @Sendable () -> Date
    /// The server keeps a plan token for 10 minutes; stop offering it a little before that.
    private let tokenLifetime: TimeInterval
    private let onStatus: (@Sendable (Status) -> Void)?

    private var target: Data?
    private var inspiration: [Data] = []
    private var scene: Keyed<Data>?
    private var references: Keyed<Data>?
    private var token: Keyed<String>?
    /// Keys whose call failed (or whose token was used), so they are not asked for again in a loop.
    /// Cleared for a part when its photos change.
    private var failed: Set<String> = []
    private var worker: Task<Void, Never>?
    private var status: Status = .idle

    public init(service: any PrecomputeService, tokenLifetime: TimeInterval = 540,
                now: @escaping @Sendable () -> Date = { Date() }, onStatus: (@Sendable (Status) -> Void)? = nil) {
        self.service = service; self.tokenLifetime = tokenLifetime; self.now = now; self.onStatus = onStatus
    }

    // MARK: keys

    static func digest(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    static func sceneKey(_ target: Data?) -> String? { target.map { "scene:" + digest($0) } }
    static func referencesKey(_ inspiration: [Data]) -> String? {
        (3...5).contains(inspiration.count) ? "refs:" + inspiration.map(digest).joined(separator: ",") : nil
    }
    static func planKey(_ target: Data?, _ inspiration: [Data]) -> String? {
        guard let s = sceneKey(target), let r = referencesKey(inspiration) else { return nil }
        return "plan:" + s + "|" + r
    }
    private var sceneKey: String? { Self.sceneKey(target) }
    private var referencesKey: String? { Self.referencesKey(inspiration) }
    private var planKey: String? { Self.planKey(target, inspiration) }

    // MARK: inputs

    /// Call whenever the target or the inspiration photos change (nil / [] for none). Starts work if any is due.
    public func update(target: Data?, inspiration: [Data]) {
        self.target = target; self.inspiration = inspiration
        if scene?.key != sceneKey { scene = nil }
        if references?.key != referencesKey { references = nil }
        if token?.key != planKey { token = nil }
        startIfNeeded()
    }

    /// What is ready for exactly these photos. Takes the plan token: it is single use on the server.
    public func prepared(target: Data, inspiration: [Data]) -> PreparedInputs {
        var out = PreparedInputs()
        if let scene, scene.key == Self.sceneKey(target) { out.targetScene = scene.value }
        if let references, references.key == Self.referencesKey(inspiration) { out.references = references.value }
        if let token, token.key == Self.planKey(target, inspiration), now().timeIntervalSince(token.at) < tokenLifetime {
            out.planToken = token.value
            self.token = nil
            failed.insert(token.key)  // used up; do not prepare another for the same photos unasked
        }
        return out
    }

    /// Stops the call in progress, if any. Everything prepared so far is kept.
    public func pause() {
        worker?.cancel(); worker = nil
        setStatus(hasResults && nextJob() == nil ? .ready : .idle)
    }

    public var currentStatus: Status { status }

    // MARK: work

    private enum Job: Sendable {
        case scene(Data, String)
        case references([Data], String)
        case plan(Data, Data, Data, String)
        var key: String {
            switch self { case let .scene(_, k), let .references(_, k), let .plan(_, _, _, k): return k }
        }
    }

    private var hasResults: Bool { scene != nil || references != nil }

    private func nextJob() -> Job? {
        if let target, let key = sceneKey, scene == nil, !failed.contains(key) { return .scene(target, key) }
        if let key = referencesKey, references == nil, !failed.contains(key) { return .references(inspiration, key) }
        if let target, let key = planKey, let s = scene, let r = references, token == nil, !failed.contains(key) {
            return .plan(target, r.value, s.value, key)
        }
        return nil
    }

    private func startIfNeeded() {
        guard worker == nil else { return }
        guard nextJob() != nil else { setStatus(hasResults ? .ready : .idle); return }
        setStatus(.working)
        worker = Task { await self.drain() }
    }

    private func drain() async {
        while !Task.isCancelled, let job = nextJob() {
            do {
                switch job {
                case let .scene(data, key):
                    let value = try await service.prepareScene(data)
                    if key == sceneKey { scene = Keyed(key: key, value: value, at: now()) }
                case let .references(photos, key):
                    let value = try await service.prepareReferences(photos)
                    if key == referencesKey { references = Keyed(key: key, value: value, at: now()) }
                case let .plan(t, r, s, key):
                    let value = try await service.preparePlan(target: t, references: r, targetScene: s)
                    if let value, key == planKey { token = Keyed(key: key, value: value, at: now()) }
                    else if value == nil { failed.insert(key) }  // no prompt cache on this server: do not ask again
                }
            } catch {
                if Task.isCancelled || error is CancellationError { break }
                failed.insert(job.key)
            }
        }
        let cancelled = Task.isCancelled
        worker = nil
        if cancelled { return }
        if nextJob() != nil { startIfNeeded() }  // photos changed during the last call
        else { setStatus(hasResults ? .ready : .idle) }
    }

    private func setStatus(_ s: Status) {
        guard s != status else { return }
        status = s
        onStatus?(s)
    }
}
