import CoreImage
import DirectorKit
import Foundation
import MLX
import MLXLMCommon
import MLXVLM
import Tokenizers
import UIKit
import os

// MARK: - Tokenizer adapter (local files only; the same mapping the iPhone benchmark proved)

private struct TokenizerBridge: MLXLMCommon.Tokenizer {
    let upstream: any Tokenizers.Tokenizer

    func encode(text: String, addSpecialTokens: Bool) -> [Int] { upstream.encode(text: text, addSpecialTokens: addSpecialTokens) }
    func decode(tokenIds: [Int], skipSpecialTokens: Bool) -> String { upstream.decode(tokens: tokenIds, skipSpecialTokens: skipSpecialTokens) }
    func convertTokenToId(_ token: String) -> Int? { upstream.convertTokenToId(token) }
    func convertIdToToken(_ id: Int) -> String? { upstream.convertIdToToken(id) }
    var bosToken: String? { upstream.bosToken }
    var eosToken: String? { upstream.eosToken }
    var unknownToken: String? { upstream.unknownToken }

    func applyChatTemplate(messages: [[String: any Sendable]], tools: [[String: any Sendable]]?,
                           additionalContext: [String: any Sendable]?) throws -> [Int] {
        do {
            return try upstream.applyChatTemplate(messages: messages, tools: tools, additionalContext: additionalContext)
        } catch Tokenizers.TokenizerError.missingChatTemplate {
            throw MLXLMCommon.TokenizerError.missingChatTemplate
        }
    }
}

private struct LocalTokenizerLoader: TokenizerLoader {
    func load(from directory: URL) async throws -> any MLXLMCommon.Tokenizer {
        TokenizerBridge(upstream: try await AutoTokenizer.from(modelFolder: directory))
    }
}

/// Runs the base Qwen3-VL-2B 4-bit model on the phone for `OfflineEngine`.
///
/// The weights (1.78 GB) are not in the app. They live in `Documents/Qwen3-VL-2B-Instruct-4bit/`
/// (during development: `xcrun devicectl device copy to ... --domain-type appDataContainer`).
/// A later version will download them over Wi-Fi with a checksum into the same folder.
/// The model loads on first use and unloads on a memory warning or after two idle minutes.
actor OnDeviceGenerator: OfflineTextGenerator {
    static let shared = OnDeviceGenerator()
    static let folderName = "Qwen3-VL-2B-Instruct-4bit"
    private static let imageMarker = "<<image>>"
    private static let idleSeconds: UInt64 = 120

    private static let log = Logger(subsystem: "com.colin.digit.gift", category: "ondevice")
    private var container: ModelContainer?
    private var active = 0
    private var idleTask: Task<Void, Never>?
    private var warningObserver: NSObjectProtocol?

    static var modelDirectory: URL? {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?.appendingPathComponent(folderName)
    }

    /// True when the weights are in place (used by Settings to say whether the phone can answer).
    nonisolated static var isInstalled: Bool {
        guard let dir = modelDirectory else { return false }
        return FileManager.default.fileExists(atPath: dir.appendingPathComponent("config.json").path)
    }

    func generate(prompt: String, image: Data?, maxImageSide: Int, maxTokens: Int) async throws -> String {
        active += 1
        idleTask?.cancel()
        defer {
            active -= 1
            if active == 0 { scheduleIdleUnload() }
        }
        let container = try await loadedContainer()

        var content: [[String: any Sendable]] = []
        let pieces = prompt.components(separatedBy: Self.imageMarker)
        guard pieces.count - 1 == (image == nil ? 0 : 1) else {
            throw DirectorError.invalidOutput("The on-device prompt and photo do not match.")
        }
        for (i, text) in pieces.enumerated() {
            if !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { content.append(["type": "text", "text": text]) }
            if i < pieces.count - 1 { content.append(["type": "image"]) }
        }
        let messages: [MLXLMCommon.Message] = [["role": "user", "content": content]]

        var imageFile: URL?
        defer { if let imageFile { try? FileManager.default.removeItem(at: imageFile) } }
        var images: [UserInput.Image] = []
        if let image {
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("director-\(UUID().uuidString).jpg")
            try Self.resized(image, longEdge: maxImageSide).write(to: url)
            imageFile = url
            images = [UserInput.Image(source: .url(url))]
        }

        let lmInput = try await container.prepare(input: UserInput(messages: messages, images: images))
        let params = GenerateParameters(maxTokens: maxTokens, temperature: 0)  // greedy, like the benchmark
        let text: String = try await container.perform(nonSendable: lmInput) { context, input in
            let stream = try MLXLMCommon.generateTokens(input: input, parameters: params, context: context)
            var tokens: [Int] = []
            for await event in stream {
                if Task.isCancelled { break }
                if case .token(let t) = event { tokens.append(t) }
            }
            Self.log.info("generated \(tokens.count) tokens (cap \(maxTokens))")  // counts only; never the text
            return context.tokenizer.decode(tokenIds: tokens, skipSpecialTokens: true)
        }
        try Task.checkCancellation()
        return text
    }

    // MARK: loading

    private func loadedContainer() async throws -> ModelContainer {
        if let container { return container }
        guard let dir = Self.modelDirectory, Self.isInstalled else {
            throw DirectorError.offlineUnavailable(
                "The on-device model is not on this phone yet. Copy \(Self.folderName) into the app's Documents folder.")
        }
        let loaded: ModelContainer
        do {
            loaded = try await VLMModelFactory.shared.loadContainer(from: dir, using: LocalTokenizerLoader())
        } catch {
            throw DirectorError.offlineUnavailable("The on-device model could not be loaded: \(error.localizedDescription)")
        }
        container = loaded
        observeMemoryWarnings()
        return loaded
    }

    func unload() {
        guard active == 0 else { return }
        container = nil
        Memory.clearCache()
    }

    private func scheduleIdleUnload() {
        idleTask?.cancel()
        idleTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: Self.idleSeconds * 1_000_000_000)
            if !Task.isCancelled { await self?.unload() }
        }
    }

    private func observeMemoryWarnings() {
        guard warningObserver == nil else { return }
        warningObserver = NotificationCenter.default.addObserver(
            forName: UIApplication.didReceiveMemoryWarningNotification, object: nil, queue: nil
        ) { [weak self] _ in
            Task { await self?.unload() }
        }
    }

    /// Long edge `longEdge`, JPEG q0.92 (the phone model never sees more pixels than the profile allows).
    private static func resized(_ jpeg: Data, longEdge: Int) throws -> Data {
        guard let image = UIImage(data: jpeg) else { throw DirectorError.invalidRequest("One of the photos could not be read.") }
        let size = image.size
        let scale = min(1, CGFloat(longEdge) / max(size.width, size.height))
        if scale >= 1 { return jpeg }
        let target = CGSize(width: (size.width * scale).rounded(), height: (size.height * scale).rounded())
        let format = UIGraphicsImageRendererFormat(); format.scale = 1
        let out = UIGraphicsImageRenderer(size: target, format: format).image { _ in image.draw(in: CGRect(origin: .zero, size: target)) }
        guard let data = out.jpegData(compressionQuality: 0.92) else { throw DirectorError.invalidRequest("A photo could not be resized.") }
        return data
    }
}
