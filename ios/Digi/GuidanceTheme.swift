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
    /// Accent for chrome and controls: blue for Full info, pink for Minimal.
    var accent: Color
    /// The palette: screen background, panel fill, tint under the glass, and the text colour.
    var body: Color
    var panel: Color
    var glass: Color
    var silver: Color

    static func make(_ style: GuidanceStyle) -> GuidanceTheme {
        switch style {
        case .full:
            return GuidanceTheme(style: .full, hint: nil, ok: .green, subject: Color(red: 0.46, green: 0.64, blue: 0.90), cueDesign: .default,
                                 cueWeight: .semibold, cueLowercase: false, monospacedLabels: true, accent: Color(red: 0.27, green: 0.49, blue: 0.86), body: Color(red: 0.02, green: 0.035, blue: 0.07), panel: Color(red: 0.055, green: 0.08, blue: 0.14), glass: Color(red: 0.02, green: 0.04, blue: 0.09), silver: Color(red: 0.80, green: 0.86, blue: 0.94))
        case .soft:
            return GuidanceTheme(style: .soft, hint: Color(red: 0.95, green: 0.73, blue: 0.70),
                                 ok: Color(red: 0.73, green: 0.89, blue: 0.66),
                                 subject: Color(red: 0.95, green: 0.73, blue: 0.70), cueDesign: .rounded,
                                 cueWeight: .medium, cueLowercase: false, monospacedLabels: false, accent: Color(red: 0.95, green: 0.73, blue: 0.70), body: Color(red: 0.075, green: 0.08, blue: 0.08), panel: Color(red: 0.13, green: 0.14, blue: 0.14), glass: Color(red: 0.07, green: 0.08, blue: 0.07), silver: Color(red: 0.90, green: 0.91, blue: 0.88))
        case .minimal:
            return GuidanceTheme(style: .minimal, hint: .white, ok: Color(red: 0.84, green: 0.94, blue: 0.72),
                                 subject: .white, cueDesign: .default, cueWeight: .regular,
                                 cueLowercase: true, monospacedLabels: false, accent: Color(red: 0.95, green: 0.73, blue: 0.70), body: Color(red: 0.075, green: 0.08, blue: 0.08), panel: Color(red: 0.13, green: 0.14, blue: 0.14), glass: Color(red: 0.07, green: 0.08, blue: 0.07), silver: Color(red: 0.90, green: 0.91, blue: 0.88))
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
