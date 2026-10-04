import XCTest
@testable import MyKhayaWidgetCore

/// Covers currentlyShownEvent, eventTimeLabel, and dueLabel — the pure
/// display-formatting helpers extracted from the widget Views/Timeline
/// files. Full "next event"/"to-do" SELECTION and ORDERING logic
/// (which event is next, overdue-then-today-then-upcoming to-do ordering)
/// is computed upstream in apps/web/components/widget-snapshot.ts and is
/// already covered by that file's vitest suite — by the time a
/// WidgetSnapshot reaches this Swift code, `upcomingEvents`/`todoItems` are
/// already filtered and ordered. `currentlyShownEvent` only ever takes
/// `.first` of an already-ordered array; there is no independent Swift-side
/// selection algorithm to test beyond that contract and the ISO-8601
/// parsing it depends on (WidgetEvent.startDate/endDate), which is what
/// this file actually exercises.
final class EventDisplayTests: XCTestCase {
    private func event(id: String = "e1", start: String, end: String, allDay: Bool = false) -> WidgetEvent {
        WidgetEvent(id: id, title: "Event \(id)", startAt: start, endAt: end, isAllDay: allDay, timezone: "Europe/London", colorHex: "#ff0000", deepLink: "/calendar?event=\(id)")
    }

    // MARK: currentlyShownEvent

    func test_currentlyShownEvent_noEvents_returnsNil() {
        let snapshot = WidgetSnapshot.signedOut()
        XCTAssertNil(currentlyShownEvent(in: snapshot, at: Date()))
    }

    func test_currentlyShownEvent_returnsFirstUpcoming() {
        let e1 = event(id: "e1", start: "2026-09-03T10:00:00.000Z", end: "2026-09-03T11:00:00.000Z")
        let e2 = event(id: "e2", start: "2026-09-04T10:00:00.000Z", end: "2026-09-04T11:00:00.000Z")
        let snapshot = WidgetSnapshot(schemaVersion: widgetSnapshotSchemaVersion, generatedAt: "2026-09-03T09:00:00.000Z", signedIn: true, activeHome: nil, upcomingEvents: [e1, e2], todayEvents: [], monthEvents: [], todoItems: [])
        XCTAssertEqual(currentlyShownEvent(in: snapshot, at: Date())?.id, "e1")
    }

    // MARK: WidgetEvent date parsing — the real per-event logic this Swift code has

    func test_eventDates_parseWithFractionalSeconds() {
        let e = event(start: "2026-09-03T10:00:00.000Z", end: "2026-09-03T11:00:00.000Z")
        XCTAssertNotNil(e.startDate)
        XCTAssertNotNil(e.endDate)
    }

    func test_eventDates_parseWithoutFractionalSeconds() {
        let e = event(start: "2026-09-03T10:00:00Z", end: "2026-09-03T11:00:00Z")
        XCTAssertNotNil(e.startDate, "must fall back to the no-fraction ISO8601 formatter")
        XCTAssertNotNil(e.endDate)
    }

    func test_eventDates_unparsable_returnsNil() {
        let e = event(start: "not-a-date", end: "also-not-a-date")
        XCTAssertNil(e.startDate)
        XCTAssertNil(e.endDate)
    }

    func test_eventEndingExactlyNow_endDateEqualsReferenceInstant() {
        let now = "2026-09-03T12:00:00.000Z"
        let e = event(start: "2026-09-03T11:00:00.000Z", end: now)
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let referenceInstant = formatter.date(from: now)!
        XCTAssertEqual(e.endDate, referenceInstant)
    }

    func test_bstBoundary_summerTimeOffsetDoesNotAffectUTCParsing() {
        // 2026-06-15 12:00 UTC is 13:00 BST — the stored value is always UTC
        // (widget-snapshot.ts emits toISOString()), so parsing must not
        // apply any local-timezone shift regardless of the device's own
        // timezone or BST/GMT clock changes.
        let e = event(start: "2026-06-15T12:00:00.000Z", end: "2026-06-15T13:00:00.000Z")
        var utc = Calendar(identifier: .gregorian)
        utc.timeZone = TimeZone(identifier: "UTC")!
        XCTAssertEqual(utc.component(.hour, from: e.startDate!), 12)
    }

    // MARK: eventTimeLabel

    func test_eventTimeLabel_allDay_returnsAllDayRegardlessOfTimes() {
        let e = event(start: "2026-09-03T00:00:00.000Z", end: "2026-09-04T00:00:00.000Z", allDay: true)
        XCTAssertEqual(eventTimeLabel(e), "All day")
    }

    func test_eventTimeLabel_timed_containsEnDashSeparator() {
        let e = event(start: "2026-09-03T10:00:00.000Z", end: "2026-09-03T11:00:00.000Z")
        XCTAssertTrue(eventTimeLabel(e).contains("–"), "expected an en-dash-separated start–end range")
    }

    func test_eventTimeLabel_unparsableStart_returnsEmptyString() {
        let e = event(start: "not-a-date", end: "also-not-a-date")
        XCTAssertEqual(eventTimeLabel(e), "")
    }

    // MARK: dueLabel

    func test_dueLabel_overdueTakesPriorityOverDueDate() {
        let item = WidgetTodoItem(id: "t1", kind: .reminder, title: "Bins", dueAt: "2026-09-01", overdue: true, scope: .household, deepLink: "/x")
        XCTAssertEqual(dueLabel(for: item, now: Date()), "Overdue")
    }

    func test_dueLabel_dueToday_returnsToday() {
        let now = ISO8601DateFormatter().date(from: "2026-09-03T09:00:00Z")!
        let item = WidgetTodoItem(id: "t1", kind: .routine, title: "Bins", dueAt: "2026-09-03", overdue: false, scope: .household, deepLink: "/x")
        XCTAssertEqual(dueLabel(for: item, now: now), "Today")
    }

    func test_dueLabel_dueFuture_returnsUpcoming() {
        let now = ISO8601DateFormatter().date(from: "2026-09-03T09:00:00Z")!
        let item = WidgetTodoItem(id: "t1", kind: .routine, title: "Bins", dueAt: "2026-09-10", overdue: false, scope: .household, deepLink: "/x")
        XCTAssertEqual(dueLabel(for: item, now: now), "Upcoming")
    }

    func test_dueLabel_noDueDate_returnsEmptyString() {
        let item = WidgetTodoItem(id: "t1", kind: .reminder, title: "Someday", dueAt: nil, overdue: false, scope: .personal, deepLink: "/x")
        XCTAssertEqual(dueLabel(for: item, now: Date()), "")
    }

    func test_dueLabel_midnightBoundary_justBeforeVsJustAfter() {
        // dueAt "2026-09-03" should read "Today" right up to 23:59:59 on
        // that date and roll to "Upcoming" (relative to a due date that has
        // now passed into yesterday) once now crosses into the next day.
        let item = WidgetTodoItem(id: "t1", kind: .routine, title: "Bins", dueAt: "2026-09-03", overdue: false, scope: .household, deepLink: "/x")
        let justBeforeMidnight = ISO8601DateFormatter().date(from: "2026-09-03T23:59:59Z")!
        let justAfterMidnight = ISO8601DateFormatter().date(from: "2026-09-04T00:00:01Z")!
        XCTAssertEqual(dueLabel(for: item, now: justBeforeMidnight), "Today")
        XCTAssertNotEqual(dueLabel(for: item, now: justAfterMidnight), "Today")
    }

    // MARK: to-do model — kind/scope round-trip (ordering itself is TS-side, see file header)

    func test_todoItem_routineVsReminderKind_roundTrips() throws {
        let routine = WidgetTodoItem(id: "t1", kind: .routine, title: "Bins", dueAt: nil, overdue: false, scope: .household, deepLink: "/x")
        let reminder = WidgetTodoItem(id: "t2", kind: .reminder, title: "Call", dueAt: nil, overdue: false, scope: .personal, deepLink: "/y")
        for item in [routine, reminder] {
            let data = try JSONEncoder().encode(item)
            let decoded = try JSONDecoder().decode(WidgetTodoItem.self, from: data)
            XCTAssertEqual(decoded.kind, item.kind)
            XCTAssertEqual(decoded.scope, item.scope)
        }
    }
}
