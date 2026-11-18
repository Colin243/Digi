import Foundation

/// JSON helpers for the on-device engine. Small models wrap JSON in prose or fences, and a token
/// cap can cut an answer off mid-object, so this finds objects instead of trusting the whole text.
enum PromptJSON {
    /// The first balanced `{...}` in the text, parsed.
    static func object(in text: String) -> [String: Any]? {
        guard let start = text.firstIndex(of: "{"), let range = balanced(in: text, from: start) else { return nil }
        return (try? JSONSerialization.jsonObject(with: Data(text[range].utf8))) as? [String: Any]
    }

    /// Like `object(in:)`, but if the object never closes (a token cap cut it off) keeps every top-level
    /// field that finished and closes the object. Nil when not even one field finished.
    static func objectAllowingTruncation(in text: String) -> [String: Any]? {
        if let whole = object(in: text) { return whole }
        guard let start = text.firstIndex(of: "{") else { return nil }
        var depth = 0, inString = false, escaped = false
        var lastComma: String.Index?
        var i = start
        while i < text.endIndex {
            let c = text[i]
            if inString {
                if escaped { escaped = false } else if c == "\\" { escaped = true } else if c == "\"" { inString = false }
            } else if c == "\"" { inString = true }
            else if c == "{" || c == "[" { depth += 1 }
            else if c == "}" || c == "]" { depth -= 1 }
            else if c == "," && depth == 1 { lastComma = i }
            i = text.index(after: i)
        }
        guard let cut = lastComma else { return nil }
        let repaired = String(text[start..<cut]) + "}"
        return (try? JSONSerialization.jsonObject(with: Data(repaired.utf8))) as? [String: Any]
    }

    /// Every complete object in the array under `key`, in order. A final object cut off by a token
    /// cap is dropped, so a truncated answer still yields its finished shots.
    static func objects(inArray key: String, in text: String) -> [[String: Any]] {
        guard let keyRange = text.range(of: "\"\(key)\""),
              let open = text[keyRange.upperBound...].firstIndex(of: "[") else { return [] }
        var out: [[String: Any]] = []
        var cursor = text.index(after: open)
        while let brace = text[cursor...].firstIndex(where: { $0 == "{" || $0 == "]" }), text[brace] == "{" {
            guard let range = balanced(in: text, from: brace) else { break }
            if let obj = (try? JSONSerialization.jsonObject(with: Data(text[range].utf8))) as? [String: Any] { out.append(obj) }
            cursor = range.upperBound
        }
        return out
    }

    /// Range of the `{...}` that starts at `start`, honoring strings and escapes. Nil if it never closes.
    private static func balanced(in text: String, from start: String.Index) -> Range<String.Index>? {
        var depth = 0, inString = false, escaped = false
        var i = start
        while i < text.endIndex {
            let c = text[i]
            if inString {
                if escaped { escaped = false } else if c == "\\" { escaped = true } else if c == "\"" { inString = false }
            } else if c == "\"" { inString = true }
            else if c == "{" { depth += 1 }
            else if c == "}" { depth -= 1; if depth == 0 { return start..<text.index(after: i) } }
            i = text.index(after: i)
        }
        return nil
    }

    /// Same text as Python `json.dumps(obj, sort_keys=True, separators=(", ", ": "), ensure_ascii=False)`.
    static func dumps(_ value: Any) -> String {
        switch value {
        case let dict as [String: Any]:
            return "{" + dict.keys.sorted().map { quote($0) + ": " + dumps(dict[$0]!) }.joined(separator: ", ") + "}"
        case let list as [Any]:
            return "[" + list.map(dumps).joined(separator: ", ") + "]"
        case let s as String: return quote(s)
        case is NSNull: return "null"
        case let n as NSNumber:
            if CFGetTypeID(n) == CFBooleanGetTypeID() { return n.boolValue ? "true" : "false" }
            return n.stringValue
        default: return quote("\(value)")
        }
    }

    private static func quote(_ s: String) -> String {
        var out = "\""
        for u in s.unicodeScalars {
            switch u {
            case "\"": out += "\\\""
            case "\\": out += "\\\\"
            case "\n": out += "\\n"
            case "\r": out += "\\r"
            case "\t": out += "\\t"
            case "\u{08}": out += "\\b"
            case "\u{0C}": out += "\\f"
            default:
                if u.value < 0x20 { out += String(format: "\\u%04x", u.value) } else { out.unicodeScalars.append(u) }
            }
        }
        return out + "\""
    }
}

/// Builds the exact prompts photography-ai sends, from the generated templates in
/// `OfflinePromptData`. `offline_prompt_golden.json` checks byte parity with Python.
enum OfflinePrompts {
    static func styleText(style: DirectorStyle?, brief: String?) -> String {
        var parts: [String] = []
        if let s = style, let b = OfflinePromptData.styleBriefs[s.rawValue] {
            parts.append("Style: \(b.zh) (\(b.en)). \(b.brief)")
        }
        let extra = (brief ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !extra.isEmpty { parts.append("The photographer adds: \(extra)") }
        return parts.isEmpty ? OfflinePromptData.styleDefault : parts.joined(separator: "\n")
    }

    /// One look (1...3). Earlier looks are listed so this one differs from them.
    static func sceneLook(scene: [String: Any], style: DirectorStyle?, brief: String?, look: Int,
                          previous: [Shot]) -> String {
        let templates = OfflinePromptData.sceneLooks
        var avoid = ""
        if !previous.isEmpty {
            let lines = previous.enumerated().map { i, p in
                "- Look \(i + 1): \(p.title): camera \(p.cameraPosition); \(p.distanceAndFraming); pose \(p.bodyPose); gaze \(p.gaze)"
            }
            avoid = OfflinePromptData.avoidIntro + "\n" + lines.joined(separator: "\n") + OfflinePromptData.avoidOutro
        }
        return templates[min(max(look, 1), templates.count) - 1]
            .replacingOccurrences(of: "__SCENE_JSON__", with: PromptJSON.dumps(scene))
            .replacingOccurrences(of: "__STYLE_TEXT__", with: styleText(style: style, brief: brief))
            .replacingOccurrences(of: "__AVOID__", with: avoid)
    }

    /// One scenery look (1...3). Earlier looks are listed so this one differs from them.
    static func sceneryLook(scene: [String: Any], brief: String?, look: Int, previous: [Shot]) -> String {
        let templates = OfflinePromptData.sceneryLooks
        var avoid = ""
        if !previous.isEmpty {
            let lines = previous.enumerated().map { i, p in
                "- Look \(i + 1): \(p.title): camera \(p.cameraPosition); \(p.distanceAndFraming); \(p.subjectPosition)"
            }
            avoid = OfflinePromptData.sceneryAvoidIntro + "\n" + lines.joined(separator: "\n") + OfflinePromptData.sceneryAvoidOutro
        }
        let note = (brief ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let noteText = note.isEmpty ? "" : "The photographer adds: \(note)\n\n"
        return templates[min(max(look, 1), templates.count) - 1]
            .replacingOccurrences(of: "__SCENE_JSON__", with: PromptJSON.dumps(scene))
            .replacingOccurrences(of: "__AVOID__", with: noteText + avoid)
    }

    static func aesthetic(notes: [String]) -> String {
        let listed = notes.enumerated().map { "Inspiration photo \($0.offset + 1): \($0.element)" }.joined(separator: "\n")
        return OfflinePromptData.aesthetic.replacingOccurrences(of: "__NOTES__", with: listed)
    }

    /// prompts.photographer_asks(): the photographer's own note, appended only when there is one.
    static func photographerAsks(_ prompt: String, brief: String?) -> String {
        let note = (brief ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return note.isEmpty ? prompt : "\(prompt)\n\nThe photographer also asks: \(note)"
    }

    /// The aesthetic without `per_image`, plus the target scene (prompts.compositions_from_parts, shot-v3).
    static func compositions(aesthetic: [String: Any], target: [String: Any]) -> String {
        var style = aesthetic
        style.removeValue(forKey: "per_image")
        return OfflinePromptData.compositions
            .replacingOccurrences(of: "__STYLE_JSON__", with: PromptJSON.dumps(style))
            .replacingOccurrences(of: "__TARGET_JSON__", with: PromptJSON.dumps(target))
    }
}
