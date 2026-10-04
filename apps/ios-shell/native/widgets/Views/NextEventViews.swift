import SwiftUI
import WidgetKit
import MyKhayaWidgetCore

private let dayFormatter: DateFormatter = {
    let formatter = DateFormatter()
    formatter.setLocalizedDateFormatFromTemplate("EEEEd MMM")
    return formatter
}()

private struct SignedOutView: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Image(systemName: "person.crop.circle.badge.questionmark")
                .font(.title3)
                .foregroundStyle(.secondary)
            Text("Open MyKhaya to sign in")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding()
        .widgetURL(WidgetDeepLink.signInHome)
    }
}

private struct EmptyEventsView: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(dayFormatter.string(from: Date()))
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            Spacer(minLength: 4)
            Text("No upcoming events")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding()
        .widgetURL(WidgetDeepLink.calendarHome)
    }
}

private struct EventRow: View {
    let event: WidgetEvent
    let showsDate: Bool

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Circle()
                .fill(Color(mykhayaHex: event.colorHex))
                .frame(width: 8, height: 8)
                .padding(.top, 5)
            VStack(alignment: .leading, spacing: 2) {
                Text(event.title)
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(2)
                    .truncationMode(.tail)
                Text(eventTimeLabel(event))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}

struct NextEventSmallView: View {
    let snapshot: WidgetSnapshot

    var body: some View {
        if !snapshot.signedIn {
            SignedOutView()
        } else if let next = snapshot.upcomingEvents.first {
            VStack(alignment: .leading, spacing: 6) {
                Text(dayFormatter.string(from: next.startDate ?? Date()))
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer(minLength: 2)
                EventRow(event: next, showsDate: false)
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .padding()
            .widgetURL(WidgetDeepLink.url(forPath: next.deepLink))
        } else {
            EmptyEventsView()
        }
    }
}

struct NextEventMediumView: View {
    let snapshot: WidgetSnapshot

    var body: some View {
        if !snapshot.signedIn {
            SignedOutView()
        } else if snapshot.upcomingEvents.isEmpty {
            EmptyEventsView()
        } else {
            VStack(alignment: .leading, spacing: 8) {
                Text(dayFormatter.string(from: Date()))
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                ForEach(Array(snapshot.upcomingEvents.prefix(3).enumerated()), id: \.element.id) { index, event in
                    Link(destination: WidgetDeepLink.url(forPath: event.deepLink) ?? WidgetDeepLink.calendarHome!) {
                        EventRow(event: event, showsDate: false)
                    }
                    if index < min(snapshot.upcomingEvents.count, 3) - 1 {
                        Divider()
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .padding()
        }
    }
}
