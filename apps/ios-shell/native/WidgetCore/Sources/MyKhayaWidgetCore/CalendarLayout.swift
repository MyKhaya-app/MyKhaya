import Foundation

// Extracted from apps/ios-shell/native/widgets/Views/CalendarViews.swift —
// pure Date/Calendar grid-shaping logic with zero SwiftUI dependency, moved
// here so it can be linked by XCTest (an app extension's own compiled code
// cannot be an XCTest host). CalendarViews.swift now imports this package
// and keeps only the SwiftUI View bodies.

/// Builds the 5- or 6-row day grid for the month containing `reference`,
/// including the leading/trailing days from adjacent months needed to fill
/// complete weeks (a widget must render a rectangular grid, unlike the web
/// calendar which can render a ragged first/last row). Weeks start on the
/// device's locale-appropriate first weekday.
public func monthGridDays(containing reference: Date, calendar: Calendar) -> [Date] {
    guard let monthInterval = calendar.dateInterval(of: .month, for: reference),
          let firstWeekInterval = calendar.dateInterval(of: .weekOfMonth, for: monthInterval.start) else {
        return []
    }
    var days: [Date] = []
    var cursor = firstWeekInterval.start
    // Six rows covers every month/first-weekday combination (a 31-day month
    // starting on the last day of a week needs 6 rows); a 5-row month just
    // renders its final row as next-month days, matched by the day-cell's
    // own "not in this month" dimming.
    let totalDays = 6 * 7
    for _ in 0..<totalDays {
        days.append(cursor)
        cursor = calendar.date(byAdding: .day, value: 1, to: cursor) ?? cursor
    }
    return days
}

public func dayKey(_ date: Date, calendar: Calendar) -> String {
    let components = calendar.dateComponents([.year, .month, .day], from: date)
    return "\(components.year ?? 0)-\(components.month ?? 0)-\(components.day ?? 0)"
}

/// A fixed UTC/Gregorian calendar — never the device's own `Calendar.current`
/// — for reading the calendar-date digits an all-day event's start/end
/// instants name. Mirrors apps/api/mykhaya/routers/calendar.py's
/// `_all_day_midnight` / apps/web/app/calendar/calendar-utils.ts's
/// `occurrenceDateKey`: an all-day event is a literal UTC-midnight calendar
/// date, not a wall-clock instant, so it must be read with plain UTC digits.
let utcCalendar: Calendar = {
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = TimeZone(identifier: "UTC")!
    return calendar
}()

/// The local (`calendar`-relative) midnight `Date` of the calendar day a
/// boundary instant represents — read from UTC digits for all-day events,
/// from `calendar`'s own (device-local) digits for timed events. Re-basing
/// to `calendar`'s midnight, rather than returning the UTC instant itself,
/// keeps every caller's subsequent day-grid arithmetic (`date(byAdding:
/// .day, ...)`, `dateComponents(_:from:to:)`) operating on Dates from one
/// consistent calendar frame — otherwise mixing a UTC-anchored instant into
/// device-local day arithmetic can itself introduce a one-day error in the
/// opposite direction for negative-offset timezones.
func localMidnightOfCalendarDay(containing date: Date, isAllDay: Bool, calendar: Calendar) -> Date {
    let sourceCalendar = isAllDay ? utcCalendar : calendar
    let components = sourceCalendar.dateComponents([.year, .month, .day], from: date)
    return calendar.date(from: components) ?? calendar.startOfDay(for: date)
}

/// Groups monthEvents by local day key. An all-day/multi-day event appears
/// under every day it spans — mirrors widget-snapshot.ts's own
/// day-spanning semantics (start/end day range, not a raw timestamp
/// comparison), so a multi-day event shows a coloured mark on each of its
/// days rather than only its start day.
///
/// All-day events' start/end are read as literal UTC calendar dates (see
/// `localMidnightOfCalendarDay`) — using the device's own `calendar` here
/// for an all-day boundary would, for any timezone offset from UTC, either
/// spill a one-day all-day event onto the following local day (positive
/// offsets) or the previous one (negative offsets).
public func eventsByDay(_ events: [WidgetEvent], calendar: Calendar) -> [String: [WidgetEvent]] {
    var result: [String: [WidgetEvent]] = [:]
    for event in events {
        guard let start = event.startDate else { continue }
        let end = event.endDate ?? start
        var cursor = localMidnightOfCalendarDay(containing: start, isAllDay: event.isAllDay, calendar: calendar)
        let lastDay = localMidnightOfCalendarDay(containing: end.addingTimeInterval(-1), isAllDay: event.isAllDay, calendar: calendar)
        var guardCount = 0
        while cursor <= lastDay, guardCount < 62 {
            result[dayKey(cursor, calendar: calendar), default: []].append(event)
            cursor = calendar.date(byAdding: .day, value: 1, to: cursor) ?? cursor
            guardCount += 1
        }
    }
    return result
}
