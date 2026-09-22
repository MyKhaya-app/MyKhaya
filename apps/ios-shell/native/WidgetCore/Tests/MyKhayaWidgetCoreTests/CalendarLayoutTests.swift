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

    // MARK: Timezone boundary regression — all-day events must never leak
    // into an adjacent local day for a device outside UTC (see
    // localMidnightOfCalendarDay in CalendarLayout.swift). Real report: a
    // Sunday-only all-day event, and a Thursday birthday, both appeared to
    // spill onto the following day on a device running BST (UTC+1).

    private var londonSummerCalendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Europe/London")! // BST = UTC+1 in September
        calendar.firstWeekday = 2
        return calendar
    }

    private var newYorkCalendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "America/New_York")! // EDT = UTC-4 in September
        calendar.firstWeekday = 2
        return calendar
    }

    func test_eventsByDay_oneDayAllDayEvent_onSunday_doesNotLeakIntoMonday_positiveOffsetDevice() {
        // 2026-09-20 is a Sunday. Stored as start=2026-09-20T00:00:00Z,
        // end=2026-09-21T00:00:00Z (exclusive) — "the 20th only".
        let sundayOnly = WidgetEvent(
            id: "e1", title: "Family day", startAt: "2026-09-20T00:00:00.000Z", endAt: "2026-09-21T00:00:00.000Z",
            isAllDay: true, timezone: "Europe/London", colorHex: "#00ff00", deepLink: "/calendar?event=e1"
        )
        let grouped = eventsByDay([sundayOnly], calendar: londonSummerCalendar)
        XCTAssertEqual(grouped["2026-9-20"]?.count, 1, "must appear on Sunday the 20th")
        XCTAssertNil(grouped["2026-9-21"], "must NOT leak onto Monday the 21st on a UTC+1 device — the reported bug")
    }

    func test_eventsByDay_oneDayAllDayBirthday_onThursday_doesNotLeakIntoFriday_positiveOffsetDevice() {
        // 2026-09-24 is a Thursday.
        let birthday = WidgetEvent(
            id: "b1", title: "Amara's Birthday", startAt: "2026-09-24T00:00:00.000Z", endAt: "2026-09-25T00:00:00.000Z",
            isAllDay: true, timezone: "Europe/London", colorHex: "#ff00ff", deepLink: "/calendar?event=b1"
        )
        let grouped = eventsByDay([birthday], calendar: londonSummerCalendar)
        XCTAssertEqual(grouped["2026-9-24"]?.count, 1, "must appear on Thursday the 24th")
        XCTAssertNil(grouped["2026-9-25"], "a birthday must NOT leak onto Friday on a UTC+1 device — the reported bug")
    }

    func test_eventsByDay_twoDayAllDayEvent_appearsOnExactlyTwoDays_positiveOffsetDevice() {
        // start=2026-09-24T00:00:00Z, end=2026-09-26T00:00:00Z (exclusive) — the 24th and 25th only.
        let twoDay = WidgetEvent(
            id: "e2", title: "Sleepover", startAt: "2026-09-24T00:00:00.000Z", endAt: "2026-09-26T00:00:00.000Z",
            isAllDay: true, timezone: "Europe/London", colorHex: "#00ff00", deepLink: "/calendar?event=e2"
        )
        let grouped = eventsByDay([twoDay], calendar: londonSummerCalendar)
        XCTAssertEqual(grouped["2026-9-24"]?.count, 1)
        XCTAssertEqual(grouped["2026-9-25"]?.count, 1)
        XCTAssertNil(grouped["2026-9-23"], "must not leak backwards either")
        XCTAssertNil(grouped["2026-9-26"], "end is exclusive — must not include the 26th")
    }

    func test_eventsByDay_oneDayAllDayEvent_doesNotLeakBackwards_negativeOffsetDevice() {
        // A negative-offset device (behind UTC) is the opposite failure
        // mode: naively converting a UTC-midnight boundary into local time
        // would push it into the *previous* local day instead.
        let thursdayOnly = WidgetEvent(
            id: "e3", title: "Appointment", startAt: "2026-09-24T00:00:00.000Z", endAt: "2026-09-25T00:00:00.000Z",
            isAllDay: true, timezone: "America/New_York", colorHex: "#00ff00", deepLink: "/calendar?event=e3"
        )
        let grouped = eventsByDay([thursdayOnly], calendar: newYorkCalendar)
        XCTAssertEqual(grouped["2026-9-24"]?.count, 1, "must appear on the 24th")
        XCTAssertNil(grouped["2026-9-23"], "must NOT leak backwards onto the 23rd on a UTC-4 device")
        XCTAssertNil(grouped["2026-9-25"], "must NOT leak forwards onto the 25th either")
    }

    func test_eventsByDay_oneDayAllDayEvent_onUkClockChangeSunday_staysConfinedToThatDay() {
        // 2026-10-25 is the UK's 2026 autumn clock-change Sunday (BST ->
        // GMT at 02:00 local, so that calendar day is actually 25 hours
        // long in Europe/London). TimeZone(identifier: "Europe/London") is
        // DST-aware, so localMidnightOfCalendarDay's `calendar.date(from:)`
        // reconstruction must resolve to the correct local midnight either
        // side of the transition without any DST-specific logic of its own.
        let clockChangeDay = WidgetEvent(
            id: "e6", title: "Clocks go back", startAt: "2026-10-25T00:00:00.000Z", endAt: "2026-10-26T00:00:00.000Z",
            isAllDay: true, timezone: "Europe/London", colorHex: "#00ff00", deepLink: "/calendar?event=e6"
        )
        let grouped = eventsByDay([clockChangeDay], calendar: londonSummerCalendar)
        XCTAssertEqual(grouped["2026-10-25"]?.count, 1, "must appear on the clock-change Sunday itself")
        XCTAssertNil(grouped["2026-10-24"], "must not leak backwards across the DST boundary")
        XCTAssertNil(grouped["2026-10-26"], "must not leak forwards across the DST boundary")
    }

    func test_eventsByDay_twoDayAllDayEvent_spanningUkClockChange_appearsOnExactlyTwoDays() {
        // Spans the clock-change Sunday (25th, BST->GMT) and the following
        // Monday (26th, now GMT) — the two calendar days genuinely differ
        // in UTC offset, so this is the sharpest test that the fix doesn't
        // silently depend on a fixed offset.
        let spanning = WidgetEvent(
            id: "e7", title: "Half term start", startAt: "2026-10-25T00:00:00.000Z", endAt: "2026-10-27T00:00:00.000Z",
            isAllDay: true, timezone: "Europe/London", colorHex: "#00ff00", deepLink: "/calendar?event=e7"
        )
        let grouped = eventsByDay([spanning], calendar: londonSummerCalendar)
        XCTAssertEqual(grouped["2026-10-25"]?.count, 1)
        XCTAssertEqual(grouped["2026-10-26"]?.count, 1)
        XCTAssertNil(grouped["2026-10-27"], "end is exclusive — must not include the 27th")
    }

    func test_eventsByDay_lateTimedEvent_staysOnItsOwnLocalDay_notUtc() {
        // 22:30-22:59 UTC is 23:30-23:59 BST on a UTC+1 device — still
        // wholly within the 20th locally. Confirms timed events (isAllDay
        // == false) keep bucketing by the device's own local day, which
        // localMidnightOfCalendarDay preserves — this fix only changes the
        // all-day branch.
        let lateEvent = WidgetEvent(
            id: "e4", title: "Late call", startAt: "2026-09-20T22:30:00.000Z", endAt: "2026-09-20T22:59:00.000Z",
            isAllDay: false, timezone: "Europe/London", colorHex: "#0000ff", deepLink: "/calendar?event=e4"
        )
        let grouped = eventsByDay([lateEvent], calendar: londonSummerCalendar)
        XCTAssertEqual(grouped.count, 1)
        XCTAssertEqual(grouped["2026-9-20"]?.count, 1, "23:30-23:59 local is still wholly the 20th locally")
    }

    func test_eventsByDay_timedEventCrossingLocalMidnight_appearsOnBothDaysItSpans() {
        // 23:30 BST on the 20th to 00:30 BST on the 21st genuinely spans
        // two local days — a timed event, unlike an all-day one, has real
        // wall-clock start/end instants, so this must appear on both days
        // it actually touches (never a leak — a correct span).
        let crossesMidnight = WidgetEvent(
            id: "e5", title: "Late film", startAt: "2026-09-20T22:30:00.000Z", endAt: "2026-09-20T23:30:00.000Z",
            isAllDay: false, timezone: "Europe/London", colorHex: "#0000ff", deepLink: "/calendar?event=e5"
        )
        let grouped = eventsByDay([crossesMidnight], calendar: londonSummerCalendar)
        XCTAssertEqual(grouped["2026-9-20"]?.count, 1)
        XCTAssertEqual(grouped["2026-9-21"]?.count, 1, "the event genuinely runs until 00:30 local on the 21st")
    }
}
