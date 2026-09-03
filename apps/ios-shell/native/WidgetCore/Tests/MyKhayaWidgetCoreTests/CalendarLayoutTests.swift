import XCTest
@testable import MyKhayaWidgetCore

/// Migrated from apps/ios-shell/native/widgetsTests/WidgetCalendarLayoutTests.swift,
/// extended with more weekday/boundary coverage. Covers CalendarViews.swift's
/// former pure month-grid/day-grouping helpers — the Swift-side logic
/// equivalent of widget-snapshot.test.ts's "Calendar" describe block, since
/// these functions (unlike event selection/ordering, owned by the TS layer)
/// are genuinely native-only.
final class CalendarLayoutTests: XCTestCase {
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

    // MARK: Month grid shape

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

    func test_monthGrid_includesTrailingDaysFromNextMonth() {
        // September 2026 has 30 days starting on a Tuesday — 30 days after a
        // Tuesday start needs trailing October days to complete the last row.
        let reference = date("2026-09-15T00:00:00Z")
        let days = monthGridDays(containing: reference, calendar: utcCalendar)
        let lastDayMonth = utcCalendar.component(.month, from: days[days.count - 1])
        XCTAssertEqual(lastDayMonth, 10, "grid must end with the next month's leading days, not clip them")
    }

    func test_monthGrid_startsOnSundayMonth_stillReturns42Days() {
        // A month whose first day IS the configured firstWeekday (Monday)
        // needs no leading days at all — still a full 6x7 grid.
        let mondayStartMonth = date("2026-06-15T00:00:00Z") // June 2026 starts Monday
        let days = monthGridDays(containing: mondayStartMonth, calendar: utcCalendar)
        XCTAssertEqual(days.count, 42)
        XCTAssertEqual(utcCalendar.component(.month, from: days[0]), 6, "no leading days needed when the month already starts on firstWeekday")
    }

    func test_monthGrid_differentFirstWeekday_shiftsLeadingDays() {
        var sundayFirst = utcCalendar
        sundayFirst.firstWeekday = 1 // Sunday
        let reference = date("2026-09-15T00:00:00Z") // Sept 2026 starts Tuesday
        let mondayFirstDays = monthGridDays(containing: reference, calendar: utcCalendar)
        let sundayFirstDays = monthGridDays(containing: reference, calendar: sundayFirst)
        XCTAssertNotEqual(mondayFirstDays[0], sundayFirstDays[0], "changing firstWeekday must change which leading day the grid starts on")
    }

    // MARK: dayKey

    func test_dayKey_matchesAcrossEquivalentDates() {
        let a = date("2026-09-03T00:00:01Z")
        let b = date("2026-09-03T23:59:59Z")
        XCTAssertEqual(dayKey(a, calendar: utcCalendar), dayKey(b, calendar: utcCalendar))
    }

    func test_dayKey_differsAcrossMidnightBoundary() {
        let justBeforeMidnight = date("2026-09-03T23:59:59Z")
        let justAfterMidnight = date("2026-09-04T00:00:01Z")
        XCTAssertNotEqual(dayKey(justBeforeMidnight, calendar: utcCalendar), dayKey(justAfterMidnight, calendar: utcCalendar))
    }

    // MARK: eventsByDay

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

    func test_eventsByDay_singleDayEvent_appearsOnlyOnce() {
        let event = WidgetEvent(
            id: "e1", title: "Standup", startAt: "2026-09-10T09:00:00.000Z", endAt: "2026-09-10T09:30:00.000Z",
            isAllDay: false, timezone: "Europe/London", colorHex: "#000000", deepLink: "/calendar?event=e1"
        )
        let grouped = eventsByDay([event], calendar: utcCalendar)
        XCTAssertEqual(grouped.count, 1)
        XCTAssertEqual(grouped["2026-9-10"]?.count, 1)
    }

    func test_eventsByDay_unparsableStartDate_isSkippedNotCrashed() {
        let broken = WidgetEvent(
            id: "e1", title: "Bad", startAt: "not-a-date", endAt: "also-not-a-date",
            isAllDay: false, timezone: "UTC", colorHex: "#000000", deepLink: "/calendar?event=e1"
        )
        let grouped = eventsByDay([broken], calendar: utcCalendar)
        XCTAssertTrue(grouped.isEmpty, "an event with an unparsable start date must be skipped, not crash")
    }
}
