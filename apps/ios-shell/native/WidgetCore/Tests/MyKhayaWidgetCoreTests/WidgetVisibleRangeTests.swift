import XCTest
@testable import MyKhayaWidgetCore

final class WidgetVisibleRangeTests: XCTestCase {
    private func calendar(_ zone: String = "UTC", firstWeekday: Int = 2) -> Calendar {
        var result = Calendar(identifier: .gregorian)
        result.timeZone = TimeZone(identifier: zone)!
        result.firstWeekday = firstWeekday
        return result
    }

    private func day(_ value: String, _ calendar: Calendar) -> Date {
        let digits = value.split(separator: "-").map { Int($0)! }
        return calendar.date(from: DateComponents(year: digits[0], month: digits[1], day: digits[2]))!
    }

    private func event(_ start: String, _ end: String, id: String? = nil, allDay: Bool = true) -> WidgetEvent {
        WidgetEvent(id: id ?? start, title: id ?? start,
                    startAt: start + "T00:00:00Z", endAt: end + "T00:00:00Z",
                    isAllDay: allDay, timezone: "Europe/London", colorHex: "#3366ff", deepLink: "/calendar")
    }

    func test_A_crossMonthWeekIncludesBothMonths() {
        let cal = calendar()
        let events = [event("2026-09-28", "2026-09-29"), event("2026-09-30", "2026-10-01"),
                      event("2026-10-01", "2026-10-02"), event("2026-10-02", "2026-10-03"),
                      event("2026-10-03", "2026-10-04")]
        let result = weekEventLayout(events: events, weekStart: day("2026-09-28", cal), calendar: cal)
        XCTAssertEqual(result.bars.map(\.startColumn), [0, 2, 3, 4, 5])
        XCTAssertEqual(result.bars.map(\.eventId), events.map(\.id))
    }

    func test_B_C_E_tripSpansExactlyFourVisibleDays_noPhantomDays() {
        for zone in ["UTC", "Europe/London", "America/Los_Angeles", "Pacific/Auckland"] {
            let cal = calendar(zone)
            let trip = event("2026-10-01", "2026-10-05", id: "Megan Portugal Trip")
            let outside = event("2026-10-05", "2026-10-06")
            let result = weekEventLayout(events: [trip, outside], weekStart: day("2026-09-28", cal), calendar: cal)
            XCTAssertEqual(result.bars.count, 1, zone)
            XCTAssertEqual(result.bars.first?.startColumn, 3, zone)
            XCTAssertEqual(result.bars.first?.endColumn, 6, zone)
            let grouped = eventsByDay([trip], calendar: cal)
            XCTAssertEqual(Set(grouped.keys), Set(["2026-10-1", "2026-10-2", "2026-10-3", "2026-10-4"]), zone)
            let nextWeek = weekEventLayout(events: [trip], weekStart: day("2026-10-05", cal), calendar: cal)
            XCTAssertTrue(nextWeek.bars.isEmpty, zone)
        }
    }

    func test_D_yearBoundaryAndReverseDirection() {
        let cal = calendar()
        let events = [event("2026-12-28", "2026-12-29"), event("2026-12-31", "2027-01-02"), event("2027-01-03", "2027-01-04")]
        let result = weekEventLayout(events: events, weekStart: day("2026-12-28", cal), calendar: cal)
        XCTAssertEqual(result.bars.map(\.startColumn), [0, 3, 6])
        XCTAssertEqual(result.bars.map(\.endColumn), [0, 4, 6])
        let january = widgetCalendarRange(containing: day("2027-01-01", cal), calendar: cal)!
        XCTAssertEqual(january.startDate, "2026-12-28")
    }

    func test_F_sameMonthAndOctoberNovemberWeeks() {
        let cal = calendar()
        for (start, eventStart, eventEnd) in [("2026-09-07", "2026-09-09", "2026-09-10"),
                                             ("2026-10-26", "2026-11-01", "2026-11-02")] {
            let result = weekEventLayout(events: [event(eventStart, eventEnd)], weekStart: day(start, cal), calendar: cal)
            XCTAssertEqual(result.bars.count, 1)
            XCTAssertEqual(result.bars[0].startColumn, result.bars[0].endColumn)
        }
    }

    func test_nativeReportedRangeMatchesAll42VisibleCellsAndTheCurrentWeek() {
        for zone in ["Europe/London", "America/Los_Angeles", "Pacific/Auckland"] {
            for firstWeekday in [1, 2, 7] {
                let cal = calendar(zone, firstWeekday: firstWeekday)
                for reference in ["2026-09-28", "2026-10-01", "2026-10-31", "2026-12-28", "2027-01-01"] {
                    let now = day(reference, cal)
                    let range = widgetCalendarRange(containing: now, calendar: cal)!
                    let grid = monthGridDays(containing: now, calendar: cal)
                    let formatter = ISO8601DateFormatter()
                    XCTAssertEqual(formatter.date(from: range.startAt), grid.first)
                    XCTAssertEqual(formatter.date(from: range.endAt), cal.date(byAdding: .day, value: 1, to: grid.last!))
                    let week = cal.dateInterval(of: .weekOfMonth, for: now)!
                    XCTAssertLessThanOrEqual(formatter.date(from: range.startAt)!, week.start)
                    XCTAssertGreaterThanOrEqual(formatter.date(from: range.endAt)!, week.end)
                }
            }
        }
    }

    func test_timedOverlapAndOverflowRemainIntact() {
        let cal = calendar()
        let crossing = event("2026-09-27", "2026-09-29", allDay: false)
        let endingAtStart = event("2026-09-27", "2026-09-28", allDay: false)
        let result = weekEventLayout(events: [crossing, endingAtStart], weekStart: day("2026-09-28", cal), calendar: cal)
        XCTAssertEqual(result.bars.count, 1)
        XCTAssertEqual(result.bars.first?.startColumn, 0)
        XCTAssertEqual(result.bars.first?.endColumn, 0)
        let crowded = (0..<6).map { event("2026-10-01", "2026-10-05", id: "event-\($0)") }
        let overflow = weekEventLayout(events: crowded, weekStart: day("2026-09-28", cal), calendar: cal, maxRows: 4)
        XCTAssertEqual(overflow.bars.count, 4)
        XCTAssertEqual(overflow.overflowByColumn, [0, 0, 0, 2, 2, 2, 2])
    }
}
