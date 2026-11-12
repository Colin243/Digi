import Foundation

/// prompts.json, exported from photography-ai/src/photo_ai/prompts.py by scripts/prepare_assets.py.
struct PromptPack: Decodable {
    struct Stage: Decodable { let prompt: String; let maxTokens: Int }
    struct Sentinels: Decodable { let note: String; let styleJson: String; let targetJson: String }
    let promptVersion: String
    let jsonFormat: String
    let imageMarker: String
    let nInspiration: Int
    let sentinels: Sentinels
    let stages: [String: Stage]

    func stage(_ name: String) throws -> Stage {
        guard let s = stages[name] else { throw AssetError.missing("prompts.json has no stage \(name)") }
        return s
    }

    static func load(url: URL? = nil) throws -> PromptPack {
        guard let url = url ?? Bundle.main.url(forResource: "prompts", withExtension: "json") else {
            throw AssetError.missing("prompts.json is not in the app bundle")
        }
        let dec = JSONDecoder()
        dec.keyDecodingStrategy = .convertFromSnakeCase
        return try dec.decode(PromptPack.self, from: Data(contentsOf: url))
    }

    func aestheticPrompt(notes: [String]) throws -> String {
        var p = try stage("aesthetic_from_notes").prompt
        for (i, n) in notes.enumerated() {
            p = p.replacingOccurrences(of: sentinels.note.replacingOccurrences(of: "{i}", with: "\(i + 1)"), with: n)
        }
        return p
    }

    /// Mirrors prompts.compositions_from_parts(): the aesthetic without per_image, and the
    /// target JSON. Valid JSON is re-serialized compactly; invalid output is passed as-is so the
    /// timing run still completes (the record notes json_valid = false).
    func compositionsPrompt(aestheticRaw: String, targetRaw: String) throws -> String {
        var style = JSONText.object(in: aestheticRaw)
        style?.removeValue(forKey: "per_image")
        let styleText = style.flatMap(JSONText.compact) ?? aestheticRaw
        let targetText = JSONText.object(in: targetRaw).flatMap(JSONText.compact) ?? targetRaw
        return try stage("compositions").prompt
            .replacingOccurrences(of: sentinels.styleJson, with: styleText)
            .replacingOccurrences(of: sentinels.targetJson, with: targetText)
    }
}

enum JSONText {
    /// First balanced {...} in the text, parsed. Small models sometimes wrap JSON in prose or fences.
    static func object(in text: String) -> [String: Any]? {
        guard let start = text.firstIndex(of: "{"), let end = text.lastIndex(of: "}"), start < end else { return nil }
        let slice = String(text[start...end])
        return (try? JSONSerialization.jsonObject(with: Data(slice.utf8))) as? [String: Any]
    }

    static func compact(_ obj: [String: Any]) -> String? {
        guard let d = try? JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys, .withoutEscapingSlashes])
        else { return nil }
        return String(data: d, encoding: .utf8)
    }

    static func isValid(_ text: String) -> Bool { object(in: text) != nil }
}

/// BenchImages/manifest.json.
struct ImageManifest: Decodable {
    struct Variant: Decodable { let file: String; let size: [Int] }
    struct Entry: Decodable { let role: String; let index: Int; let files: [String: Variant] }
    let `case`: String
    let sizes: [Int]
    let images: [Entry]

    static func load(dir: URL? = nil) throws -> (ImageManifest, URL) {
        guard let dir = dir ?? Bundle.main.url(forResource: "BenchImages", withExtension: nil),
              let data = try? Data(contentsOf: dir.appendingPathComponent("manifest.json"))
        else {
            throw AssetError.missing("BenchImages/manifest.json missing. Run scripts/prepare_assets.py, then rebuild.")
        }
        return (try JSONDecoder().decode(ImageManifest.self, from: data), dir)
    }

    func variant(role: String, index: Int, size: Int) -> Variant? {
        images.first { $0.role == role && $0.index == index }?.files[String(size)]
    }

    var inspirationCount: Int { images.filter { $0.role == "inspiration" }.count }
}

enum AssetError: LocalizedError {
    case missing(String)
    var errorDescription: String? { if case .missing(let s) = self { return s }; return nil }
}
