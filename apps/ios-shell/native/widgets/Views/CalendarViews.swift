import SwiftUI
import WidgetKit
import MyKhayaWidgetCore

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

/// Medium: the current week — a TimeTree-style view with the day header
/// (weekday label, date, today-highlight — unchanged from the previous
/// dot-based version) followed by actual coloured event tiles/bars, one row
/// per non-overlapping event, with multi-day events spanning their day
/// columns as a single continuous bar. Row/column placement itself is
/// weekEventLayout (MyKhayaWidgetCore) — pure, tested logic; this view only
/// renders whatever it computes.
struct CalendarWeekView: View {
    let snapshot: WidgetSnapshot

    // 4 rows stays the density cap (unchanged) — but row/tile HEIGHT is no
    // longer a fixed point-size guess. A fixed-height first pass measured
    // against one assumed content budget left real, observed dead space
    // below the last row (the budget estimate undershot the actual
    // available height). WeekEventBarsView now sizes rows from the real
    // GeometryReader height at render time instead, so the event area
    // always fills whatever vertical space the header's tighter padding
    // (below) actually leaves — correct across widget size classes, not
    // just the one device this was measured on.
    //
    // Reconsidered at 3 vs. 4 when single-day titles were still truncating
    // too hard, and kept at 4: title truncation was a WIDTH problem
    // (columnWidth = widget width / 7, entirely independent of row count),
    // not a height one, so dropping to 3 rows would not have widened a
    // single tile by a single point — it would only have shown fewer
    // events and pushed more into "+N" overflow for no readability gain.
    // A horizontal-expansion fix (a single-day bar growing into unused
    // adjacent columns) was tried and reverted: it made single-day events
    // visually indistinguishable from multi-day ones, which is a semantic
    // regression worse than truncation. A single-day bar's endColumn always
    // equals its startColumn (see WeekEventLayout.swift) — truncating a
    // title that doesn't fit in one column's width is the accepted,
    // correct behaviour.
    private let maxRows = 4
    private let rowSpacing: CGFloat = 4
    private let barHorizontalGap: CGFloat = 1.5

    var body: some View {
        if !snapshot.signedIn {
            SignedOutCalendarView()
        } else {
            let calendar = Calendar.current
            let today = calendar.startOfDay(for: Date())
            let week = calendar.dateInterval(of: .weekOfMonth, for: today)
            let weekStart = week?.start ?? today
            let days: [Date] = (0..<7).compactMap { offset in
                calendar.date(byAdding: .day, value: offset, to: weekStart)
            }
            let weekdaySymbols = calendar.veryShortStandaloneWeekdaySymbols
            let layout = weekEventLayout(events: snapshot.monthEvents, weekStart: weekStart, calendar: calendar, maxRows: maxRows)

            VStack(alignment: .leading, spacing: 4) {
                // spacing: 0 — WeekEventBarsView below divides its own
                // width as geo.size.width / 7 with no inter-column gap, so
                // the header's day columns must use the same division to
                // stay aligned with the event bars underneath them. The
                // previous `spacing: 4` gave the header 6 gaps (24pt) the
                // bar grid didn't know about, silently drifting the two
                // grids apart column-by-column moving rightward across the
                // week — a real (if subtle) misalignment, not just wasted
                // space; fixing it also reclaims that 24pt for date/tile
                // content, addressing the "reclaim horizontal space" ask.
                HStack(alignment: .top, spacing: 0) {
                    ForEach(days, id: \.self) { day in
                        let isToday = calendar.isDate(day, inSameDayAs: today)
                        let weekdayIndex = calendar.component(.weekday, from: day) - 1
                        VStack(spacing: 3) {
                            Text(weekdaySymbols.indices.contains(weekdayIndex) ? weekdaySymbols[weekdayIndex] : "")
                                .font(.system(size: 9, weight: .semibold))
                                .foregroundStyle(.secondary)
                            Text("\(calendar.component(.day, from: day))")
                                .font(.system(size: 13, weight: isToday ? .bold : .regular))
                                .frame(width: 22, height: 22)
                                .background(isToday ? Color.accentColor : Color.clear)
                                .foregroundStyle(isToday ? Color.white : Color.primary)
                                .clipShape(Circle())
                        }
                        .frame(maxWidth: .infinity)
                    }
                }

                WeekEventBarsView(
                    layout: layout,
                    maxRows: maxRows,
                    rowSpacing: rowSpacing,
                    barHorizontalGap: barHorizontalGap
                )
                .frame(maxHeight: .infinity)
            }
            // Horizontal inset trimmed from 12pt to 8pt each side — this is
            // an iOS 16-floor widget with no automatic system content
            // margin API available (that's an iOS 17+ WidgetKit feature),
            // so this padding is the entire inset; 8pt keeps tiles clear of
            // the widget's rounded corner without giving up width the
            // event titles need more.
            .padding(.horizontal, 8)
            .padding(.top, 8)
            .padding(.bottom, 6)
            .widgetURL(WidgetDeepLink.calendarHome)
        }
    }
}

/// Renders weekEventLayout's computed bars as absolutely-positioned tiles
/// within a 7-column grid (via GeometryReader, since a spanning bar's width
/// depends on the widget's actual rendered width, not a fixed point size),
/// plus a per-day "+N" overflow row when any column has hidden events.
private struct WeekEventBarsView: View {
    let layout: WeekEventLayoutResult
    let maxRows: Int
    let rowSpacing: CGFloat
    let barHorizontalGap: CGFloat

    private var hasOverflow: Bool { layout.overflowByColumn.contains { $0 > 0 } }

    // Row height is no longer a guessed constant: it's the real available
    // height (from the parent's .frame(maxHeight: .infinity), which is
    // whatever the header's tighter padding leaves) divided across every
    // row slot actually in use — event rows plus, when needed, one more
    // slot for the overflow badges. This is what makes the event area use
    // the full remaining space on any device rather than leaving a gap
    // under the last row, and is why the overflow indicator no longer
    // reads as a separate floating element: it occupies a row slot with
    // the exact same rowSpacing rhythm as every event row above it,
    // immediately adjacent to the last one rather than set apart.
    private func rowHeight(for totalHeight: CGFloat, slots: Int) -> CGFloat {
        guard slots > 0 else { return 0 }
        let spacingTotal = CGFloat(slots - 1) * rowSpacing
        let raw = (totalHeight - spacingTotal) / CGFloat(slots)
        return min(max(raw, 16), 26)
    }

    var body: some View {
        GeometryReader { geo in
            let columnWidth = geo.size.width / 7
            let slots = maxRows + (hasOverflow ? 1 : 0)
            let rowH = rowHeight(for: geo.size.height, slots: slots)
            ZStack(alignment: .topLeading) {
                ForEach(layout.bars, id: \.eventId) { bar in
                    let width = max(CGFloat(bar.endColumn - bar.startColumn + 1) * columnWidth - barHorizontalGap, 0)
                    EventBarTile(title: bar.title, colorHex: bar.colorHex, deepLinkPath: bar.deepLink)
                        .frame(width: width, height: rowH)
                        .offset(
                            x: CGFloat(bar.startColumn) * columnWidth + barHorizontalGap / 2,
                            y: CGFloat(bar.row) * (rowH + rowSpacing)
                        )
                }
                if hasOverflow {
                    HStack(spacing: barHorizontalGap) {
                        ForEach(0..<7, id: \.self) { column in
                            Group {
                                if layout.overflowByColumn[column] > 0 {
                                    Text("+\(layout.overflowByColumn[column])")
                                        .font(.system(size: 9, weight: .bold))
                                        .foregroundStyle(.white)
                                        .padding(.horizontal, 5)
                                        .padding(.vertical, 2)
                                        .background(Color.secondary.opacity(0.65), in: Capsule())
                                } else {
                                    Color.clear
                                }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    .frame(width: geo.size.width, height: rowH, alignment: .leading)
                    .offset(y: CGFloat(maxRows) * (rowH + rowSpacing))
                }
            }
        }
    }
}

/// One event tile/bar. Background is the event's real MyKhaya colour;
/// foreground text colour is computed per-tile from that same colour
/// (isLightBackground, MyKhayaWidgetCore) rather than hardcoded, so a pale
/// category colour still gets dark text and a deep one still gets light
/// text. Wrapped in a Link to the event's own deep link where available —
/// classic (non-interactive) multiple Link destinations within one widget
/// are supported from this widget's iOS 16 floor — falling back to plain
/// content (relying on the whole-widget widgetURL) if the path is missing.
private struct EventBarTile: View {
    let title: String
    let colorHex: String
    let deepLinkPath: String

    var body: some View {
        // 4pt of horizontal padding on both sides of an already-narrow
        // single-day tile (~1/7th of the widget's width, minus the
        // inter-tile gap) was eating a disproportionate share of its
        // width before a single character was drawn — the direct cause of
        // titles truncating to 3-4 characters. 2pt preserves a clean
        // inset without wasting space the title needs more than the gap
        // does; a multi-column spanning bar has plenty of width either
        // way, so this only meaningfully helps the tight single-day case.
        let content = Text(title)
            .font(.system(size: 10, weight: .semibold))
            .lineLimit(1)
            .truncationMode(.tail)
            .minimumScaleFactor(0.9)
            .foregroundStyle(isLightBackground(hex: colorHex) ? Color.black : Color.white)
            .padding(.horizontal, 2)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            .background(Color(mykhayaHex: colorHex), in: RoundedRectangle(cornerRadius: 4, style: .continuous))

        if let url = WidgetDeepLink.url(forPath: deepLinkPath) {
            Link(destination: url) { content }
        } else {
            content
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
