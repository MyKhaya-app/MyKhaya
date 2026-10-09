import XCTest
@testable import MyKhayaWidgetCore

/// DEV and PROD are separate apps whose Info.plists are filled in from the
/// build configuration. These tests use Info dictionaries exactly as each
/// build produces them (app and widget), and check widget-tap routing can
/// never cross from one app to the other.
final class MyKhayaEnvironmentTests: XCTestCase {
    private let devApp: [String: Any] = [
        "MyKhayaEnvironment": "development",
        "MyKhayaURLScheme": "mykhaya",
        "MyKhayaAppGroup": "group.app.mykhaya.mobile",
        "MyKhayaServerHost": "dev.mykhaya.app",
    ]
    private let prodApp: [String: Any] = [
        "MyKhayaEnvironment": "production",
        "MyKhayaURLScheme": "mykhaya-prod",
        "MyKhayaAppGroup": "group.app.mykhaya.mobile.prod",
        "MyKhayaServerHost": "mykhaya.app",
    ]

    private func widget(of app: [String: Any]) -> [String: Any] {
        var info = app
        info.removeValue(forKey: "MyKhayaServerHost")
        return info
    }

    // MARK: - Environment

    func testDevAppEnvironment() throws {
        let env = try XCTUnwrap(MyKhayaEnvironment(infoDictionary: devApp))
        XCTAssertEqual(env.name, "development")
        XCTAssertEqual(env.urlScheme, "mykhaya")
        XCTAssertEqual(env.appGroup, "group.app.mykhaya.mobile")
        XCTAssertEqual(env.serverURL, URL(string: "https://dev.mykhaya.app"))
    }

    func testProdAppEnvironment() throws {
        let env = try XCTUnwrap(MyKhayaEnvironment(infoDictionary: prodApp))
        XCTAssertEqual(env.name, "production")
        XCTAssertEqual(env.urlScheme, "mykhaya-prod")
        XCTAssertEqual(env.appGroup, "group.app.mykhaya.mobile.prod")
        XCTAssertEqual(env.serverURL, URL(string: "https://mykhaya.app"))
    }

    func testWidgetAgreesWithItsAppAndHasNoServer() throws {
        for app in [devApp, prodApp] {
            let appEnv = try XCTUnwrap(MyKhayaEnvironment(infoDictionary: app))
            let widgetEnv = try XCTUnwrap(MyKhayaEnvironment(infoDictionary: widget(of: app)))
            XCTAssertEqual(widgetEnv.appGroup, appEnv.appGroup)
            XCTAssertEqual(widgetEnv.urlScheme, appEnv.urlScheme)
            XCTAssertNil(widgetEnv.serverHost)
            XCTAssertNil(widgetEnv.serverURL)
        }
    }

    func testDevAndProdShareNothingThatMustBeUnique() throws {
        let dev = try XCTUnwrap(MyKhayaEnvironment(infoDictionary: devApp))
        let prod = try XCTUnwrap(MyKhayaEnvironment(infoDictionary: prodApp))
        XCTAssertNotEqual(dev.urlScheme, prod.urlScheme)
        XCTAssertNotEqual(dev.appGroup, prod.appGroup)
        XCTAssertNotEqual(dev.serverHost, prod.serverHost)
    }

    func testUnexpandedOrMissingValuesAreRejectedNotGuessed() {
        for key in ["MyKhayaEnvironment", "MyKhayaURLScheme", "MyKhayaAppGroup"] {
            var missing = devApp
            missing.removeValue(forKey: key)
            XCTAssertNil(MyKhayaEnvironment(infoDictionary: missing), "missing \(key)")

            var unexpanded = devApp
            unexpanded[key] = "$(MYKHAYA_VALUE)"
            XCTAssertNil(MyKhayaEnvironment(infoDictionary: unexpanded), "unexpanded \(key)")

            var empty = devApp
            empty[key] = ""
            XCTAssertNil(MyKhayaEnvironment(infoDictionary: empty), "empty \(key)")
        }
        var unexpandedHost = devApp
        unexpandedHost["MyKhayaServerHost"] = "$(MYKHAYA_SERVER_HOST)"
        XCTAssertNil(MyKhayaEnvironment(infoDictionary: unexpandedHost))
        XCTAssertNil(MyKhayaEnvironment(infoDictionary: nil))
    }

    func testMalformedValuesAreRejected() {
        var badEnvironment = devApp
        badEnvironment["MyKhayaEnvironment"] = "staging"
        XCTAssertNil(MyKhayaEnvironment(infoDictionary: badEnvironment))

        var badScheme = devApp
        badScheme["MyKhayaURLScheme"] = "my khaya"
        XCTAssertNil(MyKhayaEnvironment(infoDictionary: badScheme))

        var badGroup = devApp
        badGroup["MyKhayaAppGroup"] = "app.mykhaya.mobile"
        XCTAssertNil(MyKhayaEnvironment(infoDictionary: badGroup))

        for host in ["https://dev.mykhaya.app", "dev.mykhaya.app/path", "localhost", "DEV.mykhaya.app"] {
            var badHost = devApp
            badHost["MyKhayaServerHost"] = host
            XCTAssertNil(MyKhayaEnvironment(infoDictionary: badHost), host)
        }
    }

    // MARK: - Widget tap routing

    func testEachEnvironmentRoutesItsOwnWidgetTaps() throws {
        for scheme in ["mykhaya", "mykhaya-prod"] {
            let url = try XCTUnwrap(WidgetDeepLinkRoute.url(forPath: "/calendar?event=abc-123", scheme: scheme))
            XCTAssertEqual(url.scheme, scheme)
            XCTAssertEqual(WidgetDeepLinkRoute.path(from: url, expectedScheme: scheme), "/calendar?event=abc-123")
        }
    }

    func testAWidgetTapNeverOpensTheOtherApp() throws {
        let devTap = try XCTUnwrap(WidgetDeepLinkRoute.url(forPath: "/calendar", scheme: "mykhaya"))
        let prodTap = try XCTUnwrap(WidgetDeepLinkRoute.url(forPath: "/calendar", scheme: "mykhaya-prod"))
        XCTAssertNil(WidgetDeepLinkRoute.path(from: devTap, expectedScheme: "mykhaya-prod"))
        XCTAssertNil(WidgetDeepLinkRoute.path(from: prodTap, expectedScheme: "mykhaya"))
    }

    func testRoutingRejectsAnythingButASameOriginPath() throws {
        let rejected = [
            "mykhaya://elsewhere?path=/calendar",
            "mykhaya://open",
            "mykhaya://open?path=calendar",
            "mykhaya://open?path=//evil.example/phish",
            "https://open?path=/calendar",
        ]
        for string in rejected {
            let url = try XCTUnwrap(URL(string: string))
            XCTAssertNil(WidgetDeepLinkRoute.path(from: url, expectedScheme: "mykhaya"), string)
        }
        let uppercase = try XCTUnwrap(URL(string: "MYKHAYA://open?path=/login"))
        XCTAssertEqual(WidgetDeepLinkRoute.path(from: uppercase, expectedScheme: "mykhaya"), "/login")
    }

    func testAppGroupDerivationStillMatchesTheConfiguredGroups() throws {
        // The Stage 1 fallback (no MyKhayaAppGroup in Info.plist) must agree
        // with the configured values for both apps and both widgets.
        for (app, bundleId) in [(devApp, "app.mykhaya.mobile"), (prodApp, "app.mykhaya.mobile.prod")] {
            let configured = try XCTUnwrap(MyKhayaEnvironment(infoDictionary: app)).appGroup
            XCTAssertEqual(WidgetSnapshotStore.groupIdentifier(forBundleIdentifier: bundleId), configured)
            XCTAssertEqual(WidgetSnapshotStore.groupIdentifier(forBundleIdentifier: "\(bundleId).widgets"), configured)
        }
    }
}
