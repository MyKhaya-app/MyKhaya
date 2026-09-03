import Capacitor

/// Registers WidgetBridgePlugin — a repo-local plugin with no npm package,
/// so it isn't auto-discovered the way an installed Capacitor plugin is
/// (see WidgetBridgePlugin.swift's own comment). `capacitorDidLoad()` is
/// the documented Capacitor hook for exactly this: run after the bridge
/// exists, before the WebView starts loading, so a page-load-time JS call
/// to `Capacitor.Plugins.WidgetBridge` never races plugin registration.
///
/// scripts/install-widget-sources.sh points Main.storyboard's bridge view
/// controller at this class instead of the default `CAPBridgeViewController`
/// — everything else about the controller (the storyboard-owned lifecycle
/// ensure-storyboard-scene-delegate.sh already protects) is untouched,
/// since this subclass adds no other behaviour.
public class MainViewController: CAPBridgeViewController {
    public override func capacitorDidLoad() {
        bridge?.registerPluginInstance(WidgetBridgePlugin())
    }
}
