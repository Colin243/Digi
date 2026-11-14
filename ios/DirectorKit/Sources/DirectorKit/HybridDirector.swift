import Foundation

/// Runs the router's plan: online first with a first-shot and a total deadline, then the phone.
/// The UI sees one stream whichever engine answers.
public final class HybridDirector: Sendable {
    private let online: (any DirectorEngine)?
    private let offline: (any DirectorEngine)?
    private let conditions: any DeviceConditionsProvider
    private let config: @Sendable () -> DirectorConfig

    public init(
        online: (any DirectorEngine)?, offline: (any DirectorEngine)?,
        conditions: any DeviceConditionsProvider, config: @escaping @Sendable () -> DirectorConfig
    ) {
        self.online = online; self.offline = offline
        self.conditions = conditions; self.config = config
    }

    public func plan(_ base: DirectorRequest) -> AsyncThrowingStream<DirectorEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    try base.validate()
                    let cfg = config()
                    let route = try Router.route(conditions: await conditions.current(), config: cfg)
                    var request = base
                    request.upload = route.upload
                    request.offlineProfile = route.offlineProfile

                    var order = route.order.filter { $0 == .online ? online != nil : offline != nil }
                    if order.isEmpty { throw DirectorError.noEngineAvailable("No engine is installed.") }

                    var lastError: Error = DirectorError.noEngineAvailable("No engine ran.")
                    var switched: (from: EngineKind, reason: String)?
                    while !order.isEmpty {
                        let kind = order.removeFirst()
                        let engine = (kind == .online ? online : offline)!
                        if let s = switched {
                            continuation.yield(.engineSwitched(from: s.from, to: kind, reason: s.reason))
                            switched = nil
                        }
                        do {
                            try await Self.run(engine, request, cfg: cfg, deadlines: kind == .online, into: continuation)
                            continuation.finish()
                            return
                        } catch is CancellationError {
                            throw CancellationError()
                        } catch {
                            lastError = error
                            if !order.isEmpty { switched = (kind, Self.describe(error)) }
                        }
                    }
                    throw lastError
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    static func describe(_ e: Error) -> String {
        if let d = e as? DirectorError, d == .timedOut { return "online engine was too slow" }
        return "online engine failed: \(e.localizedDescription)"
    }

    private final class Progress: @unchecked Sendable {
        private let lock = NSLock(); private var n = 0
        func bump() { lock.lock(); n += 1; lock.unlock() }
        var shots: Int { lock.lock(); defer { lock.unlock() }; return n }
    }

    /// Streams one engine's events. For the online engine, throws .timedOut when no shot has
    /// arrived by the first-shot deadline or the run exceeds the total deadline.
    private static func run(
        _ engine: any DirectorEngine, _ request: DirectorRequest, cfg: DirectorConfig, deadlines: Bool,
        into continuation: AsyncThrowingStream<DirectorEvent, Error>.Continuation
    ) async throws {
        let progress = Progress()
        try await withThrowingTaskGroup(of: Void.self) { group in
            group.addTask {
                for try await event in engine.plan(request) {
                    if case .shot = event { progress.bump() }
                    continuation.yield(event)
                }
            }
            if deadlines {
                group.addTask {
                    try await Task.sleep(for: .seconds(cfg.onlineFirstShotDeadline))
                    if progress.shots == 0 { throw DirectorError.timedOut }
                    try await Task.sleep(for: .seconds(max(0, cfg.onlineTotalDeadline - cfg.onlineFirstShotDeadline)))
                    throw DirectorError.timedOut
                }
            }
            // The engine task finishing first ends the run; a deadline throwing first cancels it.
            try await group.next()
            group.cancelAll()
        }
    }
}
