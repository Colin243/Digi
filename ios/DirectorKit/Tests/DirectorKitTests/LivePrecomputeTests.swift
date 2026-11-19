import XCTest
@testable import DirectorKit

/// Opt-in check of the Swift client against a real `photo-ai server` (skipped unless DIGI_LIVE_SERVER is set):
///
///     DIGI_LIVE_SERVER=http://127.0.0.1:8790 DIGI_LIVE_KEY_FILE=<file with a client key> \
///     DIGI_LIVE_CASE=<folder with target.jpg and inspiration_*.jpg> swift test --filter LivePrecompute
///
/// It prepares ahead with PlanPreparer exactly as the app does, then plans with and without the prepared work and
/// prints the time to the first shot and to the end.
final class LivePrecomputeTests: XCTestCase {
    func testPreparedPlanAgainstARealServer() async throws {
        let env = ProcessInfo.processInfo.environment
        guard let base = env["DIGI_LIVE_SERVER"].flatMap(URL.init(string:)), let keyFile = env["DIGI_LIVE_KEY_FILE"],
              let folder = env["DIGI_LIVE_CASE"] else { throw XCTSkip("set DIGI_LIVE_SERVER, DIGI_LIVE_KEY_FILE and DIGI_LIVE_CASE") }
        let key = try String(contentsOfFile: keyFile, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
        let dir = URL(fileURLWithPath: folder)
        let target = try Data(contentsOf: dir.appendingPathComponent("target.jpg"))
        let names = try FileManager.default.contentsOfDirectory(atPath: folder).filter { $0.hasPrefix("inspiration_") }.sorted()
        let inspiration = try names.map { try Data(contentsOf: dir.appendingPathComponent($0)) }
        let engine = OnlineEngine(configuration: .init(baseURL: base, apiKey: key, timeout: 120))

        // Read ahead, as the app does while photos are being chosen.
        let preparer = PlanPreparer(service: engine)
        let t0 = Date()
        await preparer.update(target: target, inspiration: inspiration)
        while await preparer.currentStatus == .working { try await Task.sleep(for: .milliseconds(100)) }
        let prepSeconds = Date().timeIntervalSince(t0)
        let prepared = await preparer.prepared(target: target, inspiration: inspiration)
        XCTAssertNotNil(prepared.references); XCTAssertNotNil(prepared.targetScene); XCTAssertNotNil(prepared.planToken)

        func plan(_ p: PreparedInputs?) async throws -> (first: Double?, total: Double, shots: Int, finished: Bool) {
            let images = inspiration.map { DirectorImage(role: .inspiration, jpeg: $0) } + [DirectorImage(role: .target, jpeg: target)]
            let request = DirectorRequest(mode: .inspiration, images: images, upload: .photos, prepared: p)
            let start = Date(); var first: Double?; var shots = 0; var finished = false
            for try await e in engine.plan(request) {
                switch e {
                case .shot: shots += 1; if first == nil { first = Date().timeIntervalSince(start) }
                case .finished: finished = true
                default: break
                }
            }
            return (first, Date().timeIntervalSince(start), shots, finished)
        }
        let fast = try await plan(prepared)
        let slow = try await plan(nil)
        print(String(format: "LIVE prepare ahead %.1f s | prepared plan: first shot %.1f s, done %.1f s, %d shots | photos only: first shot %.1f s, done %.1f s, %d shots",
                     prepSeconds, fast.first ?? -1, fast.total, fast.shots, slow.first ?? -1, slow.total, slow.shots))
        XCTAssertTrue(fast.finished && slow.finished)
        XCTAssertEqual(fast.shots, 3); XCTAssertEqual(slow.shots, 3)
        XCTAssertLessThan(fast.total, slow.total)
    }
}
