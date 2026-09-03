import Foundation

// Pure row/column packing logic for the Medium Calendar widget's weekly
// event-bar view (apps/ios-shell/native/widgets/Views/CalendarViews.swift's
// CalendarWeekView). Deliberately separate from eventsByDay/monthGridDays
// (CalendarLayout.swift), which duplicate a multi-day event onto every day
// it spans — exactly what a per-day dot list needs, and exactly wrong for a
// spanning bar, which must appear once with a start/end column range. Kept
// here (not in the widget target) so the row-packing algorithm — the part
// most likely to have an off-by-one or overlap bug — is linkable by XCTest.

/// One event's placement within the 7-column (Mon..Sun) week grid: which
/// columns it spans and which vertical row it occupies. `startColumn`/
/// `endColumn` are both inclusive and already clipped to 0...6, so the
/// SwiftUI side never needs to reason about a bar extending outside the
/// widget's 7-day window.
///
/// A single-day event always has `startColumn == endColumn`: its tile must
/// stay strictly inside its own day column so the bar's geometry alone
/// tells the user whether an event lasts one day or several. Only a
/// genuinely multi-day event (real date range spans more than one calendar
/// day) has `endColumn > startColumn`. There is deliberately no mechanism
/// here that widens a single-day bar into unused neighbouring columns —
/// that was tried and rejected: it made single-day events visually
/// indistinguishable from multi-day ones. Truncating a title that doesn't
/// fit in one column's width is the accepted, correct behaviour.
public struct WeekEventBar: Equatable, Sendable {
    public let eventId: String
    public let title: String
    public let colorHex: String
    public let deepLink: String
    public let startColumn: Int
    public let endColumn: Int
    public let row: Int
}

/// `bars` holds only events that fit within `maxRows`; `overflowByColumn`
/// (always exactly 7 entries, index 0 = Monday) counts, per day, how many
/// additional events touch that day but didn't fit — a spanning event that
/// overflows increments every column it would have covered, since each of
/// those days genuinely has one more event than is shown.
public struct WeekEventLayoutResult: Equatable, Sendable {
    public let bars: [WeekEventBar]
    public let overflowByColumn: [Int]
}

/// Lays out `events` against the 7-day window starting at `weekStart`
/// (any time on the first displayed day; only the calendar day matters).
///
/// Algorithm: classic greedy interval-graph colouring (the same idea as the
/// "minimum meeting rooms" problem, adapted to also record which row each
/// event lands in, not just the row count). Events are sorted by start
/// column, then by span length descending, then by `id` ascending as a
/// final structural tiebreaker — never by title, so a title's length or
/// content can never influence which row/column an event occupies. Each
/// event is then assigned to the lowest-numbered row whose most recent
/// occupant ends before this event starts; no row is reused if that would
/// overlap, so two events overlapping in date range can never land on the
/// same row. This is deterministic: the same event set always sorts and
/// packs the same way.
public func weekEventLayout(
    events: [WidgetEvent],
    weekStart: Date,
    calendar: Calendar,
    maxRows: Int = 3
) -> WeekEventLayoutResult {
    let dayStart = calendar.startOfDay(for: weekStart)
    guard let weekEnd = calendar.date(byAdding: .day, value: 7, to: dayStart) else {
        return WeekEventLayoutResult(bars: [], overflowByColumn: Array(repeating: 0, count: 7))
    }

    struct Candidate {
        let event: WidgetEvent
        let startColumn: Int
        let endColumn: Int
    }

    var candidates: [Candidate] = []
    for event in events {
        guard let start = event.startDate else { continue }
        let end = event.endDate ?? start
        guard start < weekEnd, end > dayStart else { continue }

        // Same exclusive-end convention as eventsByDay in CalendarLayout.swift
        // (end minus one second, then take that instant's calendar day) so a
        // multi-day event occupies exactly the same set of days whether it's
        // shown as bars here or as per-day dots in the month view.
        let startDay = calendar.startOfDay(for: start)
        let endDay = calendar.startOfDay(for: end.addingTimeInterval(-1))
        guard let rawStartColumn = calendar.dateComponents([.day], from: dayStart, to: startDay).day,
              let rawEndColumn = calendar.dateComponents([.day], from: dayStart, to: endDay).day else { continue }

        let clippedStart = max(0, rawStartColumn)
        let clippedEnd = min(6, rawEndColumn)
        guard clippedStart <= clippedEnd else { continue }
        candidates.append(Candidate(event: event, startColumn: clippedStart, endColumn: clippedEnd))
    }

    let sorted = candidates.sorted { a, b in
        if a.startColumn != b.startColumn { return a.startColumn < b.startColumn }
        let aSpan = a.endColumn - a.startColumn
        let bSpan = b.endColumn - b.startColumn
        if aSpan != bSpan { return aSpan > bSpan }
        return a.event.id < b.event.id
    }

    var rowEndColumns: [Int] = []
    var placedBars: [WeekEventBar] = []
    var overflowByColumn = Array(repeating: 0, count: 7)

    for candidate in sorted {
        let existingRow = rowEndColumns.indices.first { rowEndColumns[$0] < candidate.startColumn }
        let rowIndex = existingRow ?? rowEndColumns.count
        if let existingRow {
            rowEndColumns[existingRow] = candidate.endColumn
        } else {
            rowEndColumns.append(candidate.endColumn)
        }

        if rowIndex < maxRows {
            placedBars.append(WeekEventBar(
                eventId: candidate.event.id,
                title: candidate.event.title,
                colorHex: candidate.event.colorHex,
                deepLink: candidate.event.deepLink,
                startColumn: candidate.startColumn,
                endColumn: candidate.endColumn,
                row: rowIndex
            ))
        } else {
            for column in candidate.startColumn...candidate.endColumn {
                overflowByColumn[column] += 1
            }
        }
    }

    return WeekEventLayoutResult(bars: placedBars, overflowByColumn: overflowByColumn)
}
