import Foundation

/// The shots on the Director screen, with the ones the user keeps. A refresh replaces only the shots
/// that are not kept, in place, and asks the engine for something different from everything seen so far.
public struct ShotDeck: Equatable, Sendable {
    public private(set) var shots: [Shot]
    public private(set) var kept: Set<String>
    /// Slots (indices into `shots`) waiting for a replacement, in order. Empty when not refreshing.
    public private(set) var pending: [Int] = []

    public init(shots: [Shot] = [], kept: Set<String> = []) { self.shots = shots; self.kept = kept }

    public var isRefreshing: Bool { !pending.isEmpty }
    public func isKept(_ shot: Shot) -> Bool { kept.contains(shot.id) }
    public var keptCount: Int { shots.filter(isKept).count }
    /// A refresh needs something to replace: at least one shot, and not all of them kept.
    public var canRefresh: Bool { !shots.isEmpty && keptCount < shots.count && !isRefreshing }

    public mutating func toggleKeep(_ shot: Shot) {
        if kept.contains(shot.id) { kept.remove(shot.id) } else { kept.insert(shot.id) }
    }

    /// A shot streaming in during the first run.
    public mutating func append(_ shot: Shot) { shots.append(shot) }

    /// Drops every shot that is not kept; used when the engine switches and starts over.
    public mutating func resetKeepingFavorites() { shots = shots.filter(isKept); pending = [] }

    public mutating func clear() { shots = []; kept = []; pending = [] }

    /// Starts a refresh. Returns every shot seen so far (kept and not), for the "avoid" text, or nil when
    /// there is nothing to replace.
    public mutating func beginRefresh() -> [Shot]? {
        guard canRefresh else { return nil }
        pending = shots.indices.filter { !isKept(shots[$0]) }
        return shots
    }

    /// Puts a new shot into the next waiting slot. A shot that repeats one already shown is skipped.
    /// Returns true once every waiting slot is filled.
    @discardableResult
    public mutating func fill(_ shot: Shot) -> Bool {
        guard let slot = pending.first else { return true }
        guard !shots.contains(where: { $0.id == shot.id }) else { return false }
        shots[slot] = shot
        pending.removeFirst()
        return pending.isEmpty
    }

    /// Stops waiting; slots that never got a replacement keep their old shot.
    public mutating func endRefresh() { pending = [] }

    /// The brief for a refresh: the user's own note plus the earlier ideas to steer away from.
    public static func briefAvoiding(_ shots: [Shot], base: String?) -> String {
        let seen = shots.map { s -> String in
            let where_ = s.cameraPosition.isEmpty ? "" : " (\(s.cameraPosition))"
            return s.title + where_
        }
        let avoid = seen.isEmpty ? "" : "Give new ideas, different from these earlier looks: " + seen.joined(separator: "; ") + "."
        let note = (base ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return [note, avoid].filter { !$0.isEmpty }.joined(separator: " ")
    }
}
