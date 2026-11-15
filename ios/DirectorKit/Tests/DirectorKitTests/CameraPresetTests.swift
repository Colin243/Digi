import XCTest
@testable import DirectorKit

final class CameraPresetTests: XCTestCase {
    private func shot(light: String = "", lens: String = "", title: String = "t", framing: String = "") -> Shot {
        Shot(title: title, cameraPosition: "p", cameraHeight: "h", cameraAngle: "a", subjectPosition: "s",
             distanceAndFraming: framing, zoomOrLens: lens, lightingTip: light)
    }

    func testPlainShotChangesNothing() {
        XCTAssertTrue(CameraPreset.make(for: shot()).isEmpty)
    }

    func testBacklitBrightensAndBeatsOtherLightRules() {
        let p = CameraPreset.make(for: shot(light: "Backlit by low sun at golden hour, harsh rim light"))
        XCTAssertEqual(p.exposureBias, 0.7)
        XCTAssertEqual(p.reasons.first, .backlit)
    }

    func testOtherLightRules() {
        XCTAssertEqual(CameraPreset.make(for: shot(light: "dim indoor light")).exposureBias, 0.3)
        XCTAssertEqual(CameraPreset.make(for: shot(light: "harsh midday sun")).exposureBias, -0.3)
        XCTAssertEqual(CameraPreset.make(for: shot(light: "warm golden light from the side")).exposureBias, -0.3)
    }

    func testExplicitZoomAndFocalLength() {
        XCTAssertEqual(CameraPreset.make(for: shot(lens: "Use 1.5x")).zoom, 1.5)
        XCTAssertEqual(CameraPreset.make(for: shot(lens: "about 48mm equivalent")).zoom, 2)
        XCTAssertEqual(CameraPreset.make(for: shot(lens: "35mm")).zoom ?? 0, 1.5, accuracy: 0.06)
    }

    func testZoomIsClampedToTheAppRange() {
        XCTAssertEqual(CameraPreset.make(for: shot(lens: "5x telephoto")).zoom, 2)
        XCTAssertEqual(CameraPreset.make(for: shot(lens: "0.5x ultra-wide")).zoom, 1)
    }

    func testLensWords() {
        XCTAssertEqual(CameraPreset.make(for: shot(lens: "portrait lens look")).zoom, 2)
        XCTAssertEqual(CameraPreset.make(for: shot(lens: "stay on the main lens")).zoom, 1)
    }

    func testFlashOnlyWhenTheShotSaysSo() {
        XCTAssertEqual(CameraPreset.make(for: shot(light: "use fill flash")).flash, .on)
        XCTAssertEqual(CameraPreset.make(for: shot(light: "no flash please")).flash, .off)
        XCTAssertNil(CameraPreset.make(for: shot(light: "soft window light")).flash)
    }

    func testBiasStaysSmall() {
        for light in ["backlit", "dim", "harsh", "sunset"] {
            let b = CameraPreset.make(for: shot(light: light)).exposureBias ?? 0
            XCTAssertLessThanOrEqual(abs(b), 0.7)
        }
    }

    func testEveryReasonHasWords() {
        let reasons: [CameraPreset.Reason] = [.backlit, .dim, .harsh, .warm, .zoom(1.5), .zoom(2), .flashOn, .flashOff]
        for r in reasons { for s in GuidanceStyle.allCases { for l in [GuidanceLanguage.en, .zh] {
            XCTAssertFalse(GuidanceWording.text(r, style: s, language: l).isEmpty)
        } } }
    }
}
