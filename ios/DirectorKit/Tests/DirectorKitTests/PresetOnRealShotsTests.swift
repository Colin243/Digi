import XCTest
@testable import DirectorKit

/// Runs the camera-preset rules over real model output. Skipped unless PRESET_SHOTS points at a JSON array of
/// shots (snake_case, as the Director returns them). Prints how often each rule fires.
final class PresetOnRealShotsTests: XCTestCase {
    func testRulesOnRealShots() throws {
        guard let path = ProcessInfo.processInfo.environment["PRESET_SHOTS"] else { throw XCTSkip("set PRESET_SHOTS") }
        let shots = try JSONDecoder().decode([Shot].self, from: Data(contentsOf: URL(fileURLWithPath: path)))
        var light: [String: Int] = [:], zooms: [String: Int] = [:], flash = 0, any = 0
        var samples: [String] = []
        for s in shots {
            let p = CameraPreset.make(for: s)
            if !p.isEmpty { any += 1 }
            if let b = p.exposureBias { light[String(format: "%+.1f", b), default: 0] += 1 }
            if let z = p.zoom { zooms[String(format: "%.1fx", z), default: 0] += 1 }
            if p.flash != nil { flash += 1 }
            if p.exposureBias != nil, samples.count < 14 { samples.append("\(p.reasons.first.map { "\($0)" } ?? "") | \(s.lightingTip.prefix(140)) || title: \(s.title.prefix(40)) | setup: \(s.setupChoice.prefix(60))") }
        }
        print("PRESET RESULT shots=\(shots.count) anyPreset=\(any) exposure=\(light) zoom=\(zooms) flash=\(flash)")
        samples.forEach { print("PRESET SAMPLE", $0) }
        print("PRESET EMPTY LIGHT TIPS", shots.filter { $0.lightingTip.isEmpty }.count, "EMPTY LENS", shots.filter { $0.zoomOrLens.isEmpty }.count)
    }
}
