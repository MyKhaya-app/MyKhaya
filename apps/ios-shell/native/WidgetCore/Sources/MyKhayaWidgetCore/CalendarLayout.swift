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

/// Groups monthEvents by local day key. An all-day/multi-day event appears
/// under every day it spans — mirrors widget-snapshot.ts's own
/// day-spanning semantics (start/end day range, not a raw timestamp
/// comparison), so a multi-day event shows a coloured mark on each of its
/// days rather than only its start day.
public func eventsByDay(_ events: [WidgetEvent], calendar: Calendar) -> [String: [WidgetEvent]] {
    var result: [String: [WidgetEvent]] = [:]
    for event in events {
        guard let start = event.startDate else { continue }
        let end = event.endDate ?? start
        var cursor = calendar.startOfDay(for: start)
        let lastDay = calendar.startOfDay(for: end.addingTimeInterval(-1))
        var guardCount = 0
        while cursor <= lastDay, guardCount < 62 {
            result[dayKey(cursor, calendar: calendar), default: []].append(event)
            cursor = calendar.date(byAdding: .day, value: 1, to: cursor) ?? cursor
            guardCount += 1
        }
    }
    return result
}
