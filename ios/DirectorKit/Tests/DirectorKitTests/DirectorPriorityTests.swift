import XCTest
@testable import DirectorKit

final class DirectorPriorityTests: XCTestCase {
    func testBestResultsIsTheMostPatientAndFastestTheLeast() {
        XCTAssertGreaterThan(DirectorPriority.bestResults.totalDeadline, DirectorPriority.balanced.totalDeadline)
        XCTAssertGreaterThan(DirectorPriority.balanced.totalDeadline, DirectorPriority.fastest.totalDeadline)
        XCTAssertGreaterThan(DirectorPriority.bestResults.firstShotDeadline, DirectorPriority.fastest.firstShotDeadline)
    }

    func testBestResultsAllowsAMacServerToFinish() {
        // The Mac server needs about 12 s for a first shot and 60 s overall.
        XCTAssertGreaterThanOrEqual(DirectorPriority.bestResults.firstShotDeadline, 12)
        XCTAssertGreaterThanOrEqual(DirectorPriority.bestResults.totalDeadline, 60)
    }

    func testPriorityOnlyChangesTheDeadlinesNotTheRoute() throws {
        let c = DeviceConditions(connectivity: .ok)
        for p in DirectorPriority.allCases {
            let plan = try Router.route(conditions: c, config: .make(preference: .automatic, priority: p))
            XCTAssertEqual(plan.order, [.online, .offline], "\(p)")
        }
    }

    private func rec(_ e: EngineKind, first: Double?, total: Double, shots: Int = 3, kept: Int = 0, used: Bool = false) -> RunRecord {
        var r = RunRecord(engine: e, priority: .bestResults, firstShotSeconds: first, totalSeconds: total, shotCount: shots, fellBack: false)
        r.keptCount = kept; r.usedShot = used
        return r
    }

    func testStatsPerEngine() {
        let s = RunLog.summarize([rec(.online, first: 10, total: 40, kept: 2, used: true),
                                  rec(.online, first: 14, total: 60, kept: 1),
                                  rec(.offline, first: 4, total: 9, kept: 0)])
        let on = s.first { $0.engine == .online }!
        XCTAssertEqual(on.runs, 2)
        XCTAssertEqual(on.medianFirstShotSeconds, 12)
        XCTAssertEqual(on.medianTotalSeconds, 50)
        XCTAssertEqual(on.keepRate, 0.5, accuracy: 0.001)
        XCTAssertEqual(on.useRate, 0.5, accuracy: 0.001)
        XCTAssertEqual(s.first { $0.engine == .offline }!.keepRate, 0)
    }

    func testRunsWithNoShotsAreIgnoredAndTheLogIsCapped() {
        XCTAssertTrue(RunLog.summarize([rec(.online, first: nil, total: 5, shots: 0)]).isEmpty)
        var log: [RunRecord] = []
        for i in 0..<(RunLog.maxRecords + 20) { log = RunLog.appended(log, rec(.online, first: 1, total: Double(i))) }
        XCTAssertEqual(log.count, RunLog.maxRecords)
        XCTAssertEqual(log.last?.totalSeconds, Double(RunLog.maxRecords + 19))
    }
}
