import WidgetKit
import MyKhayaWidgetCore

struct CalendarEntry: TimelineEntry {
    let date: Date
    let snapshot: WidgetSnapshot
}

struct CalendarProvider: TimelineProvider {
    func placeholder(in context: Context) -> CalendarEntry {
        CalendarEntry(date: Date(), snapshot: .signedOut())
    }

    func getSnapshot(in context: Context, completion: @escaping (CalendarEntry) -> Void) {
        completion(CalendarEntry(date: Date(), snapshot: WidgetSnapshotStore.load()))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<CalendarEntry>) -> Void) {
        let snapshot = WidgetSnapshotStore.load()
        let now = Date()
        let entry = CalendarEntry(date: now, snapshot: snapshot)

        // The month/week grid only needs to redraw when "today" changes or
        // the month rolls over — refresh at next midnight, capped so a
        // long-idle widget still periodically re-checks for fresh data.
        let midnight = Calendar.current.nextDate(after: now, matching: DateComponents(hour: 0, minute: 0, second: 0), matchingPolicy: .nextTime) ?? now.addingTimeInterval(6 * 60 * 60)
        let ceiling = now.addingTimeInterval(6 * 60 * 60)
        let nextRefresh = min(midnight, ceiling)

        completion(Timeline(entries: [entry], policy: .after(nextRefresh)))
    }
}
