import SwiftUI
import WidgetKit

struct CalendarWidget: Widget {
    let kind: String = "MyKhayaCalendarWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: CalendarProvider()) { entry in
            CalendarWidgetView(entry: entry)
        }
        .configurationDisplayName("Calendar")
        .description("A glanceable view of your MyKhaya calendar.")
        .supportedFamilies([.systemMedium, .systemLarge])
    }
}

private struct CalendarWidgetView: View {
    let entry: CalendarEntry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        switch family {
        case .systemLarge:
            CalendarMonthView(snapshot: entry.snapshot)
        default:
            CalendarWeekView(snapshot: entry.snapshot)
        }
    }
}
