import Foundation
import MyKhayaWidgetCore
import SwiftUI

/// Turns an app-relative path (e.g. "/calendar?event=abc-123", already
/// produced by widget-snapshot.ts using the exact same logic as
/// apps/api/mykhaya/notifications/deep_links.py's resolve_path()) into a
/// URL a widget's `Link`/`widgetURL` can open.
///
/// Why a custom scheme and not the live https:// origin directly: MyKhaya's
/// deep links (push, email) are ordinary https:// URLs resolved through the
/// live frontend origin (see ADR 0012) — that works from a notification or
/// an email client because the OS treats it as "open in Safari/whatever app
/// claims it", and nothing claims it today because Associated
/// Domains/Universal Links are explicitly not configured yet (ADR 0012,
/// "Consequences"). A Home Screen widget tapping an https:// URL would
/// therefore open Safari, not MyKhaya — wrong. A small, additive URL Scheme
/// (CFBundleURLTypes in Info.plist — not an Associated Domain, no Apple
/// Developer portal step) is registered only so a widget tap can hand its
/// already-canonical path back to the running app, which then loads that
/// exact path in its existing WKWebView (WidgetBridgePlugin).
///
/// The scheme is this environment's own (DEV `mykhaya`, PROD
/// `mykhaya-prod`), read from the widget's Info.plist (`MyKhayaURLScheme`,
/// set from the build configuration), so a DEV widget only ever opens the
/// DEV app and a PROD widget only the PROD app. Never hardcode it here.
enum WidgetDeepLink {
    static func url(forPath path: String) -> URL? {
        guard let scheme = MyKhayaEnvironment.current?.urlScheme else { return nil }
        return WidgetDeepLinkRoute.url(forPath: path, scheme: scheme)
    }

    /// Generic "open the Calendar" / "open Routines & Reminders" links used
    /// when a widget shows no specific item (empty states, the widget's own
    /// background tap target on the Calendar/To-do widgets).
    static let calendarHome = url(forPath: "/calendar")
    static let todoHome = url(forPath: "/settings/routines-reminders")
    static let signInHome = url(forPath: "/login")
}

/// A `Link` when there is a URL, otherwise the plain content: a widget
/// without a configured scheme stays usable (just not tappable) instead of
/// crashing on a force-unwrapped fallback URL.
struct WidgetLink<Content: View>: View {
    let url: URL?
    @ViewBuilder let content: () -> Content

    var body: some View {
        if let url {
            Link(destination: url, label: content)
        } else {
            content()
        }
    }
}
