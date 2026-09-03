// swift-tools-version:5.9
import PackageDescription

// Repository-managed local package: the reusable/testable slice of MyKhaya's
// WidgetKit domain logic (snapshot models, App Group store, pure calendar/
// event/to-do display helpers). Everything WidgetKit- or SwiftUI-rendering
// specific (Widget structs, TimelineProviders' protocol conformance, View
// bodies) stays in apps/ios-shell/native/widgets/ — an app extension's
// compiled code cannot be linked by XCTest (verified: TEST_HOST against a
// built .appex fails identically for hosted and logic-only test bundles),
// so this package exists specifically to give the shared logic a host that
// swift test/xcodebuild CAN link against. See docs/mobile/ios-widgets.md.
let package = Package(
    name: "MyKhayaWidgetCore",
    platforms: [
        // Must be <= the LOWEST deployment target of any consuming Xcode
        // target, not just the widget extension's own 16.0 floor — the App
        // target imports this package too, at 15.0 (see
        // IPHONEOS_DEPLOYMENT_TARGET in ios/App/App.xcodeproj). Nothing
        // here uses an iOS 16+-only API (WidgetCenter is iOS 14+), so this
        // reflects a real constraint, not a lowest-common-denominator
        // workaround. Re-verify before raising if App's own floor changes.
        .iOS(.v15)
    ],
    products: [
        .library(
            name: "MyKhayaWidgetCore",
            type: .static,
            targets: ["MyKhayaWidgetCore"]
        )
    ],
    targets: [
        .target(
            name: "MyKhayaWidgetCore"
        ),
        .testTarget(
            name: "MyKhayaWidgetCoreTests",
            dependencies: ["MyKhayaWidgetCore"]
        )
    ]
)
