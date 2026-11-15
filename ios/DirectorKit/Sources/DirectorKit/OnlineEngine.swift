import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// The network seam. `OnlineEngine` only needs the response head and the body as text lines,
/// so tests substitute a fake and never touch a socket.
public protocol StreamingHTTPClient: Sendable {
    /// Sends the request and returns as soon as the response head arrives. The stream yields the
    /// body line by line. Terminating the stream early (or cancelling the caller) must cancel the request.
    func send(_ request: URLRequest) async throws -> (HTTPURLResponse, AsyncThrowingStream<String, Error>)
}

/// Default transport: `URLSession.bytes(for:)` and `.lines`.
public struct URLSessionStreamingClient: StreamingHTTPClient {
    private let session: URLSession
    public init(session: URLSession = .shared) { self.session = session }

    public func send(_ request: URLRequest) async throws -> (HTTPURLResponse, AsyncThrowingStream<String, Error>) {
        let (bytes, response) = try await session.bytes(for: request)
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        let lines = AsyncThrowingStream<String, Error> { continuation in
            let task = Task {
                do {
                    for try await line in bytes.lines { continuation.yield(line) }
                    continuation.finish()
                } catch { continuation.finish(throwing: error) }
            }
            continuation.onTermination = { _ in task.cancel() }  // cancels the underlying request
        }
        return (http, lines)
    }
}

/// The online half of the hybrid Photography Director: POSTs the photos to `<baseURL>/v1/plan`
/// (`photo-ai server`) and turns its NDJSON stream into `DirectorEvent`s.
///
/// `apiKey` is a client key issued by `photo-ai server keygen`. The app keeps it in the Keychain
/// and passes it in; this package never stores, logs or hardcodes a key or a server address.
///
/// Shots are emitted as the server sends them, including any that fail `Shot.isActionable`;
/// the server already validates shots before streaming them.
public final class OnlineEngine: DirectorEngine {
    public struct Configuration: Sendable {
        public var baseURL: URL
        public var apiKey: String
        /// Per-request timeout. For a streaming response URLSession treats it as an idle timeout.
        public var timeout: TimeInterval
        public init(baseURL: URL, apiKey: String, timeout: TimeInterval = 30) {
            self.baseURL = baseURL; self.apiKey = apiKey; self.timeout = timeout
        }
    }

    public let kind: EngineKind = .online
    private let config: Configuration
    private let client: any StreamingHTTPClient

    public init(configuration: Configuration, client: any StreamingHTTPClient = URLSessionStreamingClient()) {
        self.config = configuration; self.client = client
    }

    // MARK: Request

    /// Builds the request, or throws without any network use. Only `.photos` is served today.
    func makeRequest(_ request: DirectorRequest) throws -> URLRequest {
        switch request.upload {
        case .photos: break
        case .sceneTextOnly: throw DirectorError.onlineUnavailable("Text-only requests are not supported by the server yet.")
        case .none: throw DirectorError.onlineUnavailable("Online use is switched off.")
        }
        var body = MultipartBody()
        body.addField("mode", request.mode.rawValue)
        if let style = request.style { body.addField("style", style.rawValue) }
        body.addField("brief", request.brief ?? "")
        body.addField("shot_count", String(request.shotCount))
        body.addField("upload", UploadMode.photos.rawValue)
        var n = 0
        for image in request.images {
            switch image.role {
            case .target: body.addFile("target", filename: "target.jpg", data: image.jpeg)
            case .inspiration:
                n += 1
                body.addFile("inspiration", filename: "inspiration_\(n).jpg", data: image.jpeg)
            }
        }
        var url = URLRequest(url: config.baseURL.appendingPathComponent("v1/plan"), timeoutInterval: config.timeout)
        url.httpMethod = "POST"
        url.setValue("Bearer \(config.apiKey)", forHTTPHeaderField: "Authorization")
        url.setValue(body.contentType, forHTTPHeaderField: "Content-Type")
        url.setValue("application/x-ndjson", forHTTPHeaderField: "Accept")
        url.httpBody = body.data
        return url
    }

    // MARK: Stream

    public func plan(_ request: DirectorRequest) -> AsyncThrowingStream<DirectorEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let urlRequest = try makeRequest(request)
                    try await run(urlRequest, into: continuation)
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: Self.normalize(error))
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    private func run(_ urlRequest: URLRequest, into continuation: AsyncThrowingStream<DirectorEvent, Error>.Continuation) async throws {
        let (response, lines) = try await client.send(urlRequest)
        guard response.statusCode == 200 else {
            var text = ""
            for try await line in lines { text += line; if text.count > 4096 { break } }
            throw DirectorError.onlineUnavailable(Self.errorMessage(text, status: response.statusCode))
        }
        let decoder = JSONDecoder()
        var finished = false
        for try await raw in lines {
            try Task.checkCancellation()
            let line = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            if line.isEmpty { continue }
            guard let event = try? decoder.decode(WireEvent.self, from: Data(line.utf8)) else {
                throw DirectorError.onlineUnavailable("The server sent an unreadable line.")
            }
            switch event.type {
            case "stage":
                if let s = event.stage.flatMap(DirectorStage.init(rawValue:)) { continuation.yield(.stage(s, .online)) }
            case "shot":
                guard let shot = event.shot else { throw DirectorError.onlineUnavailable("The server sent an empty shot.") }
                continuation.yield(.shot(shot, .online))
            case "finished":
                finished = true
                continuation.yield(.finished(.online))
            case "error":
                throw DirectorError.onlineUnavailable(event.message ?? "The server reported an error.")
            default: continue  // unknown event types are ignored so the server can add new ones
            }
            if finished { return }
        }
        throw DirectorError.onlineUnavailable("The connection ended before the server finished.")
    }

    private struct WireEvent: Decodable {
        let type: String
        let stage: String?
        let shot: Shot?
        let message: String?
    }

    static func errorMessage(_ body: String, status: Int) -> String {
        struct E: Decodable { let error: String }
        if let data = body.data(using: .utf8), let e = try? JSONDecoder().decode(E.self, from: data) { return e.error }
        return "The server answered HTTP \(status)."
    }

    /// Cancellation stays a cancellation; everything else becomes `onlineUnavailable` so the router falls back.
    static func normalize(_ error: Error) -> Error {
        if error is CancellationError || Task.isCancelled { return CancellationError() }
        if let e = error as? URLError, e.code == .cancelled { return CancellationError() }
        if error is DirectorError { return error }
        return DirectorError.onlineUnavailable(error.localizedDescription)
    }
}
