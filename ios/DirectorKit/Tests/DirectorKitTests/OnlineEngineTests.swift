import XCTest
@testable import DirectorKit

// MARK: - Fake transport

final class FakeHTTP: StreamingHTTPClient, @unchecked Sendable {
    enum Reply {
        case lines([String], status: Int = 200)
        case hang            // head arrives, body never ends
        case fail(Error)
    }
    private let lock = NSLock()
    private var _requests: [URLRequest] = []
    private var _terminated = false
    let reply: Reply
    init(_ reply: Reply) { self.reply = reply }
    var requests: [URLRequest] { lock.lock(); defer { lock.unlock() }; return _requests }
    var terminated: Bool { lock.lock(); defer { lock.unlock() }; return _terminated }

    private func record(_ r: URLRequest) { lock.lock(); _requests.append(r); lock.unlock() }
    private func markTerminated() { lock.lock(); _terminated = true; lock.unlock() }

    func send(_ request: URLRequest) async throws -> (HTTPURLResponse, AsyncThrowingStream<String, Error>) {
        record(request)
        let url = request.url!
        switch reply {
        case let .fail(e): throw e
        case let .lines(lines, status):
            let r = HTTPURLResponse(url: url, statusCode: status, httpVersion: nil, headerFields: nil)!
            return (r, AsyncThrowingStream { c in lines.forEach { c.yield($0) }; c.finish() })
        case .hang:
            let r = HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: nil)!
            return (r, AsyncThrowingStream { c in
                c.onTermination = { [self] _ in markTerminated() }
            })
        }
    }
}

private func shotLine(_ n: Int) -> String {
    #"{"type":"shot","shot":{"title":"Shot \#(n)","camera_position":"on the step","camera_height":"knee","camera_angle":"tilt up","subject_position":"left third","steps":"one string"}}"#
}
private let stageLines = [
    #"{"type":"stage","stage":"preparing"}"#, #"{"type":"stage","stage":"readingScene"}"#,
    #"{"type":"stage","stage":"writingShots"}"#,
]
private let finishedLine = #"{"type":"finished"}"#

private func engine(_ http: FakeHTTP) -> OnlineEngine {
    OnlineEngine(configuration: .init(baseURL: URL(string: "http://example.test:8787")!, apiKey: "test-key"), client: http)
}
private func photosRequest(_ base: DirectorRequest = request) -> DirectorRequest {
    var r = base; r.upload = .photos; return r
}
private func inspirationRequest() -> DirectorRequest {
    var imgs = (1...3).map { DirectorImage(role: .inspiration, jpeg: Data([UInt8($0)])) }
    imgs.append(DirectorImage(role: .target, jpeg: Data([9])))
    return DirectorRequest(mode: .inspiration, images: imgs, shotCount: 4, upload: .photos)
}
private func bodyString(_ r: URLRequest) -> String { String(decoding: r.httpBody ?? Data(), as: UTF8.self) }

// MARK: - Tests

final class OnlineEngineTests: XCTestCase {
    func testHappyPath() async throws {
        let http = FakeHTTP(.lines(stageLines + (1...3).map(shotLine) + [finishedLine]))
        let events = try await collect(engine(http).plan(photosRequest()))
        XCTAssertEqual(events.count, 7)
        XCTAssertEqual(events.first, .stage(.preparing, .online))
        XCTAssertEqual(events.last, .finished(.online))
        let shots = events.compactMap { e -> Shot? in if case let .shot(s, k) = e { XCTAssertEqual(k, .online); return s }; return nil }
        XCTAssertEqual(shots.map(\.title), ["Shot 1", "Shot 2", "Shot 3"])
        XCTAssertEqual(shots[0].steps, ["one string"])  // lenient Shot decoding
        let r = http.requests[0]
        XCTAssertEqual(r.httpMethod, "POST")
        XCTAssertEqual(r.url?.absoluteString, "http://example.test:8787/v1/plan")
        XCTAssertEqual(r.value(forHTTPHeaderField: "Authorization"), "Bearer test-key")
    }

    func testErrorLineThrows() async {
        let http = FakeHTTP(.lines([stageLines[0], shotLine(1), #"{"type":"error","message":"model crashed"}"#]))
        do { _ = try await collect(engine(http).plan(photosRequest())); XCTFail() }
        catch { XCTAssertEqual(error as? DirectorError, .onlineUnavailable("model crashed")) }
    }

    func testHTTPErrorStatuses() async {
        for (status, msg) in [(401, "Missing or invalid API key."), (422, "Scene mode needs a style or a brief."),
                              (429, "Too many requests."), (503, "Busy."), (413, "Image is too large.")] {
            let http = FakeHTTP(.lines([#"{"error": "\#(msg)"}"#], status: status))
            do { _ = try await collect(engine(http).plan(photosRequest())); XCTFail("\(status)") }
            catch { XCTAssertEqual(error as? DirectorError, .onlineUnavailable(msg), "\(status)") }
        }
    }

    func testHTTPErrorWithoutJSONBody() async {
        let http = FakeHTTP(.lines(["<html>bad gateway</html>"], status: 502))
        do { _ = try await collect(engine(http).plan(photosRequest())); XCTFail() }
        catch { XCTAssertEqual(error as? DirectorError, .onlineUnavailable("The server answered HTTP 502.")) }
    }

    func testTruncatedStreamIsError() async {
        let http = FakeHTTP(.lines(stageLines + [shotLine(1), shotLine(2)]))
        do { _ = try await collect(engine(http).plan(photosRequest())); XCTFail() }
        catch { guard case .onlineUnavailable = error as? DirectorError else { return XCTFail("\(error)") } }
    }

    func testGarbageLineIsError() async {
        let http = FakeHTTP(.lines(["not json"]))
        do { _ = try await collect(engine(http).plan(photosRequest())); XCTFail() }
        catch { guard case .onlineUnavailable = error as? DirectorError else { return XCTFail("\(error)") } }
    }

    func testTransportFailureMapsToOnlineUnavailable() async {
        let http = FakeHTTP(.fail(URLError(.notConnectedToInternet)))
        do { _ = try await collect(engine(http).plan(photosRequest())); XCTFail() }
        catch { guard case .onlineUnavailable = error as? DirectorError else { return XCTFail("\(error)") } }
    }

    func testNonPhotoUploadsNeverHitTheNetwork() async {
        for mode in [UploadMode.sceneTextOnly, .none] {
            let http = FakeHTTP(.lines([finishedLine]))
            var r = request; r.upload = mode
            do { _ = try await collect(engine(http).plan(r)); XCTFail() }
            catch { guard case .onlineUnavailable = error as? DirectorError else { return XCTFail("\(error)") } }
            XCTAssertTrue(http.requests.isEmpty, "\(mode)")
        }
    }

    func testSceneMultipartBody() async throws {
        let http = FakeHTTP(.lines([finishedLine]))
        var r = photosRequest(); r = DirectorRequest(mode: .scene, style: .vintageCCD, brief: "golden hour",
            images: r.images, shotCount: 5, upload: .photos)
        _ = try await collect(engine(http).plan(r))
        let req = http.requests[0]
        let ct = req.value(forHTTPHeaderField: "Content-Type")!
        XCTAssertTrue(ct.hasPrefix("multipart/form-data; boundary="))
        let boundary = String(ct.dropFirst("multipart/form-data; boundary=".count))
        let body = bodyString(req)
        for (n, v) in [("mode", "scene"), ("style", "vintage_ccd"), ("brief", "golden hour"), ("shot_count", "5"), ("upload", "photos")] {
            XCTAssertTrue(body.contains("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(n)\"\r\n\r\n\(v)\r\n"), n)
        }
        XCTAssertTrue(body.contains("name=\"target\"; filename=\"target.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n"))
        XCTAssertFalse(body.contains("name=\"inspiration\""))
        XCTAssertTrue(body.hasSuffix("--\(boundary)--\r\n"))
    }

    func testSceneOmitsStyleWhenNil() async throws {
        let http = FakeHTTP(.lines([finishedLine]))
        let r = DirectorRequest(mode: .scene, brief: "moody", images: [DirectorImage(role: .target, jpeg: Data([1]))], upload: .photos)
        _ = try await collect(engine(http).plan(r))
        XCTAssertFalse(bodyString(http.requests[0]).contains("name=\"style\""))
    }

    func testInspirationMultipartBody() async throws {
        let http = FakeHTTP(.lines([finishedLine]))
        _ = try await collect(engine(http).plan(inspirationRequest()))
        let body = bodyString(http.requests[0])
        XCTAssertTrue(body.contains("name=\"mode\"\r\n\r\ninspiration\r\n"))
        XCTAssertFalse(body.contains("name=\"style\""))
        XCTAssertTrue(body.contains("name=\"shot_count\"\r\n\r\n4\r\n"))
        for i in 1...3 { XCTAssertTrue(body.contains("name=\"inspiration\"; filename=\"inspiration_\(i).jpg\"")) }
        XCTAssertEqual(body.components(separatedBy: "name=\"target\"").count - 1, 1)
    }

    func testCancellationCancelsTheRequest() async throws {
        let http = FakeHTTP(.hang)
        let stream = engine(http).plan(photosRequest())
        let consumer = Task { for try await _ in stream {} }
        for _ in 0..<200 where http.requests.isEmpty { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertEqual(http.requests.count, 1)
        consumer.cancel()
        _ = try? await consumer.value
        for _ in 0..<200 where !http.terminated { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertTrue(http.terminated, "the transport stream should be torn down on cancel")
    }

    // MARK: Hybrid integration

    func testOnline503FallsBackToOffline() async throws {
        let http = FakeHTTP(.lines([#"{"error":"Busy."}"#], status: 503))
        let offline = FakeEngine(.offline, count: 3)
        let hybrid = HybridDirector(online: engine(http), offline: offline,
                                    conditions: FixedConditions(value: conditions(.ok)), config: { DirectorConfig() })
        let events = try await collect(hybrid.plan(request))
        XCTAssertEqual(http.requests.count, 1)
        XCTAssertTrue(events.contains { if case .engineSwitched(.online, .offline, _) = $0 { return true }; return false })
        XCTAssertEqual(events.last, .finished(.offline))
        XCTAssertEqual(offline.seen.count, 1)
    }

    func testOfflineOnlyPreferenceNeverUsesNetwork() async throws {
        let http = FakeHTTP(.lines([finishedLine]))
        let hybrid = HybridDirector(online: engine(http), offline: FakeEngine(.offline),
                                    conditions: FixedConditions(value: conditions(.ok)),
                                    config: { DirectorConfig(preference: .offlineOnly) })
        _ = try await collect(hybrid.plan(request))
        XCTAssertTrue(http.requests.isEmpty)
    }
}

final class MultipartBodyTests: XCTestCase {
    func testExactBytes() {
        var b = MultipartBody(boundary: "BB")
        b.addField("mode", "scene")
        b.addFile("target", filename: "t.jpg", data: Data([0xFF, 0xD8]))
        let expected = "--BB\r\nContent-Disposition: form-data; name=\"mode\"\r\n\r\nscene\r\n"
            + "--BB\r\nContent-Disposition: form-data; name=\"target\"; filename=\"t.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n"
        var data = Data(expected.utf8); data.append(Data([0xFF, 0xD8])); data.append(Data("\r\n--BB--\r\n".utf8))
        XCTAssertEqual(b.data, data)
        XCTAssertEqual(b.contentType, "multipart/form-data; boundary=BB")
    }

    func testDefaultBoundariesDiffer() { XCTAssertNotEqual(MultipartBody().boundary, MultipartBody().boundary) }
    func testQuotesInNamesAreEscaped() {
        var b = MultipartBody(boundary: "BB"); b.addField("a\"b", "v")
        XCTAssertTrue(String(decoding: b.data, as: UTF8.self).contains("name=\"a%22b\""))
    }
}

/// Opt-in: DIGI_LIVE_URL and DIGI_LIVE_KEY point at a running `photo-ai server serve`.
final class OnlineEngineLiveTests: XCTestCase {
    func testLiveSceneRequest() async throws {
        let env = ProcessInfo.processInfo.environment
        guard let u = env["DIGI_LIVE_URL"], let url = URL(string: u), let key = env["DIGI_LIVE_KEY"] else {
            throw XCTSkip("set DIGI_LIVE_URL and DIGI_LIVE_KEY to run")
        }
        guard let path = env["DIGI_LIVE_JPEG"], let jpeg = FileManager.default.contents(atPath: path) else {
            throw XCTSkip("set DIGI_LIVE_JPEG to a scene photo")
        }
        let live = OnlineEngine(configuration: .init(baseURL: url, apiKey: key, timeout: 180))
        let r = DirectorRequest(mode: .scene, style: .relaxedCandid, images: [DirectorImage(role: .target, jpeg: jpeg)], upload: .photos)
        let events = try await collect(live.plan(r))
        XCTAssertEqual(events.last, .finished(.online))
        XCTAssertTrue(events.contains { if case .shot = $0 { return true }; return false })
    }
}
