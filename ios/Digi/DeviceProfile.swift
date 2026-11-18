import SwiftUI
import UIKit

/// Which iPhone this is and how big the guidance controls should be on it. Apple Intelligence phones are
/// the iPhone 15 Pro and newer (model ids iPhone16,x and up); the same screens still run on older phones.
struct DeviceProfile: Equatable {
    var model: String
    var screenWidth: CGFloat
    var supportsAppleIntelligence: Bool

    /// 1.0 on a 393 pt wide phone (15 Pro, 16, 17 Pro). Compact phones shrink a little, Max sizes grow a little.
    var scale: CGFloat { min(max(screenWidth / 393, 0.9), 1.15) }

    static let current: DeviceProfile = {
        var info = utsname(); uname(&info)
        let raw = withUnsafePointer(to: &info.machine) {
            $0.withMemoryRebound(to: CChar.self, capacity: 1) { String(cString: $0) }
        }
        let model = ProcessInfo.processInfo.environment["SIMULATOR_MODEL_IDENTIFIER"] ?? raw
        let bounds = UIScreen.main.bounds
        return DeviceProfile(model: model, screenWidth: min(bounds.width, bounds.height),
                             supportsAppleIntelligence: supportsAI(model))
    }()

    static func supportsAI(_ model: String) -> Bool {
        guard model.hasPrefix("iPhone"), let major = Int(model.dropFirst(6).prefix { $0 != "," }) else { return false }
        return major >= 16
    }
}

private struct DeviceScaleKey: EnvironmentKey { static let defaultValue = DeviceProfile.current.scale }
extension EnvironmentValues {
    /// Multiply fixed sizes (button diameters, paddings) by this so controls fit the phone.
    var deviceScale: CGFloat {
        get { self[DeviceScaleKey.self] }
        set { self[DeviceScaleKey.self] = newValue }
    }
}
