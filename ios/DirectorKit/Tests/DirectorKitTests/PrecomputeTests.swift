import XCTest
@testable import DirectorKit

// MARK: - Fakes

/// Answers by URL path, in order; records every request.
private final class RoutedHTTP: StreamingHTTPClient, @unchecked Sendable {
    private let lock = NSLock()
    private var replies: [String: [(Int, [String])]]
    private var _requests: [URLRequest] = []
    init(_ replies: [String: [(Int, [String])]]) { self.replies = replies }
    var requests: [URLRequest] { lock.lock(); defer { lock.unlock() }; return _requests }

    func send(_ request: URLRequest) async throws -> (HTTPURLResponse, AsyncThrowingStream<String, Error>) {
        let path = request.url!.path
        let (status, lines) = lock.withLock {
            _requests.append(request)
            return replies[path]?.isEmpty == false ? replies[path]!.removeFirst() : (404, [#"{"error":"no reply"}"#])
        }
        let r = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!
        return (r, AsyncThrowingStream { c in lines.forEach { c.yield($0) }; c.finish() })
    }
}

private actor FakeService: PrecomputeService {
    var log: [String] = []
    var running = 0, maxRunning = 0
    var failScene = false
    var planToken: String? = "tok-1"
    private var n = 0

    func setFailScene(_ v: Bool) { failScene = v }
    func setPlanToken(_ v: String?) { planToken = v }

    private func call(_ name: String) async {
        running += 1; maxRunning = max(maxRunning, running); log.append(name)
        try? await Task.sleep(for: .milliseconds(20))
        running -= 1
    }
    nonisolated func prepareReferences(_ inspiration: [Data]) async throws -> Data {
        await call("refs\(inspiration.count)"); return Data(#"{"notes":["a","b","c"]}"#.utf8)
    }
    nonisolated func prepareScene(_ target: Data) async throws -> Data {
        await call("scene")
        if await failScene { throw DirectorError.onlineUnavailable("down") }
        return Data(#"{"target_scene":{}}"#.utf8)
    }
    nonisolated func preparePlan(target: Data, references: Data, targetScene: Data) async throws -> String? {
        await call("plan"); return await planToken
    }
}

private func waitIdle(_ p: PlanPreparer, timeout: TimeInterval = 3) async throws {
    let end = Date().addingTimeInterval(timeout)
    while Date() < end {
        if await p.currentStatus != .working { return }
        try await Task.sleep(for: .milliseconds(10))
    }
    XCTFail("preparer still working after \(timeout) s")
}

private let target = Data([1, 2, 3])
private let insp = [Data([10]), Data([11]), Data([12])]
private let shot = #"{"type":"shot","shot":{"title":"S","camera_position":"p","camera_height":"h","camera_angle":"a","subject_position":"s","steps":"x"}}"#
private let done = #"{"type":"finished"}"#

private func engine(_ http: RoutedHTTP) -> OnlineEngine {
    OnlineEngine(configuration: .init(baseURL: URL(string: "http://example.test:8787")!, apiKey: "k"), client: http)
}
private func inspirationRequest(prepared: PreparedInputs?) -> DirectorRequest {
    DirectorRequest(mode: .inspiration, images: insp.map { DirectorImage(role: .inspiration, jpeg: $0) } + [DirectorImage(role: .target, jpeg: target)],
                    upload: .photos, prepared: prepared)
}
private func body(_ r: URLRequest) -> String { String(decoding: r.httpBody ?? Data(), as: UTF8.self) }
private func count(_ s: String, _ needle: String) -> Int { s.components(separatedBy: needle).count - 1 }

// MARK: - Online engine

final class OnlineEnginePrecomputeTests: XCTestCase {
    func testPreparedFieldsAreSentAndInspirationPhotosAreSkipped() throws {
        let p = PreparedInputs(references: Data(#"{"r":1}"#.utf8), targetScene: Data(#"{"s":1}"#.utf8), planToken: "tok")
        let b = body(try engine(RoutedHTTP([:])).makeRequest(inspirationRequest(prepared: p)))
        XCTAssertTrue(b.contains(#"name="references""#) && b.contains(#"{"r":1}"#))
        XCTAssertTrue(b.contains(#"name="target_scene""#) && b.contains(#"name="plan_token""#))
        XCTAssertEqual(count(b, #"name="inspiration""#), 0)
        XCTAssertEqual(count(b, #"name="target""#), 1)
    }

    func testSceneOnlyPreparedStillSendsInspirationPhotos() throws {
        let b = body(try engine(RoutedHTTP([:])).makeRequest(inspirationRequest(prepared: PreparedInputs(targetScene: Data("{}".utf8)))))
        XCTAssertTrue(b.contains(#"name="target_scene""#))
        XCTAssertEqual(count(b, #"name="inspiration""#), 3)
    }

    func testPreparedIsIgnoredOutsideInspirationMode() throws {
        let r = DirectorRequest(mode: .scene, style: .relaxedCandid, images: [DirectorImage(role: .target, jpeg: target)],
                                upload: .photos, prepared: PreparedInputs(planToken: "tok"))
        XCTAssertFalse(body(try engine(RoutedHTTP([:])).makeRequest(r)).contains("plan_token"))
    }

    func testRefusedPreparedWorkIsRetriedOnceWithThePhotos() async throws {
        let http = RoutedHTTP(["/v1/plan": [(409, [#"{"error":"stale"}"#]), (200, [shot, done])]])
        var events: [DirectorEvent] = []
        for try await e in engine(http).plan(inspirationRequest(prepared: PreparedInputs(references: Data("{}".utf8)))) { events.append(e) }
        XCTAssertEqual(http.requests.count, 2)
        XCTAssertTrue(body(http.requests[0]).contains("references"))
        XCTAssertFalse(body(http.requests[1]).contains("references"))
        XCTAssertEqual(count(body(http.requests[1]), #"name="inspiration""#), 3)
        XCTAssertEqual(events.filter { if case .shot = $0 { true } else { false } }.count, 1)
        XCTAssertEqual(events.last, .finished(.online))
    }

    func testA409WithoutPreparedWorkIsAnErrorNotARetry() async throws {
        let http = RoutedHTTP(["/v1/plan": [(409, [#"{"error":"nope"}"#]), (200, [shot, done])]])
        do {
            for try await _ in engine(http).plan(inspirationRequest(prepared: nil)) {}
            XCTFail("expected an error")
        } catch let e as DirectorError { XCTAssertEqual(e, .onlineUnavailable("nope")) }
        XCTAssertEqual(http.requests.count, 1)
    }

    func testPrepareCallsReadTheServerReplies() async throws {
        let http = RoutedHTTP([
            "/v1/references": [(200, [#"{"references": {"version": 1, "notes": ["a"]}}"#])],
            "/v1/scene": [(200, [#"{"target_scene": {"photo_sha256": "x"}}"#])],
            "/v1/prepare-plan": [(200, [#"{"prepared": true, "plan_token": "tok-9", "expires_in_s": 600}"#]), (200, [#"{"prepared": false}"#])],
        ])
        let e = engine(http)
        let refs = try await e.prepareReferences(insp)
        XCTAssertEqual(try JSONSerialization.jsonObject(with: refs) as? NSDictionary, ["version": 1, "notes": ["a"]])
        let scene = try await e.prepareScene(target)
        XCTAssertEqual(try JSONSerialization.jsonObject(with: scene) as? NSDictionary, ["photo_sha256": "x"])
        let tok1 = try await e.preparePlan(target: target, references: refs, targetScene: scene)
        let tok2 = try await e.preparePlan(target: target, references: refs, targetScene: scene)
        XCTAssertEqual(tok1, "tok-9"); XCTAssertNil(tok2)
        XCTAssertEqual(count(body(http.requests[0]), #"name="inspiration""#), 3)
        XCTAssertTrue(body(http.requests[2]).contains(#"name="references""#) && body(http.requests[2]).contains(#"name="target""#))
        XCTAssertEqual(http.requests[0].value(forHTTPHeaderField: "Authorization"), "Bearer k")
    }

    func testPrepareCallsThrowOnServerErrors() async throws {
        let http = RoutedHTTP(["/v1/scene": [(503, [#"{"error":"busy"}"#])]])
        do { _ = try await engine(http).prepareScene(target); XCTFail("expected an error") }
        catch let e as DirectorError { XCTAssertEqual(e, .onlineUnavailable("busy")) }
    }
}

// MARK: - Preparer

final class PlanPreparerTests: XCTestCase {
    func testRunsSceneThenReferencesThenPlanOneAtATime() async throws {
        let s = FakeService(); let p = PlanPreparer(service: s)
        await p.update(target: target, inspiration: [])
        try await waitIdle(p)
        await p.update(target: target, inspiration: insp)
        try await waitIdle(p)
        let log = await s.log, maxRunning = await s.maxRunning
        XCTAssertEqual(log, ["scene", "refs3", "plan"])
        XCTAssertEqual(maxRunning, 1)
        let status = await p.currentStatus
        XCTAssertEqual(status, .ready)
        let got = await p.prepared(target: target, inspiration: insp)
        XCTAssertNotNil(got.references); XCTAssertNotNil(got.targetScene); XCTAssertEqual(got.planToken, "tok-1")
        let again = await p.prepared(target: target, inspiration: insp)
        XCTAssertNil(again.planToken, "the plan token is single use")
        XCTAssertNotNil(again.references)
    }

    func testChangingAnInspirationPhotoKeepsTheSceneAndRedoesTheRest() async throws {
        let s = FakeService(); let p = PlanPreparer(service: s)
        await p.update(target: target, inspiration: insp); try await waitIdle(p)
        await p.update(target: target, inspiration: [insp[0], insp[1], Data([99])]); try await waitIdle(p)
        let log = await s.log
        XCTAssertEqual(log, ["scene", "refs3", "plan", "refs3", "plan"])
        let old = await p.prepared(target: target, inspiration: insp)
        XCTAssertNil(old.references, "results are only given for the exact photos they were made from")
        XCTAssertNotNil(old.targetScene)
    }

    func testFewerThanThreeInspirationPhotosPreparesOnlyTheScene() async throws {
        let s = FakeService(); let p = PlanPreparer(service: s)
        await p.update(target: target, inspiration: [insp[0], insp[1]]); try await waitIdle(p)
        let log = await s.log
        XCTAssertEqual(log, ["scene"])
    }

    func testAFailingCallIsNotRetriedInALoopButNewPhotosTryAgain() async throws {
        let s = FakeService(); await s.setFailScene(true)
        let p = PlanPreparer(service: s)
        await p.update(target: target, inspiration: insp); try await waitIdle(p)
        var log = await s.log
        XCTAssertEqual(log, ["scene", "refs3"], "no plan token without a scene, and the scene is not asked again")
        await s.setFailScene(false)
        await p.update(target: Data([7]), inspiration: insp); try await waitIdle(p)
        log = await s.log
        XCTAssertEqual(log, ["scene", "refs3", "scene", "plan"])
    }

    func testNoTokenWhenTheServerHasNoPromptCache() async throws {
        let s = FakeService(); await s.setPlanToken(nil)
        let p = PlanPreparer(service: s)
        await p.update(target: target, inspiration: insp); try await waitIdle(p)
        let got = await p.prepared(target: target, inspiration: insp)
        XCTAssertNil(got.planToken); XCTAssertNotNil(got.references)
        await p.update(target: target, inspiration: insp); try await waitIdle(p)
        let log = await s.log
        XCTAssertEqual(log.filter { $0 == "plan" }.count, 1, "not asked again for the same photos")
    }

    func testAnOldTokenIsNotOffered() async throws {
        final class Clock: @unchecked Sendable { var t = Date(timeIntervalSince1970: 0) }
        let clock = Clock()
        let p = PlanPreparer(service: FakeService(), tokenLifetime: 540, now: { clock.t })
        await p.update(target: target, inspiration: insp); try await waitIdle(p)
        clock.t = clock.t.addingTimeInterval(600)
        let got = await p.prepared(target: target, inspiration: insp)
        XCTAssertNil(got.planToken); XCTAssertNotNil(got.targetScene)
    }

    func testStatusReportsWorkingThenReady() async throws {
        final class Box: @unchecked Sendable { let lock = NSLock(); var seen: [PlanPreparer.Status] = []
            func add(_ s: PlanPreparer.Status) { lock.lock(); seen.append(s); lock.unlock() } }
        let box = Box()
        let p = PlanPreparer(service: FakeService(), onStatus: { box.add($0) })
        await p.update(target: target, inspiration: insp); try await waitIdle(p)
        XCTAssertEqual(box.seen, [.working, .ready])
        await p.update(target: nil, inspiration: []); try await waitIdle(p)
        XCTAssertEqual(box.seen, [.working, .ready, .idle])
    }
}
