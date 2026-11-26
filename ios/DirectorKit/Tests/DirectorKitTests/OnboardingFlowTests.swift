import XCTest
@testable import DirectorKit

final class OnboardingFlowTests: XCTestCase {
    func testPagesRunInOrderAndFinishAfterTheLast() {
        var flow = OnboardingFlow()
        XCTAssertEqual(OnboardingFlow.pageCount, 5)
        XCTAssertTrue(flow.isFirst); XCTAssertFalse(flow.isLast); XCTAssertEqual(flow.index, 0)
        var seen = [flow.page]
        while !flow.next() { seen.append(flow.page) }
        XCTAssertEqual(seen, [.welcome, .howItWorks, .privacy, .permissions, .connect])
        XCTAssertTrue(flow.isLast)
        XCTAssertTrue(flow.next(), "Next on the last page means the flow is finished")
        XCTAssertEqual(flow.page, .connect, "and it stays on the last page")
    }

    func testBackStopsAtTheFirstPage() {
        var flow = OnboardingFlow(page: .privacy)
        flow.back(); XCTAssertEqual(flow.page, .howItWorks)
        flow.back(); flow.back(); flow.back()
        XCTAssertEqual(flow.page, .welcome)
    }

    func testSkipGoesToTheConnectPageAndIsNotOfferedThere() {
        for start in OnboardingPage.allCases {
            var flow = OnboardingFlow(page: start)
            XCTAssertEqual(flow.canSkip, start != .connect)
            flow.skip()
            XCTAssertEqual(flow.page, .connect)
            XCTAssertFalse(flow.canSkip)
        }
    }

    func testStoreRemembersCompletionAndCanBeReset() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "onboarding-test-\(UUID().uuidString)"))
        XCTAssertFalse(OnboardingStore.isCompleted(defaults), "a fresh install shows the introduction")
        OnboardingStore.markCompleted(defaults)
        XCTAssertTrue(OnboardingStore.isCompleted(defaults))
        OnboardingStore.reset(defaults)
        XCTAssertFalse(OnboardingStore.isCompleted(defaults))
        XCTAssertEqual(OnboardingStore.completedKey, "digi.onboarding.completed")
    }
}
