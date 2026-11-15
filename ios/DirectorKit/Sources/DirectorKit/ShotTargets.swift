import Foundation

/// How much of the person a shot shows. Used to judge distance from the size of the face (or,
/// for full-body shots, the whole person) in the live frame.
public enum Framing: String, Sendable, CaseIterable {
    case closeUp, waistUp, threeQuarter, fullBody

    /// Face height as a fraction of the frame's height when the framing is right (portrait frame).
    public var faceHeightRange: ClosedRange<Double> {
        switch self {
        case .closeUp: return 0.26...0.55
        case .waistUp: return 0.12...0.24
        case .threeQuarter: return 0.08...0.15
        case .fullBody: return 0.035...0.10
        }
    }

    /// Person height as a fraction of the frame's height; only meaningful for full-body shots,
    /// where the whole person is in the frame.
    public static let fullBodyPersonRange: ClosedRange<Double> = 0.55...0.93
}

/// Where the subject should sit across the frame.
public enum HorizontalTarget: String, Sendable {
    case left, center, right
    /// Target centre of the subject, 0 = left edge, 1 = right edge.
    public var x: Double { self == .left ? 1.0 / 3 : self == .right ? 2.0 / 3 : 0.5 }
}

/// What the live guidance can actually measure about a shot, parsed from the shot's free text.
/// A nil field means the text did not say (or said something we cannot measure), and the
/// guidance then stays quiet about it rather than guessing.
public struct ShotTargets: Equatable, Sendable {
    /// Camera pitch in degrees: 0 = level, positive = pointing up.
    public var pitchDegrees: Double?
    public var pitchTolerance: Double
    public var framing: Framing?
    public var horizontal: HorizontalTarget?
    /// true = portrait, false = landscape.
    public var portrait: Bool?
    /// Head turn and chin height for the subject (checked only when live subject cues are on).
    public var head: HeadTargets

    public init(pitchDegrees: Double? = nil, pitchTolerance: Double = 4, framing: Framing? = nil,
                horizontal: HorizontalTarget? = nil, portrait: Bool? = nil, head: HeadTargets = HeadTargets()) {
        self.pitchDegrees = pitchDegrees; self.pitchTolerance = pitchTolerance
        self.framing = framing; self.horizontal = horizontal; self.portrait = portrait; self.head = head
    }

    public init(shot: Shot) {
        self.init()
        if let (pitch, tolerance) = Self.pitch(from: shot.cameraAngle) {
            pitchDegrees = pitch; pitchTolerance = tolerance
        }
        framing = Self.framing(from: shot.distanceAndFraming) ?? Self.framing(from: shot.subjectPosition)
        horizontal = Self.horizontal(from: shot.subjectPosition) ?? Self.horizontal(from: shot.distanceAndFraming)
        portrait = Self.orientation(from: shot.orientation)
        head = HeadTargets(headDirection: shot.headDirection, gaze: shot.gaze)
    }

    /// True when there is something about the subject to check, so the camera needs to see them.
    public var needsSubject: Bool { framing != nil || horizontal != nil }

    // MARK: parsing

    static func words(_ text: String) -> [String] {
        text.lowercased().split { !$0.isLetter && !$0.isNumber }.map(String.init)
    }

    static let upWords: Set<String> = ["up", "upward", "upwards", "skyward", "skywards"]
    static let downWords: Set<String> = ["down", "downward", "downwards"]

    /// "Tilt up about 10°" → (10, 4); "slightly tilted down" → (-6, 4); "Level" → (0, 3).
    static func pitch(from text: String) -> (Double, Double)? {
        let lower = text.lowercased()
        let w = words(text)
        guard !w.isEmpty else { return nil }
        if lower.contains("top-down") || lower.contains("top down") || lower.contains("overhead") || lower.contains("bird") {
            return (-60, 10)
        }
        // Direction: whichever of up/down appears first.
        let upAt = w.firstIndex { upWords.contains($0) }
        let downAt = w.firstIndex { downWords.contains($0) }
        let sign: Double?
        switch (upAt, downAt) {
        case let (u?, d?): sign = u < d ? 1 : -1
        case (_?, nil): sign = 1
        case (nil, _?): sign = -1
        default: sign = nil
        }
        if let sign {
            if let degrees = explicitDegrees(lower) { return (sign * min(degrees, 80), 4) }
            if w.contains(where: { ["slightly", "slight", "little", "bit", "gently", "gentle", "subtle", "subtly"].contains($0) }) {
                return (sign * 6, 4)
            }
            if w.contains(where: { ["steeply", "steep", "strongly", "sharply", "sharp", "dramatic", "dramatically"].contains($0) }) {
                return (sign * 25, 6)
            }
            return (sign * 12, 5)
        }
        if w.contains(where: { ["level", "straight", "horizontal", "parallel", "neutral", "flat"].contains($0) }) {
            return (0, 3)
        }
        return nil
    }

    /// The first number followed by °, "degree(s)" or "deg".
    static func explicitDegrees(_ lower: String) -> Double? {
        guard let re = try? NSRegularExpression(pattern: #"(\d+(?:\.\d+)?)\s*(?:°|º|degrees?|deg\b)"#) else { return nil }
        let range = NSRange(lower.startIndex..., in: lower)
        guard let m = re.firstMatch(in: lower, range: range), let r = Range(m.range(at: 1), in: lower) else { return nil }
        return Double(lower[r])
    }

    static func framing(from text: String) -> Framing? {
        let t = text.lowercased()
        let w = Set(words(text))
        func has(_ phrases: [String]) -> Bool { phrases.contains { t.contains($0) } }
        if has(["full body", "full-body", "head to toe", "head-to-toe", "whole body", "entire body", "whole seated body", "whole figure"])
            || w.contains("feet") { return .fullBody }
        if has(["three-quarter", "three quarter", "3/4", "knees up", "knee up", "from the knees", "thigh", "mid-thigh"]) { return .threeQuarter }
        if has(["waist up", "waist-up", "from the waist", "half body", "half-body", "half length", "upper body", "torso",
                "medium shot", "mid shot", "mid-shot", "hips up", "hip up"]) { return .waistUp }
        if has(["close-up", "close up", "closeup", "headshot", "head shot", "head and shoulders", "head-and-shoulders",
                "chest up", "chest-up", "shoulders up", "bust", "tight on the face", "face fills"]) { return .closeUp }
        return nil
    }

    /// "on the right side of the frame" → right; "facing left" alone says nothing about position.
    static func horizontal(from text: String) -> HorizontalTarget? {
        var t = text.lowercased()
        // Directions the subject faces, looks or leans are not positions in the frame.
        if let re = try? NSRegularExpression(pattern: #"(facing|faces|turned|turning|turns|looking|looks|gazing|glancing|angled|leaning|leans|pointing|points|toward|towards|walking|walks)\s+(?:to\s+)?(?:the\s+|her\s+|his\s+|their\s+)?(left|right)"#) {
            t = re.stringByReplacingMatches(in: t, range: NSRange(t.startIndex..., in: t), withTemplate: " ")
        }
        let sideTails = [" third", " side", " of the frame", " edge", " half", "-hand third", " two-thirds", " column", " of center", " of centre"]
        for side in ["left", "right"] {
            let found = sideTails.contains { t.contains(side + $0) } || t.contains("on the \(side)") || t.contains("to the \(side) of the frame")
            if found {
                // "with the blossoms filling the right two-thirds" puts the subject on the other side.
                if t.contains("\(side) two-thirds") && (t.contains("filling") || t.contains("fill")) {
                    return side == "left" ? .right : .left
                }
                return side == "left" ? .left : .right
            }
        }
        if ["centered", "centred", "center of the frame", "centre of the frame", "middle of the frame", "in the center",
            "in the centre", "center column", "centre column", "center third", "centre third", "dead center", "centre of frame",
            "center of frame", "in the middle"].contains(where: { t.contains($0) }) { return .center }
        return nil
    }

    static func orientation(from text: String) -> Bool? {
        let w = Set(words(text))
        if w.contains("portrait") || w.contains("vertical") { return true }
        if w.contains("landscape") || w.contains("horizontal") { return false }
        return nil
    }
}
