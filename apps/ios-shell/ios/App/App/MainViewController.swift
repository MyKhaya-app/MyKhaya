import Capacitor
import WebKit

/// Registers WidgetBridgePlugin and SystemSettingsPlugin — repo-local
/// plugins with no npm package, so neither is auto-discovered the way an
/// installed Capacitor plugin is (see each plugin file's own comment).
/// `capacitorDidLoad()` is the documented Capacitor hook for exactly this:
/// run after the bridge exists, before the WebView starts loading, so a
/// page-load-time JS call to `Capacitor.Plugins.WidgetBridge` (or
/// `.SystemSettings`) never races plugin registration.
///
/// scripts/install-widget-sources.sh points Main.storyboard's bridge view
/// controller at this class instead of the default `CAPBridgeViewController`
/// — everything else about the controller (the storyboard-owned lifecycle
/// ensure-storyboard-scene-delegate.sh already protects) is untouched,
/// since this subclass adds no other behaviour.
public class MainViewController: CAPBridgeViewController {
    public override func capacitorDidLoad() {
        bridge?.registerPluginInstance(WidgetBridgePlugin())
        bridge?.registerPluginInstance(SystemSettingsPlugin())
        bridge?.registerPluginInstance(NativePushEnvironmentPlugin())

        // The live WKWebView must always enter the web app through `/` on a
        // native cold document. iOS can recreate a WebView with a previously
        // loaded public URL (notably `/login`), which otherwise bypasses the
        // server-selected acquisition gate before React has mounted. This is
        // document-start, before any page component or AuthProvider exists.
        let bootstrap = """
        (() => {
          const deepLinkKey = "mykhaya.native.deep-link-start";
          const path = window.location.pathname;
          const hasQuery = window.location.search.length > 0;
          const deepLink = window.sessionStorage.getItem(deepLinkKey) === "1";
          const safeUrl = window.location.origin + path;
          console.info("[NATIVE_BOOT]", {
            initial_url: safeUrl,
            initial_path: path,
            native_detected: true,
            launch_source: deepLink ? "deep_link" : "cold_start",
            persisted_path: path === "/login" ? path : null,
            normalized_path: path === "/login" && !hasQuery && !deepLink ? "/" : path
          });
          window.sessionStorage.removeItem(deepLinkKey);
          if (path === "/login" && !hasQuery && !deepLink) {
            console.info("[NATIVE_BOOT]", {
              event: "normalize_public_startup_route",
              from: path,
              to: "/",
              reason: "plain_login_restored_on_native_document_start"
            });
            window.location.replace("/");
          }
        })();
        """
        bridge?.webView?.configuration.userContentController.addUserScript(
            WKUserScript(source: bootstrap, injectionTime: .atDocumentStart, forMainFrameOnly: true)
        )
    }
}
