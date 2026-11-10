import Foundation
import MLX
import Network
import UIKit
import os

// MARK: - Clock

@inline(__always) func now() -> Double { CFAbsoluteTimeGetCurrent() }

// MARK: - Memory

enum MemoryProbe {
    /// task_vm_info: phys_footprint is what jetsam counts against the app's limit.
    static func vmInfo() -> task_vm_info_data_t? {
        var info = task_vm_info_data_t()
        var count = mach_msg_type_number_t(MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<natural_t>.size)
        let kr = withUnsafeMutablePointer(to: &info) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count)
            }
        }
        return kr == KERN_SUCCESS ? info : nil
    }

    static var footprint: UInt64 { vmInfo()?.phys_footprint ?? 0 }

    /// Lifetime peak of phys_footprint for this process, as the kernel ledger records it.
    static var lifetimePeakFootprint: UInt64 { UInt64(vmInfo()?.ledger_phys_footprint_peak ?? 0) }

    /// Bytes this process can still allocate before hitting its jetsam limit.
    static var available: Int { Int(os_proc_available_memory()) }
}

/// Samples footprint / available memory every 25 ms on a background queue so short
/// peaks between call boundaries are not missed.
final class MemorySampler: @unchecked Sendable {
    private let lock = NSLock()
    private var timer: DispatchSourceTimer?
    private var peak: UInt64 = 0
    private var minAvail: Int = .max

    func start() {
        lock.lock()
        peak = MemoryProbe.footprint
        minAvail = MemoryProbe.available
        lock.unlock()
        let t = DispatchSource.makeTimerSource(queue: .global(qos: .utility))
        t.schedule(deadline: .now(), repeating: .milliseconds(25))
        t.setEventHandler { [weak self] in self?.sample() }
        t.resume()
        timer = t
    }

    private func sample() {
        let f = MemoryProbe.footprint, a = MemoryProbe.available
        lock.lock()
        peak = max(peak, f)
        minAvail = min(minAvail, a)
        lock.unlock()
    }

    func stop() -> (peak: UInt64, minAvailable: Int) {
        timer?.cancel()
        timer = nil
        sample()
        lock.lock()
        defer { lock.unlock() }
        return (peak, minAvail)
    }
}

// MARK: - Thermal

extension ProcessInfo.ThermalState {
    var label: String {
        switch self {
        case .nominal: "nominal"
        case .fair: "fair"
        case .serious: "serious"
        case .critical: "critical"
        @unknown default: "unknown"
        }
    }
}

var thermalNow: String { ProcessInfo.processInfo.thermalState.label }

// MARK: - Network (evidence the run was offline)

enum NetworkProbe {
    static func snapshot() async -> NetworkSnapshot {
        await withCheckedContinuation { cont in
            let monitor = NWPathMonitor()
            let queue = DispatchQueue(label: "net.probe")
            final class Once: @unchecked Sendable { var done = false }  // only touched on `queue`
            let once = Once()
            monitor.pathUpdateHandler = { path in
                guard !once.done else { return }
                once.done = true
                monitor.cancel()
                let status: String
                switch path.status {
                case .satisfied: status = "satisfied"
                case .unsatisfied: status = "unsatisfied"
                case .requiresConnection: status = "requiresConnection"
                @unknown default: status = "unknown"
                }
                let ifaces = path.availableInterfaces.map { "\($0.type)" }
                cont.resume(returning: NetworkSnapshot(
                    status: status, interfaces: ifaces,
                    note: status == "satisfied"
                        ? "network reachable: airplane mode was OFF (the app still makes no network calls)"
                        : "no network path: consistent with airplane mode"))
            }
            monitor.start(queue: queue)
        }
    }
}

// MARK: - Device and runtime

enum DeviceProbe {
    static var machine: String {
        #if targetEnvironment(simulator)
        return ProcessInfo.processInfo.environment["SIMULATOR_MODEL_IDENTIFIER"] ?? "simulator"
        #else
        var u = utsname()
        uname(&u)
        return withUnsafeBytes(of: &u.machine) { raw in
            String(decoding: raw.prefix(while: { $0 != 0 }), as: UTF8.self)
        }
        #endif
    }

    static let knownModels = ["iPhone18,1": "iPhone 17 Pro", "iPhone18,2": "iPhone 17 Pro Max"]

    static var osBuild: String? {
        var size = 0
        sysctlbyname("kern.osversion", nil, &size, nil, 0)
        guard size > 0 else { return nil }
        var buf = [CChar](repeating: 0, count: size)
        sysctlbyname("kern.osversion", &buf, &size, nil, 0)
        return String(cString: buf)
    }

    static var buildConfiguration: String {
        #if DEBUG
        "Debug"
        #else
        "Release"
        #endif
    }

    @MainActor
    static func info() async -> DeviceInfo {
        let dev = UIDevice.current
        dev.isBatteryMonitoringEnabled = true
        let battery: String
        switch dev.batteryState {
        case .charging: battery = "charging"
        case .full: battery = "full"
        case .unplugged: battery = "unplugged"
        default: battery = "unknown"
        }
        let gpu = GPU.deviceInfo()
        let m = machine
        #if targetEnvironment(simulator)
        let sim = true
        #else
        let sim = false
        #endif
        return DeviceInfo(
            machine: m, modelName: knownModels[m], systemName: dev.systemName,
            systemVersion: dev.systemVersion, osBuild: osBuild,
            physicalMemory: ProcessInfo.processInfo.physicalMemory,
            processorCount: ProcessInfo.processInfo.processorCount,
            gpuArchitecture: gpu.architecture, gpuRecommendedWorkingSet: gpu.maxRecommendedWorkingSetSize,
            lowPowerMode: ProcessInfo.processInfo.isLowPowerModeEnabled,
            batteryLevel: dev.batteryLevel >= 0 ? dev.batteryLevel : nil, batteryState: battery,
            thermalStateAtStart: thermalNow, availableMemoryAtStart: MemoryProbe.available,
            footprintAtStart: MemoryProbe.footprint,
            systemUptimeAtStart: ProcessInfo.processInfo.systemUptime,
            networkAtStart: await NetworkProbe.snapshot(),
            buildConfiguration: buildConfiguration, isSimulator: sim)
    }

    /// Package versions from the Package.resolved that the build bundles.
    static func packageVersions() -> [String: String] {
        guard let url = Bundle.main.url(forResource: "Package", withExtension: "resolved"),
              let data = try? Data(contentsOf: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let pins = obj["pins"] as? [[String: Any]]
        else { return ["error": "Package.resolved not bundled"] }
        var out: [String: String] = [:]
        for pin in pins {
            guard let id = pin["identity"] as? String, let state = pin["state"] as? [String: Any] else { continue }
            let rev = (state["revision"] as? String).map { String($0.prefix(12)) } ?? "?"
            out[id] = (state["version"] as? String).map { "\($0) (\(rev))" } ?? (state["branch"] as? String ?? rev)
        }
        return out
    }
}

func formatBytes(_ b: some BinaryInteger) -> String {
    String(format: "%.2f GB", Double(b) / 1_073_741_824)
}
