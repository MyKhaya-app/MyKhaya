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
//
// Lives in the MyKhayaWidgetCore package (not apps/ios-shell/native/widgets/
// directly) so both the MyKhayaWidgets extension target and the main App
// target compile exactly one copy via `import MyKhayaWidgetCore`, and so
// XCTest can link against it (an app extension's own compiled code cannot
// be an XCTest host).

/// Bump in lockstep with WIDGET_SNAPSHOT_SCHEMA_VERSION in widget-snapshot.ts.
/// `WidgetSnapshotStore.load()` treats a decode failure or a mismatched
/// version as "no data" rather than guessing at a shape it wasn't built
/// for — see its doc comment.
public let widgetSnapshotSchemaVersion = 1

public struct WidgetHome: Codable, Equatable, Sendable {
    public let id: String
    public let displayName: String

    public init(id: String, displayName: String) {
        self.id = id
        self.displayName = displayName
    }
}

public struct WidgetEvent: Codable, Equatable, Identifiable, Sendable {
    public let id: String
    public let title: String
    /// ISO-8601 UTC (e.g. "2026-09-03T09:00:00.000Z") as produced by
    /// JavaScript's `Date.prototype.toISOString()`.
    public let startAt: String
    public let endAt: String
    public let isAllDay: Bool
    public let timezone: String
    public let colorHex: String
    public let deepLink: String

    public init(id: String, title: String, startAt: String, endAt: String, isAllDay: Bool, timezone: String, colorHex: String, deepLink: String) {
        self.id = id
        self.title = title
        self.startAt = startAt
        self.endAt = endAt
        self.isAllDay = isAllDay
        self.timezone = timezone
        self.colorHex = colorHex
        self.deepLink = deepLink
    }

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

    public var startDate: Date? { Self.parse(startAt) }
    public var endDate: Date? { Self.parse(endAt) }
}

public enum WidgetTodoKind: String, Codable, Equatable, Sendable {
    case routine
    case reminder
}

public enum WidgetTodoScope: String, Codable, Equatable, Sendable {
    case personal
    case household
}

public struct WidgetTodoItem: Codable, Equatable, Identifiable, Sendable {
    public let id: String
    public let kind: WidgetTodoKind
    public let title: String
    /// ISO date ("2026-09-03") or date+time ("2026-09-03T09:00:00"); nil if
    /// the item has no concrete next occurrence.
    public let dueAt: String?
    public let overdue: Bool
    public let scope: WidgetTodoScope
    public let deepLink: String

    public init(id: String, kind: WidgetTodoKind, title: String, dueAt: String?, overdue: Bool, scope: WidgetTodoScope, deepLink: String) {
        self.id = id
        self.kind = kind
        self.title = title
        self.dueAt = dueAt
        self.overdue = overdue
        self.scope = scope
        self.deepLink = deepLink
    }
}

public struct WidgetSnapshot: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    /// ISO-8601 UTC — when the web app produced this snapshot.
    public let generatedAt: String
    public let signedIn: Bool
    public let activeHome: WidgetHome?
    public let upcomingEvents: [WidgetEvent]
    public let todayEvents: [WidgetEvent]
    public let monthEvents: [WidgetEvent]
    public let todoItems: [WidgetTodoItem]

    public init(schemaVersion: Int, generatedAt: String, signedIn: Bool, activeHome: WidgetHome?, upcomingEvents: [WidgetEvent], todayEvents: [WidgetEvent], monthEvents: [WidgetEvent], todoItems: [WidgetTodoItem]) {
        self.schemaVersion = schemaVersion
        self.generatedAt = generatedAt
        self.signedIn = signedIn
        self.activeHome = activeHome
        self.upcomingEvents = upcomingEvents
        self.todayEvents = todayEvents
        self.monthEvents = monthEvents
        self.todoItems = todoItems
    }

    /// The state used before any real snapshot has ever been written, and
    /// whenever decoding fails/mismatches — matches
    /// signedOutWidgetSnapshot() in widget-snapshot.ts.
    public static func signedOut(generatedAt: Date = Date()) -> WidgetSnapshot {
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
