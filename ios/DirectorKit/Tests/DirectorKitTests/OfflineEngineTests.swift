import XCTest
@testable import DirectorKit

/// Byte parity with photography-ai's prompts, plus the engine's stages with a scripted model.
final class OfflinePromptTests: XCTestCase {
    private func golden() throws -> [String: Any] {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("Fixtures/offline_prompt_golden.json")
        return try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as! [String: Any]
    }

    private func shot(_ title: String, _ cam: String, _ framing: String, _ pose: String, _ gaze: String) -> Shot {
        Shot(title: title, cameraPosition: cam, cameraHeight: "h", cameraAngle: "a", subjectPosition: "s",
             distanceAndFraming: framing, bodyPose: pose, gaze: gaze)
    }

    func testStaticPromptsMatchPython() throws {
        let g = try golden(), exp = g["expected"] as! [String: Any]
        XCTAssertEqual(OfflinePromptData.sceneReading, exp["sceneReading"] as? String)
        XCTAssertEqual(OfflinePromptData.imageNotes, exp["imageNotes"] as? String)
        XCTAssertEqual(OfflinePromptData.targetScene, exp["targetScene"] as? String)
    }

    func testSceneLooksMatchPython() throws {
        let g = try golden(), inp = g["inputs"] as! [String: Any], exp = g["expected"] as! [String: Any]
        let scene = inp["scene"] as! [String: Any]
        let prevAll = [
            shot("Wide at the door", "by the door", "full body, far", "leaning on the frame", "away"),
            shot("Medium by the bar", "across the bar", "waist up", "hand on the counter", "to the lens"),
        ]
        let cases = exp["sceneLooks"] as! [[String: Any]]
        XCTAssertEqual(cases.count, 12)
        for c in cases {
            let style = (c["style"] as? String).flatMap(DirectorStyle.init(rawValue:))
            let look = c["look"] as! Int, n = c["previous"] as! Int
            let text = OfflinePrompts.sceneLook(scene: scene, style: style, brief: c["brief"] as? String, look: look,
                                                previous: Array(prevAll.prefix(n)))
            XCTAssertEqual(text, c["prompt"] as? String, "style \(String(describing: c["style"])) look \(look)")
        }
    }

    func testInspirationPromptsMatchPython() throws {
        let g = try golden(), inp = g["inputs"] as! [String: Any], exp = g["expected"] as! [String: Any]
        XCTAssertEqual(OfflinePrompts.aesthetic(notes: inp["notes"] as! [String]), exp["aesthetic"] as? String)
        XCTAssertEqual(OfflinePrompts.compositions(aesthetic: inp["aesthetic"] as! [String: Any], target: inp["target"] as! [String: Any]),
                       exp["compositions"] as? String)
    }

    func testDumpsMatchesPython() {
        XCTAssertEqual(PromptJSON.dumps(["b": 1, "a": ["x", true, NSNull()], "c": "café \"q\" \\ \n"] as [String: Any]),
                       "{\"a\": [\"x\", true, null], \"b\": 1, \"c\": \"café \\\"q\\\" \\\\ \\n\"}")
    }

    func testObjectFindsJSONInsideProseAndFences() {
        let text = "Sure!\n```json\n{\"a\": \"x}y\", \"b\": [1, 2]}\n```"
        XCTAssertEqual(PromptJSON.object(in: text)?["a"] as? String, "x}y")
        XCTAssertNil(PromptJSON.object(in: "{\"a\": \"cut off"))
    }

    func testTruncatedObjectKeepsFinishedFields() {
        let cut = #"{"title": "T", "camera_position": "on the dock", "steps": ["a, b", "c"], "body_pose": "standing, hand in poc"#
        let obj = PromptJSON.objectAllowingTruncation(in: cut)
        XCTAssertEqual(obj?["title"] as? String, "T")
        XCTAssertEqual(obj?["steps"] as? [String], ["a, b", "c"])
        XCTAssertNil(obj?["body_pose"], "the unfinished field is dropped, not guessed")
        XCTAssertNil(PromptJSON.objectAllowingTruncation(in: #"{"title": "cut off"#))
    }

    func testObjectsInArrayKeepsFinishedOnesWhenTruncated() {
        let text = "{\"compositions\": [{\"title\": \"One\"}, {\"title\": \"Two {braces}\"}, {\"title\": \"Thr"
        XCTAssertEqual(PromptJSON.objects(inArray: "compositions", in: text).compactMap { $0["title"] as? String },
                       ["One", "Two {braces}"])
    }
}

final class OfflineEngineTests: XCTestCase {
    /// Replies from a script, in order, and records the prompts and image sizes it saw.
    actor Script: OfflineTextGenerator {
        var replies: [String]
        private(set) var prompts: [String] = []
        private(set) var sides: [Int] = []
        private(set) var tokens: [Int] = []
        init(_ replies: [String]) { self.replies = replies }
        func generate(prompt: String, image: Data?, maxImageSide: Int, maxTokens: Int) async throws -> String {
            prompts.append(prompt); sides.append(maxImageSide); tokens.append(maxTokens)
            return replies.isEmpty ? "" : replies.removeFirst()
        }
    }

    static let scene = #"{"description": "a lake", "key_elements": ["dock"]}"#
    static func look(_ n: Int) -> String {
        #"{"title": "Look \#(n)", "camera_position": "on the dock", "camera_height": "chest", "camera_angle": "level", "subject_position": "left third", "distance_and_framing": "full body", "body_pose": "standing", "gaze": "away", "steps": ["step back"]}"#
    }

    private func collect(_ engine: OfflineEngine, _ request: DirectorRequest) async throws -> [DirectorEvent] {
        var events: [DirectorEvent] = []
        for try await e in engine.plan(request) { events.append(e) }
        return events
    }

    private func sceneRequest(profile: OfflineProfile = .standard) -> DirectorRequest {
        DirectorRequest(mode: .scene, style: .relaxedCandid, images: [DirectorImage(role: .target, jpeg: Data([1]))],
                        upload: .none, offlineProfile: profile)
    }

    func testSceneModeStreamsThreeShotsInOrder() async throws {
        let script = Script([Self.scene, Self.look(1), Self.look(2), Self.look(3)])
        let events = try await collect(OfflineEngine(generator: script), sceneRequest())
        let titles = events.compactMap { e -> String? in if case .shot(let s, .offline) = e { return s.title }; return nil }
        XCTAssertEqual(titles, ["Look 1", "Look 2", "Look 3"])
        XCTAssertEqual(events.last, .finished(.offline))
        XCTAssertEqual(events.first, .stage(.preparing, .offline))
        let prompts = await script.prompts
        XCTAssertTrue(prompts[1].contains("look 1 of 3"))
        XCTAssertTrue(prompts[3].contains("Earlier looks for this scene"))
        XCTAssertTrue(prompts[3].contains("Look 2: Look 2"), "later looks list the earlier ones")
    }

    func testReducedProfileShrinksImagesAndTokens() async throws {
        let script = Script([Self.scene, Self.look(1), Self.look(2), Self.look(3)])
        _ = try await collect(OfflineEngine(generator: script), sceneRequest(profile: .reduced))
        let sides = await script.sides, tokens = await script.tokens
        XCTAssertEqual(Set(sides), [768])
        XCTAssertEqual(tokens.dropFirst(), [750, 750, 750])
    }

    func testInvalidJSONRetriesOnceThenSucceeds() async throws {
        let script = Script(["not json at all", Self.scene, Self.look(1), Self.look(2), Self.look(3)])
        let events = try await collect(OfflineEngine(generator: script), sceneRequest())
        XCTAssertEqual(events.filter { if case .shot = $0 { return true }; return false }.count, 3)
        let prompts = await script.prompts
        XCTAssertTrue(prompts[1].hasSuffix(OfflinePromptData.retrySuffix))
    }

    func testInvalidTwiceFailsClearly() async {
        let script = Script(["nope", "still nope"])
        do { _ = try await collect(OfflineEngine(generator: script), sceneRequest()); XCTFail("expected an error") }
        catch let e as DirectorError { guard case .invalidOutput = e else { return XCTFail("\(e)") } }
        catch { XCTFail("\(error)") }
    }

    func testCutOffLookWithCoreFieldsStillBecomesAShot() async throws {
        let cutLook = #"{"title": "Cut", "camera_position": "dock", "camera_height": "chest", "camera_angle": "level", "subject_position": "left third", "body_pose": "standing, hand in poc"#
        let script = Script([Self.scene, cutLook, Self.look(2), Self.look(3)])
        let events = try await collect(OfflineEngine(generator: script), sceneRequest())
        let titles = events.compactMap { e -> String? in if case .shot(let s, _) = e { return s.title }; return nil }
        XCTAssertEqual(titles, ["Cut", "Look 2", "Look 3"])
    }

    func testIncompleteShotIsAnError() async {
        let script = Script([Self.scene, #"{"title": "Only a title"}"#])
        do { _ = try await collect(OfflineEngine(generator: script), sceneRequest()); XCTFail("expected an error") }
        catch let e as DirectorError { guard case .invalidOutput = e else { return XCTFail("\(e)") } }
        catch { XCTFail("\(error)") }
    }

    func testInspirationModeKeepsFinishedShotsFromACutOffAnswer() async throws {
        let notes = ["note 1", "note 2", "note 3"]
        let aesthetic = #"{"summary": "airy", "per_image": ["a", "b", "c"], "techniques": ["backlight"]}"#
        let cut = #"{"compositions": ["# + Self.look(1) + ", " + Self.look(2) + #", {"title": "Look 3", "camera_pos"#
        let script = Script(notes + [aesthetic, Self.scene, cut])
        let images = (0..<3).map { _ in DirectorImage(role: .inspiration, jpeg: Data([2])) } + [DirectorImage(role: .target, jpeg: Data([1]))]
        let request = DirectorRequest(mode: .inspiration, images: images, upload: .none)
        let events = try await collect(OfflineEngine(generator: script), request)
        let titles = events.compactMap { e -> String? in if case .shot(let s, _) = e { return s.title }; return nil }
        XCTAssertEqual(titles, ["Look 1", "Look 2"])
        let prompts = await script.prompts
        XCTAssertTrue(prompts[3].contains("Inspiration photo 3: note 3"))
        XCTAssertFalse(prompts.last!.contains("per_image"), "compositions prompt drops per_image")
    }

    func testCancellingTheConsumerCancelsTheModelCall() async {
        actor Slow: OfflineTextGenerator {
            private(set) var sawCancellation = false
            func generate(prompt: String, image: Data?, maxImageSide: Int, maxTokens: Int) async throws -> String {
                do { try await Task.sleep(nanoseconds: 10_000_000_000) } catch { sawCancellation = true; throw error }
                return ""
            }
        }
        let slow = Slow()
        let engine = OfflineEngine(generator: slow)
        let request = sceneRequest()
        let task = Task { for try await _ in engine.plan(request) {} }
        try? await Task.sleep(nanoseconds: 200_000_000)
        task.cancel()
        _ = try? await task.value
        try? await Task.sleep(nanoseconds: 200_000_000)
        let cancelled = await slow.sawCancellation
        XCTAssertTrue(cancelled)
    }
}
