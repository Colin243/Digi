import Foundation
import SwiftUI
import UIKit
import CoreMotion
import Vision
import QuartzCore
import DirectorKit

/// Live guidance toward the pinned shot: how the phone is held (CoreMotion, ~15 Hz) and where the
/// person is in the preview (Vision, ~5 fps). Each preview frame is analysed in memory and dropped;
/// nothing is stored, and nothing leaves the phone. No language model runs per frame.
final class LiveGuidance: ObservableObject, @unchecked Sendable {
    static let shared = LiveGuidance()

    /// What person detection saw in the latest analysed frame (upright, top-left origin), for overlays.
    struct Detections: Equatable {
        var people: [NormalizedBox] = []
        var faces: [NormalizedBox] = []
        var subject: NormalizedBox?
        var subjectFace: NormalizedBox?
        var subjectPose: FacePose?
        var locked = false
        /// The chosen person has been out of view for a while; nobody else is directed instead.
        var lost = false
    }

    @Published private(set) var guidance: Guidance = .idle
    @Published private(set) var targetPitch: Double?
    @Published private(set) var targets: ShotTargets?
    @Published private(set) var running = false
    @Published private(set) var detections = Detections()
    /// Experimental: live head-turn and chin cues for the subject, from Vision's face pose.
    @Published var subjectCuesEnabled = UserDefaults.standard.bool(forKey: LiveGuidance.subjectCuesKey) {
        didSet {
            UserDefaults.standard.set(subjectCuesEnabled, forKey: Self.subjectCuesKey)
            lock.lock(); tracker?.subjectCuesEnabled = subjectCuesEnabled; lock.unlock()
        }
    }
    static let subjectCuesKey = "digi.liveSubjectCues"
    #if DEBUG
    /// Debug only: show a fixed cue so the guidance visuals can be seen without a camera or motion.
    func debugShow(_ g: Guidance) { guidance = g }
    #endif
    /// Vision's yaw/pitch signs, mapped to "+ = toward the frame's right" and "+ = chin up".
    /// Check them with the debug readout (turn a face toward the frame's right: yaw should go up).
    static let visionYawSign = 1.0, visionPitchSign = -1.0

    private let motion = CMMotionManager()
    private let motionQueue: OperationQueue = { let q = OperationQueue(); q.maxConcurrentOperationCount = 1; return q }()
    private let visionQueue = DispatchQueue(label: "digi.guidance.vision", qos: .utility)
    private let lock = NSLock()
    // Guarded by `lock`:
    private var tracker: GuidanceTracker?
    private var visionBusy = false
    private var lastVisionAt: TimeInterval = 0
    private var frameOrientation: CGImagePropertyOrientation = .right
    private var selector = SubjectSelector()
    private var zoomState: (Double, ClosedRange<Double>?) = (1, nil)
    private var lastPeople: [NormalizedBox] = [], lastFaces: [NormalizedBox] = []
    private var publishTimer: Timer?

    static let visionInterval: TimeInterval = 0.2  // ~5 fps
    static let publishInterval: TimeInterval = 0.1

    private init() {}

    /// Starts (or restarts) guidance for `shot`. Main thread.
    func start(shot: Shot) {
        let targets = ShotTargets(shot: shot)
        var fresh = GuidanceTracker(targets: targets)
        fresh.subjectCuesEnabled = subjectCuesEnabled
        lock.lock(); (fresh.zoom, fresh.zoomRange) = zoomState; lock.unlock()
        lock.lock(); fresh.subjectChosen = selector.isLocked; tracker = fresh; lock.unlock()
        targetPitch = targets.pitchDegrees
        self.targets = targets
        if motion.isDeviceMotionAvailable, !motion.isDeviceMotionActive {
            motion.deviceMotionUpdateInterval = 1.0 / 15
            motion.startDeviceMotionUpdates(to: motionQueue) { [weak self] m, _ in
                guard let self, let g = m?.gravity else { return }
                let sample = PoseSample(gravityX: g.x, y: g.y, z: g.z)
                self.lock.lock(); self.tracker?.addPose(sample); self.lock.unlock()
            }
        }
        publishTimer?.invalidate()
        publishTimer = Timer.scheduledTimer(withTimeInterval: Self.publishInterval, repeats: true) { [weak self] _ in self?.publish() }
        running = true
    }

    /// Main thread.
    func stop() {
        guard running || publishTimer != nil else { return }
        publishTimer?.invalidate(); publishTimer = nil
        motion.stopDeviceMotionUpdates()
        lock.lock(); tracker = nil; selector.clear(); lastPeople = []; lastFaces = []; lock.unlock()
        guidance = .idle; targetPitch = nil; targets = nil; running = false
        detections = Detections()
    }

    /// Chooses the person under a tap on the viewfinder (normalized, top-left origin). Main thread.
    @discardableResult
    func selectSubject(atX x: Double, y: Double) -> Bool {
        lock.lock()
        let ok = selector.lock(atX: x, y: y, people: lastPeople, faces: lastFaces, now: CACurrentMediaTime())
        if ok { tracker?.subjectChosen = true }
        lock.unlock()
        if ok { detections.locked = true; detections.lost = false }
        return ok
    }

    /// Back to following whoever is largest in the frame. Main thread.
    func clearSubject() {
        lock.lock(); selector.clear(); tracker?.subjectChosen = false; lock.unlock()
        detections.locked = false; detections.lost = false
    }

    /// How preview frames must be rotated to be upright (same mapping as the rendered preview).
    /// Current zoom and its range, so distance cues can offer zoom as well as walking. Main thread.
    func setZoom(_ zoom: Double, range: ClosedRange<Double>?) {
        lock.lock(); tracker?.zoom = zoom; tracker?.zoomRange = range; zoomState = (zoom, range); lock.unlock()
    }

    func setInterfaceOrientation(_ o: UIInterfaceOrientation) {
        let orientation: CGImagePropertyOrientation = o == .portrait ? .right : o == .landscapeLeft ? .down : .up
        lock.lock(); frameOrientation = orientation; lock.unlock()
    }

    /// Called on the camera's video queue for each preview frame; returns at once. At most one
    /// frame is in flight, at most every `visionInterval`.
    func consider(_ pixel: CVPixelBuffer) {
        let now = CACurrentMediaTime()
        lock.lock()
        guard tracker != nil, !visionBusy, now - lastVisionAt >= Self.visionInterval else { lock.unlock(); return }
        visionBusy = true; lastVisionAt = now
        let orientation = frameOrientation
        lock.unlock()
        visionQueue.async { [weak self] in
            let (people, found) = Self.detect(pixel, orientation: orientation)
            let faces = found.map(\.box)
            guard let self else { return }
            let now = CACurrentMediaTime()
            self.lock.lock()
            self.lastPeople = people; self.lastFaces = faces
            let (person, face) = self.selector.choose(people: people, faces: faces, now: now)
            let pose = face.flatMap { f in found.first { $0.box == f }?.pose }
            self.tracker?.addSubject(person: person, face: face, facePose: pose, at: now)
            let seen = Detections(people: people, faces: faces, subject: person ?? face, subjectFace: face, subjectPose: pose,
                                  locked: self.selector.isLocked, lost: self.selector.isLost)
            let active = self.tracker != nil
            self.visionBusy = false
            self.lock.unlock()
            if active { DispatchQueue.main.async { if self.running, self.detections != seen { self.detections = seen } } }
        }
    }

    private func publish() {
        lock.lock(); let g = tracker?.guidance(at: CACurrentMediaTime()); lock.unlock()
        if let g, g != guidance { guidance = g }
    }

    /// Every person and face found, in upright top-left-origin coordinates, with each face's head pose.
    private static func detect(_ pixel: CVPixelBuffer, orientation: CGImagePropertyOrientation)
        -> ([NormalizedBox], [(box: NormalizedBox, pose: FacePose?)]) {
        let people = VNDetectHumanRectanglesRequest(); people.upperBodyOnly = false
        // Two passes: face rectangles (revision 3) for the chin angle, then landmarks on those faces
        // for the head turn (nose position within the face outline). The detector's own yaw only
        // reports 0 / ±45 / ±90, and the landmarks request alone reports no pitch.
        let rects = VNDetectFaceRectanglesRequest()
        rects.revision = VNDetectFaceRectanglesRequestRevision3
        let handler = VNImageRequestHandler(cvPixelBuffer: pixel, orientation: orientation)
        do { try handler.perform([people, rects]) } catch { return ([], []) }
        let found = (rects.results ?? []).filter { $0.confidence > 0.5 }
        let landmarks = VNDetectFaceLandmarksRequest()
        landmarks.inputFaceObservations = found
        if !found.isEmpty { try? handler.perform([landmarks]) }
        let marked = Dictionary((landmarks.results ?? []).map { ($0.uuid, $0) }, uniquingKeysWith: { a, _ in a })

        let degrees = 180 / Double.pi
        func box(_ r: CGRect) -> NormalizedBox {
            NormalizedBox(x: Double(r.minX), y: Double(1 - r.maxY), width: Double(r.width), height: Double(r.height))
        }
        let faces = found.enumerated().map { i, f -> (box: NormalizedBox, pose: FacePose?) in
            let lm = (marked[f.uuid] ?? (i < (landmarks.results?.count ?? 0) ? landmarks.results?[i] : nil))?.landmarks
            let detectorYaw = f.yaw.map { visionYawSign * $0.doubleValue * degrees }
            let landmarkYaw = FacePose.yawFromLandmarks(
                contourX: lm?.faceContour?.normalizedPoints.map { Double($0.x) } ?? [],
                noseX: lm?.nose?.normalizedPoints.map { Double($0.x) } ?? [])
            let pose = (landmarkYaw ?? detectorYaw).map { y in
                FacePose(yawDegrees: y, pitchDegrees: f.pitch.map { visionPitchSign * $0.doubleValue * degrees },
                         detectorYawDegrees: detectorYaw)
            }
            return (box(f.boundingBox), pose)
        }
        return ((people.results ?? []).filter { $0.confidence > 0.4 }.map { box($0.boundingBox) }, faces)
    }
}

/// The top live cue for the pinned shot, shown inside the shot card (also when it is collapsed).
struct LiveCueRow: View {
    @ObservedObject var live: LiveGuidance
    @ObservedObject private var settings = GuidanceSettings.shared
    @Environment(\.guidanceTheme) private var theme
    let accent: Color
    var style: CueRowStyle = .topPlusCount

    private var look: GuidanceStyle { settings.prefs.style }
    private func words(_ c: GuidanceCue) -> String {
        let t = GuidanceWording.text(for: c, style: look)
        return theme.cueLowercase ? t.lowercased() : t
    }

    var body: some View {
        let g = live.guidance
        if style != .off {
        VStack(alignment: .leading, spacing: 4) {
            cameraLine(g)
            if live.subjectCuesEnabled, let s = g.subjectCues.first {
                Label(words(s), systemImage: s.symbol).font(.system(.footnote, design: theme.cueDesign, weight: theme.cueWeight))
                    .foregroundStyle(theme.subject)
                    .accessibilityIdentifier("live-subject-cue")
            }
        }
        }
    }

    @ViewBuilder private func cameraLine(_ g: Guidance) -> some View {
        if g.isSatisfied {
            let text = GuidanceWording.text(.satisfied, style: look)
            Label(text, systemImage: "checkmark.circle.fill")
                .labelStyle(.automatic)
                .font(.system(.subheadline, design: theme.cueDesign, weight: theme.cueWeight)).foregroundStyle(theme.ok)
                .accessibilityIdentifier("live-cue-satisfied")
        } else if let cue = g.top {
            HStack(spacing: 8) {
                Image(systemName: cue.symbol).frame(width: 20)
                Text(words(cue)).font(.system(.subheadline, design: theme.cueDesign, weight: theme.cueWeight))
                if style == .topPlusCount && g.cues.count > 1 { Text("+\(g.cues.count - 1)").font(.caption2).foregroundStyle(.white.opacity(0.6)) }
            }
            .foregroundStyle(theme.hint ?? accent)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("live-cue")
        } else if live.running && !g.hasTargets && g.pitchDegrees != nil {
            Text(GuidanceWording.text(.noChecks, style: look)).font(.caption).foregroundStyle(.white.opacity(0.6))
        }
    }
}

/// Horizon line plus a tilt dot over the viewfinder. The line follows the real horizon; the dot
/// sits in the centre ring when the camera's tilt matches the shot.
struct LevelIndicator: View {
    @ObservedObject var live: LiveGuidance
    @Environment(\.guidanceTheme) private var theme
    var style: LevelIndicatorStyle = .full

    var body: some View {
        let g = live.guidance
        if style != .off, live.running, let roll = g.rollDegrees, let pitch = g.pitchDegrees, abs(pitch) < 55 {
            let level = abs(roll) < g.levelTolerance
            let lineColor: Color = level ? theme.ok : .white
            let thickness: CGFloat = theme.style == .minimal ? 1 : 1.5
            ZStack {
                if style == .full {
                    HStack(spacing: 70) {
                        Rectangle().frame(width: 18, height: 1.5)
                        Rectangle().frame(width: 18, height: 1.5)
                    }.foregroundStyle(.white.opacity(0.55))
                }
                Rectangle().fill(lineColor).frame(width: 120, height: thickness)
                    .rotationEffect(.degrees(-roll))
                if style == .full, let target = live.targetPitch {
                    let off = max(-70, min(70, (pitch - target) * 3))
                    let onTarget = abs(pitch - target) < 2.5
                    Circle().stroke(.white.opacity(0.6), lineWidth: 1).frame(width: 22, height: 22)
                    Circle().fill(onTarget ? theme.ok : Color.white).frame(width: 9, height: 9).offset(y: -off)
                }
            }
            .shadow(color: .black.opacity(0.6), radius: 2)
            .allowsHitTesting(false)
            .accessibilityHidden(true)
            .animation(.linear(duration: 0.1), value: roll)
        }
    }
}

/// Over the viewfinder: the box on the subject being directed, the boxes Vision found (debug), and
/// tap targets on every detected person. Guidance follows the largest person automatically; tapping
/// a person chooses them, and "Auto" goes back. Taps anywhere else fall through to tap-to-focus.
struct SubjectOverlay: View {
    @ObservedObject var live: LiveGuidance
    /// Detection boxes (people, faces).
    let debug: Bool
    /// The raw-number readout. Defaults to following `debug`, as the old single switch did.
    var readout: Bool? = nil
    /// The box and label on the subject being directed.
    var brackets = true
    /// Four corner marks instead of a labelled box (Soft and Minimal).
    var corners = false
    var okColor: Color = .green

    var body: some View {
        GeometryReader { area in
            let d = live.detections
            let w = area.size.width, h = area.size.height
            let rect = { (b: NormalizedBox) in CGRect(x: b.x * w, y: b.y * h, width: b.width * w, height: b.height * h) }
            let targets = d.people.isEmpty ? d.faces : d.people
            ZStack(alignment: .topLeading) {
                if debug || d.lost {
                    ForEach(Array(d.people.enumerated()), id: \.offset) { _, b in
                        let r = rect(b)
                        Rectangle().stroke(.white.opacity(0.75), style: StrokeStyle(lineWidth: 1, dash: d.lost ? [6, 4] : []))
                            .frame(width: r.width, height: r.height).position(x: r.midX, y: r.midY)
                    }.allowsHitTesting(false)
                }
                if debug {
                    ForEach(Array(d.faces.enumerated()), id: \.offset) { _, b in
                        let r = rect(b)
                        Rectangle().stroke(.cyan, lineWidth: 1).frame(width: r.width, height: r.height).position(x: r.midX, y: r.midY)
                    }.allowsHitTesting(false)
                }
                if brackets, let s = d.subject {
                    let r = rect(s)
                    let color: Color = d.locked ? okColor : .white
                    if corners {
                        CornerMarks().stroke(color.opacity(d.locked ? 1 : 0.85), style: StrokeStyle(lineWidth: 1.5, lineCap: .round))
                            .frame(width: r.width, height: r.height).position(x: r.midX, y: r.midY)
                            .allowsHitTesting(false)
                    } else {
                    RoundedRectangle(cornerRadius: 4).stroke(color.opacity(d.locked ? 1 : 0.7), lineWidth: d.locked ? 2 : 1)
                        .frame(width: r.width, height: r.height).position(x: r.midX, y: r.midY)
                        .allowsHitTesting(false)
                    Text(d.locked ? "Subject" : "Auto").font(.caption2.weight(.semibold))
                        .padding(.horizontal, 4).background(color.opacity(d.locked ? 1 : 0.8), in: RoundedRectangle(cornerRadius: 3)).foregroundStyle(.black)
                        // The shot card covers roughly the top quarter: label the box from below there.
                        .position(x: min(max(r.minX + 40, 40), w - 40), y: r.minY < h * 0.28 ? min(r.maxY + 9, h - 9) : r.minY - 8)
                        .allowsHitTesting(false)
                    }
                }
                if live.running {
                    // Tap a person to direct them. Only the boxes take taps.
                    ForEach(Array(targets.enumerated()), id: \.offset) { _, b in
                        let r = rect(b)
                        Color.clear.contentShape(Rectangle())
                            .frame(width: r.width, height: r.height).position(x: r.midX, y: r.midY)
                            .onTapGesture(coordinateSpace: .named("subjectOverlay")) { p in live.selectSubject(atX: p.x / w, y: p.y / h) }
                            .accessibilityLabel("Direct this person")
                            .accessibilityAddTraits(.isButton)
                    }
                }
                if readout ?? debug { debugReadout(d).position(x: w / 2, y: h - (d.locked ? 138 : 92)).allowsHitTesting(false) }
            }
            .coordinateSpace(name: "subjectOverlay")
        }
    }

    private func debugReadout(_ d: LiveGuidance.Detections) -> some View {
        let t = live.targets
        var lines = ["people \(d.people.count) · faces \(d.faces.count)" + (d.locked ? (d.lost ? " · locked, lost" : " · locked") : "")]
        if let f = d.subjectFace {
            let want = t?.framing.map { r in String(format: " (want %.2f–%.2f)", r.faceHeightRange.lowerBound, r.faceHeightRange.upperBound) } ?? ""
            lines.append(String(format: "face height %.2f", f.height) + want)
        } else if let p = d.subject {
            lines.append(String(format: "person height %.2f", p.height) + (t?.framing == .fullBody ? " (want 0.55–0.93)" : " (no face: distance not judged)"))
        }
        if let s = d.subject {
            lines.append(String(format: "centre x %.2f", s.midX) + (t?.horizontal.map { String(format: " (want %.2f)", $0.x) } ?? ""))
        }
        if let y = live.guidance.headYawDegrees {
            let t2 = t?.head
            var head = String(format: "head yaw %+.0f°", y)
            if let w = t2?.yaw { head += String(format: t2!.yawEitherSide ? " (want ±%.0f°)" : " (want %+.0f°)", w) }
            if let raw = live.detections.subjectPose?.detectorYawDegrees { head += String(format: " [vision %+.0f°]", raw) }
            lines.append(head)
            if let p = live.guidance.headPitchDegrees {
                lines.append(String(format: "chin %+.0f°", p) + (t2?.pitch.map { String(format: " (want %+.0f°)", $0) } ?? ""))
            }
        }
        if let p = live.guidance.pitchDegrees {
            lines.append(String(format: "pitch %.0f°", p) + (t?.pitchDegrees.map { String(format: " (want %.0f°)", $0) } ?? "")
                         + String(format: " · roll %.1f°", live.guidance.rollDegrees ?? 0))
        }
        return Text(lines.joined(separator: "\n")).font(.system(size: 10, design: .monospaced))
            .padding(6).background(.black.opacity(0.7), in: RoundedRectangle(cornerRadius: 6)).foregroundStyle(.white)
            .allowsHitTesting(false)
    }
}

/// Short corner marks around a rectangle, like a camera's focus frame.
struct CornerMarks: Shape {
    func path(in r: CGRect) -> Path {
        let n = min(16, r.width / 3, r.height / 3)
        var p = Path()
        for (x, dx) in [(r.minX, n), (r.maxX, -n)] {
            for (y, dy) in [(r.minY, n), (r.maxY, -n)] {
                p.move(to: CGPoint(x: x + dx, y: y)); p.addLine(to: CGPoint(x: x, y: y)); p.addLine(to: CGPoint(x: x, y: y + dy))
            }
        }
        return p
    }
}

/// Soft and Minimal show the live hint here, over the lower viewfinder, instead of inside the shot
/// card. Full info keeps the cue row in the card, so this draws nothing for it.
struct FloatingCue: View {
    @ObservedObject var live: LiveGuidance
    @ObservedObject private var settings = GuidanceSettings.shared
    @Environment(\.guidanceTheme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    private let haptic = UINotificationFeedbackGenerator()

    var body: some View {
        let style = settings.prefs.style
        let rows = settings.display.cueRow
        let g = live.guidance
        if style != .full && rows != .off {
            VStack(spacing: 6) {
                if g.isSatisfied {
                    let t = GuidanceWording.text(.satisfied, style: style)
                    pill(icon: "checkmark", text: t, color: theme.ok, spoken: GuidanceWording.text(.satisfied, style: .soft))
                } else {
                    ForEach(Array(g.cues.prefix(rows == .topPlusCount ? 2 : 1).enumerated()), id: \.offset) { _, c in
                        pill(icon: c.symbol, text: words(c), color: theme.hint ?? .white, spoken: GuidanceWording.text(for: c, style: .soft))
                    }
                }
                if live.subjectCuesEnabled, let s = g.subjectCues.first {
                    pill(icon: s.symbol, text: words(s), color: theme.subject, spoken: GuidanceWording.text(for: s, style: .soft))
                }
            }
            .allowsHitTesting(false)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.2), value: g.top?.kind)
            .onChange(of: g.isSatisfied) { _, now in
                if now && settings.display.haptics { haptic.notificationOccurred(.success) }
            }
        }
    }

    private func words(_ c: GuidanceCue) -> String {
        let t = GuidanceWording.text(for: c, style: settings.prefs.style)
        return theme.cueLowercase ? t.lowercased() : t
    }

    /// `spoken` is what VoiceOver reads, in plain words even when Minimal shows an icon or a terse word.
    @ViewBuilder private func pill(icon: String, text: String, color: Color, spoken: String) -> some View {
        shape(icon: icon, text: text, color: color)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(spoken)
            .accessibilityIdentifier("floating-cue")
    }

    @ViewBuilder private func shape(icon: String, text: String, color: Color) -> some View {
        let font = Font.system(.footnote, design: theme.cueDesign, weight: theme.cueWeight)
        if theme.style == .soft {
            HStack(spacing: 6) {
                Image(systemName: icon).font(.system(size: 13, weight: .semibold)).foregroundStyle(color)
                Text(text).font(font)
            }
            .foregroundStyle(.white).padding(.horizontal, 12).padding(.vertical, 7)
            .background(.black.opacity(0.5), in: Capsule())
        } else if text.isEmpty {
            Image(systemName: icon).font(.system(size: 14, weight: .regular)).foregroundStyle(color)
                .shadow(color: .black.opacity(0.6), radius: 2)
        } else {
            Text(text).font(font).tracking(0.3).foregroundStyle(color)
                .shadow(color: .black.opacity(0.6), radius: 2)
        }
    }
}

/// Shown while a chosen person is being directed: their state, and the way back to automatic.
/// Lives in the camera's bottom column so it never overlaps the hint or the zoom readout.
struct SubjectChip: View {
    @ObservedObject var live: LiveGuidance

    var body: some View {
        if live.detections.locked { chip(lost: live.detections.lost) }
    }

    private func chip(lost: Bool) -> some View {
        HStack(spacing: 10) {
            Label(lost ? "Lost: tap them to choose again" : "Directing the person you chose",
                  systemImage: lost ? "person.crop.rectangle.badge.questionmark" : "person.crop.rectangle")
                .foregroundStyle(lost ? .orange : .green)
                .accessibilityIdentifier(lost ? "subject-lost" : "subject-locked")
            Button { live.clearSubject() } label: {
                Label("Auto", systemImage: "xmark.circle.fill")
                    .padding(.horizontal, 8).padding(.vertical, 4)
                    .background(.white.opacity(0.18), in: Capsule())
            }
            .foregroundStyle(.white)
            .accessibilityLabel("Stop following the chosen person and pick automatically")
            .accessibilityIdentifier("subject-clear")
        }
        .font(.caption.weight(.semibold))
        .padding(.leading, 12).padding(.trailing, 6).padding(.vertical, 6)
        .background(.black.opacity(0.75), in: Capsule())
    }
}
