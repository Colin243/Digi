import Foundation

/// What the user chose in Settings.
public enum UserEnginePreference: String, Codable, Sendable {
    /// Use the online engine when the router allows it, otherwise the phone. Photos go with the request.
    case automatic
    /// Online is allowed, but only the on-device scene reading (text) leaves the phone, never pixels.
    /// The privacy option for users who don't want photos sent.
    case textOnly
    /// Never use the network.
    case offlineOnly
}

/// App-level configuration. Photos go out by default, with no prompt; a user can switch to
/// `.textOnly` or `.offlineOnly` (the Settings screen for that comes later).
public struct DirectorConfig: Equatable, Sendable {
    public var preference: UserEnginePreference
    /// The online engine gets this long to show its first shot, and this long overall.
    public var onlineFirstShotDeadline: TimeInterval
    public var onlineTotalDeadline: TimeInterval
    /// Free memory the phone must have beyond the weights before the model is loaded.
    public var weightsBytes: UInt64
    public var memoryHeadroomBytes: UInt64

    public init(
        preference: UserEnginePreference = .automatic,
        onlineFirstShotDeadline: TimeInterval = 6, onlineTotalDeadline: TimeInterval = 15,
        weightsBytes: UInt64 = 1_780_000_000, memoryHeadroomBytes: UInt64 = 1_500_000_000
    ) {
        self.preference = preference
        self.onlineFirstShotDeadline = onlineFirstShotDeadline
        self.onlineTotalDeadline = onlineTotalDeadline
        self.weightsBytes = weightsBytes
        self.memoryHeadroomBytes = memoryHeadroomBytes
    }

    public var uploadMode: UploadMode {
        switch preference {
        case .offlineOnly: return .none
        case .textOnly: return .sceneTextOnly
        case .automatic: return .photos
        }
    }
}

public enum Connectivity: String, Sendable { case none, constrained, ok }
public enum Thermal: String, Sendable, Comparable {
    case nominal, fair, serious, critical
    private var rank: Int { [Thermal.nominal, .fair, .serious, .critical].firstIndex(of: self)! }
    public static func < (a: Thermal, b: Thermal) -> Bool { a.rank < b.rank }
}

/// A snapshot of the phone. A protocol-free value so the router is a pure function and testable.
public struct DeviceConditions: Equatable, Sendable {
    public var connectivity: Connectivity
    public var thermal: Thermal
    public var lowPowerMode: Bool
    public var availableMemoryBytes: UInt64
    public init(connectivity: Connectivity, thermal: Thermal = .nominal, lowPowerMode: Bool = false,
                availableMemoryBytes: UInt64 = 6_000_000_000) {
        self.connectivity = connectivity; self.thermal = thermal
        self.lowPowerMode = lowPowerMode; self.availableMemoryBytes = availableMemoryBytes
    }
}

public protocol DeviceConditionsProvider: Sendable {
    func current() async -> DeviceConditions
}
