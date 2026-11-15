import Foundation

/// Camera settings worth applying for a pinned shot, picked by plain rules from the shot's text (light,
/// lens) so no model is needed. Every field is optional: nil means "leave the camera as it is".
/// Later a trained model may fill the same struct; the rules stay as the baseline to beat.
public struct CameraPreset: Equatable, Sendable {
    public enum Flash: String, Sendable { case off, auto, on }

    /// Zoom multiplier, 1...2 (the app's range).
    public var zoom: Double?
    /// Exposure bias in stops (EV), small and safe: within -0.7...+0.7.
    public var exposureBias: Double?
    public var flash: Flash?
    public var reasons: [Reason] = []

    public var isEmpty: Bool { zoom == nil && exposureBias == nil && flash == nil }

    /// Why a setting changed, in words the user will recognise.
    public enum Reason: Equatable, Sendable {
        case backlit, dim, harsh, warm
        case zoom(Double)
        case flashOn, flashOff
    }

    public init() {}

    /// The rules. Light comes from the lighting tip and scene reading, zoom from the lens and framing text.
    public static func make(for shot: Shot, baseFocalLengthMM: Double = 24) -> CameraPreset {
        var p = CameraPreset()
        // Light comes from the lighting tip. The title is only checked for backlight ("Sun behind the subject").
        // Phrases like "no harsh shadows" are removed first, so a warning against a problem is not read as the problem.
        let tip = Self.withoutNegations(shot.lightingTip.lowercased())
        let lens = [shot.zoomOrLens, shot.distanceAndFraming].joined(separator: " ").lowercased()
        func has(_ patterns: [String], in text: String) -> Bool {
            patterns.contains { text.range(of: $0, options: .regularExpression) != nil }
        }

        // Light. The first rule that matches wins, strongest problem first.
        let backlit = [#"\bback-?lit\b"#, #"\bbacklight"#, #"contre-?jour"#, #"\b(light|sun|sunlight) (is |from |comes from |low )?behind\b"#,
                       #"against the light"#, #"\brim light"#, #"sun is behind"#]
        if has(backlit, in: tip) || has([#"sun behind"#, #"backlit"#, #"light behind"#], in: shot.title.lowercased()) {
            p.exposureBias = 0.7; p.reasons.append(.backlit)
        } else if has([#"\blow[- ]light\b"#, #"\bdimly\b"#, #"\bdim (light|room|interior)"#, #"\bdusk\b"#, #"\btwilight\b"#,
                       #"\bnight\b"#, #"\bindoors?\b"#, #"face[^.]{0,30}\b(dark|shadow(ed)?)\b"#, #"\bdark\b[^.]{0,20}\bface"#], in: tip) {
            p.exposureBias = 0.3; p.reasons.append(.dim)
        } else if has([#"\bharsh\b"#, #"\bmidday\b"#, #"\bnoon\b"#, #"\b(bright|direct|strong) sun"#, #"\bhigh[- ]contrast\b"#], in: tip) {
            p.exposureBias = -0.3; p.reasons.append(.harsh)
        } else if has([#"\bgolden[- ]hour\b"#, #"\bsunset\b"#, #"\bsunrise\b"#, #"\bwarm,? (low|golden)"#, #"low[- ]angle (light|sun)"#, #"\bgolden light\b"#], in: tip) {
            p.exposureBias = -0.3; p.reasons.append(.warm)
        }

        // Zoom: an explicit "1.5x" or "35mm" wins, then lens words.
        if let z = explicitZoom(lens, baseMM: baseFocalLengthMM) ?? wordZoom(lens) {
            let clamped = min(max((z * 10).rounded() / 10, 1), 2)
            p.zoom = clamped; p.reasons.append(.zoom(clamped))
        }

        // Flash only when the shot says so.
        let flashText = lens + " " + shot.lightingTip.lowercased()
        if has([#"no flash"#, #"without flash"#, #"flash off"#, #"turn off the flash"#], in: flashText) {
            p.flash = .off; p.reasons.append(.flashOff)
        } else if has([#"fill flash"#, #"use (the )?flash"#, #"flash on"#], in: flashText) {
            p.flash = .on; p.reasons.append(.flashOn)
        }
        return p
    }

    /// Drops "no harsh", "without dark", "avoid glare" and similar, so a warning is not read as a problem.
    static func withoutNegations(_ s: String) -> String {
        s.replacingOccurrences(of: #"\b(no|without|not|avoid|avoiding|never|free of)\s+(\w+\s+)?(harsh|dark|dim|glare|backlight\w*|shadows?)\b"#,
                               with: " ", options: .regularExpression)
    }

    private static func explicitZoom(_ s: String, baseMM: Double) -> Double? {
        if let m = s.range(of: #"(\d+(?:\.\d+)?)\s*[x×]"#, options: .regularExpression),
           let v = Double(s[m].filter { $0.isNumber || $0 == "." }), v > 0 { return v }
        if let m = s.range(of: #"(\d+(?:\.\d+)?)\s*mm"#, options: .regularExpression),
           let v = Double(s[m].filter { $0.isNumber || $0 == "." }), v > 0 { return v / baseMM }
        return nil
    }

    private static func wordZoom(_ s: String) -> Double? {
        if ["telephoto", "portrait lens", "compress", "tight crop"].contains(where: s.contains) { return 2 }
        if ["ultra-wide", "ultrawide", "wide angle", "wide-angle", "main lens", "standard lens"].contains(where: s.contains) { return 1 }
        return nil
    }
}

public extension GuidanceWording {
    /// One short line for the "Set for you" chip.
    static func text(_ r: CameraPreset.Reason, style: GuidanceStyle, language: GuidanceLanguage = .current) -> String {
        func z(_ v: Double) -> String { v.truncatingRemainder(dividingBy: 1) == 0 ? String(format: "%.0f×", v) : String(format: "%.1f×", v) }
        switch (language, style) {
        case (.en, .minimal):
            switch r {
            case .backlit, .dim: return "brighter"
            case .harsh, .warm: return "darker"
            case .zoom(let v): return "zoom \(z(v))"
            case .flashOn: return "flash on"
            case .flashOff: return "flash off"
            }
        case (.en, _):
            switch r {
            case .backlit: return "Brighter, so the backlight doesn't darken them"
            case .dim: return "Brighter for the low light"
            case .harsh: return "Slightly darker for the strong sun"
            case .warm: return "Slightly darker to keep the warm glow"
            case .zoom(let v): return "Zoom set to \(z(v))"
            case .flashOn: return "Flash on for fill light"
            case .flashOff: return "Flash off"
            }
        case (.zh, .minimal):
            switch r {
            case .backlit, .dim: return "调亮"
            case .harsh, .warm: return "调暗"
            case .zoom(let v): return "变焦 \(z(v))"
            case .flashOn: return "开闪光灯"
            case .flashOff: return "关闪光灯"
            }
        case (.zh, _):
            switch r {
            case .backlit: return "已调亮一点，避免逆光让人物发暗"
            case .dim: return "光线较暗，已调亮一点"
            case .harsh: return "阳光较强，已稍微调暗"
            case .warm: return "已稍微调暗，保留暖暖的光感"
            case .zoom(let v): return "已把变焦设为 \(z(v))"
            case .flashOn: return "已开闪光灯补光"
            case .flashOff: return "已关闭闪光灯"
            }
        }
    }
}
