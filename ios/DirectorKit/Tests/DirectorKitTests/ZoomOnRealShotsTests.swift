import XCTest
@testable import DirectorKit

/// Before/after of the zoom rule on real model output. Skipped unless ZOOM_REAL points at the exported JSON
/// ({eval: [{shot, posing_space, setting}]}). Before = the zoom the model's own lens text gives; after = the rule.
final class ZoomOnRealShotsTests: XCTestCase {
    struct Row: Decodable { let shot: Shot; let posing_space: String; let setting: String }

    func testRuleAgainstModelZoom() throws {
        guard let path = ProcessInfo.processInfo.environment["ZOOM_REAL"] else { throw XCTSkip("set ZOOM_REAL") }
        let all = try JSONDecoder().decode([String: [Row]].self, from: Data(contentsOf: URL(fileURLWithPath: path)))
        for (name, rows) in all.sorted(by: { $0.key < $1.key }) {
            var beforeZoomed = 0, afterZoomed = 0, beforeLimited = 0, afterLimited = 0, limited = 0
            var roomRight = 0, roomKnown = 0, distMismatch = 0
            for r in rows {
                let b = CameraPreset.make(for: r.shot).zoom ?? 1
                let res = ZoomPlan.resolved(r.shot)
                let a = CameraPreset.make(for: res).zoom ?? 1
                let isLimited = r.posing_space == "limited"
                if isLimited { limited += 1 }
                if b > 1.01 { beforeZoomed += 1; if isLimited { beforeLimited += 1 } }
                if a > 1.01 { afterZoomed += 1; if isLimited { afterLimited += 1 } }
                // Model said zoom but its distance text is the same as a 1x look (nothing to match the zoom).
                if b > 1.01, ZoomPlan.parseMeters(r.shot.distanceAndFraming) != nil, r.shot.distanceAndFraming == res.distanceAndFraming { distMismatch += 1 }
                let inferred = ZoomPlan.infer(from: r.shot).room
                if r.posing_space == "open" || r.posing_space == "limited" {
                    if inferred != .unknown { roomKnown += 1; if (inferred == .yes) == (r.posing_space == "open") { roomRight += 1 } }
                }
            }
            print("ZOOMREAL \(name) shots=\(rows.count) before: zoomed=\(beforeZoomed) inLimitedSpace=\(beforeLimited) distanceNotScaled=\(distMismatch) | after: zoomed=\(afterZoomed) inLimitedSpace=\(afterLimited) | limitedShots=\(limited) roomGuessed=\(roomKnown) roomRight=\(roomRight)")
        }
    }
}
