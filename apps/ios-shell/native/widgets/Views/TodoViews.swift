import SwiftUI
import WidgetKit
import MyKhayaWidgetCore

private struct SignedOutTodoView: View {
    var body: some View {
        VStack(spacing: 4) {
            Image(systemName: "checklist")
                .foregroundStyle(.secondary)
            Text("Open MyKhaya to sign in")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding()
        .widgetURL(WidgetDeepLink.signInHome)
    }
}

private struct EmptyTodoView: View {
    var body: some View {
        VStack(spacing: 4) {
            Image(systemName: "checkmark.circle")
                .font(.title3)
                .foregroundStyle(.green)
            Text("All caught up")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding()
        .widgetURL(WidgetDeepLink.todoHome)
    }
}

private struct TodoRow: View {
    let item: WidgetTodoItem

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: item.kind == .routine ? "repeat.circle" : "bell")
                .foregroundStyle(item.overdue ? Color.red : Color.accentColor)
                .font(.footnote)
                .padding(.top, 1)
            VStack(alignment: .leading, spacing: 1) {
                Text(item.title)
                    .font(.subheadline.weight(.medium))
                    .lineLimit(2)
                    .truncationMode(.tail)
                Text(dueLabel(for: item))
                    .font(.caption2)
                    .foregroundStyle(item.overdue ? Color.red : Color.secondary)
            }
        }
    }
}

struct TodoSmallView: View {
    let snapshot: WidgetSnapshot

    var body: some View {
        if !snapshot.signedIn {
            SignedOutTodoView()
        } else if snapshot.todoItems.isEmpty {
            EmptyTodoView()
        } else {
            let overdueCount = snapshot.todoItems.filter(\.overdue).count
            VStack(alignment: .leading, spacing: 4) {
                Text("\(snapshot.todoItems.count)")
                    .font(.system(size: 30, weight: .bold))
                Text(snapshot.todoItems.count == 1 ? "to do" : "to do")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if overdueCount > 0 {
                    Text("\(overdueCount) overdue")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(.red)
                }
                Spacer(minLength: 0)
                if let next = snapshot.todoItems.first {
                    Text(next.title)
                        .font(.caption2)
                        .lineLimit(1)
                        .foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .padding()
            .widgetURL(snapshot.todoItems.first.flatMap { WidgetDeepLink.url(forPath: $0.deepLink) } ?? WidgetDeepLink.todoHome)
        }
    }
}

struct TodoMediumView: View {
    let snapshot: WidgetSnapshot

    var body: some View {
        if !snapshot.signedIn {
            SignedOutTodoView()
        } else if snapshot.todoItems.isEmpty {
            EmptyTodoView()
        } else {
            let items = Array(snapshot.todoItems.prefix(4))
            VStack(alignment: .leading, spacing: 6) {
                ForEach(Array(items.enumerated()), id: \.element.id) { index, item in
                    Link(destination: WidgetDeepLink.url(forPath: item.deepLink) ?? WidgetDeepLink.todoHome!) {
                        TodoRow(item: item)
                    }
                    if index < items.count - 1 {
                        Divider()
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .padding()
        }
    }
}

struct TodoLargeView: View {
    let snapshot: WidgetSnapshot

    var body: some View {
        if !snapshot.signedIn {
            SignedOutTodoView()
        } else if snapshot.todoItems.isEmpty {
            EmptyTodoView()
        } else {
            let items = Array(snapshot.todoItems.prefix(8))
            VStack(alignment: .leading, spacing: 8) {
                Text("Routines & Reminders")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                ForEach(Array(items.enumerated()), id: \.element.id) { index, item in
                    Link(destination: WidgetDeepLink.url(forPath: item.deepLink) ?? WidgetDeepLink.todoHome!) {
                        TodoRow(item: item)
                    }
                    if index < items.count - 1 {
                        Divider()
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .padding()
        }
    }
}
