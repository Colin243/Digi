import XCTest
@testable import DirectorKit

final class GuidanceDisplayTests: XCTestCase {
    private func rank(_ d: GuidanceDisplay) -> [Int] {
        [d.cueRow == .off ? 0 : d.cueRow == .topOnly ? 1 : 2,
         d.levelIndicator == .off ? 0 : d.levelIndicator == .subtle ? 1 : 2,
         d.subjectBrackets ? 1 : 0, d.headCues ? 1 : 0,
         d.detectionBoxes ? 1 : 0, d.debugReadout ? 1 : 0]
    }

    func testHigherLevelNeverHidesWhatALowerOneShowed() {
        for style in GuidanceStyle.allCases {
            var prev: [Int]?
            for level in GuidanceLevel.allCases {
                let r = rank(.make(style: style, level: level, developerReadout: true))
                if let p = prev { XCTAssertTrue(zip(p, r).allSatisfy { $0 <= $1 }, "\(style) \(level)") }
                prev = r
            }
        }
    }

    func testEssentialsIsOneCueAndNothingElse() {
        let d = GuidanceDisplay.make(style: .soft, level: .essentials)
        XCTAssertEqual(d.cueRow, .topOnly)
        XCTAssertEqual(d.levelIndicator, .off)
        XCTAssertFalse(d.subjectBrackets)
        XCTAssertFalse(d.headCues)
    }

    func testRawReadoutsNeedTheDeveloperToggle() {
        XCTAssertFalse(GuidanceDisplay.make(style: .full, level: .everything).debugReadout)
        XCTAssertTrue(GuidanceDisplay.make(style: .full, level: .everything, developerReadout: true).debugReadout)
        XCTAssertFalse(GuidanceDisplay.make(style: .full, level: .detailed, developerReadout: true).debugReadout)
    }

    func testSoftAndMinimalCapAtDetailed() {
        for style in [GuidanceStyle.soft, .minimal] {
            XCTAssertEqual(GuidanceDisplay.make(style: style, level: .everything, developerReadout: true),
                           GuidanceDisplay.make(style: style, level: .detailed, developerReadout: true))
        }
    }

    func testZoomIsSimpleOutsideFullInfo() {
        XCTAssertEqual(GuidanceDisplay.make(style: .full, level: .helpful).zoomDetail, .ruler)
        XCTAssertEqual(GuidanceDisplay.make(style: .soft, level: .helpful).zoomDetail, .simple)
        XCTAssertEqual(GuidanceDisplay.make(style: .minimal, level: .helpful).zoomDetail, .simple)
    }

    func testPhotoThumbnailIsInEveryPreset() {
        for s in GuidanceStyle.allCases { for l in GuidanceLevel.allCases {
            XCTAssertTrue(GuidanceDisplay.make(style: s, level: l).photoThumbnail, "\(s) \(l)")
        } }
    }

    func testLevelIsRememberedPerStyle() {
        var p = GuidancePrefs(style: .soft)
        p.level = .essentials
        p.select(.minimal)
        XCTAssertEqual(p.level, .helpful)
        p.level = .detailed
        p.select(.soft)
        XCTAssertEqual(p.level, .essentials)
    }

    func testLevelClampsToTheStylesCeiling() {
        var p = GuidancePrefs(style: .minimal)
        p.level = .everything
        XCTAssertEqual(p.level, .detailed)
    }

    func testCustomTurnsOnAndBackOff() {
        var p = GuidancePrefs(style: .soft)
        XCTAssertFalse(p.isCustom)
        p.override { $0.levelIndicator = .full }
        XCTAssertTrue(p.isCustom)
        XCTAssertEqual(p.display.levelIndicator, .full)
        p.override { $0.levelIndicator = .subtle }
        XCTAssertFalse(p.isCustom)
    }

    func testChangingStyleDropsOverrides() {
        var p = GuidancePrefs(style: .full)
        p.override { $0.haptics = false }
        p.select(.soft)
        XCTAssertFalse(p.isCustom)
        XCTAssertTrue(p.display.haptics)
    }

    func testMigrationKeepsExistingUsersOnFullInfo() {
        let p = GuidancePrefs.migrated(liveSubjectCues: false, guidanceDebug: false)
        XCTAssertEqual(p.style, .full)
        XCTAssertFalse(p.display.headCues)
        XCTAssertFalse(p.display.detectionBoxes)
        XCTAssertEqual(p.display.cueRow, .topPlusCount)
        XCTAssertEqual(p.display.zoomDetail, .ruler)
    }

    func testMigrationCarriesTheOldSwitches() {
        let p = GuidancePrefs.migrated(liveSubjectCues: true, guidanceDebug: true)
        XCTAssertTrue(p.display.headCues)
        XCTAssertTrue(p.display.detectionBoxes)
        XCTAssertTrue(p.display.debugReadout)
        XCTAssertTrue(p.developerReadout)
    }

    func testPrefsRoundTripThroughJSON() throws {
        var p = GuidancePrefs(style: .minimal)
        p.level = .essentials
        p.override { $0.haptics = false }
        let back = try JSONDecoder().decode(GuidancePrefs.self, from: JSONEncoder().encode(p))
        XCTAssertEqual(back, p)
    }
}
