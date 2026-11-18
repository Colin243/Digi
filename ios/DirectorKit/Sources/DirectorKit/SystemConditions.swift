import Foundation
#if canImport(Network)
import Network
#endif
#if canImport(os)
import os
#endif

/// Live device snapshot. Connectivity comes from NWPathMonitor; memory from os_proc_available_memory
/// on iOS (what jetsam counts) and a large constant elsewhere so Mac tests are not memory-gated.
public final class SystemConditionsProvider: DeviceConditionsProvider, @unchecked Sendable {
    #if canImport(Network)
    private let monitor = NWPathMonitor()
    private let lock = NSLock()
    private var path: NWPath?
    #endif

    public init() {
        #if canImport(Network)
        monitor.pathUpdateHandler = { [weak self] p in
            self?.lock.lock(); self?.path = p; self?.lock.unlock()
        }
        monitor.start(queue: DispatchQueue(label: "digi.director.path"))
        #endif
    }

    deinit {
        #if canImport(Network)
        monitor.cancel()
        #endif
    }

    #if canImport(Network)
    private func latestPath() -> NWPath {
        lock.lock(); defer { lock.unlock() }
        return path ?? monitor.currentPath
    }
    #endif

    public func current() async -> DeviceConditions {
        var connectivity = Connectivity.ok
        #if canImport(Network)
        let p = latestPath()
        if p.status != .satisfied { connectivity = .none }
        else if p.isConstrained { connectivity = .constrained }
        #endif

        let thermal: Thermal
        switch ProcessInfo.processInfo.thermalState {
        case .nominal: thermal = .nominal
        case .fair: thermal = .fair
        case .serious: thermal = .serious
        case .critical: thermal = .critical
        @unknown default: thermal = .serious
        }

        var memory: UInt64 = 64_000_000_000
        #if os(iOS)
        memory = UInt64(os_proc_available_memory())
        #endif
        return DeviceConditions(
            connectivity: connectivity, thermal: thermal,
            lowPowerMode: ProcessInfo.processInfo.isLowPowerModeEnabled, availableMemoryBytes: memory)
    }
}
