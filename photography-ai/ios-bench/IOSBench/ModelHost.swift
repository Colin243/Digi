import CoreImage
import Foundation
import MLX
import MLXLMCommon
import MLXVLM
import Tokenizers

// MARK: - Tokenizer adapter (local files only; same mapping as MLXHuggingFace's macro)

struct TokenizerBridge: MLXLMCommon.Tokenizer {
    let upstream: any Tokenizers.Tokenizer

    func encode(text: String, addSpecialTokens: Bool) -> [Int] {
        upstream.encode(text: text, addSpecialTokens: addSpecialTokens)
    }
    func decode(tokenIds: [Int], skipSpecialTokens: Bool) -> String {
        upstream.decode(tokens: tokenIds, skipSpecialTokens: skipSpecialTokens)
    }
    func convertTokenToId(_ token: String) -> Int? { upstream.convertTokenToId(token) }
    func convertIdToToken(_ id: Int) -> String? { upstream.convertIdToToken(id) }
    var bosToken: String? { upstream.bosToken }
    var eosToken: String? { upstream.eosToken }
    var unknownToken: String? { upstream.unknownToken }

    func applyChatTemplate(
        messages: [[String: any Sendable]], tools: [[String: any Sendable]]?,
        additionalContext: [String: any Sendable]?
    ) throws -> [Int] {
        do {
            return try upstream.applyChatTemplate(
                messages: messages, tools: tools, additionalContext: additionalContext)
        } catch Tokenizers.TokenizerError.missingChatTemplate {
            throw MLXLMCommon.TokenizerError.missingChatTemplate
        }
    }
}

struct LocalTokenizerLoader: TokenizerLoader {
    func load(from directory: URL) async throws -> any MLXLMCommon.Tokenizer {
        TokenizerBridge(upstream: try await AutoTokenizer.from(modelFolder: directory))
    }
}

// MARK: - Model location

enum ModelLocator {
    static let repoId = "mlx-community/Qwen3-VL-2B-Instruct-4bit"
    static let folderName = "Qwen3-VL-2B-Instruct-4bit"

    /// Documents/<folderName> (copied with devicectl or Finder) wins over the copy inside the app.
    static func find() -> (url: URL, location: String)? {
        let fm = FileManager.default
        if let docs = fm.urls(for: .documentDirectory, in: .userDomainMask).first {
            let d = docs.appendingPathComponent(folderName)
            if fm.fileExists(atPath: d.appendingPathComponent("config.json").path) { return (d, "documents") }
        }
        if let b = Bundle.main.url(forResource: "Model", withExtension: nil),
           fm.fileExists(atPath: b.appendingPathComponent("config.json").path) {
            return (b, "bundle")
        }
        return nil
    }

    static func info(at url: URL, location: String) -> ModelInfo {
        var revision: String?, sha: String?
        if let data = try? Data(contentsOf: url.appendingPathComponent("REVISION.json")),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            revision = obj["revision"] as? String
            sha = obj["config_sha256"] as? String
        }
        var bytes: UInt64 = 0
        if let files = try? FileManager.default.contentsOfDirectory(at: url, includingPropertiesForKeys: [.fileSizeKey]) {
            for f in files where f.pathExtension == "safetensors" {
                bytes += UInt64((try? f.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0)
            }
        }
        return ModelInfo(repoId: repoId, revision: revision, configSha256: sha, weightsBytes: bytes,
                         location: location, path: url.lastPathComponent)
    }
}

// MARK: - Inference

struct Generated: Sendable {
    let text: String
    let firstToken: Double?
    let info: GenerateCompletionInfo?
}

struct CallResult {
    var text: String
    var promptTokens: Int
    var generatedTokens: Int
    var stopReason: String
    var prepare: Double
    var prefill: Double
    var ttft: Double  // request start -> first generated token
    var decode: Double
    var e2e: Double
    var promptTPS: Double
    var genTPS: Double
}

enum HostError: LocalizedError {
    case badPrompt(String)
    var errorDescription: String? {
        switch self { case .badPrompt(let s): "prompt error: \(s)" }
    }
}

final class ModelHost {
    private(set) var container: ModelContainer?

    var isLoaded: Bool { container != nil }

    func load(from url: URL) async throws {
        container = try await VLMModelFactory.shared.loadContainer(from: url, using: LocalTokenizerLoader())
    }

    /// Drops the model and returns MLX's buffer cache to the OS.
    func unload() {
        container = nil
        Memory.clearCache()
    }

    /// One generation. `template` uses `marker` where the image goes, exactly like the Mac
    /// backend's build_messages(): text before the marker, the image, text after.
    func run(template: String, marker: String, image: URL?, maxTokens: Int) async throws -> CallResult {
        guard let container else { throw HostError.badPrompt("model not loaded") }
        let t0 = now()

        var content: [[String: any Sendable]] = []
        let pieces = template.components(separatedBy: marker)
        let nImages = image == nil ? 0 : 1
        guard pieces.count - 1 == nImages else {
            throw HostError.badPrompt("\(pieces.count - 1) image markers but \(nImages) images")
        }
        for (i, text) in pieces.enumerated() {
            if !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                content.append(["type": "text", "text": text])
            }
            if i < nImages { content.append(["type": "image"]) }
        }
        let messages: [MLXLMCommon.Message] = [["role": "user", "content": content]]
        let images = image.map { [UserInput.Image(source: .url($0))] } ?? []
        let input = UserInput(messages: messages, images: images)

        let lmInput = try await container.prepare(input: input)
        let tPrepared = now()

        // Greedy, like the Mac benchmark (temperature 0, no repetition penalty).
        // Raw token stream: the text stream (generate -> Generation) holds back JSON-looking
        // output while it checks for tool calls, which hides the real time to first token.
        let params = GenerateParameters(maxTokens: maxTokens, temperature: 0)
        let gen = try await container.perform(nonSendable: lmInput) { context, input in
            let stream = try MLXLMCommon.generateTokens(input: input, parameters: params, context: context)
            var tokens: [Int] = []
            var first: Double?
            var info: GenerateCompletionInfo?
            for await g in stream {
                switch g {
                case .token(let t):
                    if first == nil { first = now() }
                    tokens.append(t)
                case .info(let i):
                    info = i
                }
            }
            let text = context.tokenizer.decode(tokenIds: tokens, skipSpecialTokens: true)
            return Generated(text: text, firstToken: first, info: info)
        }
        let text = gen.text, first = gen.firstToken, info = gen.info
        let tEnd = now()
        let stop: String
        switch info?.stopReason {
        case .stop: stop = "stop"
        case .length: stop = "length"
        case .cancelled: stop = "cancelled"
        case nil: stop = "unknown"
        }
        return CallResult(
            text: text,
            promptTokens: info?.promptTokenCount ?? 0,
            generatedTokens: info?.generationTokenCount ?? 0,
            stopReason: stop,
            prepare: tPrepared - t0,
            prefill: info?.promptTime ?? 0,
            ttft: (first ?? tEnd) - t0,
            decode: info?.generateTime ?? 0,
            e2e: tEnd - t0,
            promptTPS: info?.promptTokensPerSecond ?? 0,
            genTPS: info?.tokensPerSecond ?? 0)
    }
}
