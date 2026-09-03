#!/usr/bin/env bash
set -euo pipefail

# Installs the repo-managed native widget/plugin sources
# (apps/ios-shell/native/) into the Mac-generated ios/ Xcode project, then
# runs setup-widget-extension.rb to create/update the MyKhayaWidgets target.
# Idempotent — safe to re-run after `git pull` picks up source changes.
# Called from mac-bootstrap.sh; see docs/mobile/ios-widgets.md for the full
# picture and docs/mobile/ios-shell-mac-checklist.md for the manual
# verification checklist this feeds into.

if [ "$(uname)" != "Darwin" ]; then
  echo "ERROR: this script only runs on macOS (Xcode/xcodeproj required)." >&2
  exit 1
fi

if [ ! -d ios ]; then
  echo "ERROR: ios/ not found. Run 'npx cap add ios' first (see docs/mobile/ios-shell-mac-checklist.md)." >&2
  exit 1
fi

if ! gem list -i xcodeproj >/dev/null 2>&1; then
  echo "ERROR: the 'xcodeproj' Ruby gem is not installed. It ships with CocoaPods" >&2
  echo "       (brew install cocoapods, per docs/mobile/ios-shell-mac-checklist.md)." >&2
  echo "       If CocoaPods is installed and this still fails, run: gem install xcodeproj" >&2
  exit 1
fi

echo "== 1. Copy widget extension Swift sources =="
mkdir -p MyKhayaWidgets
rsync -a --delete native/widgets/ MyKhayaWidgets/
echo "Copied $(find MyKhayaWidgets -name '*.swift' | wc -l | tr -d ' ') Swift files into MyKhayaWidgets/"

echo "== 2. Copy main-app plugin sources (WidgetBridgePlugin, MainViewController) =="
cp native/plugin/WidgetBridgePlugin.swift ios/App/App/WidgetBridgePlugin.swift
cp native/plugin/MainViewController.swift ios/App/App/MainViewController.swift
# The plugin also needs the shared snapshot model/store — the main app
# target reads nothing from these directly, but WidgetBridgePlugin.swift
# does (WidgetSnapshot, WidgetSnapshotStore), so the main app target must
# compile them too, not just the widget extension.
cp native/widgets/Shared/WidgetSnapshot.swift ios/App/App/WidgetSnapshot.swift
cp native/widgets/Shared/WidgetSnapshotStore.swift ios/App/App/WidgetSnapshotStore.swift

echo "== 3. Add WidgetBridgePlugin/MainViewController/WidgetSnapshot*.swift to the App target =="
ruby scripts/add-app-target-sources.rb

echo "== 4. Point Main.storyboard's bridge view controller at MainViewController =="
STORYBOARD="ios/App/App/Base.lproj/Main.storyboard"
if [ -f "$STORYBOARD" ]; then
  if grep -q 'customClass="MainViewController"' "$STORYBOARD"; then
    echo "Storyboard already uses MainViewController: $STORYBOARD"
  elif grep -q 'customClass="CAPBridgeViewController"' "$STORYBOARD"; then
    perl -pi -e 's/customClass="CAPBridgeViewController"/customClass="MainViewController"/' "$STORYBOARD"
    echo "Updated storyboard custom class to MainViewController: $STORYBOARD"
  else
    echo "WARNING: $STORYBOARD has neither CAPBridgeViewController nor MainViewController as its custom class — inspect manually." >&2
  fi
else
  echo "WARNING: $STORYBOARD not found — inspect manually (see ensure-storyboard-scene-delegate.sh)." >&2
fi

echo "== 5. Register the mykhaya:// URL scheme (widget deep links only — see native/widgets/Shared/DeepLink.swift) =="
INFO_PLIST="ios/App/App/Info.plist"
if [ -f "$INFO_PLIST" ] && ! grep -q '<string>mykhaya</string>' "$INFO_PLIST"; then
  /usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes array" "$INFO_PLIST" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0 dict" "$INFO_PLIST"
  /usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLName string app.mykhaya.mobile.widgets" "$INFO_PLIST"
  /usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes array" "$INFO_PLIST"
  /usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes:0 string mykhaya" "$INFO_PLIST"
  echo "Added mykhaya:// URL scheme to $INFO_PLIST"
else
  echo "mykhaya:// URL scheme already present or Info.plist missing"
fi

echo "== 6. Create/update the MyKhayaWidgets Xcode target, App Group, entitlements, embed phase =="
ruby scripts/setup-widget-extension.rb

echo "== 7. Post-install entitlement audit (APNs must survive) =="
ENTITLEMENTS_FILE="ios/App/App/App.entitlements"
if [ -f "$ENTITLEMENTS_FILE" ]; then
  echo "-- $ENTITLEMENTS_FILE --"
  /usr/libexec/PlistBuddy -c "Print" "$ENTITLEMENTS_FILE" | grep -A2 -E 'aps-environment|application-groups' || true
fi

echo ""
echo "== Done. Widget sources installed. Next: open Xcode, build the App scheme, =="
echo "   then work through docs/mobile/ios-widgets.md's manual verification checklist."
