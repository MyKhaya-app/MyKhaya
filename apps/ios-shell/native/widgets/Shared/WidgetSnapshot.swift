import Foundation

// MyKhaya iOS widgets (Phase 5). This file is the Swift mirror of
// apps/web/components/widget-snapshot.ts's TypeScript types — the two must
// be kept in sync by hand (there is no shared codegen for this narrow,
// deliberately display-only contract). Property names match the JSON keys
// the web app emits (camelCase) exactly, so no CodingKeys mapping is
// needed; JSONDecoder's default keyDecodingStrategy already lines up.
//
// This is NOT a copy of any backend API model — see
// docs/mobile/ios-widgets.md "What is stored / what is not" for the full
// list of fields deliberately excluded (auth tokens, cookies, PINs,
// biometric data, raw backend metadata).

/// Bump in lockstep with WIDGET_SNAPSHOT_SCHEMA_VERSION in widget-snapshot.ts.
/// `WidgetSnapshotStore.load()` treats a decode failure or a mismatched
/// version as "no data" rather than guessing at a shape it wasn't built
/// for — see its doc comment.
let widgetSnapshotSchemaVersion = 1

struct WidgetHome: Codable, Equatable {
    let id: String
    let displayName: String
}

struct WidgetEvent: Codable, Equatable, Identifiable {
    let id: String
    let title: String
    /// ISO-8601 UTC (e.g. "2026-09-03T09:00:00.000Z") as produced by
    /// JavaScript's `Date.prototype.toISOString()`.
    let startAt: String
    let endAt: String
    let isAllDay: Bool
    let timezone: String
    let colorHex: String
    let deepLink: String

    private static let isoFormatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    private static let isoFormatterNoFraction: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    private static func parse(_ iso: String) -> Date? {
        Self.isoFormatter.date(from: iso) ?? Self.isoFormatterNoFraction.date(from: iso)
    }

    var startDate: Date? { Self.parse(startAt) }
    var endDate: Date? { Self.parse(endAt) }
}

enum WidgetTodoKind: String, Codable, Equatable {
    case routine
    case reminder
}

enum WidgetTodoScope: String, Codable, Equatable {
    case personal
    case household
}

struct WidgetTodoItem: Codable, Equatable, Identifiable {
    let id: String
    let kind: WidgetTodoKind
    let title: String
    /// ISO date ("2026-09-03") or date+time ("2026-09-03T09:00:00"); nil if
    /// the item has no concrete next occurrence.
    let dueAt: String?
    let overdue: Bool
    let scope: WidgetTodoScope
    let deepLink: String
}

struct WidgetSnapshot: Codable, Equatable {
    let schemaVersion: Int
    /// ISO-8601 UTC — when the web app produced this snapshot.
    let generatedAt: String
    let signedIn: Bool
    let activeHome: WidgetHome?
    let upcomingEvents: [WidgetEvent]
    let todayEvents: [WidgetEvent]
    let monthEvents: [WidgetEvent]
    let todoItems: [WidgetTodoItem]

    /// The state used before any real snapshot has ever been written, and
    /// whenever decoding fails/mismatches — matches
    /// signedOutWidgetSnapshot() in widget-snapshot.ts.
    static func signedOut(generatedAt: Date = Date()) -> WidgetSnapshot {
        WidgetSnapshot(
            schemaVersion: widgetSnapshotSchemaVersion,
            generatedAt: ISO8601DateFormatter().string(from: generatedAt),
            signedIn: false,
            activeHome: nil,
            upcomingEvents: [],
            todayEvents: [],
            monthEvents: [],
            todoItems: []
        )
    }
}
