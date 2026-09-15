import Capacitor
import Foundation
import UIKit

/// Native side of apps/web/components/system-settings-bridge.ts's
/// `SystemSettings` plugin. Deliberately tiny: one method, opening this
/// app's own page in the OS Settings app via Apple's documented
/// `UIApplication.openSettingsURLString` — the mechanism App Store review
/// guidelines expect for a "take me to my notification settings" action,
/// rather than relying on WKWebView's undocumented handling of a bare
/// `app-settings:` URL navigation (system-settings-bridge.ts still falls
/// back to that only if this plugin call itself fails).
///
/// This is a repo-local plugin (no npm package): Capacitor auto-discovers
/// installed *npm* plugins via `cap sync`, but a plugin that lives directly
/// in the app target needs one explicit registration call, done in
/// MainViewController.swift's `capacitorDidLoad()` override — see that
/// file's comment for why, and scripts/install-widget-sources.sh for how
/// both files get installed into the Mac-generated ios/ project.
@objc(SystemSettingsPlugin)
public class SystemSettingsPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "SystemSettingsPlugin"
    public let jsName = "SystemSettings"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "openAppSettings", returnType: CAPPluginReturnPromise),
    ]

    @objc func openAppSettings(_ call: CAPPluginCall) {
        guard let url = URL(string: UIApplication.openSettingsURLString) else {
            call.reject("Could not construct the Settings URL")
            return
        }
        DispatchQueue.main.async {
            UIApplication.shared.open(url, options: [:]) { success in
                if success {
                    call.resolve()
                } else {
                    call.reject("Could not open Settings")
                }
            }
        }
    }
}
