import XCTest
@testable import DirectorKit

final class ZoomPlanTests: XCTestCase {
    func testTwoXOnlyWithRoomAndSomethingWorthEnlarging() {
        XCTAssertEqual(ZoomPlan.make(oneXDistanceMeters: 2, room: .yes, background: .worthEnlarging).zoom, 2)
        XCTAssertEqual(ZoomPlan.make(oneXDistanceMeters: 2, room: .yes, background: .neutral).zoom, 1)
        XCTAssertEqual(ZoomPlan.make(oneXDistanceMeters: 2, room: .no, background: .worthEnlarging).zoom, 1)
        XCTAssertEqual(ZoomPlan.make(oneXDistanceMeters: 2, room: .unknown, background: .worthEnlarging).zoom, 1)
    }

    func testMaybeRoomGivesAHalfStep() {
        XCTAssertEqual(ZoomPlan.make(oneXDistanceMeters: 2, room: .maybe, background: .worthEnlarging).zoom, 1.5)
    }

    func testDistanceAlwaysScalesWithZoom() {
        for (room, bg) in [(ZoomPlan.Room.yes, ZoomPlan.Background.worthEnlarging), (.maybe, .worthEnlarging), (.no, .neutral)] {
            let p = ZoomPlan.make(oneXDistanceMeters: 2.4, room: room, background: bg)
            XCTAssertEqual(p.distanceMeters ?? 0, 2.4 * p.zoom, accuracy: 0.06)
        }
        XCTAssertNil(ZoomPlan.make(oneXDistanceMeters: nil, room: .yes, background: .worthEnlarging).distanceMeters)
    }

    func testParsesRealDistanceText() {
        XCTAssertEqual(ZoomPlan.parseMeters("about 2 m, half body"), 2)
        XCTAssertEqual(ZoomPlan.parseMeters("About 1.2 m away, full body"), 1.2)
        XCTAssertEqual(ZoomPlan.parseMeters("2-3 m from the subject"), 2)
        XCTAssertNil(ZoomPlan.parseMeters("close, head and shoulders"))
    }

    func testRewritesTheDistanceTextForTheZoom() {
        XCTAssertEqual(ZoomPlan.rewriteDistance("about 2 m, half body", zoom: 2), "about 4 m, half body")
        XCTAssertEqual(ZoomPlan.rewriteDistance("about 1.2 m, close-up", zoom: 2), "about 2.4 m, close-up")
        XCTAssertEqual(ZoomPlan.rewriteDistance("about 2 m, half body", zoom: 1), "about 2 m, half body")
        XCTAssertEqual(ZoomPlan.rewriteDistance("close up", zoom: 2), "close up")
    }

    private func shot(position: String = "", distance: String = "about 2 m, half body", lens: String = "", scene: String = "", steps: [String] = []) -> Shot {
        Shot(title: "t", cameraPosition: position, cameraHeight: "", cameraAngle: "", subjectPosition: "", sceneReading: scene,
             distanceAndFraming: distance, zoomOrLens: lens, steps: steps)
    }

    func testInfersRoomAndBackground() {
        let a = ZoomPlan.infer(from: shot(position: "In the open plaza, step back", scene: "The clock tower rises behind the fountain"))
        XCTAssertEqual(a.room, .yes); XCTAssertEqual(a.background, .worthEnlarging)
        let b = ZoomPlan.infer(from: shot(position: "In a narrow hallway", scene: "Tower in view"))
        XCTAssertEqual(b.room, .no)
        XCTAssertEqual(ZoomPlan.infer(from: shot(position: "By the table")).room, .unknown)
    }

    func testResolvedReplacesTheModelsZoomAndScalesTheDistance() {
        let r = ZoomPlan.resolved(shot(position: "Open plaza, step back", distance: "about 2 m, half body", lens: "1x main lens", scene: "A tower behind"))
        XCTAssertTrue(r.zoomOrLens.hasPrefix("2x")); XCTAssertEqual(r.distanceAndFraming, "about 4 m, half body")
        XCTAssertEqual(CameraPreset.make(for: r).zoom, 2)
        // The model asked for 2x but the place gives no reason: back to 1x, distance untouched.
        let n = ZoomPlan.resolved(shot(position: "By the table", distance: "about 2 m, half body", lens: "2x telephoto"))
        XCTAssertEqual(CameraPreset.make(for: n).zoom, 1); XCTAssertEqual(n.distanceAndFraming, "about 2 m, half body")
    }

    func testTheModelsOwnAnswersWinOverTheTextRules() {
        var s = shot(position: "By the table", distance: "about 2 m, half body")
        s.roomToStepBack = "yes"; s.backgroundWorthEnlarging = "yes"
        XCTAssertEqual(ZoomPlan.resolved(s).distanceAndFraming, "about 4 m, half body")
        s.roomToStepBack = "no"
        XCTAssertTrue(ZoomPlan.resolved(s).zoomOrLens.hasPrefix("1x"))
    }
}

/// Shot formats v5-v7 write the distance for the model's own zoom ("About 2.4 m at 2x"). The rule must undo that
/// before it applies its own zoom; these are real fused-q5 v7 lines that came out doubled or contradictory before.
final class ZoomPlanAtZoomTests: XCTestCase {
    private func shot(_ distance: String, room: String = "", background: String = "") -> Shot {
        var s = Shot(title: "t", cameraPosition: "p", cameraHeight: "h", cameraAngle: "a", subjectPosition: "s")
        s.distanceAndFraming = distance; s.roomToStepBack = room; s.backgroundWorthEnlarging = background
        return s
    }

    func testReadsTheOneXDistanceBackOut() {
        XCTAssertEqual(ZoomPlan.oneXMeters("About 2.4 m at 2x; waist up with the trees") ?? 0, 1.2, accuracy: 0.001)
        XCTAssertEqual(ZoomPlan.oneXMeters("About 3 m at 1.5x; half body") ?? 0, 2, accuracy: 0.001)
        XCTAssertEqual(ZoomPlan.oneXMeters("About 2 m at 1x; full body") ?? 0, 2, accuracy: 0.001)
        XCTAssertEqual(ZoomPlan.oneXMeters("About 2 m away, head to toe.") ?? 0, 2, accuracy: 0.001)  // v3: already 1x
        XCTAssertNil(ZoomPlan.oneXMeters("close, head and shoulders"))
    }

    func testModelTwoXRuleTwoXIsNotScaledTwice() {
        // Was "About 4.8 m at 2x": the 2x distance doubled again.
        let r = ZoomPlan.resolved(shot("About 2.4 m at 2x; waist up with the trees", room: "yes", background: "yes"))
        XCTAssertEqual(r.distanceAndFraming, "About 2.4 m at 2x; waist up with the trees")
        XCTAssertTrue(r.zoomOrLens.hasPrefix("2x"))
    }

    func testModelTwoXRuleOneXGoesBackToTheOneXDistance() {
        // Was "About 2.4 m at 2x" under a "1x main lens" line.
        let r = ZoomPlan.resolved(shot("About 2.4 m at 2x; head and shoulders with the bridge", room: "no", background: "no"))
        XCTAssertEqual(r.zoomOrLens, "1x main lens")
        XCTAssertEqual(r.distanceAndFraming, "About 1.2 m at 1x; head and shoulders with the bridge")
    }

    func testModelOneXRuleTwoXSaysTwoX() {
        // Was "About 4 m at 1x" under a 2x lens line.
        let r = ZoomPlan.resolved(shot("About 2 m at 1x; full body with the mountains", room: "yes", background: "yes"))
        XCTAssertEqual(r.distanceAndFraming, "About 4 m at 2x; full body with the mountains")
        XCTAssertTrue(r.zoomOrLens.hasPrefix("2x"))
    }

    func testHalfStepAndUnchangedCases() {
        XCTAssertEqual(ZoomPlan.resolved(shot("About 2 m at 1x; full body", room: "maybe", background: "yes")).distanceAndFraming,
                       "About 2 m at 1x; full body")  // "maybe" in the trained field is not yes/no: text rules, no zoom
        XCTAssertEqual(ZoomPlan.rewriteDistance("About 2 m at 1x; full body", zoom: 1.5), "About 3 m at 1.5x; full body")
        XCTAssertEqual(ZoomPlan.rewriteDistance("About 1.2 m at 1x; waist up", zoom: 1), "About 1.2 m at 1x; waist up")
        XCTAssertEqual(ZoomPlan.rewriteDistance("about 2 m, half body", zoom: 2), "about 4 m, half body")  // v3 text: as before
        XCTAssertEqual(ZoomPlan.rewriteDistance("about 2 m, half body", zoom: 1), "about 2 m, half body")
    }

    func testIgnoresImplausibleZoomText() {
        XCTAssertEqual(ZoomPlan.oneXMeters("About 3 m at 10x") ?? 0, 3, accuracy: 0.001)
    }
}
