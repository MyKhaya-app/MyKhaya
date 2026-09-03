import SwiftUI
import WidgetKit

/// Builds the 5- or 6-row day grid for the month containing `reference`,
/// including the leading/trailing days from adjacent months needed to fill
/// complete weeks (a widget must render a rectangular grid, unlike the web
/// calendar which can render a ragged first/last row). Weeks start on the
/// device's locale-appropriate first weekday.
func monthGridDays(containing reference: Date, calendar: Calendar) -> [Date] {
    guard let monthInterval = calendar.dateInterval(of: .month, for: reference),
          let firstWeekInterval = calendar.dateInterval(of: .weekOfMonth, for: monthInterval.start) else {
        return []
    }
    var days: [Date] = []
    var cursor = firstWeekInterval.start
    // Six rows covers every month/first-weekday combination (a 31-day month
    // starting on the last day of a week needs 6 rows); a 5-row month just
    // renders its final row as next-month days, matched by the day-cell's
    // own "not in this month" dimming.
    let totalDays = 6 * 7
    for _ in 0..<totalDays {
        days.append(cursor)
        cursor = calendar.date(byAdding: .day, value: 1, to: cursor) ?? cursor
    }
    return days
}

func dayKey(_ date: Date, calendar: Calendar) -> String {
    let components = calendar.dateComponents([.year, .month, .day], from: date)
    return "\(components.year ?? 0)-\(components.month ?? 0)-\(components.day ?? 0)"
}

/// Groups monthEvents by local day key. An all-day/multi-day event appears
/// under every day it spans — mirrors widget-snapshot.ts's own
/// day-spanning semantics (start/end day range, not a raw timestamp
/// comparison), so a multi-day event shows a coloured mark on each of its
/// days rather than only its start day.
func eventsByDay(_ events: [WidgetEvent], calendar: Calendar) -> [String: [WidgetEvent]] {
    var result: [String: [WidgetEvent]] = [:]
    for event in events {
        guard let start = event.startDate else { continue }
        let end = event.endDate ?? start
        var cursor = calendar.startOfDay(for: start)
        let lastDay = calendar.startOfDay(for: end.addingTimeInterval(-1))
        var guardCount = 0
        while cursor <= lastDay, guardCount < 62 {
            result[dayKey(cursor, calendar: calendar), default: []].append(event)
            cursor = calendar.date(byAdding: .day, value: 1, to: cursor) ?? cursor
            guardCount += 1
        }
    }
    return result
}

private struct SignedOutCalendarView: View {
    var body: some View {
        VStack(spacing: 4) {
            Image(systemName: "calendar.badge.exclamationmark")
                .foregroundStyle(.secondary)
            Text("Open MyKhaya to sign in")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .widgetURL(WidgetDeepLink.signInHome)
    }
}

/// Medium: the current week only — 7 compact day columns with up to two
/// colour chips per day, deliberately not attempting the full month
/// (Apple's own Medium widget height guidance rules out a legible 6-row
/// grid at that size).
struct CalendarWeekView: View {
    let snapshot: WidgetSnapshot

    var body: some View {
        if !snapshot.signedIn {
            SignedOutCalendarView()
        } else {
            let calendar = Calendar.current
            let today = calendar.startOfDay(for: Date())
            let week = calendar.dateInterval(of: .weekOfMonth, for: today)
            let days: [Date] = (0..<7).compactMap { offset in
                guard let start = week?.start else { return nil }
                return calendar.date(byAdding: .day, value: offset, to: start)
            }
            let grouped = eventsByDay(snapshot.monthEvents, calendar: calendar)
            let weekdaySymbols = calendar.veryShortStandaloneWeekdaySymbols

            HStack(alignment: .top, spacing: 4) {
                ForEach(days, id: \.self) { day in
                    let key = dayKey(day, calendar: calendar)
                    let isToday = calendar.isDate(day, inSameDayAs: today)
                    let weekdayIndex = calendar.component(.weekday, from: day) - 1
                    VStack(spacing: 4) {
                        Text(weekdaySymbols.indices.contains(weekdayIndex) ? weekdaySymbols[weekdayIndex] : "")
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(.secondary)
                        Text("\(calendar.component(.day, from: day))")
                            .font(.system(size: 13, weight: isToday ? .bold : .regular))
                            .frame(width: 22, height: 22)
                            .background(isToday ? Color.accentColor : Color.clear)
                            .foregroundStyle(isToday ? Color.white : Color.primary)
                            .clipShape(Circle())
                        HStack(spacing: 2) {
                            ForEach(Array((grouped[key] ?? []).prefix(3).enumerated()), id: \.offset) { _, event in
                                Circle()
                                    .fill(Color(mykhayaHex: event.colorHex))
                                    .frame(width: 4, height: 4)
                            }
                        }
                        .frame(height: 4)
                    }
                    .frame(maxWidth: .infinity)
                }
            }
            .padding()
            .widgetURL(WidgetDeepLink.calendarHome)
        }
    }
}

/// Large: the current month as a 6-row grid. Each cell shows the day
/// number and up to 2 coloured event bars, plus a "+N" overflow label
/// rather than trying to render every event — the task's explicit
/// "graceful condensed representation" requirement.
struct CalendarMonthView: View {
    let snapshot: WidgetSnapshot

    private let maxBarsPerCell = 2

    var body: some View {
        if !snapshot.signedIn {
            SignedOutCalendarView()
        } else {
            let calendar = Calendar.current
            let today = calendar.startOfDay(for: Date())
            let days = monthGridDays(containing: today, calendar: calendar)
            let grouped = eventsByDay(snapshot.monthEvents, calendar: calendar)
            let currentMonth = calendar.component(.month, from: today)
            let weekdaySymbols = calendar.veryShortStandaloneWeekdaySymbols
            let columns = Array(repeating: GridItem(.flexible(), spacing: 2), count: 7)

            VStack(spacing: 4) {
                HStack {
                    ForEach(weekdaySymbols, id: \.self) { symbol in
                        Text(symbol)
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity)
                    }
                }
                LazyVGrid(columns: columns, spacing: 3) {
                    ForEach(days, id: \.self) { day in
                        let key = dayKey(day, calendar: calendar)
                        let dayEvents = grouped[key] ?? []
                        let inCurrentMonth = calendar.component(.month, from: day) == currentMonth
                        let isToday = calendar.isDate(day, inSameDayAs: today)
                        MonthDayCell(
                            day: day,
                            events: dayEvents,
                            isToday: isToday,
                            inCurrentMonth: inCurrentMonth,
                            maxBars: maxBarsPerCell
                        )
                    }
                }
            }
            .padding(10)
            .widgetURL(WidgetDeepLink.calendarHome)
        }
    }
}

private struct MonthDayCell: View {
    let day: Date
    let events: [WidgetEvent]
    let isToday: Bool
    let inCurrentMonth: Bool
    let maxBars: Int

    var body: some View {
        VStack(spacing: 1) {
            Text("\(Calendar.current.component(.day, from: day))")
                .font(.system(size: 10, weight: isToday ? .bold : .regular))
                .frame(width: 16, height: 16)
                .background(isToday ? Color.accentColor : Color.clear)
                .foregroundStyle(isToday ? Color.white : (inCurrentMonth ? Color.primary : Color.secondary.opacity(0.4)))
                .clipShape(Circle())
            VStack(spacing: 1) {
                ForEach(Array(events.prefix(maxBars).enumerated()), id: \.offset) { _, event in
                    Capsule()
                        .fill(Color(mykhayaHex: event.colorHex).opacity(inCurrentMonth ? 1 : 0.35))
                        .frame(height: 3)
                }
                if events.count > maxBars {
                    Text("+\(events.count - maxBars)")
                        .font(.system(size: 7, weight: .semibold))
                        .foregroundStyle(.secondary)
                }
            }
            .frame(height: CGFloat(maxBars) * 4 + 6)
        }
        .frame(maxWidth: .infinity)
    }
}
