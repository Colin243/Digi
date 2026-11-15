import XCTest
@testable import DirectorKit

final class ShotTargetsTests: XCTestCase {
    // Phrases below are real model output from photography-ai benchmark runs.

    func testPitchPhrases() {
        let cases: [(String, Double?)] = [
            ("Tilt up about 10°", 10), ("Tilt down about 10°.", -10), ("tilt the phone down about 10°, aimed at the stomach", -10),
            ("slightly upward", 6), ("slightly tilted down", -6), ("slightly upward tilt", 6), ("tilt up slightly to emphasize height", 6),
            ("level, slight tilt upward", 6), ("Level.", 0), ("level", 0), ("tilt up 15 degrees", 15),
            ("pointing up at the sky", 12), ("steeply upward from the ground", 25), ("overhead, top-down", -60),
            ("", nil), ("natural", nil),
        ]
        for (text, want) in cases {
            XCTAssertEqual(ShotTargets.pitch(from: text)?.0, want, text)
        }
        XCTAssertEqual(ShotTargets.pitch(from: "Level")?.1, 3)
    }

    func testFramingPhrases() {
        let cases: [(String, Framing?)] = [
            ("About 2 m; full body, head to toe, feet at bottom edge.", .fullBody),
            ("About 10 m away, full-body, centered, with the path and the trees blurred behind her.", .fullBody),
            ("about 1.5 m (5 ft) away, the whole seated body laid along the frame's diagonal", .fullBody),
            ("about 1.2 m (4 ft) away, waist up, the face in the centre column of the frame", .waistUp),
            ("knees up, about 2 m", .threeQuarter),
            ("close-up, about 0.6 m", .closeUp), ("head and shoulders", .closeUp),
            ("about 3 meters away, with the vertical pattern of the building being the main focus", nil),
        ]
        for (text, want) in cases { XCTAssertEqual(ShotTargets.framing(from: text), want, text) }
    }

    func testHorizontalPhrases() {
        let cases: [(String, HorizontalTarget?)] = [
            ("on the right side of the frame, near the illuminated street lamp", .right),
            ("left third, facing the window", .left),
            ("Standing in the middle of the path, head bowed", .center),
            ("about 1.2 m away, waist up, the face in the centre column of the frame", .center),
            ("facing left, looking at the lake", nil),
            ("walking toward the right, head down", nil),
            ("About 2 m away, full body, with the blossoms filling the right two-thirds.", .left),
            ("at the edge of the frame, with the bridge's towers filling the background", nil),
        ]
        for (text, want) in cases { XCTAssertEqual(ShotTargets.horizontal(from: text), want, text) }
    }

    func testShotTargetsFromShot() {
        let shot = Shot(title: "t", cameraPosition: "beside the dock", cameraHeight: "Chest height", cameraAngle: "Tilt up about 10°",
                        subjectPosition: "on the left side of the frame, hand at side",
                        distanceAndFraming: "About 2 m; full body, head to toe", orientation: "landscape")
        let t = ShotTargets(shot: shot)
        XCTAssertEqual(t.pitchDegrees, 10)
        XCTAssertEqual(t.framing, .fullBody)
        XCTAssertEqual(t.horizontal, .left)
        XCTAssertEqual(t.portrait, false)
        XCTAssertTrue(t.needsSubject)
    }
}

final class PoseSampleTests: XCTestCase {
    func testUprightPortraitIsLevel() {
        let p = PoseSample(gravityX: 0, y: -1, z: 0)
        XCTAssertEqual(p.pitchDegrees, 0, accuracy: 0.01)
        XCTAssertEqual(p.rollDegrees, 0, accuracy: 0.01)
        XCTAssertEqual(p.portrait, true)
    }

    func testFlatFaceUpPointsCameraDown() {
        let p = PoseSample(gravityX: 0, y: 0, z: -1)
        XCTAssertEqual(p.pitchDegrees, -90, accuracy: 0.01)
        XCTAssertNil(p.portrait)
    }

    func testTiltingBackPointsCameraUp() {
        // Screen leaning back 20°: gravity gains a +z component (toward the screen's back).
        let a = 20.0 * .pi / 180
        let p = PoseSample(gravityX: 0, y: -cos(a), z: sin(a))
        XCTAssertEqual(p.pitchDegrees, 20, accuracy: 0.01)
    }

    func testClockwiseRollAndLandscape() {
        let a = 5.0 * .pi / 180
        XCTAssertEqual(PoseSample(gravityX: sin(a), y: -cos(a), z: 0).rollDegrees, 5, accuracy: 0.01)
        let side = PoseSample(gravityX: -1, y: 0, z: 0)
        XCTAssertEqual(side.portrait, false)
        XCTAssertEqual(side.rollDegrees, 0, accuracy: 0.01)
    }
}

final class GuidanceTrackerTests: XCTestCase {
    func pose(_ pitch: Double, roll: Double = 0, portrait: Bool? = true) -> PoseSample {
        PoseSample(pitchDegrees: pitch, rollDegrees: roll, portrait: portrait)
    }

    func testTiltCueAndHysteresis() {
        var g = GuidanceTracker(targets: ShotTargets(pitchDegrees: 10, pitchTolerance: 4))
        for _ in 0..<30 { g.addPose(pose(0)) }
        XCTAssertEqual(g.guidance(at: 0).top?.text, "Tilt up 10°")
        // Inside the entry tolerance but outside the exit band: the cue stays on.
        for _ in 0..<30 { g.addPose(pose(7)) }
        XCTAssertEqual(g.guidance(at: 1).top?.kind, .tilt)
        // Within half the tolerance: it clears and the shot is satisfied.
        for _ in 0..<30 { g.addPose(pose(9)) }
        let done = g.guidance(at: 2)
        XCTAssertTrue(done.cues.isEmpty)
        XCTAssertTrue(done.isSatisfied)
        // Back out to 7° does not re-trigger (needs > 4° off).
        for _ in 0..<30 { g.addPose(pose(7)) }
        XCTAssertTrue(g.guidance(at: 3).cues.isEmpty)
    }

    func testTooHighSaysTiltDown() {
        var g = GuidanceTracker(targets: ShotTargets(pitchDegrees: 0, pitchTolerance: 3))
        for _ in 0..<30 { g.addPose(pose(12)) }
        XCTAssertEqual(g.guidance(at: 0).top?.text, "Tilt down 12°")
    }

    func testOrientationComesFirst() {
        var g = GuidanceTracker(targets: ShotTargets(pitchDegrees: 10, portrait: false))
        for _ in 0..<30 { g.addPose(pose(0, portrait: true)) }
        let out = g.guidance(at: 0)
        XCTAssertEqual(out.cues.map(\.kind), [.orientation, .tilt])
        XCTAssertEqual(out.top?.text, "Turn the phone sideways")
    }

    func testLevelIgnoredWhenFlat() {
        var g = GuidanceTracker(targets: ShotTargets(pitchDegrees: -60, pitchTolerance: 10))
        for _ in 0..<30 { g.addPose(pose(-62, roll: 20)) }
        XCTAssertTrue(g.guidance(at: 0).cues.isEmpty)
        var h = GuidanceTracker(targets: ShotTargets(pitchDegrees: 0))
        for _ in 0..<30 { h.addPose(pose(0, roll: 6)) }
        XCTAssertEqual(h.guidance(at: 0).top?.text, "Straighten: rotate the phone left")
    }

    func testSubjectCues() {
        var g = GuidanceTracker(targets: ShotTargets(framing: .waistUp, horizontal: .left))
        for _ in 0..<5 { g.addPose(pose(0)) }
        XCTAssertEqual(g.guidance(at: 0).top?.kind, .findSubject)
        XCTAssertFalse(g.guidance(at: 0).isSatisfied)

        // Small face, centred: too far and too far right of the left third.
        let face = NormalizedBox(x: 0.47, y: 0.2, width: 0.06, height: 0.06)
        for i in 0..<10 { g.addSubject(person: nil, face: face, at: 1 + Double(i) * 0.2) }
        let out = g.guidance(at: 3)
        XCTAssertEqual(out.cues.map(\.kind), [.distance, .horizontal])
        XCTAssertEqual(out.cues[0].text, "Step closer")
        XCTAssertEqual(out.cues[1].text, "Pan right so the subject sits on the left third")

        // Right size, on the left third.
        let good = NormalizedBox(x: 0.25, y: 0.2, width: 0.16, height: 0.18)
        for i in 0..<20 { g.addSubject(person: nil, face: good, at: 3.2 + Double(i) * 0.2) }
        XCTAssertTrue(g.guidance(at: 7.2).isSatisfied)

        // Subject lost for longer than the timeout.
        XCTAssertEqual(g.guidance(at: 10).top?.kind, .findSubject)
    }

    func testFullBodyUsesPersonWithoutFace() {
        var g = GuidanceTracker(targets: ShotTargets(framing: .fullBody))
        g.addPose(pose(0))
        let big = NormalizedBox(x: 0.3, y: 0.0, width: 0.4, height: 1.0)
        for i in 0..<10 { g.addSubject(person: big, face: nil, at: Double(i) * 0.2) }
        XCTAssertEqual(g.guidance(at: 2).top?.text, "Step back")
    }

    func testTopCueIsHeldBriefly() {
        var g = GuidanceTracker(targets: ShotTargets(pitchDegrees: 0, pitchTolerance: 3, portrait: true))
        for _ in 0..<30 { g.addPose(pose(10, portrait: true)) }
        XCTAssertEqual(g.guidance(at: 0).top?.kind, .tilt)
        // A higher-priority cue appears; the tilt cue stays on top for the hold period, then yields.
        g.addPose(pose(10, portrait: false))
        XCTAssertEqual(g.guidance(at: 0.3).top?.kind, .tilt)
        XCTAssertEqual(g.guidance(at: 1.0).top?.kind, .orientation)
    }

    func testNothingMeasurable() {
        var g = GuidanceTracker(targets: ShotTargets())
        g.addPose(pose(0))
        let out = g.guidance(at: 0)
        XCTAssertFalse(out.hasTargets)
        XCTAssertFalse(out.isSatisfied)
    }
}

final class SubjectSelectorTests: XCTestCase {
    let left = NormalizedBox(x: 0.05, y: 0.2, width: 0.25, height: 0.7)
    let right = NormalizedBox(x: 0.6, y: 0.1, width: 0.35, height: 0.85)  // bigger
    let leftFace = NormalizedBox(x: 0.12, y: 0.22, width: 0.08, height: 0.07)
    let rightFace = NormalizedBox(x: 0.72, y: 0.12, width: 0.1, height: 0.09)

    func testAutoPicksLargestPersonAndItsFace() {
        var s = SubjectSelector()
        let out = s.choose(people: [left, right], faces: [leftFace, rightFace], now: 0)
        XCTAssertEqual(out.person, right)
        XCTAssertEqual(out.face, rightFace)
    }

    func testLockedSubjectIgnoresOthersAndFollowsMovement() {
        var s = SubjectSelector()
        XCTAssertTrue(s.lock(atX: 0.15, y: 0.5, people: [left, right], faces: [leftFace, rightFace], now: 0))
        XCTAssertEqual(s.choose(people: [left, right], faces: [leftFace, rightFace], now: 0.2).person, left)
        // The chosen person walks right a little; the bigger person is still ignored.
        let moved = NormalizedBox(x: 0.12, y: 0.2, width: 0.25, height: 0.7)
        XCTAssertEqual(s.choose(people: [moved, right], faces: [], now: 0.4).person, moved)
        // They leave the frame: no subject, even though someone else is visible.
        let gone = s.choose(people: [right], faces: [rightFace], now: 0.6)
        XCTAssertNil(gone.person); XCTAssertNil(gone.face)
        XCTAssertTrue(s.isLocked); XCTAssertFalse(s.isLost)
    }

    func testLostSubjectNeverSwitchesToSomeoneElse() {
        var s = SubjectSelector()
        XCTAssertTrue(s.lock(atX: 0.15, y: 0.5, people: [left, right], faces: [leftFace, rightFace], now: 0))
        // Long after the chosen person left, the other person is still not picked.
        for t in stride(from: 0.2, through: 10, by: 0.2) {
            let out = s.choose(people: [right], faces: [rightFace], now: t)
            XCTAssertNil(out.person); XCTAssertNil(out.face)
        }
        XCTAssertTrue(s.isLocked); XCTAssertTrue(s.isLost)
        // The chosen person comes back where they were: picked up again, no longer lost.
        XCTAssertEqual(s.choose(people: [left, right], faces: [leftFace, rightFace], now: 10.2).person, left)
        XCTAssertFalse(s.isLost)
        // Clearing goes back to automatic.
        s.clear()
        XCTAssertFalse(s.isLocked); XCTAssertFalse(s.isLost)
        XCTAssertEqual(s.choose(people: [left, right], faces: [], now: 10.4).person, right)
    }

    func testNotLostWithinTimeout() {
        var s = SubjectSelector()
        XCTAssertTrue(s.lock(atX: 0.15, y: 0.5, people: [left], faces: [], now: 0))
        _ = s.choose(people: [], faces: [], now: 2.9)
        XCTAssertFalse(s.isLost)
        _ = s.choose(people: [], faces: [], now: 3.1)
        XCTAssertTrue(s.isLost)
    }

    func testAutoKeepsFollowingTheSamePersonWhenSizesSwap() {
        var s = SubjectSelector()
        let a = NormalizedBox(x: 0.05, y: 0.2, width: 0.3, height: 0.7)
        let b = NormalizedBox(x: 0.6, y: 0.2, width: 0.28, height: 0.68)
        XCTAssertEqual(s.choose(people: [a, b], faces: [], now: 0).person, a)
        // b now reads slightly larger (detector jitter): auto stays on a.
        let bBigger = NormalizedBox(x: 0.6, y: 0.2, width: 0.31, height: 0.71)
        XCTAssertEqual(s.choose(people: [a, bBigger], faces: [], now: 0.2).person, a)
        // a leaves: auto moves to whoever is there.
        XCTAssertEqual(s.choose(people: [bBigger], faces: [], now: 0.4).person, bBigger)
    }

    func testTapAwayFromEveryoneDoesNotLock() {
        var s = SubjectSelector()
        XCTAssertFalse(s.lock(atX: 0.45, y: 0.05, people: [left, right], faces: [], now: 0))
        XCTAssertFalse(s.isLocked)
    }

    func testFaceOnlyCloseUp() {
        var s = SubjectSelector()
        XCTAssertTrue(s.lock(atX: 0.16, y: 0.25, people: [], faces: [leftFace, rightFace], now: 0))
        let out = s.choose(people: [], faces: [leftFace, rightFace], now: 0.2)
        XCTAssertNil(out.person)
        XCTAssertEqual(out.face, leftFace)
    }
}

final class HeadTargetsTests: XCTestCase {
    // Real head_direction / gaze phrasing from benchmark runs.
    func testTurnAndChinPhrases() {
        func head(_ h: String, gaze: String = "") -> HeadTargets { HeadTargets(headDirection: h, gaze: gaze) }

        var t = head("looking slightly down and to the right")
        XCTAssertEqual(t.yaw, 20); XCTAssertFalse(t.yawEitherSide); XCTAssertEqual(t.pitch, -8)

        t = head("looking straight into the lens"); XCTAssertEqual(t.yaw, 0); XCTAssertNil(t.pitch)
        t = head("looking slightly up and to the right"); XCTAssertEqual(t.yaw, 20); XCTAssertEqual(t.pitch, 8)
        t = head("level", gaze: "the lens"); XCTAssertEqual(t.yaw, 0); XCTAssertEqual(t.pitch, 0)
        t = head("looking down at the ground"); XCTAssertNil(t.yaw); XCTAssertEqual(t.pitch, -15)
        t = head("to the right"); XCTAssertEqual(t.yaw, 30)
        t = head("toward the lens, with the chin slightly lowered"); XCTAssertEqual(t.yaw, 0); XCTAssertEqual(t.pitch, -8)
        t = head("looking slightly to the left, with the chin level"); XCTAssertEqual(t.yaw, -20); XCTAssertEqual(t.pitch, 0)
        t = head("turned over her left shoulder"); XCTAssertEqual(t.yaw, 45)  // her left = frame right
        t = head("three-quarter turn away from the camera"); XCTAssertEqual(t.yaw, 40); XCTAssertTrue(t.yawEitherSide)
        t = head("toward the street lamp"); XCTAssertTrue(t.isEmpty)
        t = head("", gaze: "away from the lens, looking at the path ahead"); XCTAssertNil(t.yaw)
        t = head("看向建筑的前方"); XCTAssertTrue(t.isEmpty)
    }
}

final class HeadCueTests: XCTestCase {
    let face = NormalizedBox(x: 0.4, y: 0.2, width: 0.15, height: 0.18)

    func tracker(_ head: HeadTargets) -> GuidanceTracker {
        var g = GuidanceTracker(targets: ShotTargets(head: head))
        g.subjectCuesEnabled = true
        g.addPose(PoseSample(pitchDegrees: 0, rollDegrees: 0, portrait: true))
        return g
    }

    func feed(_ g: inout GuidanceTracker, yaw: Double, pitch: Double?, from t0: Double) {
        for i in 0..<15 { g.addSubject(person: nil, face: face, facePose: FacePose(yawDegrees: yaw, pitchDegrees: pitch), at: t0 + Double(i) * 0.2) }
    }

    func testOffByDefault() {
        var g = GuidanceTracker(targets: ShotTargets(head: HeadTargets(yaw: 20)))
        g.addSubject(person: nil, face: face, facePose: FacePose(yawDegrees: 0, pitchDegrees: 0), at: 0)
        XCTAssertTrue(g.guidance(at: 0).subjectCues.isEmpty)
    }

    func testTurnCueUsesTheSubjectsOwnSide() {
        var g = tracker(HeadTargets(yaw: 20, yawTolerance: 10))  // toward the frame's right
        feed(&g, yaw: 0, pitch: 0, from: 0)
        XCTAssertEqual(g.guidance(at: 3).subjectCues.first?.text, "Say: “Turn your head a little to your left”")
        feed(&g, yaw: 45, pitch: 0, from: 3)
        XCTAssertEqual(g.guidance(at: 6).subjectCues.first?.text, "Say: “Turn your head a little to your right”")
        feed(&g, yaw: 21, pitch: 0, from: 6)
        let ok = g.guidance(at: 9)
        XCTAssertTrue(ok.subjectCues.isEmpty)
        XCTAssertTrue(ok.subjectSatisfied)
    }

    func testEitherSideAndChin() {
        var g = tracker(HeadTargets(yaw: 40, yawEitherSide: true, yawTolerance: 12, pitch: -15, pitchTolerance: 8))
        feed(&g, yaw: -5, pitch: 5, from: 0)
        XCTAssertEqual(g.guidance(at: 3).subjectCues.map(\.text),
                       ["Say: “Turn your head a little away from me”", "Say: “Lower your chin a little”"])
        feed(&g, yaw: -38, pitch: -14, from: 3)
        XCTAssertTrue(g.guidance(at: 6).subjectSatisfied)
    }

    func testNoFaceAndCameraSatisfactionWaitsForHead() {
        var g = GuidanceTracker(targets: ShotTargets(pitchDegrees: 0, head: HeadTargets(yaw: 0)))
        g.subjectCuesEnabled = true
        for _ in 0..<10 { g.addPose(PoseSample(pitchDegrees: 0, rollDegrees: 0, portrait: true)) }
        let none = g.guidance(at: 0)
        XCTAssertEqual(none.subjectCues.first?.kind, .findFace)
        XCTAssertFalse(none.isSatisfied)
        feed(&g, yaw: 2, pitch: nil, from: 0)
        XCTAssertTrue(g.guidance(at: 3).isSatisfied)
    }
}

final class LandmarkYawTests: XCTestCase {
    func testNosePositionGivesTurn() {
        let contour = stride(from: 0.1, through: 0.9, by: 0.1).map { $0 }
        XCTAssertEqual(FacePose.yawFromLandmarks(contourX: contour, noseX: [0.48, 0.5, 0.52])!, 0, accuracy: 0.01)
        XCTAssertEqual(FacePose.yawFromLandmarks(contourX: contour, noseX: [0.7])!, 30, accuracy: 0.01)   // toward frame right
        XCTAssertEqual(FacePose.yawFromLandmarks(contourX: contour, noseX: [0.1])!, -90, accuracy: 0.01)  // profile, frame left
        XCTAssertNil(FacePose.yawFromLandmarks(contourX: [0.5, 0.52], noseX: [0.5]))
        XCTAssertNil(FacePose.yawFromLandmarks(contourX: contour, noseX: []))
    }
}

final class FullBodyDistanceTests: XCTestCase {
    /// From the phone test: face 0.04 tall (inside the face range) but the body only 0.45 of the frame.
    func testFullBodyTrustsThePersonOverASmallFace() {
        var g = GuidanceTracker(targets: ShotTargets(framing: .fullBody))
        g.addPose(PoseSample(pitchDegrees: 0, rollDegrees: 0, portrait: true))
        let person = NormalizedBox(x: 0.4, y: 0.2, width: 0.2, height: 0.45)
        let face = NormalizedBox(x: 0.47, y: 0.21, width: 0.04, height: 0.04)
        for i in 0..<10 { g.addSubject(person: person, face: face, at: Double(i) * 0.2) }
        XCTAssertEqual(g.guidance(at: 2).top?.text, "Step closer")
    }
}
