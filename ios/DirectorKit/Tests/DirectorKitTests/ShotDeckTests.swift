import XCTest
@testable import DirectorKit

final class ShotDeckTests: XCTestCase {
    private func shot(_ n: Int) -> Shot {
        Shot(title: "Shot \(n)", cameraPosition: "spot \(n)", cameraHeight: "h", cameraAngle: "a", subjectPosition: "s")
    }
    private func deck(_ n: Int = 3) -> ShotDeck { ShotDeck(shots: (1...n).map(shot)) }

    func testRefreshReplacesOnlyTheShotsThatAreNotKept() {
        var d = deck()
        d.toggleKeep(d.shots[1])
        XCTAssertNotNil(d.beginRefresh())
        XCTAssertEqual(d.pending, [0, 2])
        XCTAssertFalse(d.fill(shot(4)))
        XCTAssertTrue(d.fill(shot(5)))
        XCTAssertEqual(d.shots.map(\.title), ["Shot 4", "Shot 2", "Shot 5"])
        XCTAssertFalse(d.isRefreshing)
    }

    func testNothingToRefreshWhenAllKeptOrEmpty() {
        var d = deck()
        for s in d.shots { d.toggleKeep(s) }
        XCTAssertFalse(d.canRefresh)
        XCTAssertNil(d.beginRefresh())
        var empty = ShotDeck()
        XCTAssertNil(empty.beginRefresh())
    }

    func testARepeatedShotIsSkipped() {
        var d = deck()
        _ = d.beginRefresh()
        XCTAssertFalse(d.fill(shot(2)), "a repeat of a shown shot does not take the slot")
        XCTAssertEqual(d.pending, [0, 1, 2])
        d.fill(shot(9))
        XCTAssertEqual(d.shots[0].title, "Shot 9")
    }

    func testEndRefreshKeepsOldShotsInUnfilledSlots() {
        var d = deck()
        _ = d.beginRefresh()
        d.fill(shot(7))
        d.endRefresh()
        XCTAssertEqual(d.shots.map(\.title), ["Shot 7", "Shot 2", "Shot 3"])
        XCTAssertTrue(d.canRefresh)
    }

    func testToggleKeepIsReversible() {
        var d = deck()
        d.toggleKeep(d.shots[0]); XCTAssertEqual(d.keptCount, 1)
        d.toggleKeep(d.shots[0]); XCTAssertEqual(d.keptCount, 0)
    }

    func testEngineSwitchKeepsFavoritesAndDropsTheRest() {
        var d = deck()
        d.toggleKeep(d.shots[2])
        d.resetKeepingFavorites()
        XCTAssertEqual(d.shots.map(\.title), ["Shot 3"])
    }

    func testBriefAvoidingListsEarlierLooksAndKeepsTheUsersNote() {
        let text = ShotDeck.briefAvoiding([shot(1), shot(2)], base: "she prefers seated poses")
        XCTAssertTrue(text.hasPrefix("she prefers seated poses "))
        XCTAssertTrue(text.contains("Shot 1 (spot 1); Shot 2 (spot 2)"))
        XCTAssertEqual(ShotDeck.briefAvoiding([], base: nil), "")
    }
}
