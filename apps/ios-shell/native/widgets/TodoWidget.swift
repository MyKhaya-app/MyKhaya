import SwiftUI
import WidgetKit

struct TodoWidget: Widget {
    let kind: String = "MyKhayaTodoWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: TodoProvider()) { entry in
            TodoWidgetView(entry: entry)
        }
        .configurationDisplayName("To-do")
        .description("Overdue and upcoming routines and reminders.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge])
    }
}

private struct TodoWidgetView: View {
    let entry: TodoEntry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        switch family {
        case .systemMedium:
            TodoMediumView(snapshot: entry.snapshot)
        case .systemLarge:
            TodoLargeView(snapshot: entry.snapshot)
        default:
            TodoSmallView(snapshot: entry.snapshot)
        }
    }
}
