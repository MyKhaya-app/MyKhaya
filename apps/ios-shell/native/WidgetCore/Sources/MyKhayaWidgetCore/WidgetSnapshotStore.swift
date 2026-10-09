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
    /// The App Group shared by the main app and its widget extension, never
    /// hardcoded, because DEV and PROD are separate apps built from this same
    /// source:
    ///   DEV   app.mykhaya.mobile       (+ .widgets) -> group.app.mykhaya.mobile
    ///   PROD  app.mykhaya.mobile.prod  (+ .widgets) -> group.app.mykhaya.mobile.prod
    /// Read from the target's Info.plist (`MyKhayaAppGroup`, set from the
    /// same build setting as the entitlements, `MYKHAYA_APP_GROUP`); a build
    /// without that key falls back to `group.` + the app's bundle identifier.
    /// Both targets therefore always agree. nil when neither is available.
    public static let appGroupIdentifier: String? =
        MyKhayaEnvironment.current?.appGroup
            ?? groupIdentifier(forBundleIdentifier: Bundle.main.bundleIdentifier)

    private static let widgetExtensionSuffix = ".widgets"

    /// Pure mapping from a bundle identifier (the app's, or its widget
    /// extension's) to the shared App Group. Internal for unit tests.
    static func groupIdentifier(forBundleIdentifier bundleIdentifier: String?) -> String? {
        guard var appBundleIdentifier = bundleIdentifier, !appBundleIdentifier.isEmpty else {
            return nil
        }
        if appBundleIdentifier.hasSuffix(widgetExtensionSuffix) {
            appBundleIdentifier.removeLast(widgetExtensionSuffix.count)
        }
        guard !appBundleIdentifier.isEmpty else { return nil }
        return "group.\(appBundleIdentifier)"
    }

    private static let fileName = "widget-snapshot.json"

    /// nil when the App Group isn't available to this process (iOS logs
    /// "client is not entitled"). Every caller treats that as "no widget
    /// storage", never as a crash: widgets are an extra, not app startup.
    private static var containerURL: URL? {
        guard let group = appGroupIdentifier else { return nil }
        return FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: group)
    }

    private static var snapshotURL: URL? {
        containerURL?.appendingPathComponent(fileName)
    }

    /// Atomically replaces the stored snapshot and asks WidgetKit to reload
    /// every MyKhaya widget's timeline. Called only from the main app
    /// target (WidgetBridgePlugin); the widget extension is read-only.
    public static func save(_ snapshot: WidgetSnapshot) {
        guard let url = snapshotURL else {
            // Log, never trap: an assertion here crashed Debug builds at
            // startup (the web app syncs the snapshot right after restoring
            // a session) whenever the group was missing from the entitlements.
            NSLog(
                "[MyKhayaWidgets] App Group container unavailable for '%@' — is that App Group in this target's entitlements? Widget snapshot not saved.",
                appGroupIdentifier ?? "(no bundle identifier)"
            )
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
