import Foundation

/// A box in the upright camera frame, normalized to 0...1 with the origin at the top left.
public struct NormalizedBox: Equatable, Sendable {
    public var x: Double, y: Double, width: Double, height: Double
    public init(x: Double, y: Double, width: Double, height: Double) {
        self.x = x; self.y = y; self.width = width; self.height = height
    }
    public var midX: Double { x + width / 2 }
    public var midY: Double { y + height / 2 }
}

/// How the phone is held, from the gravity vector (CoreMotion `CMDeviceMotion.gravity`, device axes:
/// x to the right of the screen, y to its top, z out of the screen toward the user).
public struct PoseSample: Equatable, Sendable {
    /// Camera pitch in degrees: 0 = the back camera points at the horizon, + = pointing up.
    public var pitchDegrees: Double
    /// Horizon tilt in degrees within ±45, whichever way the phone is turned. + = rotated clockwise
    /// as the user sees the screen.
    public var rollDegrees: Double
    /// true = held upright, false = sideways, nil = lying too flat (or too diagonal) to tell.
    public var portrait: Bool?

    public init(pitchDegrees: Double, rollDegrees: Double, portrait: Bool?) {
        self.pitchDegrees = pitchDegrees; self.rollDegrees = rollDegrees; self.portrait = portrait
    }

    public init(gravityX x: Double, y: Double, z: Double) {
        let degrees = 180 / Double.pi
        pitchDegrees = atan2(z, hypot(x, y)) * degrees
        let raw = atan2(x, -y) * degrees
        rollDegrees = raw - 90 * (raw / 90).rounded()
        if abs(z) > 0.8 { portrait = nil }
        else if abs(y) > abs(x) * 1.3 { portrait = true }
        else if abs(x) > abs(y) * 1.3 { portrait = false }
        else { portrait = nil }
    }
}

/// One instruction for the photographer, in priority order of `Kind`.
public struct GuidanceCue: Equatable, Sendable {
    public enum Kind: Int, Comparable, Sendable, CaseIterable {
        case orientation, level, tilt, findSubject, distance, horizontal
        // Subject cues (Guidance.subjectCues), in their own list.
        case findFace, headTurn, headTilt
        public static func < (a: Kind, b: Kind) -> Bool { a.rawValue < b.rawValue }
    }
    public var kind: Kind
    public var text: String
    /// SF Symbol name for the cue.
    public var symbol: String
}

public struct Guidance: Equatable, Sendable {
    /// Active cues, most important first.
    public var cues: [GuidanceCue]
    /// Everything the shot asks for that can be measured is right.
    public var isSatisfied: Bool
    /// False when the shot's text gave nothing the camera can check.
    public var hasTargets: Bool
    public var pitchDegrees: Double?
    public var rollDegrees: Double?
    /// Roll within this many degrees counts as level.
    public var levelTolerance: Double
    /// Things to tell the subject (head turn, chin), only when live subject cues are on.
    public var subjectCues: [GuidanceCue] = []
    /// The subject's head matches what the shot asks (false when off or nothing to check).
    public var subjectSatisfied = false
    /// Smoothed head pose of the subject, for the debug readout.
    public var headYawDegrees: Double?
    public var headPitchDegrees: Double?
    public var top: GuidanceCue? { cues.first }

    public static let idle = Guidance(cues: [], isSatisfied: false, hasTargets: false, pitchDegrees: nil,
                                      rollDegrees: nil, levelTolerance: GuidanceTracker.levelEnter)
}

/// Turns a stream of pose and subject observations into steady cues for one shot. Values are
/// smoothed, each cue switches on past one threshold and off only inside a tighter one, and the
/// cue on top is held briefly so the text does not flicker. Pure and clock-free: callers pass time.
public struct GuidanceTracker: Sendable {
    public let targets: ShotTargets

    static let levelEnter = 2.5, levelExit = 1.2
    static let horizontalEnter = 0.10, horizontalExit = 0.05
    static let distanceEnter = 0.10  // relative error outside the framing range
    static let subjectTimeout: TimeInterval = 1.2
    static let topHold: TimeInterval = 0.8
    /// Pitch beyond this (phone nearly flat) makes roll meaningless.
    static let flatPitch = 55.0

    private var pitch = Smoother(alpha: 0.3), roll = Smoother(alpha: 0.3)
    private var portrait: Bool?
    private var faceHeight = Smoother(alpha: 0.4), personHeight = Smoother(alpha: 0.4), centerX = Smoother(alpha: 0.4)
    private var lastSubjectAt: TimeInterval?, lastFaceAt: TimeInterval?, lastPersonAt: TimeInterval?
    private var active: Set<GuidanceCue.Kind> = []
    private var shownTop: GuidanceCue.Kind?
    private var shownSince: TimeInterval = 0
    private var headYaw = Smoother(alpha: 0.55), headPitch = Smoother(alpha: 0.55)  // 5 fps: quick to follow a turn
    private var lastFacePoseAt: TimeInterval?

    /// Live head-direction cues for the subject (experimental, off by default).
    public var subjectCuesEnabled = false
    /// True when the user chose who to direct; the "find the subject" cue then names that person.
    public var subjectChosen = false

    public init(targets: ShotTargets) { self.targets = targets }

    public var hasTargets: Bool {
        targets.pitchDegrees != nil || targets.portrait != nil || targets.needsSubject
    }

    public mutating func addPose(_ sample: PoseSample) {
        pitch.add(sample.pitchDegrees)
        roll.add(sample.rollDegrees)
        if let p = sample.portrait { portrait = p }
    }

    /// One person-detection result. Pass nils when nobody was found in the frame.
    public mutating func addSubject(person: NormalizedBox?, face: NormalizedBox?, facePose: FacePose? = nil, at t: TimeInterval) {
        guard person != nil || face != nil else { return }
        if let last = lastSubjectAt, t - last <= Self.subjectTimeout {} else {
            faceHeight.reset(); personHeight.reset(); centerX.reset()  // reacquired: start fresh
            headYaw.reset(); headPitch.reset()
        }
        lastSubjectAt = t
        if let face { faceHeight.add(face.height); lastFaceAt = t }
        if face != nil, let pose = facePose {
            headYaw.add(pose.yawDegrees)
            if let p = pose.pitchDegrees { headPitch.add(p) }
            lastFacePoseAt = t
        }
        if let person { personHeight.add(person.height); lastPersonAt = t }
        if let x = person?.midX ?? face?.midX { centerX.add(x) }
    }

    public mutating func guidance(at t: TimeInterval) -> Guidance {
        var cues: [GuidanceCue] = []
        let recent = { (time: TimeInterval?) in time.map { t - $0 <= Self.subjectTimeout } ?? false }

        // Orientation (no smoothing needed: PoseSample only reports it when it is clear).
        if let want = targets.portrait, let have = portrait, want != have {
            cues.append(GuidanceCue(kind: .orientation, text: want ? "Hold the phone upright" : "Turn the phone sideways",
                                    symbol: want ? "rectangle.portrait.rotate" : "rectangle.landscape.rotate"))
        }

        // Level horizon.
        if let r = roll.value, let p = pitch.value, abs(p) < Self.flatPitch,
           gate(.level, error: abs(r), enter: Self.levelEnter, exit: Self.levelExit) {
            cues.append(GuidanceCue(kind: .level, text: r > 0 ? "Straighten: rotate the phone left" : "Straighten: rotate the phone right",
                                    symbol: r > 0 ? "rotate.left" : "rotate.right"))
        } else { active.remove(.level) }

        // Tilt.
        if let want = targets.pitchDegrees, let p = pitch.value {
            let error = p - want
            if gate(.tilt, error: abs(error), enter: targets.pitchTolerance, exit: targets.pitchTolerance * 0.5) {
                let n = max(2, Int((abs(error) / 2).rounded()) * 2)
                cues.append(GuidanceCue(kind: .tilt, text: error > 0 ? "Tilt down \(n)°" : "Tilt up \(n)°",
                                        symbol: error > 0 ? "arrow.down" : "arrow.up"))
            }
        }

        // Subject.
        if targets.needsSubject {
            if !recent(lastSubjectAt) {
                active.subtract([.distance, .horizontal])
                cues.append(GuidanceCue(kind: .findSubject, text: subjectChosen ? "Find the person you chose" : "Point the camera at your subject", symbol: "person.crop.rectangle"))
            } else {
                if let framing = targets.framing, let (error, tooSmall) = distanceError(framing, recent: recent),
                   gate(.distance, error: error, enter: Self.distanceEnter, exit: 0.0001) {
                    cues.append(GuidanceCue(kind: .distance, text: tooSmall ? "Step closer" : "Step back",
                                            symbol: tooSmall ? "figure.walk" : "arrow.uturn.backward"))
                } else { active.remove(.distance) }

                if let side = targets.horizontal, let x = centerX.value {
                    let dx = x - side.x
                    if gate(.horizontal, error: abs(dx), enter: Self.horizontalEnter, exit: Self.horizontalExit) {
                        // Subject too far right: panning right moves them left in the frame.
                        let pan = dx > 0 ? "right" : "left"
                        let goal = side == .center ? "to center the subject" : "so the subject sits on the \(side.rawValue) third"
                        cues.append(GuidanceCue(kind: .horizontal, text: "Pan \(pan) \(goal)",
                                                symbol: dx > 0 ? "arrow.right" : "arrow.left"))
                    }
                }
            }
        }

        cues.sort { $0.kind < $1.kind }
        // Hold the cue on top for a moment if it is still active, so the text does not jump around.
        if let shown = shownTop, let i = cues.firstIndex(where: { $0.kind == shown }), i > 0, t - shownSince < Self.topHold {
            cues.insert(cues.remove(at: i), at: 0)
        }
        if cues.first?.kind != shownTop { shownTop = cues.first?.kind; shownSince = t }

        let (subjectCues, subjectOK) = headCues(recent: recent)
        let checksHead = subjectCuesEnabled && !targets.head.isEmpty
        let hasPose = pitch.value != nil
        let cameraOK = hasTargets && hasPose && cues.isEmpty && (!targets.needsSubject || recent(lastSubjectAt))
        var out = Guidance(cues: cues, isSatisfied: cameraOK && (!checksHead || subjectOK), hasTargets: hasTargets,
                           pitchDegrees: pitch.value, rollDegrees: roll.value, levelTolerance: Self.levelEnter)
        out.subjectCues = subjectCues
        out.subjectSatisfied = subjectOK
        out.headYawDegrees = headYaw.value
        out.headPitchDegrees = headPitch.value
        return out
    }

    /// What to say to the subject about their head, phrased as the words to use.
    private mutating func headCues(recent: (TimeInterval?) -> Bool) -> ([GuidanceCue], Bool) {
        let head = targets.head
        guard subjectCuesEnabled, !head.isEmpty else { active.subtract([.headTurn, .headTilt]); return ([], false) }
        guard recent(lastFacePoseAt) else {
            active.subtract([.headTurn, .headTilt])
            return ([GuidanceCue(kind: .findFace, text: "Can't see their face yet", symbol: "face.dashed")], false)
        }
        var cues: [GuidanceCue] = []
        if let want = head.yaw, let yaw = headYaw.value {
            let error = head.yawEitherSide ? abs(yaw) - want : yaw - want
            if gate(.headTurn, error: abs(error), enter: head.yawTolerance, exit: head.yawTolerance * 0.5) {
                let say: String
                if head.yawEitherSide { say = error < 0 ? "Turn your head a little away from me" : "Turn back toward me a little" }
                // Face needs to turn toward the frame's right = the subject's own left.
                else { say = error < 0 ? "Turn your head a little to your left" : "Turn your head a little to your right" }
                cues.append(GuidanceCue(kind: .headTurn, text: "Say: “\(say)”", symbol: "person.bust"))
            }
        } else { active.remove(.headTurn) }
        if let want = head.pitch, let p = headPitch.value {
            let error = p - want
            if gate(.headTilt, error: abs(error), enter: head.pitchTolerance, exit: head.pitchTolerance * 0.5) {
                cues.append(GuidanceCue(kind: .headTilt, text: error < 0 ? "Say: “Lift your chin a little”" : "Say: “Lower your chin a little”",
                                        symbol: error < 0 ? "chevron.up" : "chevron.down"))
            }
        } else { active.remove(.headTilt) }
        return (cues, cues.isEmpty)
    }

    /// Relative error outside the framing's size range, and whether the subject looks too small.
    private func distanceError(_ framing: Framing, recent: (TimeInterval?) -> Bool) -> (Double, Bool)? {
        let measured: Double, range: ClosedRange<Double>
        // Full body: the whole person is the better ruler (a small face can sit in range while the
        // body fills under half the frame, as on the phone test). Otherwise the face.
        if framing == .fullBody, recent(lastPersonAt), let h = personHeight.value {
            // A box spanning the whole frame is cut off at the edges, so its size understates how close they are.
            if h > 0.97 { return (1, false) }
            measured = h; range = Framing.fullBodyPersonRange
        }
        else if recent(lastFaceAt), let h = faceHeight.value { measured = h; range = framing.faceHeightRange }
        else { return nil }  // no face and not a full-body shot: distance can't be judged
        if measured < range.lowerBound { return ((range.lowerBound - measured) / range.lowerBound, true) }
        if measured > range.upperBound { return ((measured - range.upperBound) / range.upperBound, false) }
        return (0, false)
    }

    /// Switches a cue on when `error` exceeds `enter` and off only once it falls below `exit`.
    private mutating func gate(_ kind: GuidanceCue.Kind, error: Double, enter: Double, exit: Double) -> Bool {
        if active.contains(kind) { if error < exit { active.remove(kind) } }
        else if error > enter { active.insert(kind) }
        return active.contains(kind)
    }
}

struct Smoother: Sendable {
    let alpha: Double
    private(set) var value: Double?
    init(alpha: Double) { self.alpha = alpha }
    mutating func add(_ x: Double) { value = value.map { $0 + alpha * (x - $0) } ?? x }
    mutating func reset() { value = nil }
}

// MARK: - Subject selection

/// Picks which detected person is "the subject" each frame.
///
/// With nobody chosen it follows one person automatically: the largest at first, then the same
/// person for as long as they stay matched, so it does not flip between two people of similar size.
/// Once the user taps someone it follows that person by overlap and position and ignores everyone
/// else. It never switches to another person on its own: after `lostTimeout` without a match it
/// reports `isLost` and keeps waiting for the chosen person near where they were last seen, until
/// the user taps someone again or clears the choice.
public struct SubjectSelector: Sendable {
    /// The chosen person's last matched box (nil = automatic).
    public private(set) var locked: NormalizedBox?
    /// True when the chosen person has not been matched for longer than `lostTimeout`.
    public private(set) var isLost = false
    private var lastSeen: TimeInterval = 0
    private var auto: NormalizedBox?
    public static let lostTimeout: TimeInterval = 3

    public init() {}
    public var isLocked: Bool { locked != nil }

    /// Locks onto the person (or, with no people detected, the face) under the tapped point.
    /// `x`/`y` are normalized, top-left origin. Returns false when nothing is near the tap.
    @discardableResult
    public mutating func lock(atX x: Double, y: Double, people: [NormalizedBox], faces: [NormalizedBox], now: TimeInterval) -> Bool {
        let candidates = people.isEmpty ? faces : people
        let hit = candidates.filter { $0.contains(x: x, y: y) }.min { $0.area < $1.area }
            ?? candidates.map { ($0, hypot($0.midX - x, $0.midY - y)) }.filter { $0.1 < 0.2 }.min { $0.1 < $1.1 }?.0
        guard let hit else { return false }
        locked = hit; lastSeen = now; isLost = false; auto = nil
        return true
    }

    /// Back to automatic: follow the largest person.
    public mutating func clear() { locked = nil; isLost = false; auto = nil }

    /// The subject's person box and face box for this frame (either may be nil). With a chosen
    /// subject that is out of view, both are nil even if other people are visible.
    public mutating func choose(people: [NormalizedBox], faces: [NormalizedBox], now: TimeInterval) -> (person: NormalizedBox?, face: NormalizedBox?) {
        let usingFaces = people.isEmpty
        let candidates = usingFaces ? faces : people
        let result = { (b: NormalizedBox) -> (person: NormalizedBox?, face: NormalizedBox?) in
            usingFaces ? (nil, b) : (b, Self.face(in: b, faces))
        }
        if let l = locked {
            if let best = Self.match(l, in: candidates) {
                locked = best; lastSeen = now; isLost = false
                return result(best)
            }
            isLost = now - lastSeen > Self.lostTimeout
            return (nil, nil)
        }
        if let a = auto, let best = Self.match(a, in: candidates) {
            auto = best
            return result(best)
        }
        auto = candidates.max { $0.area < $1.area }
        return auto.map(result) ?? (nil, nil)
    }

    /// The candidate that best continues `previous`, if any is close enough to be the same person.
    static func match(_ previous: NormalizedBox, in candidates: [NormalizedBox]) -> NormalizedBox? {
        candidates.compactMap { c -> (NormalizedBox, Double)? in
            let iou = previous.iou(c), dist = hypot(previous.midX - c.midX, previous.midY - c.midY)
            guard iou > 0.1 || dist < 0.15 || previous.contains(x: c.midX, y: c.midY) else { return nil }
            return (c, iou - dist)
        }.max { $0.1 < $1.1 }?.0
    }

    static func face(in person: NormalizedBox, _ faces: [NormalizedBox]) -> NormalizedBox? {
        faces.filter { person.contains(x: $0.midX, y: $0.midY) }.max { $0.area < $1.area }
    }
}

extension NormalizedBox {
    public var area: Double { width * height }
    public func contains(x px: Double, y py: Double) -> Bool { px >= x && px <= x + width && py >= y && py <= y + height }
    public func iou(_ o: NormalizedBox) -> Double {
        let w = max(0, min(x + width, o.x + o.width) - max(x, o.x))
        let h = max(0, min(y + height, o.y + o.height) - max(y, o.y))
        let inter = w * h, union = area + o.area - inter
        return union > 0 ? inter / union : 0
    }
}
