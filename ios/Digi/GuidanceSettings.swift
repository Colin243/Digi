import Foundation
import SwiftUI
import DirectorKit

/// The user's guidance style and level, stored as one JSON value. Views read `display` instead of
/// their own flags (phase 2 moves them over; nothing reads it yet, so there is no visual change).
@MainActor
final class GuidanceSettings: ObservableObject {
    static let shared = GuidanceSettings()
    private static let key = "digi.guidancePrefs"

    @Published var prefs: GuidancePrefs { didSet { save(); syncLive() } }
    var display: GuidanceDisplay { prefs.display }

    /// Whether the user has picked a look yet. Until then the first pinned shot offers the choice.
    @Published var hasChosen: Bool { didSet { UserDefaults.standard.set(hasChosen, forKey: "digi.guidanceChosen") } }

    /// "Live head cues" in the pinned card. Writes a fine-tune override, so it follows the preset until touched.
    var headCues: Binding<Bool> {
        Binding(get: { self.display.headCues }, set: { v in self.prefs.override { $0.headCues = v } })
    }
    /// "Show detection boxes": boxes and the raw readout together, as the old single switch did.
    var detectionBoxes: Binding<Bool> {
        Binding(get: { self.display.detectionBoxes },
                set: { v in self.prefs.override { $0.detectionBoxes = v; $0.debugReadout = v } })
    }

    private init() {
        let d = UserDefaults.standard
        hasChosen = d.bool(forKey: "digi.guidanceChosen")
        if let data = d.data(forKey: Self.key), let saved = try? JSONDecoder().decode(GuidancePrefs.self, from: data) {
            prefs = saved
        } else {
            // First launch with this feature: keep existing users on the screen they already have.
            prefs = .migrated(liveSubjectCues: d.bool(forKey: LiveGuidance.subjectCuesKey),
                              guidanceDebug: d.bool(forKey: "digi.guidanceDebug"))
        }
        #if DEBUG
        // Debug only: `simctl launch … -digiGuidanceStyle soft -digiGuidanceLevel 1` to look at a preset.
        if let s = d.string(forKey: "digiGuidanceStyle"), let style = GuidanceStyle(rawValue: s) {
            prefs.select(style); hasChosen = true
            if d.object(forKey: "digiGuidanceLevel") != nil, let l = GuidanceLevel(rawValue: d.integer(forKey: "digiGuidanceLevel")) { prefs.level = l }
        }
        if let c = d.string(forKey: "digiDebugCue") {
            var g = Guidance.idle
            if c == "ok" { g.isSatisfied = true; g.hasTargets = true }
            else {
                g.cues = [GuidanceCue(kind: .tilt, text: "Tilt up 14°", symbol: "arrow.up", variant: .tilt(up: true, degrees: 14)),
                          GuidanceCue(kind: .distance, text: "Step back", symbol: "arrow.uturn.backward", variant: .back(canZoom: false))]
                g.hasTargets = true
            }
            LiveGuidance.shared.debugShow(g)
        }
        #endif
        syncLive()
    }

    /// The tracker reads LiveGuidance's own switch; keep it equal to the display flag.
    private func syncLive() {
        let want = display.headCues
        if LiveGuidance.shared.subjectCuesEnabled != want { LiveGuidance.shared.subjectCuesEnabled = want }
    }

    private func save() {
        if let data = try? JSONEncoder().encode(prefs) { UserDefaults.standard.set(data, forKey: Self.key) }
    }
}
