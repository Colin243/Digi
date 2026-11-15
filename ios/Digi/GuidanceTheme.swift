import SwiftUI
import DirectorKit

/// How a guidance style looks: type, colours, shape and motion. One per style, read through the
/// environment so views never hard-code a colour or font. Full info reproduces today's look exactly;
/// Soft and Minimal values are first guesses from the mockups and get tuned in phase 4.
struct GuidanceTheme: Equatable {
    var style: GuidanceStyle
    /// Cue text colour. Nil keeps the colour the caller passes in (the shot card's gold in Full info).
    var hint: Color?
    var ok: Color
    var subject: Color
    var cueDesign: Font.Design
    var cueWeight: Font.Weight
    var cueLowercase: Bool
    /// Top-bar labels (AUTO, 3:4 JPEG) in monospaced type. Full info only.
    var monospacedLabels: Bool

    static func make(_ style: GuidanceStyle) -> GuidanceTheme {
        switch style {
        case .full:
            return GuidanceTheme(style: .full, hint: nil, ok: .green, subject: .cyan, cueDesign: .default,
                                 cueWeight: .semibold, cueLowercase: false, monospacedLabels: true)
        case .soft:
            return GuidanceTheme(style: .soft, hint: Color(red: 0.95, green: 0.73, blue: 0.70),
                                 ok: Color(red: 0.73, green: 0.89, blue: 0.66),
                                 subject: Color(red: 0.95, green: 0.73, blue: 0.70), cueDesign: .rounded,
                                 cueWeight: .medium, cueLowercase: false, monospacedLabels: false)
        case .minimal:
            return GuidanceTheme(style: .minimal, hint: .white, ok: Color(red: 0.84, green: 0.94, blue: 0.72),
                                 subject: .white, cueDesign: .default, cueWeight: .regular,
                                 cueLowercase: true, monospacedLabels: false)
        }
    }
}

private struct GuidanceThemeKey: EnvironmentKey { static let defaultValue = GuidanceTheme.make(.full) }
extension EnvironmentValues {
    var guidanceTheme: GuidanceTheme {
        get { self[GuidanceThemeKey.self] }
        set { self[GuidanceThemeKey.self] = newValue }
    }
}

/// Puts the current style's theme in the environment for everything below it.
struct GuidanceThemed<Content: View>: View {
    @ObservedObject private var settings = GuidanceSettings.shared
    @ViewBuilder var content: () -> Content
    var body: some View { content().environment(\.guidanceTheme, .make(settings.prefs.style)) }
}
