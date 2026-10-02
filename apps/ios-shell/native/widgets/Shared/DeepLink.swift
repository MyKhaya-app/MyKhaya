import Foundation

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
/// therefore open Safari, not MyKhaya — wrong. `mykhaya://` is a small,
/// additive URL Scheme (CFBundleURLTypes in Info.plist — not an Associated
/// Domain, no Apple Developer portal step) registered only so a widget tap
/// can hand its already-canonical path back to the running app, which then
/// loads that exact path in its existing WKWebView. It carries no new
/// routing logic of its own — MainViewController's application(_:open:)
/// handler (installed by scripts/install-widget-sources.sh) does nothing
/// but extract `path` and navigate the WebView there.
enum WidgetDeepLink {
    private static let scheme = "mykhaya"

    static func url(forPath path: String) -> URL? {
        var components = URLComponents()
        components.scheme = scheme
        components.host = "open"
        components.queryItems = [URLQueryItem(name: "path", value: path)]
        return components.url
    }

    /// Generic "open the Calendar" / "open Routines & Reminders" links used
    /// when a widget shows no specific item (empty states, the widget's own
    /// background tap target on the Calendar/To-do widgets).
    static let calendarHome = url(forPath: "/calendar")
    static let todoHome = url(forPath: "/settings/routines-reminders")
    static let signInHome = url(forPath: "/login")
}
