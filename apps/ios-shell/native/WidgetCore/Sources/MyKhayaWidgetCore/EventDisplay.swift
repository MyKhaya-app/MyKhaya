import Foundation

// Pure display-formatting helpers extracted from
// apps/ios-shell/native/widgets/Views/NextEventViews.swift and
// TodoViews.swift — no SwiftUI dependency, moved here so they're linkable
// by XCTest. `currentlyShownEvent` was originally in Timeline/
// NextEventProvider.swift.

/// The event a Small widget's single-event view is currently showing —
/// same "soonest not-yet-finished" rule the snapshot itself already
/// applied (in widget-snapshot.ts, upstream of this Swift code — see
/// docs/mobile/ios-widgets.md), kept here only to pick a sensible
/// next-refresh instant. `date` is accepted for future flexibility (e.g. a
/// caller wanting "as of a specific instant") even though the current
/// implementation only needs `snapshot.upcomingEvents`, which is already
/// filtered/ordered by the time it reaches Swift.
public func currentlyShownEvent(in snapshot: WidgetSnapshot, at date: Date) -> WidgetEvent? {
    snapshot.upcomingEvents.first
}

private let eventTimeFormatter: DateFormatter = {
    let formatter = DateFormatter()
    formatter.timeStyle = .short
    formatter.dateStyle = .none
    return formatter
}()

/// Shared across Small/Medium: "10:00 – 11:00" for a timed event, "All day"
/// for an all-day one, "Ends 6pm" style is intentionally avoided — Apple
/// widget layout guidance favours short, glanceable strings.
public func eventTimeLabel(_ event: WidgetEvent) -> String {
    if event.isAllDay { return "All day" }
    guard let start = event.startDate else { return "" }
    if let end = event.endDate {
        return "\(eventTimeFormatter.string(from: start)) – \(eventTimeFormatter.string(from: end))"
    }
    return eventTimeFormatter.string(from: start)
}

/// "Overdue" / "Today" / "Upcoming" label for a to-do item, matching the
/// widget's To-do row rendering.
public func dueLabel(for item: WidgetTodoItem, now: Date = Date()) -> String {
    if item.overdue { return "Overdue" }
    guard let dueAt = item.dueAt else { return "" }
    let todayKey = ISO8601DateFormatter().string(from: now).prefix(10)
    return dueAt.hasPrefix(todayKey) ? "Today" : "Upcoming"
}
