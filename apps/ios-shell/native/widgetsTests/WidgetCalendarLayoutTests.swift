import XCTest
@testable import MyKhayaWidgets

// See WidgetSnapshotStoreTests.swift's header comment re: wiring this into
// a runnable Xcode test target on the Mac. Covers CalendarViews.swift's
// pure month-grid/day-grouping helpers — the Swift-side logic equivalent
// of widget-snapshot.test.ts's "Calendar" describe block, since these two
// functions (unlike event selection/ordering, owned by the TS layer) are
// genuinely native-only.

final class WidgetCalendarLayoutTests: XCTestCase {
    private var utcCalendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        calendar.firstWeekday = 2 // Monday, matching MyKhaya's web calendar
        return calendar
    }

    private func date(_ iso: String) -> Date {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: iso)!
    }

    func test_monthGrid_alwaysReturns42Days_sixCompleteWeeks() {
        // A five-week month (e.g. Feb 2026, starts Sunday) and a six-week
        // month (e.g. Aug 2026, starts Saturday) both produce a fixed
        // 6x7 grid — the day-cell view is what dims out-of-month days,
        // not the grid shape itself.
        let fiveWeekMonth = date("2026-02-15T00:00:00Z")
        let sixWeekMonth = date("2026-08-15T00:00:00Z")
        XCTAssertEqual(monthGridDays(containing: fiveWeekMonth, calendar: utcCalendar).count, 42)
        XCTAssertEqual(monthGridDays(containing: sixWeekMonth, calendar: utcCalendar).count, 42)
    }

    func test_monthGrid_includesLeadingDaysFromPreviousMonth() {
        // September 2026 starts on a Tuesday — the grid's first row must
        // include the trailing days of August to fill the week.
        let reference = date("2026-09-15T00:00:00Z")
        let days = monthGridDays(containing: reference, calendar: utcCalendar)
        let firstDayMonth = utcCalendar.component(.month, from: days[0])
        XCTAssertEqual(firstDayMonth, 8, "grid must start with the previous month's trailing days, not clip them")
    }

    func test_eventsByDay_multiDayEventAppearsOnEveryDayItSpans() {
        let multiDay = WidgetEvent(
            id: "e1", title: "Holiday", startAt: "2026-09-02T00:00:00.000Z", endAt: "2026-09-05T00:00:00.000Z",
            isAllDay: true, timezone: "Europe/London", colorHex: "#00ff00", deepLink: "/calendar?event=e1"
        )
        let grouped = eventsByDay([multiDay], calendar: utcCalendar)
        for day in ["2026-9-2", "2026-9-3", "2026-9-4"] {
            XCTAssertEqual(grouped[day]?.count, 1, "expected the multi-day event on \(day)")
        }
        XCTAssertNil(grouped["2026-9-5"], "end_at is exclusive — the event should not appear on its end day")
    }

    func test_eventsByDay_severalEventsOnSameDayAllPresent() {
        let events = (0..<5).map { i in
            WidgetEvent(
                id: "e\(i)", title: "Event \(i)", startAt: "2026-09-10T0\(i):00:00.000Z", endAt: "2026-09-10T0\(i):30:00.000Z",
                isAllDay: false, timezone: "Europe/London", colorHex: "#0000ff", deepLink: "/calendar?event=e\(i)"
            )
        }
        let grouped = eventsByDay(events, calendar: utcCalendar)
        XCTAssertEqual(grouped["2026-9-10"]?.count, 5)
    }

    func test_dayKey_matchesAcrossEquivalentDates() {
        let a = date("2026-09-03T00:00:01Z")
        let b = date("2026-09-03T23:59:59Z")
        XCTAssertEqual(dayKey(a, calendar: utcCalendar), dayKey(b, calendar: utcCalendar))
    }
}
