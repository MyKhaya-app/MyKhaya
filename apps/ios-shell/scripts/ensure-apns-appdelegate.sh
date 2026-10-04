#!/usr/bin/env bash
set -euo pipefail

# Capacitor Push Notifications 8 observes these NotificationCenter events, but
# does not install UIApplicationDelegate callbacks on the generated app
# delegate. Keep this patch next to the shell because ios/ is generated on a
# Mac and may not exist in a Windows checkout.

APP_DELEGATE="${1:-ios/App/App/AppDelegate.swift}"

if [ ! -f "$APP_DELEGATE" ]; then
  echo "ERROR: AppDelegate.swift not found: $APP_DELEGATE" >&2
  exit 1
fi

if grep -q 'capacitorDidRegisterForRemoteNotifications' "$APP_DELEGATE" || \
   grep -q 'capacitorDidFailToRegisterForRemoteNotifications' "$APP_DELEGATE"; then
  if grep -q 'application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken' "$APP_DELEGATE" && \
     grep -q 'application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError' "$APP_DELEGATE"; then
    echo "APNs AppDelegate forwarding already present: $APP_DELEGATE"
    exit 0
  fi
  echo "ERROR: AppDelegate contains partial/custom APNs forwarding; inspect it manually: $APP_DELEGATE" >&2
  exit 1
fi

if grep -q 'application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken' "$APP_DELEGATE" || \
   grep -q 'application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError' "$APP_DELEGATE"; then
  echo "ERROR: AppDelegate contains a custom APNs callback without Capacitor forwarding; inspect it manually: $APP_DELEGATE" >&2
  exit 1
fi

cat >> "$APP_DELEGATE" <<'SWIFT'

// MyKhaya: Capacitor Push Notifications 8 integration.
// The plugin listens for these NotificationCenter events; never log the token
// or the NSError's localizedDescription because either can expose sensitive
// or unstable device/provider details.
extension AppDelegate {
    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        NSLog("[MyKhaya native push] apns_delegate_success token_present=true")
        NotificationCenter.default.post(name: .capacitorDidRegisterForRemoteNotifications, object: deviceToken)
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        NSLog("[MyKhaya native push] apns_delegate_failure error_category=apns_registration_failure")
        NotificationCenter.default.post(name: .capacitorDidFailToRegisterForRemoteNotifications, object: error)
    }
}
SWIFT

echo "Added Capacitor APNs AppDelegate forwarding and safe diagnostics: $APP_DELEGATE"
