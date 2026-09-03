import WidgetKit
import MyKhayaWidgetCore

struct TodoEntry: TimelineEntry {
    let date: Date
    let snapshot: WidgetSnapshot
}

struct TodoProvider: TimelineProvider {
    func placeholder(in context: Context) -> TodoEntry {
        TodoEntry(date: Date(), snapshot: .signedOut())
    }

    func getSnapshot(in context: Context, completion: @escaping (TodoEntry) -> Void) {
        completion(TodoEntry(date: Date(), snapshot: WidgetSnapshotStore.load()))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<TodoEntry>) -> Void) {
        let snapshot = WidgetSnapshotStore.load()
        let now = Date()
        let entry = TodoEntry(date: now, snapshot: snapshot)

        // Overdue status only changes at a day boundary; a 30-minute
        // ceiling still gives a reasonably fresh view of app-driven writes
        // (completing an item, a new reminder created) between manual
        // opens of the app.
        let midnight = Calendar.current.nextDate(after: now, matching: DateComponents(hour: 0, minute: 0, second: 0), matchingPolicy: .nextTime) ?? now.addingTimeInterval(30 * 60)
        let ceiling = now.addingTimeInterval(30 * 60)
        let nextRefresh = min(midnight, ceiling)

        completion(Timeline(entries: [entry], policy: .after(nextRefresh)))
    }
}
