import Foundation

/// How the user trades result quality against waiting. The default is best results: the online model
/// writes better shots than the phone, so it gets generous time before the phone takes over.
/// Speed is something the user chooses, never something the app assumes.
public enum DirectorPriority: String, Codable, CaseIterable, Sendable {
    case bestResults, balanced, fastest

    /// How long the online engine gets to show a first shot, and to finish, before the phone takes over.
    /// The Mac-hosted server needs about 12 s for a first shot and 30 to 60 s overall.
    public var firstShotDeadline: TimeInterval {
        switch self { case .bestResults: return 40; case .balanced: return 15; case .fastest: return 6 }
    }
    public var totalDeadline: TimeInterval {
        switch self { case .bestResults: return 120; case .balanced: return 45; case .fastest: return 15 }
    }
}

public extension DirectorConfig {
    /// The config for a user's choices. Only the waiting limits depend on priority.
    static func make(preference: UserEnginePreference, priority: DirectorPriority) -> DirectorConfig {
        DirectorConfig(preference: preference, onlineFirstShotDeadline: priority.firstShotDeadline,
                       onlineTotalDeadline: priority.totalDeadline)
    }
}

/// One planning run, kept on the phone so quality and speed can be compared with real use.
public struct RunRecord: Codable, Equatable, Identifiable, Sendable {
    public var id: UUID
    public var date: Date
    public var engine: EngineKind
    public var priority: DirectorPriority
    /// Seconds to the first shot, and to the end. Nil when no shot arrived.
    public var firstShotSeconds: Double?
    public var totalSeconds: Double
    public var shotCount: Int
    /// The online engine was tried first and the phone answered instead.
    public var fellBack: Bool
    /// How the person responded: shots they starred, and whether they pinned one to the camera.
    public var keptCount = 0
    public var usedShot = false

    public init(id: UUID = UUID(), date: Date = Date(), engine: EngineKind, priority: DirectorPriority,
                firstShotSeconds: Double?, totalSeconds: Double, shotCount: Int, fellBack: Bool) {
        self.id = id; self.date = date; self.engine = engine; self.priority = priority
        self.firstShotSeconds = firstShotSeconds; self.totalSeconds = totalSeconds
        self.shotCount = shotCount; self.fellBack = fellBack
    }
}

/// What the run log says about each engine. Starred shots and pinned shots are the quality signal
/// (people keep what they like); times are the cost. Blind review in `scene-eval` stays the judge of
/// model quality; this shows how each engine behaves for real use.
public struct EngineStats: Equatable, Sendable {
    public var engine: EngineKind
    public var runs: Int
    public var medianFirstShotSeconds: Double?
    public var medianTotalSeconds: Double
    /// Starred shots per shot shown, and the share of runs where a shot was pinned.
    public var keepRate: Double
    public var useRate: Double
}

public enum RunLog {
    public static let maxRecords = 200

    public static func summarize(_ records: [RunRecord]) -> [EngineStats] {
        EngineKind.allCases.compactMap { kind in
            let rs = records.filter { $0.engine == kind && $0.shotCount > 0 }
            guard !rs.isEmpty else { return nil }
            let shots = rs.reduce(0) { $0 + $1.shotCount }
            return EngineStats(
                engine: kind, runs: rs.count,
                medianFirstShotSeconds: median(rs.compactMap(\.firstShotSeconds)),
                medianTotalSeconds: median(rs.map(\.totalSeconds)) ?? 0,
                keepRate: shots == 0 ? 0 : Double(rs.reduce(0) { $0 + $1.keptCount }) / Double(shots),
                useRate: Double(rs.filter(\.usedShot).count) / Double(rs.count))
        }
    }

    /// Newest last, capped, so the log never grows without bound.
    public static func appended(_ records: [RunRecord], _ new: RunRecord) -> [RunRecord] {
        Array((records + [new]).suffix(maxRecords))
    }

    static func median(_ xs: [Double]) -> Double? {
        guard !xs.isEmpty else { return nil }
        let s = xs.sorted(), m = s.count / 2
        return s.count % 2 == 1 ? s[m] : (s[m - 1] + s[m]) / 2
    }
}

extension EngineKind: CaseIterable { public static var allCases: [EngineKind] { [.online, .offline] } }
