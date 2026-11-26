import Foundation

/// The five first-run screens, in order.
public enum OnboardingPage: Int, CaseIterable, Sendable {
    case welcome, howItWorks, privacy, permissions, connect
}

/// Where the person is in the first-run introduction, and what Next, Back and Skip do.
/// Skip jumps to the last page (connecting a server) rather than leaving: the privacy and permission pages are
/// skipped, but the person still sees how to connect, and the last page carries a one-line note about photos.
public struct OnboardingFlow: Equatable, Sendable {
    public private(set) var page: OnboardingPage

    public init(page: OnboardingPage = .welcome) { self.page = page }

    public static let pageCount = OnboardingPage.allCases.count
    public var index: Int { page.rawValue }
    public var isFirst: Bool { page == .welcome }
    public var isLast: Bool { page == .connect }
    /// Skip is offered on every page but the last, which has its own "Set up later".
    public var canSkip: Bool { !isLast }

    /// Moves to the next page. Returns true when there is no next page, so the flow is finished.
    @discardableResult
    public mutating func next() -> Bool {
        guard let following = OnboardingPage(rawValue: page.rawValue + 1) else { return true }
        page = following
        return false
    }

    public mutating func back() {
        if let earlier = OnboardingPage(rawValue: page.rawValue - 1) { page = earlier }
    }

    public mutating func skip() { page = .connect }
}

/// Remembers, in UserDefaults, that the introduction has been seen.
public enum OnboardingStore {
    public static let completedKey = "digi.onboarding.completed"

    public static func isCompleted(_ defaults: UserDefaults = .standard) -> Bool { defaults.bool(forKey: completedKey) }
    public static func markCompleted(_ defaults: UserDefaults = .standard) { defaults.set(true, forKey: completedKey) }
    /// Makes the introduction show again the next time the app opens.
    public static func reset(_ defaults: UserDefaults = .standard) { defaults.set(false, forKey: completedKey) }
}
