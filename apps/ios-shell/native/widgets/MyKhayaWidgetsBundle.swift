import WidgetKit
import SwiftUI

/// Entry point for the MyKhayaWidgets extension target. To add a fourth
/// MyKhaya widget later: add its Widget struct next to NextEventWidget.swift
/// / CalendarWidget.swift / TodoWidget.swift (own TimelineProvider under
/// Timeline/, own SwiftUI views under Views/), then list it here — no other
/// wiring is needed, since WidgetSnapshotStore/WidgetSnapshot are already
/// shared. See docs/mobile/ios-widgets.md, "Adding another widget".
@main
struct MyKhayaWidgetsBundle: WidgetBundle {
    var body: some Widget {
        NextEventWidget()
        CalendarWidget()
        TodoWidget()
    }
}
