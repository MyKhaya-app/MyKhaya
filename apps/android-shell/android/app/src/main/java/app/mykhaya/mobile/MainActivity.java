package app.mykhaya.mobile;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        // Repo-local plugins (no npm package, so `cap sync` cannot discover
        // them) must be registered before super.onCreate() runs the
        // Capacitor bridge's own init — see SystemSettingsPlugin's own
        // comment for what this plugin does and why it exists.
        registerPlugin(SystemSettingsPlugin.class);
        super.onCreate(savedInstanceState);
        // Idempotent — see NotificationChannels' own comment for why this
        // set exists and must stay in sync with the backend's FCM sender.
        NotificationChannels.createAll(getApplicationContext());
    }
}
