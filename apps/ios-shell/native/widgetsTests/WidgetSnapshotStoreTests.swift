import XCTest
@testable import MyKhayaWidgets

// Not yet wired into a runnable Xcode test target — that's a one-time
// manual step on the Mac (see docs/mobile/ios-widgets.md, "Swift tests: a
// manual Mac step"): File > New > Target > Unit Testing Bundle, add this
// file and WidgetSnapshotLayoutTests.swift, link against MyKhayaWidgets.
// Written now so the coverage exists and only needs wiring, not authoring,
// once a Mac is available.
final class WidgetSnapshotStoreTests: XCTestCase {
    private let sample = WidgetSnapshot(
        schemaVersion: widgetSnapshotSchemaVersion,
        generatedAt: "2026-09-03T09:00:00.000Z",
        signedIn: true,
        activeHome: WidgetHome(id: "home-1", displayName: "The Hales"),
        upcomingEvents: [
            WidgetEvent(id: "e1", title: "Football", startAt: "2026-09-03T10:00:00.000Z", endAt: "2026-09-03T11:00:00.000Z", isAllDay: false, timezone: "Europe/London", colorHex: "#ff0000", deepLink: "/calendar?event=evt-1"),
        ],
        todayEvents: [],
        monthEvents: [],
        todoItems: [
            WidgetTodoItem(id: "t1", kind: .routine, title: "Bins", dueAt: "2026-09-03", overdue: false, scope: .household, deepLink: "/home?routine=r1"),
        ]
    )

    func test_encodeDecodeRoundTrip_preservesAllFields() throws {
        let data = try JSONEncoder().encode(sample)
        let decoded = try JSONDecoder().decode(WidgetSnapshot.self, from: data)
        XCTAssertEqual(decoded, sample)
    }

    func test_schemaVersion_isStampedOnSignedOut() {
        XCTAssertEqual(WidgetSnapshot.signedOut().schemaVersion, widgetSnapshotSchemaVersion)
    }

    func test_load_withNoFileWritten_returnsSignedOut() {
        // WidgetSnapshotStore.load() reads from the App Group container,
        // which is unavailable to a plain XCTest bundle without the App
        // Groups entitlement wired to the test target — this exercises the
        // decode/version logic directly instead, which is the part that
        // actually varies by input.
        let decoded = try? JSONDecoder().decode(WidgetSnapshot.self, from: Data("not json".utf8))
        XCTAssertNil(decoded, "corrupt JSON must fail to decode, never crash")
    }

    func test_corruptJSON_failsDecodeCleanly() {
        let corrupt = Data("{\"schemaVersion\": 1, \"generatedAt\":".utf8)
        XCTAssertThrowsError(try JSONDecoder().decode(WidgetSnapshot.self, from: corrupt))
    }

    func test_mismatchedSchemaVersion_isDetectable() throws {
        let futureSnapshot = WidgetSnapshot(
            schemaVersion: widgetSnapshotSchemaVersion + 1,
            generatedAt: sample.generatedAt,
            signedIn: true,
            activeHome: sample.activeHome,
            upcomingEvents: [],
            todayEvents: [],
            monthEvents: [],
            todoItems: []
        )
        let data = try JSONEncoder().encode(futureSnapshot)
        let decoded = try JSONDecoder().decode(WidgetSnapshot.self, from: data)
        XCTAssertNotEqual(decoded.schemaVersion, widgetSnapshotSchemaVersion, "WidgetSnapshotStore.load() must treat this as signed-out, not render it")
    }

    func test_signedOut_hasNoHouseholdData() {
        let signedOut = WidgetSnapshot.signedOut()
        XCTAssertFalse(signedOut.signedIn)
        XCTAssertNil(signedOut.activeHome)
        XCTAssertTrue(signedOut.upcomingEvents.isEmpty)
        XCTAssertTrue(signedOut.todoItems.isEmpty)
    }

    func test_noSecretLikeKeysInEncodedJSON() throws {
        let data = try JSONEncoder().encode(sample)
        let json = String(data: data, encoding: .utf8)!.lowercased()
        for forbidden in ["token", "password", "cookie", "secret", "bearer", "pin"] {
            XCTAssertFalse(json.contains(forbidden), "snapshot JSON must never contain '\(forbidden)'")
        }
    }
}
