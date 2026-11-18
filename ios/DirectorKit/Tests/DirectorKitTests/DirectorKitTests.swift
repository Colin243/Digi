import XCTest
@testable import DirectorKit

// MARK: - Fakes

struct FixedConditions: DeviceConditionsProvider {
    let value: DeviceConditions
    func current() async -> DeviceConditions { value }
}

func makeShot(_ n: Int) -> Shot {
    Shot(title: "Shot \(n)", cameraPosition: "on the bottom step", cameraHeight: "knee height",
         cameraAngle: "tilt up 15 degrees", subjectPosition: "left third")
}

/// Emits `count` shots, `gap` seconds apart (after an initial `delay`), then optionally fails.
final class FakeEngine: DirectorEngine, @unchecked Sendable {
    let kind: EngineKind
    let delay: Double, gap: Double, count: Int, failAfter: Int?
    private let lock = NSLock()
    private var requests: [DirectorRequest] = []
    var seen: [DirectorRequest] { lock.lock(); defer { lock.unlock() }; return requests }

    init(_ kind: EngineKind, delay: Double = 0, gap: Double = 0, count: Int = 3, failAfter: Int? = nil) {
        self.kind = kind; self.delay = delay; self.gap = gap; self.count = count; self.failAfter = failAfter
    }

    func plan(_ request: DirectorRequest) -> AsyncThrowingStream<DirectorEvent, Error> {
        lock.lock(); requests.append(request); lock.unlock()
        return AsyncThrowingStream { c in
            let t = Task {
                do {
                    c.yield(.stage(.preparing, kind))
                    try await Task.sleep(for: .seconds(delay))
                    for i in 1...max(count, 1) {
                        if let f = failAfter, i > f { throw DirectorError.onlineUnavailable("boom") }
                        c.yield(.shot(makeShot(i), kind))
                        try await Task.sleep(for: .seconds(gap))
                    }
                    if failAfter == 0 { throw DirectorError.onlineUnavailable("boom") }
                    c.yield(.finished(kind)); c.finish()
                } catch { c.finish(throwing: error) }
            }
            c.onTermination = { _ in t.cancel() }
        }
    }
}

func collect(_ s: AsyncThrowingStream<DirectorEvent, Error>) async throws -> [DirectorEvent] {
    var out: [DirectorEvent] = []
    for try await e in s { out.append(e) }
    return out
}

let request = DirectorRequest(mode: .scene, style: .relaxedCandid,
                              images: [DirectorImage(role: .target, jpeg: Data([1, 2, 3]))])

func conditions(_ c: Connectivity = .ok, _ t: Thermal = .nominal, lowPower: Bool = false,
                memory: UInt64 = 6_000_000_000) -> DeviceConditions {
    DeviceConditions(connectivity: c, thermal: t, lowPowerMode: lowPower, availableMemoryBytes: memory)
}

// MARK: - Router

final class RouterTests: XCTestCase {
    func testConnectedGoesOnlineThenOffline() throws {
        let r = try Router.route(conditions: conditions(), config: DirectorConfig())
        XCTAssertEqual(r.order, [.online, .offline])
    }

    func testNoConnectionIsOfflineAndNothingUploads() throws {
        let r = try Router.route(conditions: conditions(.none), config: DirectorConfig())
        XCTAssertEqual(r.order, [.offline])
        XCTAssertEqual(r.upload, .none)
    }

    func testOfflineOnlySettingNeverUsesNetwork() throws {
        let r = try Router.route(conditions: conditions(), config: DirectorConfig(preference: .offlineOnly))
        XCTAssertEqual(r.order, [.offline])
        XCTAssertEqual(r.upload, .none)
    }

    func testPhotosGoOutByDefaultWithNoPrompt() throws {
        XCTAssertEqual(try Router.route(conditions: conditions(), config: DirectorConfig()).upload, .photos)
    }

    func testTextOnlySettingStillUsesOnlineButSendsNoPixels() throws {
        let r = try Router.route(conditions: conditions(), config: DirectorConfig(preference: .textOnly))
        XCTAssertEqual(r.order, [.online, .offline])
        XCTAssertEqual(r.upload, .sceneTextOnly)
    }

    func testLowDataModePrefersThePhone() throws {
        let r = try Router.route(conditions: conditions(.constrained), config: DirectorConfig())
        XCTAssertEqual(r.order, [.offline, .online])
    }

    func testSeriousHeatOrLowPowerShrinksOfflineWork() throws {
        XCTAssertEqual(try Router.route(conditions: conditions(.none, .serious), config: DirectorConfig()).offlineProfile, .reduced)
        XCTAssertEqual(try Router.route(conditions: conditions(.none, lowPower: true), config: DirectorConfig()).offlineProfile, .reduced)
        XCTAssertEqual(try Router.route(conditions: conditions(.none, .fair), config: DirectorConfig()).offlineProfile, .standard)
    }

    func testCriticalHeatSkipsThePhoneButStillUsesOnline() throws {
        XCTAssertEqual(try Router.route(conditions: conditions(.ok, .critical), config: DirectorConfig()).order, [.online])
        XCTAssertThrowsError(try Router.route(conditions: conditions(.none, .critical), config: DirectorConfig()))
    }

    func testLowMemorySkipsThePhone() throws {
        XCTAssertEqual(try Router.route(conditions: conditions(.ok, memory: 2_000_000_000), config: DirectorConfig()).order, [.online])
        XCTAssertThrowsError(try Router.route(conditions: conditions(.none, memory: 2_000_000_000), config: DirectorConfig()))
    }
}

// MARK: - HybridDirector

final class HybridDirectorTests: XCTestCase {
    func director(online: FakeEngine?, offline: FakeEngine?, c: DeviceConditions = conditions(),
                  cfg: DirectorConfig = DirectorConfig(onlineFirstShotDeadline: 0.3, onlineTotalDeadline: 0.6)) -> HybridDirector {
        HybridDirector(online: online, offline: offline, conditions: FixedConditions(value: c), config: { cfg })
    }

    func testOnlineAnswersWhenHealthy() async throws {
        let on = FakeEngine(.online), off = FakeEngine(.offline)
        let events = try await collect(director(online: on, offline: off).plan(request))
        XCTAssertEqual(events.filter { if case .shot = $0 { true } else { false } }.count, 3)
        XCTAssertEqual(events.last, .finished(.online))
        XCTAssertTrue(off.seen.isEmpty, "offline engine must not run when online succeeds")
    }

    func testRequestCarriesPolicyAndProfile() async throws {
        let on = FakeEngine(.online)
        _ = try await collect(director(online: on, offline: FakeEngine(.offline),
                                       c: conditions(.ok, .serious)).plan(request))
        XCTAssertEqual(on.seen.first?.upload, .photos)
        XCTAssertEqual(on.seen.first?.offlineProfile, .reduced)
    }

    func testSlowOnlineFallsBackToOffline() async throws {
        let on = FakeEngine(.online, delay: 5), off = FakeEngine(.offline)
        let events = try await collect(director(online: on, offline: off).plan(request))
        XCTAssertTrue(events.contains(.engineSwitched(from: .online, to: .offline, reason: "online engine was too slow")))
        XCTAssertEqual(events.last, .finished(.offline))
    }

    func testOnlineErrorFallsBackToOffline() async throws {
        let on = FakeEngine(.online, count: 3, failAfter: 0), off = FakeEngine(.offline)
        let events = try await collect(director(online: on, offline: off).plan(request))
        XCTAssertEqual(events.last, .finished(.offline))
    }

    func testMidStreamFailureSignalsASwitchSoUIClearsShots() async throws {
        let on = FakeEngine(.online, count: 3, failAfter: 1), off = FakeEngine(.offline)
        let events = try await collect(director(online: on, offline: off).plan(request))
        let switchIndex = events.firstIndex { if case .engineSwitched = $0 { true } else { false } }
        let firstOfflineShot = events.firstIndex { if case .shot(_, .offline) = $0 { true } else { false } }
        XCTAssertNotNil(switchIndex)
        XCTAssertLessThan(switchIndex!, firstOfflineShot!)
    }

    func testSlowStreamAfterFirstShotHitsTotalDeadline() async throws {
        let on = FakeEngine(.online, gap: 5), off = FakeEngine(.offline)
        let events = try await collect(director(online: on, offline: off).plan(request))
        XCTAssertEqual(events.last, .finished(.offline))
    }

    func testOfflineEngineIsNeverGivenDeadlines() async throws {
        let off = FakeEngine(.offline, delay: 0.8)   // slower than the online deadlines
        let events = try await collect(director(online: nil, offline: off, c: conditions(.none)).plan(request))
        XCTAssertEqual(events.last, .finished(.offline))
    }

    func testBothEnginesFailingSurfacesTheError() async {
        let on = FakeEngine(.online, count: 1, failAfter: 0), off = FakeEngine(.offline, count: 1, failAfter: 0)
        do { _ = try await collect(director(online: on, offline: off).plan(request)); XCTFail("expected an error") }
        catch { XCTAssertTrue(error is DirectorError) }
    }

    func testNoEngineAvailableIsReported() async {
        do { _ = try await collect(director(online: nil, offline: FakeEngine(.offline), c: conditions(.none, .critical)).plan(request)); XCTFail() }
        catch { XCTAssertTrue(error is DirectorError) }
    }
}

// MARK: - Shot decoding

final class ShotTests: XCTestCase {
    func testLenientDecodingMatchesPythonSchema() throws {
        let json = """
        {"title":"Low hero","camera_position":"bottom step","camera_height":"knee","camera_angle":"up 15",
         "subject_position":"left third","steps":"Crouch, then shoot","gaze":"the lens"}
        """
        let s = try JSONDecoder().decode(Shot.self, from: Data(json.utf8))
        XCTAssertTrue(s.isActionable)
        XCTAssertEqual(s.steps, ["Crouch, then shoot"])
        XCTAssertEqual(s.bodyPose, "")
    }

    func testMissingCoreFieldIsNotActionable() throws {
        let s = try JSONDecoder().decode(Shot.self, from: Data(#"{"title":"x"}"#.utf8))
        XCTAssertFalse(s.isActionable)
    }
}

// MARK: - Both functions

final class RequestValidationTests: XCTestCase {
    func img(_ r: ImageRole) -> DirectorImage { DirectorImage(role: r, jpeg: Data([1])) }

    func testSceneModeNeedsOneTargetAndAStyleOrBrief() {
        XCTAssertNoThrow(try DirectorRequest(mode: .scene, style: .coolEditorial, images: [img(.target)]).validate())
        XCTAssertNoThrow(try DirectorRequest(mode: .scene, brief: "seated poses", images: [img(.target)]).validate())
        XCTAssertThrowsError(try DirectorRequest(mode: .scene, images: [img(.target)]).validate())
        XCTAssertThrowsError(try DirectorRequest(mode: .scene, style: .coolEditorial, images: [img(.target), img(.inspiration)]).validate())
    }

    func testInspirationModeNeedsThreeToFiveReferencesAndATarget() {
        func req(_ n: Int, target: Bool = true) -> DirectorRequest {
            DirectorRequest(mode: .inspiration, images: Array(repeating: img(.inspiration), count: n) + (target ? [img(.target)] : []))
        }
        XCTAssertThrowsError(try req(2).validate())
        XCTAssertNoThrow(try req(3).validate())
        XCTAssertNoThrow(try req(5).validate())
        XCTAssertThrowsError(try req(6).validate())
        XCTAssertThrowsError(try req(4, target: false).validate())
    }

    func testBothModesRouteThroughTheSameDirector() async throws {
        let on = FakeEngine(.online)
        let d = HybridDirector(online: on, offline: FakeEngine(.offline), conditions: FixedConditions(value: conditions()), config: { DirectorConfig() })
        _ = try await collect(d.plan(request))
        let insp = DirectorRequest(mode: .inspiration, images: (0..<3).map { _ in img(.inspiration) } + [img(.target)])
        let events = try await collect(d.plan(insp))
        XCTAssertEqual(events.last, .finished(.online))
        XCTAssertEqual(on.seen.map(\.mode), [.scene, .inspiration])
    }

    func testInvalidRequestFailsBeforeAnyEngineRuns() async {
        let on = FakeEngine(.online)
        let d = HybridDirector(online: on, offline: nil, conditions: FixedConditions(value: conditions()), config: { DirectorConfig() })
        do { _ = try await collect(d.plan(DirectorRequest(mode: .scene, images: []))); XCTFail() }
        catch { XCTAssertEqual(error as? DirectorError, .invalidRequest("Add exactly one photo of the place you will shoot.")) }
        XCTAssertTrue(on.seen.isEmpty)
    }
}
