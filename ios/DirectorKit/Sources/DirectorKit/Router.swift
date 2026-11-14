import Foundation

public struct RoutePlan: Equatable, Sendable {
    /// Engines to try, in order.
    public var order: [EngineKind]
    public var upload: UploadMode
    public var offlineProfile: OfflineProfile
    public var reason: String
}

/// Pure routing rules. Mirrors iphone-benchmark.md section 6 (graceful fallback).
public enum Router {
    public static func route(conditions c: DeviceConditions, config: DirectorConfig) throws -> RoutePlan {
        let profile: OfflineProfile = (c.thermal >= .serious || c.lowPowerMode) ? .reduced : .standard

        let memoryOK = c.availableMemoryBytes >= config.weightsBytes + config.memoryHeadroomBytes
        let thermalOK = c.thermal < .critical
        let offlineOK = memoryOK && thermalOK
        let onlineOK = config.preference != .offlineOnly && c.connectivity != .none

        var order: [EngineKind] = []
        var reason: String
        switch (onlineOK, offlineOK) {
        case (true, true):
            // Low Data Mode: keep photos off the cellular link when the phone can do it.
            order = c.connectivity == .constrained ? [.offline, .online] : [.online, .offline]
            reason = c.connectivity == .constrained ? "Low Data Mode: on-device first" : "connected: online first"
        case (true, false):
            order = [.online]
            reason = !thermalOK ? "phone too hot for on-device" : "not enough free memory for on-device"
        case (false, true):
            order = [.offline]
            reason = config.preference == .offlineOnly ? "offline-only setting" : "no connection"
        case (false, false):
            if !thermalOK { throw DirectorError.noEngineAvailable("The phone is too hot. Let it cool down and try again.") }
            if !memoryOK { throw DirectorError.noEngineAvailable("Not enough free memory for the on-device director. Close other apps and try again.") }
            throw DirectorError.noEngineAvailable("No connection and the on-device director is unavailable.")
        }
        // Nothing may leave the phone when only the on-device engine will run.
        let upload: UploadMode = order.contains(.online) ? config.uploadMode : .none
        return RoutePlan(order: order, upload: upload, offlineProfile: profile, reason: reason)
    }
}
