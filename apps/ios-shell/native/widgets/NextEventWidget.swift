import SwiftUI
import WidgetKit

struct NextEventWidget: Widget {
    let kind: String = "MyKhayaNextEventWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: NextEventProvider()) { entry in
            NextEventWidgetView(entry: entry)
        }
        .configurationDisplayName("Next Event")
        .description("See what's next on your MyKhaya calendar.")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

private struct NextEventWidgetView: View {
    let entry: NextEventEntry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        switch family {
        case .systemMedium:
            NextEventMediumView(snapshot: entry.snapshot)
        default:
            NextEventSmallView(snapshot: entry.snapshot)
        }
    }
}
