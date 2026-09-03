import XCTest
@testable import MyKhayaWidgetCore

/// Migrated from apps/ios-shell/native/widgetsTests/WidgetSnapshotStoreTests.swift
/// (never previously runnable — an app extension's compiled code cannot be
/// an XCTest host; this package exists so it finally can be). Covers the
/// Codable contract and WidgetSnapshotStore's decode/validate logic
/// directly (via the internal `decode(_:)` factored out of `load()`),
/// since the real App Group container isn't available to a plain
/// `swift test` process.
final class WidgetSnapshotTests: XCTestCase {
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

    // MARK: Codable round-trip / schema

    func test_encodeDecodeRoundTrip_preservesAllFields() throws {
        let data = try JSONEncoder().encode(sample)
        let decoded = try JSONDecoder().decode(WidgetSnapshot.self, from: data)
        XCTAssertEqual(decoded, sample)
    }

    func test_schemaVersion_isStampedOnSignedOut() {
        XCTAssertEqual(WidgetSnapshot.signedOut().schemaVersion, widgetSnapshotSchemaVersion)
    }

    func test_signedOut_hasNoHouseholdData() {
        let signedOut = WidgetSnapshot.signedOut()
        XCTAssertFalse(signedOut.signedIn)
        XCTAssertNil(signedOut.activeHome)
        XCTAssertTrue(signedOut.upcomingEvents.isEmpty)
        XCTAssertTrue(signedOut.todayEvents.isEmpty)
        XCTAssertTrue(signedOut.monthEvents.isEmpty)
        XCTAssertTrue(signedOut.todoItems.isEmpty)
    }

    func test_signedIn_roundTrip_preservesActiveHome() throws {
        let data = try JSONEncoder().encode(sample)
        let decoded = try JSONDecoder().decode(WidgetSnapshot.self, from: data)
        XCTAssertTrue(decoded.signedIn)
        XCTAssertEqual(decoded.activeHome, WidgetHome(id: "home-1", displayName: "The Hales"))
    }

    func test_noSecretLikeKeysInEncodedJSON() throws {
        let data = try JSONEncoder().encode(sample)
        let json = String(data: data, encoding: .utf8)!.lowercased()
        for forbidden in ["token", "password", "cookie", "secret", "bearer", "pin"] {
            XCTAssertFalse(json.contains(forbidden), "snapshot JSON must never contain '\(forbidden)'")
        }
    }

    // MARK: WidgetSnapshotStore.decode — corrupt/unsupported snapshot handling

    func test_decode_corruptJSON_fallsBackToSignedOut() {
        let corrupt = Data("{\"schemaVersion\": 1, \"generatedAt\":".utf8)
        let decoded = WidgetSnapshotStore.decode(corrupt)
        XCTAssertFalse(decoded.signedIn, "corrupt JSON must collapse to signed-out, never crash or guess")
    }

    func test_decode_notJSON_fallsBackToSignedOut() {
        let decoded = WidgetSnapshotStore.decode(Data("not json".utf8))
        XCTAssertFalse(decoded.signedIn)
    }

    func test_decode_mismatchedSchemaVersion_fallsBackToSignedOut() throws {
        let futureSnapshot = WidgetSnapshot(
            schemaVersion: widgetSnapshotSchemaVersion + 1,
            generatedAt: sample.generatedAt,
            signedIn: true,
            activeHome: sample.activeHome,
            upcomingEvents: sample.upcomingEvents,
            todayEvents: [],
            monthEvents: [],
            todoItems: []
        )
        let data = try JSONEncoder().encode(futureSnapshot)
        let decoded = WidgetSnapshotStore.decode(data)
        XCTAssertFalse(decoded.signedIn, "a schema version the extension doesn't understand must never be rendered")
        XCTAssertEqual(decoded.schemaVersion, widgetSnapshotSchemaVersion, "fallback must stamp the extension's own current schema version")
    }

    func test_decode_matchingSchemaVersion_passesThrough() throws {
        let data = try JSONEncoder().encode(sample)
        let decoded = WidgetSnapshotStore.decode(data)
        XCTAssertEqual(decoded, sample)
    }
}
