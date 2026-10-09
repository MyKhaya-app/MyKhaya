import Foundation

/// The environment (DEV or PROD) of the running app or widget extension.
///
/// MyKhaya ships two separate iOS apps from one project. Every
/// environment-specific value comes from the target's Info.plist, which
/// Xcode fills in from the build configuration's xcconfig
/// (ios/App/Config/Environment-Dev.xcconfig / Environment-Prod.xcconfig).
/// Shared native code must read them from here and never hardcode either
/// environment's identifiers: a hardcoded PROD value in shared code is how
/// the DEV app broke after commit fb3e1b2.
public struct MyKhayaEnvironment: Equatable, Sendable {
    public static let nameKey = "MyKhayaEnvironment"
    public static let urlSchemeKey = "MyKhayaURLScheme"
    public static let appGroupKey = "MyKhayaAppGroup"
    public static let serverHostKey = "MyKhayaServerHost"

    /// "development" or "production".
    public let name: String
    /// The custom URL scheme widget taps use to reach this app.
    public let urlScheme: String
    /// The App Group shared by this app and its widget extension.
    public let appGroup: String
    /// The live frontend host this app loads (main app only; the widget
    /// extension makes no network requests and has none).
    public let serverHost: String?

    /// The environment of the current process, or nil when its Info.plist
    /// is missing a value (or still holds an unexpanded `$(...)`).
    public static let current = MyKhayaEnvironment(infoDictionary: Bundle.main.infoDictionary)

    public init?(infoDictionary: [String: Any]?) {
        guard let info = infoDictionary,
              let name = Self.configured(info[Self.nameKey]),
              ["development", "production"].contains(name),
              let urlScheme = Self.configured(info[Self.urlSchemeKey]),
              Self.isValidScheme(urlScheme),
              let appGroup = Self.configured(info[Self.appGroupKey]),
              appGroup.hasPrefix("group.") else {
            return nil
        }
        var serverHost: String?
        if info[Self.serverHostKey] != nil {
            guard let host = Self.configured(info[Self.serverHostKey]), Self.isValidHost(host) else {
                return nil
            }
            serverHost = host
        }
        self.name = name
        self.urlScheme = urlScheme
        self.appGroup = appGroup
        self.serverHost = serverHost
    }

    /// `https://<serverHost>`, the only origin this app may load.
    public var serverURL: URL? {
        serverHost.flatMap { URL(string: "https://\($0)") }
    }

    /// A non-empty value that the build actually substituted.
    private static func configured(_ value: Any?) -> String? {
        guard let string = (value as? String)?.trimmingCharacters(in: .whitespacesAndNewlines),
              !string.isEmpty,
              !string.contains("$(") else {
            return nil
        }
        return string
    }

    private static func isValidScheme(_ scheme: String) -> Bool {
        scheme.range(of: "^[a-z][a-z0-9+.-]*$", options: .regularExpression) != nil
    }

    private static func isValidHost(_ host: String) -> Bool {
        host.range(of: "^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$",
                   options: .regularExpression) != nil
    }
}

/// Widget tap deep links: `<scheme>://open?path=/calendar?event=…`.
///
/// Built by the widget extension and accepted by the main app only with that
/// environment's own scheme (DEV `mykhaya`, PROD `mykhaya-prod`, from the
/// build configuration). Each app registers only its own scheme, and
/// `path(from:expectedScheme:)` rejects any other, so a DEV widget can never
/// drive the PROD app or the reverse.
public enum WidgetDeepLinkRoute {
    public static let host = "open"
    public static let pathQueryItem = "path"

    public static func url(forPath path: String, scheme: String) -> URL? {
        var components = URLComponents()
        components.scheme = scheme
        components.host = host
        components.queryItems = [URLQueryItem(name: pathQueryItem, value: path)]
        return components.url
    }

    /// The in-app path a widget tap should open, or nil unless the URL uses
    /// exactly `expectedScheme` and host `open` and carries a same-origin
    /// absolute path (never `//other.host`).
    public static func path(from url: URL, expectedScheme: String) -> String? {
        guard url.scheme?.lowercased() == expectedScheme.lowercased(),
              url.host?.lowercased() == host,
              let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let path = components.queryItems?.first(where: { $0.name == pathQueryItem })?.value,
              path.hasPrefix("/"),
              !path.hasPrefix("//") else {
            return nil
        }
        return path
    }
}
