import Foundation

// What the camera screen shows while a shot is pinned, and how much of it. Pure logic with no UI
// dependency, so it is unit-tested with `swift test`. The app maps these flags onto views.
//
// A preset is (style, level). The style picks the look (and later the wording); the level picks how
// much information is shown. Both feed one table, so 3 styles x 4 levels needs no hand-built screens.

public enum GuidanceStyle: String, Codable, CaseIterable, Sendable {
    /// Today's UI: every number for people who want it.
    case full
    /// Toned down and friendly, the XHS-leaning look.
    case soft
    /// Sleek and quiet; nearly nothing until something is off.
    case minimal

    /// The level a style starts at. Full matches today's screen; the others start gentler.
    public var defaultLevel: GuidanceLevel {
        switch self {
        case .full: return .detailed
        case .soft, .minimal: return .helpful
        }
    }

    /// Soft and Minimal stop at Detailed: raw numbers belong to Full info.
    public var maxLevel: GuidanceLevel {
        switch self {
        case .full: return .everything
        case .soft, .minimal: return .detailed
        }
    }
}

public enum GuidanceLevel: Int, Codable, CaseIterable, Comparable, Sendable {
    case essentials = 0, helpful, detailed, everything
    public static func < (a: GuidanceLevel, b: GuidanceLevel) -> Bool { a.rawValue < b.rawValue }
}

public enum CueRowStyle: String, Codable, Sendable { case off, topOnly, topPlusCount }
public enum LevelIndicatorStyle: String, Codable, Sendable { case off, subtle, full }
public enum ZoomDetail: String, Codable, Sendable { case simple, ruler }

/// One flag per visual element.
public struct GuidanceDisplay: Codable, Equatable, Sendable {
    public var cueRow: CueRowStyle
    public var levelIndicator: LevelIndicatorStyle
    public var subjectBrackets: Bool
    public var headCues: Bool
    public var detectionBoxes: Bool
    public var debugReadout: Bool
    public var zoomDetail: ZoomDetail
    public var haptics: Bool
    /// The last-photo thumbnail in the corner. On in every style, including Minimal.
    public var photoThumbnail: Bool

    /// The preset table. `developerReadout` gates the two raw-data flags that only exist at
    /// `.everything`, so a normal user never sees them even in Full info.
    public static func make(style: GuidanceStyle, level: GuidanceLevel, developerReadout: Bool = false) -> GuidanceDisplay {
        let level = min(level, style.maxLevel)
        let indicator: LevelIndicatorStyle
        switch (style, level) {
        case (_, .essentials): indicator = .off
        case (.full, _): indicator = .full
        case (_, .helpful): indicator = .subtle
        default: indicator = .full
        }
        return GuidanceDisplay(
            cueRow: level == .essentials || level == .helpful ? .topOnly : .topPlusCount,
            levelIndicator: indicator,
            subjectBrackets: level >= .helpful,
            headCues: level >= .helpful,
            detectionBoxes: level == .everything && developerReadout,
            debugReadout: level == .everything && developerReadout,
            zoomDetail: style == .full ? .ruler : .simple,
            haptics: true,
            photoThumbnail: true)
    }

    func applying(_ o: GuidanceOverrides) -> GuidanceDisplay {
        var d = self
        if let v = o.cueRow { d.cueRow = v }
        if let v = o.levelIndicator { d.levelIndicator = v }
        if let v = o.subjectBrackets { d.subjectBrackets = v }
        if let v = o.headCues { d.headCues = v }
        if let v = o.detectionBoxes { d.detectionBoxes = v }
        if let v = o.debugReadout { d.debugReadout = v }
        if let v = o.zoomDetail { d.zoomDetail = v }
        if let v = o.haptics { d.haptics = v }
        return d
    }
}

/// Per-toggle changes on top of a preset ("Fine-tune"). Nil means "follow the preset".
public struct GuidanceOverrides: Codable, Equatable, Sendable {
    public var cueRow: CueRowStyle?
    public var levelIndicator: LevelIndicatorStyle?
    public var subjectBrackets: Bool?
    public var headCues: Bool?
    public var detectionBoxes: Bool?
    public var debugReadout: Bool?
    public var zoomDetail: ZoomDetail?
    public var haptics: Bool?
    public init() {}
    public var isEmpty: Bool { self == GuidanceOverrides() }
}

/// Everything the user chose: style, a level remembered per style, fine-tune overrides and the
/// developer toggle. Codable so the app can store it as one value.
public struct GuidancePrefs: Codable, Equatable, Sendable {
    public private(set) var style: GuidanceStyle
    private var levels: [String: GuidanceLevel]
    public private(set) var overrides: GuidanceOverrides
    public var developerReadout: Bool

    public init(style: GuidanceStyle = .full) {
        self.style = style
        levels = [:]
        overrides = GuidanceOverrides()
        developerReadout = false
    }

    /// The level for the current style, clamped to what the style allows.
    public var level: GuidanceLevel {
        get { min(levels[style.rawValue] ?? style.defaultLevel, style.maxLevel) }
        set { levels[style.rawValue] = min(newValue, style.maxLevel); normalize() }
    }

    /// Switching style keeps each style's own level but drops fine-tune overrides, which were
    /// relative to the old preset.
    public mutating func select(_ s: GuidanceStyle) {
        style = s
        overrides = GuidanceOverrides()
    }

    /// The flags to render: the preset, then fine-tune overrides.
    public var display: GuidanceDisplay {
        GuidanceDisplay.make(style: style, level: level, developerReadout: developerReadout).applying(overrides)
    }

    /// True once any fine-tune toggle differs from the preset.
    public var isCustom: Bool { !overrides.isEmpty }

    /// Set one flag. An override equal to the preset is dropped, so Custom switches off again when
    /// the user puts every toggle back.
    public mutating func override(_ edit: (inout GuidanceOverrides) -> Void) {
        edit(&overrides)
        normalize()
    }

    public mutating func resetOverrides() { overrides = GuidanceOverrides() }

    private mutating func normalize() {
        let base = GuidanceDisplay.make(style: style, level: level, developerReadout: developerReadout)
        func keep<T: Equatable>(_ o: T?, _ b: T) -> T? { o == b ? nil : o }
        overrides.cueRow = keep(overrides.cueRow, base.cueRow)
        overrides.levelIndicator = keep(overrides.levelIndicator, base.levelIndicator)
        overrides.subjectBrackets = keep(overrides.subjectBrackets, base.subjectBrackets)
        overrides.headCues = keep(overrides.headCues, base.headCues)
        overrides.detectionBoxes = keep(overrides.detectionBoxes, base.detectionBoxes)
        overrides.debugReadout = keep(overrides.debugReadout, base.debugReadout)
        overrides.zoomDetail = keep(overrides.zoomDetail, base.zoomDetail)
        overrides.haptics = keep(overrides.haptics, base.haptics)
    }

    /// First launch after this ships: carry the two older switches over so nobody loses a setting.
    /// Existing users stay on Full info, which is the screen they already have.
    /// - `liveSubjectCues`: "Live head cues (experimental)"; off by default in the old UI.
    /// - `guidanceDebug`: "Show detection boxes".
    public static func migrated(liveSubjectCues: Bool, guidanceDebug: Bool) -> GuidancePrefs {
        var p = GuidancePrefs(style: .full)
        p.developerReadout = guidanceDebug
        p.override {
            $0.headCues = liveSubjectCues
            $0.detectionBoxes = guidanceDebug
            $0.debugReadout = guidanceDebug
        }
        return p
    }
}
