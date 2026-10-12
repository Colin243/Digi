import XCTest

final class CameraUITests: XCTestCase {
    func testCaptureStudySettingPersistsAcrossLaunch() throws {
        let app = XCUIApplication()
        XCUIDevice.shared.orientation = .portrait
        app.launch()
        XCTAssertTrue(app.buttons["Camera options"].waitForExistence(timeout: 10))
        app.buttons["Camera options"].tap()
        app.scrollViews.firstMatch.swipeUp()
        let toggle = app.switches["Capture study"]
        XCTAssertTrue(toggle.waitForExistence(timeout: 3))
        XCTAssertTrue(toggle.isHittable)
        if (toggle.value as? String) != "1" { toggle.tap() }
        XCTAssertEqual(toggle.value as? String, "1")
        app.terminate()
        app.launch()
        app.buttons["Camera options"].tap()
        app.scrollViews.firstMatch.swipeUp()
        let restored = app.switches["Capture study"]
        XCTAssertTrue(restored.waitForExistence(timeout: 3))
        XCTAssertEqual(restored.value as? String, "1")
        restored.tap()
        XCTAssertEqual(restored.value as? String, "0")
    }
    func testOptionsAndReview() throws {
        let app = XCUIApplication()
        XCUIDevice.shared.orientation = .landscapeRight
        addUIInterruptionMonitor(withDescription: "Camera permission") { alert in
            if alert.buttons["Allow"].exists { alert.buttons["Allow"].tap(); return true }
            return false
        }
        app.launch()
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        if springboard.alerts.buttons["Allow"].waitForExistence(timeout: 3) { springboard.alerts.buttons["Allow"].tap() }
        XCTAssertTrue(app.buttons["Camera options"].waitForExistence(timeout: 10))
        app.buttons["Camera options"].tap()
        XCTAssertTrue(app.staticTexts["Shooting options"].waitForExistence(timeout: 3))
        XCTAssertTrue(app.staticTexts["Focus: Auto"].exists)
        XCTAssertTrue(app.sliders["Brightness"].exists)
        XCTAssertFalse(app.sliders["Brightness"].isEnabled)
        XCTAssertFalse(app.buttons["Auto focus"].isEnabled)
        let flash = app.segmentedControls["flash-mode"]
        XCTAssertTrue(flash.exists)
        XCTAssertTrue(flash.buttons["Off"].isSelected)
        // The simulator has no flash hardware; never offer a fake working flash.
        XCTAssertFalse(flash.isEnabled)
        app.scrollViews.firstMatch.swipeUp()
        XCTAssertFalse(app.switches["G12 Look"].exists)
        app.scrollViews.firstMatch.swipeDown()
        let grid = app.switches["Framing grid"]
        XCTAssertTrue(grid.exists)
        let oldValue = grid.value as? String
        grid.tap()
        XCTAssertNotEqual(grid.value as? String, oldValue)
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = "Camera options"
        screenshot.lifetime = .keepAlways
        add(screenshot)
        app.buttons["Done"].tap()
        app.buttons["Review last photo"].tap()
        XCTAssertTrue(app.staticTexts["Take a photo to see it here."].waitForExistence(timeout: 3))
        app.buttons["Done"].tap()
        XCTAssertTrue(app.buttons["Take photo"].exists)
        let cameraScreenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        cameraScreenshot.name = "Landscape camera"
        cameraScreenshot.lifetime = .keepAlways
        add(cameraScreenshot)
    }
    func testCameraPicker() throws {
        let app = XCUIApplication()
        XCUIDevice.shared.orientation = .portrait
        app.launch()
        let picker = app.buttons["camera-picker"]
        XCTAssertTrue(picker.waitForExistence(timeout: 10))
        picker.tap()
        XCTAssertTrue(app.navigationBars["Your cameras"].waitForExistence(timeout: 3))
        XCTAssertTrue(app.buttons["camera-G12"].isEnabled)
        XCTAssertFalse(app.buttons["camera-S95"].isEnabled)
        XCTAssertFalse(app.buttons["camera-G7 X"].isEnabled)
        let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        shot.name = "Camera picker portrait"
        shot.lifetime = .keepAlways
        add(shot)
        app.buttons["camera-G12"].tap()
        XCTAssertTrue(picker.waitForExistence(timeout: 3))
        XCUIDevice.shared.orientation = .landscapeRight
        picker.tap()
        XCTAssertTrue(app.navigationBars["Your cameras"].waitForExistence(timeout: 3))
        app.buttons["Done"].tap()
        XCTAssertTrue(picker.waitForExistence(timeout: 3))
    }

    func testRotationPreservesControlsAndPanels() throws {
        let app = XCUIApplication()
        XCUIDevice.shared.orientation = .portrait
        app.launch()
        XCTAssertTrue(app.buttons["Camera options"].waitForExistence(timeout: 10))
        func inspect(_ name: String, portrait: Bool) {
            let shutter = app.buttons["Take photo"]
            let options = app.buttons["Camera options"]
            let review = app.buttons["Review last photo"]
            // UIKit rotation can finish after XCTest's app-idle notification.
            // Wait for the actual layout and hit targets, not a fixed delay.
            let settled = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                (app.frame.height > app.frame.width) == portrait && options.isHittable && review.isHittable
            }, object: nil)
            XCTAssertEqual(XCTWaiter.wait(for: [settled], timeout: 3), .completed, "Rotation did not settle: \(name)")
            XCTAssertTrue(options.isHittable)
            XCTAssertTrue(review.isHittable)
            XCTAssertTrue(app.frame.contains(shutter.frame))
            XCTAssertEqual(app.frame.height > app.frame.width, portrait)
            if portrait {
                XCTAssertLessThan(abs(options.frame.midY - shutter.frame.midY), 25)
            } else {
                XCTAssertLessThan(abs(options.frame.midX - shutter.frame.midX), 25)
            }
            let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            shot.name = name
            shot.lifetime = .keepAlways
            add(shot)
        }
        inspect("Portrait camera", portrait: true)
        app.buttons["Camera options"].tap()
        XCUIDevice.shared.orientation = .landscapeLeft
        XCTAssertTrue(app.buttons["Done"].waitForExistence(timeout: 3))
        XCTAssertTrue(app.switches["Framing grid"].isHittable)
        app.buttons["Done"].tap()
        inspect("Landscape left camera", portrait: false)
        app.buttons["Review last photo"].tap()
        XCUIDevice.shared.orientation = .portrait
        XCTAssertTrue(app.staticTexts["Take a photo to see it here."].waitForExistence(timeout: 3))
        XCTAssertTrue(app.buttons["Done"].isHittable)
        app.buttons["Done"].tap()
        inspect("Portrait after review", portrait: true)
        XCUIDevice.shared.orientation = .landscapeRight
        inspect("Landscape right camera", portrait: false)
        XCUIDevice.shared.orientation = .portrait
        inspect("Portrait return", portrait: true)
    }

}
