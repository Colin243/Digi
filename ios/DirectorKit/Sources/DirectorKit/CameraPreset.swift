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
        let light = [shot.lightingTip, shot.sceneReading, shot.setupChoice, shot.title].joined(separator: " ").lowercased()
        let lens = [shot.zoomOrLens, shot.distanceAndFraming].joined(separator: " ").lowercased()
        func has(_ words: [String], in text: String) -> Bool { words.contains { text.contains($0) } }

        // Light. The first rule that matches wins, strongest problem first.
        if has(["backlit", "backlight", "back-lit", "contre-jour", "light behind", "sun behind", "against the light", "rim light"], in: light) {
            p.exposureBias = 0.7; p.reasons.append(.backlit)
        } else if has(["low light", "low-light", "dim", "dark", "night", "dusk", "twilight", "indoor"], in: light) {
            p.exposureBias = 0.3; p.reasons.append(.dim)
        } else if has(["harsh", "midday", "noon", "bright sun", "direct sun", "high contrast", "high-contrast"], in: light) {
            p.exposureBias = -0.3; p.reasons.append(.harsh)
        } else if has(["golden hour", "golden-hour", "sunset", "sunrise", "warm light", "golden light"], in: light) {
            p.exposureBias = -0.3; p.reasons.append(.warm)
        }

        // Zoom: an explicit "1.5x" or "35mm" wins, then lens words.
        if let z = explicitZoom(lens, baseMM: baseFocalLengthMM) ?? wordZoom(lens) {
            let clamped = min(max((z * 10).rounded() / 10, 1), 2)
            p.zoom = clamped; p.reasons.append(.zoom(clamped))
        }

        // Flash only when the shot says so.
        if has(["no flash", "without flash", "flash off", "turn off the flash"], in: lens + " " + light) {
            p.flash = .off; p.reasons.append(.flashOff)
        } else if has(["fill flash", "use flash", "flash on", "use the flash"], in: lens + " " + light) {
            p.flash = .on; p.reasons.append(.flashOn)
        }
        return p
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
