package app.mykhaya.mobile;

import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;

import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * Android side of apps/web/components/system-settings-bridge.ts's
 * `SystemSettings` plugin — mirrors iOS's SystemSettingsPlugin.swift (one
 * method, "open this app's own notification settings screen") exactly, so
 * the shared TS wrapper needs no platform branching: Capacitor dispatches
 * `SystemSettings.openAppSettings()` to whichever native implementation is
 * registered for the running platform.
 *
 * Settings.ACTION_APP_NOTIFICATION_SETTINGS (the documented "take the user
 * straight to this app's notification settings" intent) only exists from
 * API 26 — this shell's minSdk is 24 (variables.gradle), so API 24/25 fall
 * back to the general app-details settings screen, which has always existed
 * and still lets the user reach notification controls from there.
 */
@CapacitorPlugin(name = "SystemSettings")
public class SystemSettingsPlugin extends Plugin {

    @PluginMethod
    public void openAppSettings(PluginCall call) {
        String packageName = getContext().getPackageName();
        Intent intent;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            intent = new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS);
            intent.putExtra(Settings.EXTRA_APP_PACKAGE, packageName);
        } else {
            intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
            intent.setData(Uri.fromParts("package", packageName, null));
        }
        try {
            getActivity().startActivity(intent);
            call.resolve();
        } catch (Exception error) {
            call.reject("Could not open notification settings", error);
        }
    }
}
