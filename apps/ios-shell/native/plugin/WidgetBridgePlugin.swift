import Capacitor
import Foundation

/// Native side of apps/web/components/widget-bridge.ts's `WidgetBridge`
/// plugin. Deliberately tiny: two methods, both delegating straight to
/// `WidgetSnapshotStore` (shared with the widget extension target — this
/// file must be added to the main app target only, never the extension).
///
/// This is a repo-local plugin (no npm package): Capacitor auto-discovers
/// installed *npm* plugins via `cap sync`, but a plugin that lives directly
/// in the app target needs one explicit registration call, done in
/// MainViewController.swift's `capacitorDidLoad()` override — see that
/// file's comment for why, and scripts/install-widget-sources.sh for how
/// both files get installed into the Mac-generated ios/ project.
@objc(WidgetBridgePlugin)
public class WidgetBridgePlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "WidgetBridgePlugin"
    public let jsName = "WidgetBridge"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "setSnapshot", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "clearSnapshot", returnType: CAPPluginReturnPromise),
    ]

    // Widget tap deep-linking (see Shared/DeepLink.swift for why a custom
    // scheme). SceneDelegateProxy.shared.scene(_:openURLContexts:) —
    // already present, unmodified, in the Capacitor-generated SceneDelegate
    // (see ensure-storyboard-scene-delegate.sh) — posts this notification
    // for every open-URL event; this is the same
    // observe-a-Capacitor-posted-notification pattern
    // ensure-apns-appdelegate.sh already uses for
    // .capacitorDidRegisterForRemoteNotifications, chosen here for the same
    // reason: it needs no hand-edit of a generated lifecycle method body.
    public override func load() {
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleOpenURL(_:)),
            name: Notification.Name.capacitorOpenURL,
            object: nil
        )
    }

    @objc private func handleOpenURL(_ notification: Notification) {
        guard let url = notification.userInfo?["url"] as? URL,
              url.scheme?.lowercased() == "mykhaya",
              let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let path = components.queryItems?.first(where: { $0.name == "path" })?.value,
              path.hasPrefix("/") else {
            return
        }
        // The WKWebView is already on the live frontend origin (ADR 0012) —
        // a same-origin relative navigation needs no knowledge of which
        // environment (dev.mykhaya.app / mykhaya.app) is currently loaded.
        let escaped = path.replacingOccurrences(of: "'", with: "%27")
        bridge?.webView?.evaluateJavaScript("window.location.assign('\(escaped)')", completionHandler: nil)
    }

    @objc func setSnapshot(_ call: CAPPluginCall) {
        guard let json = call.getString("json"), let data = json.data(using: .utf8) else {
            call.reject("Missing or invalid 'json' argument")
            return
        }
        do {
            let snapshot = try JSONDecoder().decode(WidgetSnapshot.self, from: data)
            WidgetSnapshotStore.save(snapshot)
            call.resolve()
        } catch {
            // Never reject with the decode error's raw description into a
            // webview-visible promise rejection if it might echo back
            // attacker-controlled content — this JSON is produced by
            // MyKhaya's own web code, not user input, but the same
            // discipline as elsewhere in this app: log detail, return a
            // generic message.
            NSLog("[MyKhayaWidgets] WidgetBridge.setSnapshot decode failed: %@", error.localizedDescription)
            call.reject("Could not decode widget snapshot")
        }
    }

    @objc func clearSnapshot(_ call: CAPPluginCall) {
        WidgetSnapshotStore.clear()
        call.resolve()
    }
}
