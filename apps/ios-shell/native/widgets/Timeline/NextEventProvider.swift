import WidgetKit
import MyKhayaWidgetCore

// Deployment target note: written against the classic `TimelineProvider`
// protocol (not `AppIntentTimelineProvider`, iOS 17+ only) and plain
// `StaticConfiguration`, so it builds against whatever deployment target
// the Mac-generated Xcode project actually has — no `ios/` project exists
// in this repo to read a real minimum version from (see
// docs/mobile/ios-widgets.md, "Deployment target"). Verify on the Mac and
// raise this note if the project's minimum turns out to already be iOS 17+.

struct NextEventEntry: TimelineEntry {
    let date: Date
    let snapshot: WidgetSnapshot
}

struct NextEventProvider: TimelineProvider {
    func placeholder(in context: Context) -> NextEventEntry {
        NextEventEntry(date: Date(), snapshot: .signedOut())
    }

    func getSnapshot(in context: Context, completion: @escaping (NextEventEntry) -> Void) {
        completion(NextEventEntry(date: Date(), snapshot: WidgetSnapshotStore.load()))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<NextEventEntry>) -> Void) {
        let snapshot = WidgetSnapshotStore.load()
        let now = Date()
        let entry = NextEventEntry(date: now, snapshot: snapshot)

        // WidgetKit controls actual refresh cadence — this only requests a
        // sensible next attempt. Refresh at whichever comes first: the end
        // of the event currently shown (so "Now" flips to the next event
        // promptly), midnight (today's date/label rolls over), or a
        // 30-minute ceiling so a widget with no events still occasionally
        // re-checks for a snapshot the app wrote in the background.
        var candidates: [Date] = [now.addingTimeInterval(30 * 60)]
        if let currentEndDate = currentlyShownEvent(in: snapshot, at: now)?.endDate {
            candidates.append(currentEndDate)
        }
        if let midnight = Calendar.current.nextDate(after: now, matching: DateComponents(hour: 0, minute: 0, second: 0), matchingPolicy: .nextTime) {
            candidates.append(midnight)
        }
        let nextRefresh = candidates.filter { $0 > now }.min() ?? now.addingTimeInterval(30 * 60)

        completion(Timeline(entries: [entry], policy: .after(nextRefresh)))
    }
}
