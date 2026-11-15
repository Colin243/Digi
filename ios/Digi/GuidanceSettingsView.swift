import SwiftUI
import DirectorKit

extension GuidanceStyle {
    var title: String {
        switch self { case .full: return "Full info"; case .soft: return "Soft"; case .minimal: return "Minimal" }
    }
    var blurb: String {
        switch self {
        case .full: return "Every number and detail, for people who want them."
        case .soft: return "One friendly hint at a time, in plain words."
        case .minimal: return "Nearly nothing on screen until something is off."
        }
    }
    var next: GuidanceStyle {
        switch self { case .full: return .soft; case .soft: return .minimal; case .minimal: return .full }
    }
}

extension GuidanceLevel {
    var title: String {
        switch self { case .essentials: return "Basics"; case .helpful: return "Helpful"; case .detailed: return "Detailed"; case .everything: return "Everything" }
    }
    var blurb: String {
        switch self {
        case .essentials: return "Just tell me what to do next."
        case .helpful: return "Adds a level line, a frame on your subject and tips for their head."
        case .detailed: return "Adds a second tip and a fuller level guide."
        case .everything: return "Adds the raw numbers behind each tip."
        }
    }
}

/// Pick a look, set how much help, fine-tune. Also used as the first-run "pick your look" step.
struct GuidanceSettingsView: View {
    @ObservedObject private var settings = GuidanceSettings.shared
    var firstRun = false
    var done: () -> Void
    @State private var taps = 0

    private var prefs: GuidancePrefs { settings.prefs }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(firstRun ? "Pick your look" : "Guidance").font(.title2.weight(.semibold))
                        .onTapGesture { taps += 1; if taps >= 5 { settings.prefs.developerReadout.toggle(); taps = 0 } }
                    Text(firstRun ? "How much should the camera tell you while you shoot? You can change this any time."
                                  : "How the camera helps you line up a shot.")
                        .font(.subheadline).foregroundStyle(.white.opacity(0.7))
                }

                VStack(spacing: 10) {
                    ForEach([GuidanceStyle.soft, .minimal, .full], id: \.self) { style in
                        StyleCard(style: style, selected: prefs.style == style) {
                            settings.prefs.select(style)
                            settings.hasChosen = true
                        }
                    }
                }

                if !firstRun {
                    levelSection
                    fineTune
                    if settings.prefs.developerReadout || DEBUGBuild.isDebug { developer }
                }

                Button(firstRun ? "Continue" : "Done") { settings.hasChosen = true; done() }
                    .font(.headline).frame(maxWidth: .infinity, minHeight: 48)
                    .background(CameraStyle.accent, in: RoundedRectangle(cornerRadius: 14)).foregroundStyle(.black)
                    .accessibilityIdentifier("guidance-done")
            }.padding(20)
        }
        .background(CameraStyle.body.ignoresSafeArea())
        .foregroundStyle(.white)
        .preferredColorScheme(.dark)
    }

    private var levelSection: some View {
        let levels = GuidanceLevel.allCases.filter { $0 <= prefs.style.maxLevel }
        return VStack(alignment: .leading, spacing: 10) {
            Text("Amount of guidance").font(.headline)
            Picker("Amount of guidance", selection: Binding(get: { settings.prefs.level }, set: { settings.prefs.level = $0 })) {
                ForEach(levels, id: \.self) { Text($0.title).tag($0) }
            }.pickerStyle(.segmented).accessibilityIdentifier("guidance-level")
            Text(prefs.level.blurb).font(.footnote).foregroundStyle(.white.opacity(0.7))
        }
    }

    private var fineTune: some View {
        DisclosureGroup {
            VStack(alignment: .leading, spacing: 12) {
                let d = prefs.display
                Toggle("Level line", isOn: flag(d.levelIndicator != .off) { o, v in
                    o.levelIndicator = v ? (prefs.style == .full ? .full : .subtle) : .off })
                Toggle("Frame around your subject", isOn: flag(d.subjectBrackets) { o, v in o.subjectBrackets = v })
                Toggle("Tips for their head and chin", isOn: settings.headCues)
                Toggle("Show a second tip", isOn: flag(d.cueRow == .topPlusCount) { o, v in o.cueRow = v ? .topPlusCount : .topOnly })
                Toggle("Buzz when it looks right", isOn: flag(d.haptics) { o, v in o.haptics = v })
                if prefs.isCustom {
                    Button("Reset to \(prefs.style.title)") { settings.prefs.resetOverrides() }
                        .font(.subheadline).foregroundStyle(CameraStyle.accent)
                }
            }.padding(.top, 10)
        } label: {
            HStack {
                Text("Fine-tune").font(.headline)
                if prefs.isCustom { Text("Custom").font(.caption).padding(.horizontal, 8).padding(.vertical, 2)
                    .background(.white.opacity(0.15), in: Capsule()) }
            }
        }.tint(.white)
    }

    private var developer: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Developer").font(.headline)
            Toggle("Raw readout and detection boxes", isOn: Binding(
                get: { settings.prefs.developerReadout }, set: { settings.prefs.developerReadout = $0 }))
            Text("Shows at the Everything level in Full info.").font(.footnote).foregroundStyle(.white.opacity(0.7))
        }
    }

    /// A Bool toggle that writes a fine-tune override (dropped again when it matches the preset).
    private func flag(_ current: Bool, _ write: @escaping (inout GuidanceOverrides, Bool) -> Void) -> Binding<Bool> {
        Binding(get: { current }, set: { v in settings.prefs.override { write(&$0, v) } })
    }
}

enum DEBUGBuild {
    static var isDebug: Bool {
        #if DEBUG
        return true
        #else
        return false
        #endif
    }
}

private struct StyleCard: View {
    let style: GuidanceStyle
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 14) {
                StyleSample(style: style).frame(width: 64, height: 84)
                VStack(alignment: .leading, spacing: 4) {
                    Text(style.title).font(.headline)
                    Text(style.blurb).font(.footnote).foregroundStyle(.white.opacity(0.7)).multilineTextAlignment(.leading)
                }
                Spacer()
                Image(systemName: selected ? "checkmark.circle.fill" : "circle").font(.title3)
                    .foregroundStyle(selected ? CameraStyle.accent : .white.opacity(0.35))
            }
            .padding(12)
            .background(.white.opacity(selected ? 0.12 : 0.06), in: RoundedRectangle(cornerRadius: 16))
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(selected ? CameraStyle.accent : .clear, lineWidth: 1.5))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("guidance-style-\(style.rawValue)")
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

/// A tiny stand-in viewfinder showing how each style's hint looks.
private struct StyleSample: View {
    let style: GuidanceStyle
    var body: some View {
        let theme = GuidanceTheme.make(style)
        ZStack {
            RoundedRectangle(cornerRadius: 8).fill(Color(red: 0.36, green: 0.40, blue: 0.34))
            Rectangle().fill(.white.opacity(style == .full ? 0 : 0.8)).frame(height: 1).padding(.horizontal, 6)
            VStack {
                Spacer()
                switch style {
                case .full:
                    Text("Tilt up 14° +1").font(.system(size: 7, weight: .semibold)).foregroundStyle(CameraStyle.accent)
                        .padding(3).background(.black.opacity(0.6), in: RoundedRectangle(cornerRadius: 3))
                case .soft:
                    HStack(spacing: 2) {
                        Image(systemName: "arrow.up").font(.system(size: 7)).foregroundStyle(theme.hint ?? .white)
                        Text("Tilt up a bit").font(.system(size: 7, design: .rounded))
                    }.padding(.horizontal, 5).padding(.vertical, 3).background(.black.opacity(0.5), in: Capsule())
                case .minimal:
                    Text("tilt up").font(.system(size: 7)).tracking(0.3)
                }
                Spacer().frame(height: 8)
            }.foregroundStyle(.white)
        }
    }
}
