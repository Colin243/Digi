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
    /// When the references are not ready yet: the notes already read, one entry per inspiration photo (nil = not read),
    /// so the plan reads only the photos that are missing.
    public var notes: [Data?]?

    public init(references: Data? = nil, targetScene: Data? = nil, planToken: String? = nil, notes: [Data?]? = nil) {
        self.references = references; self.targetScene = targetScene; self.planToken = planToken; self.notes = notes
    }

    public var isEmpty: Bool { references == nil && targetScene == nil && planToken == nil && notes == nil }
}

/// The server calls the preparer needs. `OnlineEngine` implements them; tests substitute a fake.
public protocol PrecomputeService: Sendable {
    /// One inspiration photo's notes (a JSON object), read as soon as the photo is picked.
    func prepareNote(_ photo: Data) async throws -> Data
    /// The references (notes + aesthetic) from notes already read: no photo is sent again.
    func prepareReferences(notes: [Data]) async throws -> Data
    func prepareScene(_ target: Data) async throws -> Data
    /// Returns nil when the server has no prompt cache for this model.
    func preparePlan(target: Data, references: Data, targetScene: Data) async throws -> String?
}

/// Reads the photos ahead of time, while the person is still choosing them, one server call at a time.
///
/// Order: the target photo's scene as soon as it is picked, then each inspiration photo's notes as soon as that photo
/// is there, then the references (only the aesthetic is left) once 3-5 photos all have notes, then the prompt prefix
/// once both exist. Notes are kept per photo, so swapping one photo reads only that one. Changing a photo drops only what depended on it. Results are
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
    private var inspirationComplete = true
    private var scene: Keyed<Data>?
    private var references: Keyed<Data>?
    /// Notes per inspiration photo, keyed by its bytes. Kept when a photo is removed, in case it comes back.
    private var notes: [String: Keyed<Data>] = [:]
    private static let maxNotes = 24
    private var token: Keyed<String>?
    /// Keys whose call failed (or whose token was used), so they are not asked for again in a loop.
    /// Cleared for a part when its photos change.
    private var failed: Set<String> = []
    private var worker: Task<Void, Never>?
    /// Set by finishCurrent (Plan was pressed): finish the call in progress, start no new one until the next update.
    private var stopAfterCurrent = false
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
    static func noteKey(_ photo: Data) -> String { "note:" + digest(photo) }

    // MARK: inputs

    /// Call whenever the target or the inspiration photos change (nil / [] for none). Starts work if any is due.
    /// `inspirationComplete` false while photos of one pick are still loading: their notes are read as each arrives,
    /// but the references wait for the whole set (an aesthetic built from 3 of 5 photos would be thrown away).
    public func update(target: Data?, inspiration: [Data], inspirationComplete: Bool = true) {
        let before = (Self.sceneKey(self.target), self.inspiration.map(Self.digest), self.inspirationComplete)
        self.target = target; self.inspiration = inspiration; self.inspirationComplete = inspirationComplete
        // After Plan, reading ahead resumes only for different photos; the same photos sent again (a view refreshing)
        // must not start work the plan no longer needs.
        if before != (Self.sceneKey(target), inspiration.map(Self.digest), inspirationComplete) { stopAfterCurrent = false }
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
        else {
            let read = inspiration.map { notes[Self.noteKey($0)]?.value }
            if read.contains(where: { $0 != nil }) { out.notes = read }
        }
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

    /// For the moment Plan is pressed: start no new call, but let the one in progress finish and keep its result.
    /// The server runs one job at a time, so a plan sent now would queue behind that call anyway; cancelling it only
    /// threw its result away (the server still did the work) and made the plan redo it. Returns the seconds waited.
    /// Gives up after `maxWait` (the call is then cancelled). Reading ahead resumes on the next `update`.
    @discardableResult
    public func finishCurrent(maxWait: TimeInterval = 40) async -> TimeInterval {
        stopAfterCurrent = true
        guard let w = worker else { return 0 }
        let start = now()
        let finished = await withTaskGroup(of: Bool.self) { group in
            group.addTask { await w.value; return true }
            group.addTask { try? await Task.sleep(for: .seconds(maxWait)); return false }
            let first = await group.next() ?? false
            group.cancelAll()
            return first
        }
        if !finished { w.cancel(); worker = nil }
        setStatus(hasResults ? .ready : .idle)
        return now().timeIntervalSince(start)
    }

    public var currentStatus: Status { status }

    // MARK: work

    private enum Job: Sendable {
        case scene(Data, String)
        case note(Data, String)
        case references([Data], String)
        case plan(Data, Data, Data, String)
        var key: String {
            switch self { case let .scene(_, k), let .note(_, k), let .references(_, k), let .plan(_, _, _, k): return k }
        }
    }

    private var hasResults: Bool { scene != nil || references != nil }

    private func nextJob() -> Job? {
        if let target, let key = sceneKey, scene == nil, !failed.contains(key) { return .scene(target, key) }
        for photo in inspiration {
            let key = Self.noteKey(photo)
            if notes[key] == nil, !failed.contains(key) { return .note(photo, key) }
        }
        if inspirationComplete, let key = referencesKey, references == nil, !failed.contains(key) {
            let read = inspiration.compactMap { notes[Self.noteKey($0)]?.value }
            if read.count == inspiration.count { return .references(read, key) }  // else a note failed: no references
        }
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
        while !Task.isCancelled, !stopAfterCurrent, let job = nextJob() {
            do {
                switch job {
                case let .scene(data, key):
                    let value = try await service.prepareScene(data)
                    if key == sceneKey { scene = Keyed(key: key, value: value, at: now()) }
                case let .note(photo, key):
                    let value = try await service.prepareNote(photo)
                    notes[key] = Keyed(key: key, value: value, at: now())
                    if notes.count > Self.maxNotes, let oldest = notes.min(by: { $0.value.at < $1.value.at })?.key,
                       !inspiration.contains(where: { Self.noteKey($0) == oldest }) { notes[oldest] = nil }
                case let .references(read, key):
                    let value = try await service.prepareReferences(notes: read)
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
        if nextJob() != nil && !stopAfterCurrent { startIfNeeded() }  // photos changed during the last call
        else { setStatus(hasResults ? .ready : .idle) }
    }

    private func setStatus(_ s: Status) {
        guard s != status else { return }
        status = s
        onStatus?(s)
    }
}
