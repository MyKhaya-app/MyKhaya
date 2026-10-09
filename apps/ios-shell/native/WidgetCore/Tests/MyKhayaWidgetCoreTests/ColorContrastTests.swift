import XCTest
@testable import MyKhayaWidgetCore

final class ColorContrastTests: XCTestCase {
    func test_white_isLight() {
        XCTAssertTrue(isLightBackground(hex: "#FFFFFF"))
    }

    func test_black_isNotLight() {
        XCTAssertFalse(isLightBackground(hex: "#000000"))
    }

    func test_brightYellow_isLight() {
        XCTAssertTrue(isLightBackground(hex: "#FFFF00"))
    }

    func test_navy_isNotLight() {
        XCTAssertFalse(isLightBackground(hex: "#000080"))
    }

    func test_hexWithoutHashPrefix_parsesTheSame() {
        XCTAssertEqual(isLightBackground(hex: "#FFFFFF"), isLightBackground(hex: "FFFFFF"))
    }

    func test_unparsableHex_fallsBackToLight() {
        XCTAssertTrue(isLightBackground(hex: "not-a-colour"))
    }

    func test_parseHexRGB_roundTripsComponents() throws {
        let rgb = try XCTUnwrap(parseHexRGB("#3366FF"))
        XCTAssertEqual(rgb.red, Double(0x33) / 255, accuracy: 0.0001)
        XCTAssertEqual(rgb.green, Double(0x66) / 255, accuracy: 0.0001)
        XCTAssertEqual(rgb.blue, Double(0xFF) / 255, accuracy: 0.0001)
    }
}
