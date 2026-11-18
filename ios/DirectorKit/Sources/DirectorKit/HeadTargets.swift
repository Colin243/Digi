import Foundation

/// The subject's head pose as Vision reports it for one face, in degrees.
///
/// Both angles are relative to the camera's line of sight, not to the room: a level head seen
/// from below reads chin-up (about +15° in phone tests). That is deliberate (decided 2026-11-14):
/// it is how the head looks in the photo, it needs no calibration, and correcting for camera
/// height overshot because Vision's pitch is compressed. A per-subject "set level" calibration
/// is the planned route if room-level chin targets are ever needed.
public struct FacePose: Equatable, Sendable {
    /// + = face turned toward the right of the frame (the subject's own left).
    public var yawDegrees: Double
    /// + = chin up, as the camera sees it. nil when the detector did not report it.
    public var pitchDegrees: Double?
    /// The detector's own yaw, kept only to compare against in the debug readout.
    public var detectorYawDegrees: Double?
    public init(yawDegrees: Double, pitchDegrees: Double?, detectorYawDegrees: Double? = nil) {
        self.yawDegrees = yawDegrees; self.pitchDegrees = pitchDegrees; self.detectorYawDegrees = detectorYawDegrees
    }
}

/// What the shot asks of the subject's head, parsed from `headDirection` (and `gaze` for chin
/// height). Directions without "her/his/their" are read as directions in the frame, the way the
/// rest of the shot is written for the photographer; "her left" is the subject's own left.
public struct HeadTargets: Equatable, Sendable {
    /// Head turn in degrees, + = toward the frame's right. With `yawEitherSide` only the size counts.
    public var yaw: Double?
    public var yawEitherSide: Bool
    public var yawTolerance: Double
    /// Chin height in degrees, + = up.
    public var pitch: Double?
    public var pitchTolerance: Double

    public init(yaw: Double? = nil, yawEitherSide: Bool = false, yawTolerance: Double = 12,
                pitch: Double? = nil, pitchTolerance: Double = 8) {
        self.yaw = yaw; self.yawEitherSide = yawEitherSide; self.yawTolerance = yawTolerance
        self.pitch = pitch; self.pitchTolerance = pitchTolerance
    }

    public var isEmpty: Bool { yaw == nil && pitch == nil }

    public init(headDirection: String, gaze: String) {
        self.init()
        if let (amount, tolerance, side) = Self.turn(headDirection) ?? Self.facingOnly(gaze) {
            yaw = side.map { amount * $0 } ?? amount
            yawEitherSide = side == nil && amount != 0
            yawTolerance = tolerance
        }
        if let p = Self.chin(headDirection) ?? Self.chin(gaze) { pitch = p.0; pitchTolerance = p.1 }
    }

    static let facingPhrases = ["facing the camera", "toward the camera", "towards the camera", "to the camera", "at the camera",
                                "into the camera", "into the lens", "at the lens", "toward the lens", "towards the lens", "the lens",
                                "square to the camera", "straight on", "face-on", "facing forward", "facing the viewer", "at the viewer"]
    static let slightWords: Set<String> = ["slightly", "slight", "little", "bit", "subtle", "subtly", "gently", "softly"]

    /// (degrees of turn, tolerance, side: +1 frame right / -1 frame left / nil unknown)
    static func turn(_ text: String) -> (Double, Double, Double?)? {
        let t = text.lowercased()
        let w = ShotTargets.words(text)
        let turnWords: Set<String> = ["turned", "turn", "turning", "turns", "angled", "rotated"]
        let lookWords: Set<String> = ["looking", "looks", "look", "toward", "towards", "to", "facing", "faces", "gazing", "glancing", "gaze"]
        let away = has(t, ["away from the lens", "away from the camera", "away from the viewer"]) || w.contains("away")
        let sideSign = side(t, words: w)
        let amount: (Double, Double)?
        if has(t, ["profile", "side-on", "side on", "90°", "90 degrees"]) { amount = (70, 15) }
        else if has(t, ["three-quarter", "three quarter", "3/4", "45°", "45 degrees"]) { amount = (40, 12) }
        else if w.contains("over") && (w.contains("shoulder") || w.contains("shoulders")) { amount = (45, 15) }
        else if away || w.contains(where: { turnWords.contains($0) }) || (sideSign != nil && w.contains(where: { lookWords.contains($0) })) {
            amount = w.contains(where: { slightWords.contains($0) }) ? (20, 10) : (30, 12)
        } else { amount = nil }

        guard let amount else { return facingOnly(text) }
        return (amount.0, amount.1, sideSign)
    }

    static func facingOnly(_ text: String) -> (Double, Double, Double?)? {
        let t = text.lowercased()
        if has(t, ["away from"]) { return nil }
        return has(t, facingPhrases) ? (0, 12, 1) : nil
    }

    /// +1 = toward the frame's right, -1 = toward its left.
    static func side(_ lower: String, words w: [String]) -> Double? {
        for (own, frameSign) in [("left", 1.0), ("right", -1.0)] {
            // The subject's own left is the frame's right.
            if ["her ", "his ", "their ", "own "].contains(where: { lower.contains($0 + own) }) { return frameSign }
        }
        if w.contains("left") { return -1 }
        if w.contains("right") { return 1 }
        return nil
    }

    /// (chin degrees, tolerance): "looking slightly down" → -8, "down at the ground" → -15, "level" → 0.
    static func chin(_ text: String) -> (Double, Double)? {
        let t = text.lowercased().trimmingCharacters(in: .whitespacesAndNewlines.union(.punctuationCharacters))
        let w = Set(ShotTargets.words(text))
        let size = w.contains(where: { slightWords.contains($0) }) ? 8.0 : 15.0
        if t == "level" || has(t, ["chin level", "chin parallel", "level chin", "chin straight", "head level"]) { return (0, 8) }
        let chin = w.contains("chin")
        if has(t, ["head bowed", "bowed", "eyes down", "gaze down", "lowered gaze"]) || w.contains("down") || w.contains("downward")
            || (chin && !w.isDisjoint(with: ["lowered", "tucked", "dropped"])) { return (-size, 8) }
        if has(t, ["toward the sky", "towards the sky", "skyward"]) || w.contains("up") || w.contains("upward") || w.contains("upwards")
            || (chin && !w.isDisjoint(with: ["raised", "lifted"])) { return (size, 8) }
        return nil
    }

    private static func has(_ t: String, _ phrases: [String]) -> Bool { phrases.contains { t.contains($0) } }
}

extension FacePose {
    /// Head turn from 2D face landmarks: where the nose sits between the two sides of the face
    /// outline. 0 = facing the camera, ±90 = profile, + = turned toward the frame's right.
    /// Inputs are x coordinates in any one normalized space with x growing to the right. Nil when
    /// the outline is degenerate. Vision's own yaw proved too noisy on the phone to use for cues.
    public static func yawFromLandmarks(contourX: [Double], noseX: [Double]) -> Double? {
        guard let lo = contourX.min(), let hi = contourX.max(), hi - lo > 0.05, !noseX.isEmpty else { return nil }
        let nose = noseX.reduce(0, +) / Double(noseX.count)
        let offset = max(-1, min(1, ((nose - lo) / (hi - lo) - 0.5) * 2))
        return asin(offset) * 180 / .pi
    }
}
