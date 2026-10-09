import XCTest
@testable import MyKhayaWidgetCore

/// DEV and PROD are separate apps built from the same sources, each with its
/// own App Group. The group is derived from the running bundle identifier so
/// shared code never carries one environment's identifier into the other, and
/// so the main app and its widget extension always resolve the same group.
final class WidgetAppGroupTests: XCTestCase {
    func testDevAppAndDevWidgetShareTheDevGroup() {
        XCTAssertEqual(
            WidgetSnapshotStore.groupIdentifier(forBundleIdentifier: "app.mykhaya.mobile"),
            "group.app.mykhaya.mobile"
        )
        XCTAssertEqual(
            WidgetSnapshotStore.groupIdentifier(forBundleIdentifier: "app.mykhaya.mobile.widgets"),
            "group.app.mykhaya.mobile"
        )
    }

    func testProdAppAndProdWidgetShareTheProdGroup() {
        XCTAssertEqual(
            WidgetSnapshotStore.groupIdentifier(forBundleIdentifier: "app.mykhaya.mobile.prod"),
            "group.app.mykhaya.mobile.prod"
        )
        XCTAssertEqual(
            WidgetSnapshotStore.groupIdentifier(forBundleIdentifier: "app.mykhaya.mobile.prod.widgets"),
            "group.app.mykhaya.mobile.prod"
        )
    }

    func testDevNeverResolvesToTheProdGroupOrTheReverse() {
        let dev = WidgetSnapshotStore.groupIdentifier(forBundleIdentifier: "app.mykhaya.mobile")
        let prod = WidgetSnapshotStore.groupIdentifier(forBundleIdentifier: "app.mykhaya.mobile.prod")
        XCTAssertNotEqual(dev, prod)
    }

    func testMissingOrEmptyBundleIdentifierHasNoGroup() {
        XCTAssertNil(WidgetSnapshotStore.groupIdentifier(forBundleIdentifier: nil))
        XCTAssertNil(WidgetSnapshotStore.groupIdentifier(forBundleIdentifier: ""))
        XCTAssertNil(WidgetSnapshotStore.groupIdentifier(forBundleIdentifier: ".widgets"))
    }

    /// Without an entitled App Group (the plain `swift test` process has
    /// none), saving and clearing must be harmless no-ops and loading must
    /// fall back to the signed-out placeholder: never a crash.
    func testStoreWithoutAnEntitledGroupNeverCrashes() {
        WidgetSnapshotStore.save(WidgetSnapshot.signedOut())
        WidgetSnapshotStore.clear()
        let loaded = WidgetSnapshotStore.load()
        XCTAssertFalse(loaded.signedIn)
        XCTAssertNil(loaded.activeHome)
    }
}
