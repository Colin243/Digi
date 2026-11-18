import XCTest
@testable import DirectorKit

final class GuidanceWordingTests: XCTestCase {
    private let variants: [CueVariant] = [
        .holdUpright, .turnSideways, .straighten(rotateLeft: true), .straighten(rotateLeft: false),
        .tilt(up: true, degrees: 14), .tilt(up: false, degrees: 6), .findSubject(chosen: true), .findSubject(chosen: false),
        .closer(canZoom: true), .closer(canZoom: false), .back(canZoom: true), .back(canZoom: false),
        .pan(right: true, goal: "center"), .pan(right: false, goal: "left"), .findFace,
        .headTurn(.subjectLeft), .headTurn(.subjectRight), .headTurn(.awayFromCamera), .headTurn(.towardCamera),
        .chin(up: true), .chin(up: false)]
    private func cue(_ v: CueVariant) -> GuidanceCue { GuidanceCue(kind: .tilt, text: "engine text", symbol: "arrow.up", variant: v) }

    func testEveryVariantHasWordsInEveryStyleAndLanguage() {
        for v in variants { for s in GuidanceStyle.allCases { for l in [GuidanceLanguage.en, .zh] {
            XCTAssertFalse(GuidanceWording.text(for: cue(v), style: s, language: l).isEmpty, "\(v) \(s) \(l)")
        } } }
    }

    func testFullEnglishKeepsTheEngineText() {
        for v in variants { XCTAssertEqual(GuidanceWording.text(for: cue(v), style: .full, language: .en), "engine text") }
    }

    func testCuesWithoutAVariantKeepTheirText() {
        let c = GuidanceCue(kind: .tilt, text: "engine text", symbol: "x")
        XCTAssertEqual(GuidanceWording.text(for: c, style: .soft, language: .zh), "engine text")
    }

    func testSoftAndMinimalHaveNoDegreesOrAxisNames() {
        for v in variants { for s in [GuidanceStyle.soft, .minimal] { for l in [GuidanceLanguage.en, .zh] {
            let t = GuidanceWording.text(for: cue(v), style: s, language: l).lowercased()
            XCTAssertFalse(t.contains("°") || t.rangeOfCharacter(from: .decimalDigits) != nil, t)
            for w in ["yaw", "pitch", "roll"] { XCTAssertFalse(t.contains(w), t) }
        } } }
    }

    func testMinimalIsQuietAndShort() {
        for m in GuidanceMessage.allCases { XCTAssertEqual(GuidanceWording.text(m, style: .minimal, language: .en), "") }
        for v in variants { XCTAssertLessThanOrEqual(GuidanceWording.text(for: cue(v), style: .minimal, language: .en).count, 15) }
    }

    func testSoftAndFullHaveEveryMessage() {
        for m in GuidanceMessage.allCases { for s in [GuidanceStyle.full, .soft] { for l in [GuidanceLanguage.en, .zh] {
            XCTAssertFalse(GuidanceWording.text(m, style: s, language: l).isEmpty)
        } } }
    }

    func testTheTrackerAttachesVariantsToItsCues() {
        var t = GuidanceTracker(targets: ShotTargets(pitchDegrees: 10, pitchTolerance: 3))
        for i in 0..<10 { t.addPose(PoseSample(pitchDegrees: -3, rollDegrees: 0, portrait: true)); _ = i }
        let g = t.guidance(at: 1.0)
        XCTAssertEqual(g.top?.variant, .tilt(up: true, degrees: 14))
    }
}
