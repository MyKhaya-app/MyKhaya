import XCTest
@testable import MyKhayaWidgetCore

/// Covers weekEventLayout's row-packing algorithm for the Medium Calendar
/// widget's event-tile view. All fixtures use a fixed Monday-start week —
/// 2026-08-31 (Mon) .. 2026-09-06 (Sun) — so column indices are unambiguous:
/// 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun.
final class WeekEventLayoutTests: XCTestCase {
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

    private var weekStart: Date { date("2026-08-31T00:00:00Z") } // Monday

    private func event(
        _ id: String,
        title: String = "Event",
        start: String,
        end: String,
        allDay: Bool = false
    ) -> WidgetEvent {
        WidgetEvent(
            id: id, title: title, startAt: start, endAt: end,
            isAllDay: allDay, timezone: "UTC", colorHex: "#3366ff", deepLink: "/calendar?event=\(id)"
        )
    }

    // MARK: Single-day events

    func test_singleDayEvent_occupiesOneColumnOneRow() {
        let e = event("e1", start: "2026-09-02T09:00:00Z", end: "2026-09-02T10:00:00Z") // Wednesday
        let result = weekEventLayout(events: [e], weekStart: weekStart, calendar: utcCalendar)
        XCTAssertEqual(result.bars.count, 1)
        XCTAssertEqual(result.bars[0].startColumn, 2, "still anchored to its real day, Wednesday")
        XCTAssertEqual(result.bars[0].row, 0)
        XCTAssertEqual(result.bars[0].endColumn, 2, "a single-day event's tile must stay inside its own column, never wider")
    }

    func test_singleDayEvent_neverExceedsItsOwnColumn() {
        // A lone Wednesday event with the entire rest of the week free —
        // there must be no mechanism that widens it into that empty space.
        // Single-day vs. multi-day must be readable from bar geometry
        // alone, so startColumn == endColumn is absolute for a single-day
        // event, regardless of how much unused row space surrounds it.
        let e = event("e1", title: "Erin's Appointment", start: "2026-09-02T09:00:00Z", end: "2026-09-02T10:00:00Z")
        let result = weekEventLayout(events: [e], weekStart: weekStart, calendar: utcCalendar)
        XCTAssertEqual(result.bars[0].startColumn, result.bars[0].endColumn, "single-day bars must never span more than their own column")
    }

    func test_singleDayEvent_widthUnaffectedByEmptyNeighbouringColumns() {
        // Same event, but assert explicitly against the specific regression
        // this test guards: an event surrounded by empty columns on both
        // sides must not grow into any of them.
        let e = event("e1", title: "Solo Event", start: "2026-09-02T09:00:00Z", end: "2026-09-02T10:00:00Z") // Wednesday, Tue+Thu both empty
        let result = weekEventLayout(events: [e], weekStart: weekStart, calendar: utcCalendar)
        XCTAssertEqual(result.bars[0].startColumn, 2)
        XCTAssertEqual(result.bars[0].endColumn, 2, "adjacent empty days must not change this event's width")
    }

    func test_twoSingleDayEvents_onNeighbouringDays_remainVisuallySeparate() {
        let wed = event("wed", title: "Wed Event", start: "2026-09-02T09:00:00Z", end: "2026-09-02T10:00:00Z")
        let thu = event("thu", title: "Thu Event", start: "2026-09-03T09:00:00Z", end: "2026-09-03T10:00:00Z")
        let result = weekEventLayout(events: [wed, thu], weekStart: weekStart, calendar: utcCalendar)
        let wedBar = result.bars.first { $0.eventId == "wed" }!
        let thuBar = result.bars.first { $0.eventId == "thu" }!
        XCTAssertEqual(wedBar.startColumn, wedBar.endColumn, "Wednesday's event stays confined to Wednesday")
        XCTAssertEqual(thuBar.startColumn, thuBar.endColumn, "Thursday's event stays confined to Thursday")
        XCTAssertEqual(wedBar.startColumn, 2)
        XCTAssertEqual(thuBar.startColumn, 3)
    }

    func test_singleDayEvent_nextToMultiDayEvent_remainsConfined() {
        // Monday single-day event; a Thu-Fri multi-day trip on the same
        // row (no date overlap, so a correct packer shares the row). The
        // single-day event must not be pulled into the trip's span, and
        // the trip's own span must be exactly what its real dates say.
        let mon = event("mon", title: "Monday Event", start: "2026-08-31T09:00:00Z", end: "2026-08-31T10:00:00Z")
        let trip = event("trip", title: "Trip", start: "2026-09-03T00:00:00Z", end: "2026-09-05T00:00:00Z", allDay: true) // Thu-Fri (end exclusive)
        let result = weekEventLayout(events: [mon, trip], weekStart: weekStart, calendar: utcCalendar)
        let monBar = result.bars.first { $0.eventId == "mon" }!
        let tripBar = result.bars.first { $0.eventId == "trip" }!
        XCTAssertEqual(monBar.startColumn, monBar.endColumn, "Monday's single-day event stays confined to Monday")
        XCTAssertEqual(tripBar.startColumn, 3)
        XCTAssertEqual(tripBar.endColumn, 4, "the trip's span is exactly Thu-Fri, unaffected by the neighbouring single-day event")
    }

    func test_singleDayEvent_onSunday_remainsInsideSunday() {
        let e = event("sun", title: "Dentist", start: "2026-09-06T09:00:00Z", end: "2026-09-06T10:00:00Z") // Sunday
        let result = weekEventLayout(events: [e], weekStart: weekStart, calendar: utcCalendar)
        XCTAssertEqual(result.bars[0].startColumn, 6)
        XCTAssertEqual(result.bars[0].endColumn, 6, "confined to Sunday, the week's last column")
    }

    func test_severalIndependentSingleDayEvents_allShareRowZero() {
        // Football (Mon), Piano (Fri), Dentist (Sun) never overlap in date
        // range, so a correct packer reuses row 0 for all three rather than
        // stacking them unnecessarily.
        let events = [
            event("football", title: "Football", start: "2026-08-31T09:00:00Z", end: "2026-08-31T10:00:00Z"),
            event("piano", title: "Piano", start: "2026-09-04T09:00:00Z", end: "2026-09-04T10:00:00Z"),
            event("dentist", title: "Dentist", start: "2026-09-06T09:00:00Z", end: "2026-09-06T10:00:00Z"),
        ]
        let result = weekEventLayout(events: events, weekStart: weekStart, calendar: utcCalendar)
        XCTAssertEqual(result.bars.count, 3)
        XCTAssertTrue(result.bars.allSatisfy { $0.row == 0 })
    }

    // MARK: Multi-day events

    func test_multiDayEvent_spansCorrectColumnRange() {
        // Business Trip: Wed through Fri (end exclusive at Sat midnight).
        let e = event("trip", title: "Business Trip", start: "2026-09-02T00:00:00Z", end: "2026-09-05T00:00:00Z", allDay: true)
        let result = weekEventLayout(events: [e], weekStart: weekStart, calendar: utcCalendar)
        XCTAssertEqual(result.bars.count, 1)
        XCTAssertEqual(result.bars[0].startColumn, 2, "Wednesday")
        XCTAssertEqual(result.bars[0].endColumn, 4, "Friday — end is exclusive, so the bar stops at Friday not Saturday")
    }

    func test_multiDayEvent_appearsAsOneBar_notDuplicatedPerDay() {
        let e = event("trip", title: "Business Trip", start: "2026-09-02T00:00:00Z", end: "2026-09-05T00:00:00Z", allDay: true)
        let result = weekEventLayout(events: [e], weekStart: weekStart, calendar: utcCalendar)
        XCTAssertEqual(result.bars.count, 1, "a spanning event must be one bar, never one entry per day")
    }

    func test_overlappingMultiDayEvents_getDifferentRows() {
        // Business Trip: Wed-Fri. Travel: Fri-Sun. They share Friday, so
        // must not land on the same row.
        let trip = event("trip", title: "Business Trip", start: "2026-09-02T00:00:00Z", end: "2026-09-05T00:00:00Z", allDay: true)
        let travel = event("travel", title: "Travel", start: "2026-09-04T00:00:00Z", end: "2026-09-07T00:00:00Z", allDay: true)
        let result = weekEventLayout(events: [trip, travel], weekStart: weekStart, calendar: utcCalendar)
        let tripBar = result.bars.first { $0.eventId == "trip" }!
        let travelBar = result.bars.first { $0.eventId == "travel" }!
        XCTAssertNotEqual(tripBar.row, travelBar.row)
    }

    func test_singleDayEventInsideMultiDaySpan_getsDifferentRow() {
        // Tutoring on Wednesday, inside the Business Trip's Wed-Fri span —
        // must not share a row with the trip.
        let trip = event("trip", title: "Business Trip", start: "2026-09-02T00:00:00Z", end: "2026-09-05T00:00:00Z", allDay: true)
        let tutoring = event("tutoring", title: "Tutoring", start: "2026-09-02T15:00:00Z", end: "2026-09-02T16:00:00Z")
        let result = weekEventLayout(events: [trip, tutoring], weekStart: weekStart, calendar: utcCalendar)
        let tripBar = result.bars.first { $0.eventId == "trip" }!
        let tutoringBar = result.bars.first { $0.eventId == "tutoring" }!
        XCTAssertNotEqual(tripBar.row, tutoringBar.row)
    }

    // MARK: Week-boundary clipping

    func test_eventBeginningBeforeDisplayedWeek_clipsToMonday() {
        // Starts the previous Saturday, ends Tuesday of this week.
        let e = event("holiday", title: "Holiday", start: "2026-08-29T00:00:00Z", end: "2026-09-02T00:00:00Z", allDay: true)
        let result = weekEventLayout(events: [e], weekStart: weekStart, calendar: utcCalendar)
        XCTAssertEqual(result.bars.count, 1)
        XCTAssertEqual(result.bars[0].startColumn, 0, "must clip to Monday, not extend into negative columns")
        XCTAssertEqual(result.bars[0].endColumn, 1, "Tuesday — end exclusive")
    }

    func test_eventEndingAfterDisplayedWeek_clipsToSunday() {
        // Starts Saturday of this week, ends the following Wednesday.
        let e = event("holiday", title: "Holiday", start: "2026-09-05T00:00:00Z", end: "2026-09-09T00:00:00Z", allDay: true)
        let result = weekEventLayout(events: [e], weekStart: weekStart, calendar: utcCalendar)
        XCTAssertEqual(result.bars.count, 1)
        XCTAssertEqual(result.bars[0].startColumn, 5, "Saturday")
        XCTAssertEqual(result.bars[0].endColumn, 6, "must clip to Sunday, not extend into column 7+")
    }

    func test_eventSpanningEntireWeek_coversAllSevenColumns() {
        let e = event("longHoliday", title: "Long Holiday", start: "2026-08-20T00:00:00Z", end: "2026-09-20T00:00:00Z", allDay: true)
        let result = weekEventLayout(events: [e], weekStart: weekStart, calendar: utcCalendar)
        XCTAssertEqual(result.bars.count, 1)
        XCTAssertEqual(result.bars[0].startColumn, 0)
        XCTAssertEqual(result.bars[0].endColumn, 6)
    }

    // MARK: Determinism

    func test_rowAssignment_isDeterministic_acrossRepeatedCalls() {
        let events = [
            event("a", title: "A", start: "2026-09-02T00:00:00Z", end: "2026-09-05T00:00:00Z", allDay: true),
            event("b", title: "B", start: "2026-09-04T00:00:00Z", end: "2026-09-07T00:00:00Z", allDay: true),
            event("c", title: "C", start: "2026-08-31T09:00:00Z", end: "2026-08-31T10:00:00Z"),
        ]
        let first = weekEventLayout(events: events, weekStart: weekStart, calendar: utcCalendar)
        let second = weekEventLayout(events: events, weekStart: weekStart, calendar: utcCalendar)
        XCTAssertEqual(first, second)
    }

    func test_noTwoOverlappingEvents_shareARow() {
        let events = [
            event("a", title: "A", start: "2026-08-31T00:00:00Z", end: "2026-09-03T00:00:00Z", allDay: true), // Mon-Wed
            event("b", title: "B", start: "2026-09-01T09:00:00Z", end: "2026-09-01T10:00:00Z"), // Tue, inside A
            event("c", title: "C", start: "2026-09-02T09:00:00Z", end: "2026-09-02T10:00:00Z"), // Wed, inside A
        ]
        let result = weekEventLayout(events: events, weekStart: weekStart, calendar: utcCalendar, maxRows: 10)
        for i in result.bars.indices {
            for j in result.bars.indices where j != i {
                let a = result.bars[i], b = result.bars[j]
                guard a.row == b.row else { continue }
                let overlaps = a.startColumn <= b.endColumn && b.startColumn <= a.endColumn
                XCTAssertFalse(overlaps, "\(a.eventId) and \(b.eventId) share row \(a.row) but overlap columns")
            }
        }
    }

    // MARK: Overflow

    func test_overflowBeyondMaxRows_reportedPerColumn_notPlaced() {
        // Four independent Monday-only events, maxRows 3: the 4th must be
        // dropped from `bars` and counted as overflow on Monday (column 0).
        let events = (0..<4).map { i in
            event("e\(i)", title: "Event \(i)", start: "2026-08-31T0\(i):00:00Z", end: "2026-08-31T0\(i):30:00Z")
        }
        let result = weekEventLayout(events: events, weekStart: weekStart, calendar: utcCalendar, maxRows: 3)
        XCTAssertEqual(result.bars.count, 3, "only 3 rows fit")
        XCTAssertEqual(result.overflowByColumn[0], 1, "the 4th Monday event should be counted as overflow")
        XCTAssertEqual(result.overflowByColumn[1...6], ArraySlice(Array(repeating: 0, count: 6)), "no other day has overflow")
    }

    func test_overflow_prioritizesSpanningEventOverSingleDayEvents_whenRowsAreScarce() {
        // Sort order places the widest span first at a shared start column,
        // so a multi-day event claims a row before same-start single-day
        // events do — the packer's way of honouring "preserve multi-day
        // events appropriately" (spec) when rows are scarce, rather than
        // three single-day events accidentally crowding out the trip.
        let blockers = (0..<3).map { i in
            event("blocker\(i)", title: "Blocker \(i)", start: "2026-09-02T0\(i):00:00Z", end: "2026-09-02T0\(i):30:00Z") // Wed
        }
        let spanning = event("trip", title: "Business Trip", start: "2026-09-02T00:00:00Z", end: "2026-09-05T00:00:00Z", allDay: true) // Wed-Fri
        let result = weekEventLayout(events: blockers + [spanning], weekStart: weekStart, calendar: utcCalendar, maxRows: 3)
        XCTAssertTrue(result.bars.contains { $0.eventId == "trip" }, "the wider spanning event should win a row over narrower same-start events")
        XCTAssertFalse(result.bars.contains { $0.eventId == "blocker2" }, "the third single-day event is what should overflow instead")
        XCTAssertEqual(result.overflowByColumn[2], 1, "Wed — blocker2 overflowed")
        XCTAssertEqual(result.overflowByColumn[3], 0, "Thu — the overflowing event was single-day, not the spanning one")
        XCTAssertEqual(result.overflowByColumn[4], 0, "Fri — same reason")
    }

    // MARK: Title independence

    func test_longTitle_doesNotAffectRowOrColumnAssignment() {
        let shortTitle = event("a", title: "X", start: "2026-08-31T09:00:00Z", end: "2026-08-31T10:00:00Z")
        let longTitle = event(
            "a", title: "An Extremely Long Event Title That Goes On And On And On",
            start: "2026-08-31T09:00:00Z", end: "2026-08-31T10:00:00Z"
        )
        let shortResult = weekEventLayout(events: [shortTitle], weekStart: weekStart, calendar: utcCalendar)
        let longResult = weekEventLayout(events: [longTitle], weekStart: weekStart, calendar: utcCalendar)
        XCTAssertEqual(shortResult.bars[0].startColumn, longResult.bars[0].startColumn)
        XCTAssertEqual(shortResult.bars[0].endColumn, longResult.bars[0].endColumn)
        XCTAssertEqual(shortResult.bars[0].row, longResult.bars[0].row)
    }

}
