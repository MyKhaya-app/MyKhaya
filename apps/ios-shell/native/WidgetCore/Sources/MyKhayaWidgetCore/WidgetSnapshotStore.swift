import Foundation
import WidgetKit

/// The single read/write surface for the shared widget snapshot. Used by
/// both the main app target (via WidgetBridgePlugin, write side) and the
/// widget extension (TimelineProviders, read side) — both import this same
/// package, which is why it lives in MyKhayaWidgetCore rather than
/// apps/ios-shell/native/widgets/.
///
/// Storage: one JSON blob written atomically to a file inside the App
/// Group container, not scattered UserDefaults keys — a widget must never
/// observe a half-applied update (task's "atomic writes" requirement). File
/// storage is used instead of `UserDefaults(suiteName:)` because
/// `Data.write(options: .atomic)` gives a real atomic-rename guarantee;
/// UserDefaults's own persistence timing is not documented as atomic for a
/// single call from WidgetKit's perspective.
///
/// This type imports WidgetKit (for `WidgetCenter.shared.reloadAllTimelines()`)
/// — that is not a new dependency introduced by moving it into this package:
/// before the package existed, this exact file was compiled separately into
/// both the App target and the MyKhayaWidgets extension target, each of
/// which already linked WidgetKit. Splitting the WidgetKit-touching
/// `save`/`clear` methods out from the WidgetKit-independent `load()` method
/// was considered and rejected: they share the same App Group file path and
/// are conceptually one read/write surface, and the main App target already
/// needs a WidgetKit-linked build (it calls this type to trigger timeline
/// reloads), so no target gains or loses a framework dependency by this move.
public enum WidgetSnapshotStore {
    /// Must match the App Group configured on both the main app target and
    /// the widget extension target's entitlements (see
    /// scripts/setup-widget-extension.rb and docs/mobile/ios-widgets.md).
    /// Reused, not invented fresh: matches the `app.mykhaya.mobile` bundle
    /// ID convention used throughout apps/ios-shell.
    public static let appGroupIdentifier = "group.app.mykhaya.mobile"

    private static let fileName = "widget-snapshot.json"

    private static var containerURL: URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroupIdentifier)
    }

    private static var snapshotURL: URL? {
        containerURL?.appendingPathComponent(fileName)
    }

    /// Atomically replaces the stored snapshot and asks WidgetKit to reload
    /// every MyKhaya widget's timeline. Called only from the main app
    /// target (WidgetBridgePlugin); the widget extension is read-only.
    public static func save(_ snapshot: WidgetSnapshot) {
        guard let url = snapshotURL else {
            assertionFailure("MyKhaya widget App Group container unavailable — is the '\(appGroupIdentifier)' capability configured on this target?")
            return
        }
        do {
            let data = try JSONEncoder().encode(snapshot)
            try data.write(to: url, options: .atomic)
        } catch {
            NSLog("[MyKhayaWidgets] failed to write snapshot: %@", error.localizedDescription)
            return
        }
        WidgetCenter.shared.reloadAllTimelines()
    }

    /// Replaces the stored snapshot with the signed-out state and reloads
    /// timelines — the logout path. Deliberately the same "reload all"
    /// call as save(): MyKhaya has three widget kinds sharing one snapshot,
    /// so a per-kind reload would still need to cover all three.
    public static func clear() {
        save(WidgetSnapshot.signedOut())
    }

    /// Read path used by every TimelineProvider. Missing file (never
    /// synced yet), corrupt JSON, and a schema-version mismatch all
    /// collapse to the same signed-out placeholder rather than crashing
    /// the widget or guessing at an incompatible shape — see the task's
    /// "handle cleanly" requirement for exactly these cases.
    public static func load() -> WidgetSnapshot {
        guard let url = snapshotURL,
              let data = try? Data(contentsOf: url) else {
            return WidgetSnapshot.signedOut()
        }
        return decode(data)
    }

    /// Decode-and-validate logic factored out of `load()` so it can be unit
    /// tested directly without depending on the App Group container being
    /// available (it isn't, in a plain `swift test` process — see
    /// WidgetSnapshotStoreTests.swift).
    static func decode(_ data: Data) -> WidgetSnapshot {
        guard let snapshot = try? JSONDecoder().decode(WidgetSnapshot.self, from: data) else {
            NSLog("[MyKhayaWidgets] snapshot file present but failed to decode — treating as signed out")
            return WidgetSnapshot.signedOut()
        }
        guard snapshot.schemaVersion == widgetSnapshotSchemaVersion else {
            NSLog("[MyKhayaWidgets] snapshot schema version %d != expected %d — treating as signed out", snapshot.schemaVersion, widgetSnapshotSchemaVersion)
            return WidgetSnapshot.signedOut()
        }
        return snapshot
    }
}
