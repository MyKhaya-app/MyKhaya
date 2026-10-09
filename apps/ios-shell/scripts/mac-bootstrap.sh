#!/usr/bin/env bash
# Phase 4 Mac bootstrap for the MyKhaya Capacitor iOS shell.
# Paste this whole file into a Terminal on the Mac (or `bash mac-bootstrap.sh`
# from apps/ios-shell/scripts/ after explicitly checking out the approved ref).
# It is CLI-only end to end —
# no Xcode GUI interaction is required to reach a running simulator build.
# The only steps that genuinely need Xcode's GUI (real Apple Developer Team
# signing, for a physical device rather than the simulator) are called out
# in a separate, short list at the bottom of this file — they are NOT part
# of this script.
set -euo pipefail

# DEV and PROD are two separate apps built from this one Xcode project, each
# with its own schemes and build configurations (docs/mobile/ios-environments.md).
# Every environment value (bundle IDs, App Group, URL scheme, live frontend
# host) comes from the build configuration, so nothing this script does
# (cap sync, widget install) can turn one app into the other.
# MYKHAYA_IOS_ENV only picks which app this script builds and launches in the
# simulator at the end. The checkout/ref is selected separately:
#   MYKHAYA_IOS_ENV=production MYKHAYA_IOS_REF=main bash mac-bootstrap.sh
#   MYKHAYA_IOS_ENV=production MYKHAYA_IOS_REF=<40-char-commit-sha> bash mac-bootstrap.sh
export MYKHAYA_IOS_ENV="${MYKHAYA_IOS_ENV:-development}"
case "$MYKHAYA_IOS_ENV" in
  development) SCHEME="MyKhaya-Dev"; CONFIGURATION="Debug-Dev"; BUNDLE_ID="app.mykhaya.mobile"; DEFAULT_REF="dev" ;;
  production) SCHEME="MyKhaya-Prod"; CONFIGURATION="Debug-Prod"; BUNDLE_ID="app.mykhaya.mobile.prod"; DEFAULT_REF="" ;;
  *) echo "MYKHAYA_IOS_ENV must be development or production (got '$MYKHAYA_IOS_ENV')" >&2; exit 1 ;;
esac
MYKHAYA_IOS_REF="${MYKHAYA_IOS_REF:-$DEFAULT_REF}"
if [ -z "$MYKHAYA_IOS_REF" ]; then
  echo "Refusing production bootstrap without MYKHAYA_IOS_REF (local branch or full 40-character commit SHA)." >&2
  exit 1
fi
echo "== MYKHAYA_IOS_ENV=$MYKHAYA_IOS_ENV: will build $SCHEME ($CONFIGURATION, $BUNDLE_ID) =="
echo "== Selected immutable checkout ref: $MYKHAYA_IOS_REF =="

echo "== 0. Tool versions (record these in the completion report) =="
sw_vers
xcodebuild -version
node -v
pnpm -v
git --version

echo "== 1. Repo state =="
cd "$(git rev-parse --show-toplevel)"
CURRENT_BRANCH=$(git branch --show-current)
if [ -n "$(git status --porcelain)" ]; then
  echo "Refusing to update a working copy with local changes. Review or stash them manually; this script never discards stashes or files." >&2
  exit 1
fi
if git show-ref --verify --quiet "refs/heads/$MYKHAYA_IOS_REF"; then
  if [ "$CURRENT_BRANCH" != "$MYKHAYA_IOS_REF" ]; then
    echo "Refusing to switch branches: current branch is '$CURRENT_BRANCH', selected branch is '$MYKHAYA_IOS_REF'. Check it out explicitly and rerun." >&2
    exit 1
  fi
  SELECTED_SHA=$(git rev-parse "refs/heads/$MYKHAYA_IOS_REF^{commit}")
else
  if ! printf '%s\n' "$MYKHAYA_IOS_REF" | grep -Eq '^[0-9a-fA-F]{40}$'; then
    echo "Refusing invalid checkout ref '$MYKHAYA_IOS_REF'; use a local branch name or full 40-character commit SHA." >&2
    exit 1
  fi
  SELECTED_SHA=$(git rev-parse "$MYKHAYA_IOS_REF^{commit}")
fi
CURRENT_SHA=$(git rev-parse HEAD)
if [ "$CURRENT_SHA" != "$SELECTED_SHA" ]; then
  echo "Refusing to switch or pull: HEAD $CURRENT_SHA does not match selected ref $MYKHAYA_IOS_REF ($SELECTED_SHA). Check out the ref explicitly and rerun." >&2
  exit 1
fi
echo "Validated checkout: branch='${CURRENT_BRANCH:-detached}' HEAD=$CURRENT_SHA"

echo "== 2. Install workspace deps =="
pnpm install

echo "== 3. Confirm the ios-shell package is clean before generating native files =="
pnpm --filter @mykhaya/ios-shell typecheck
pnpm --filter @mykhaya/ios-shell test

echo "== 4. Generate the iOS project (one-time; safe to re-run — Capacitor no-ops if ios/ already exists) =="
cd apps/ios-shell
if [ -d ios ]; then
  echo "ios/ already exists — skipping cap add ios. Delete it first if you want a clean regenerate."
else
  npx cap add ios
fi

echo "== 5. Sync capacitor.config.ts + www/ + native plugin deps into the Xcode project =="
# Safe for both apps: cap sync rewrites ios/App/App/capacitor.config.json for
# one environment, but MainViewController takes the live frontend from the
# build configuration (MyKhayaServerHost), never from that file.
npx cap sync ios

echo "== 5a. Ensure Capacitor Push Notifications 8 AppDelegate forwarding =="
bash scripts/ensure-apns-appdelegate.sh

echo "== 5b. Ensure storyboard-owned Capacitor scene lifecycle =="
bash scripts/ensure-storyboard-scene-delegate.sh

echo "== 5c. Ensure Face ID usage description =="
INFO_PLIST="ios/App/App/Info.plist"
if [ -f "$INFO_PLIST" ] && ! grep -q 'NSFaceIDUsageDescription' "$INFO_PLIST"; then
  /usr/libexec/PlistBuddy -c "Add :NSFaceIDUsageDescription string Use Face ID to securely unlock MyKhaya and access your family information." "$INFO_PLIST"
fi

echo "== 5c-widgets. Install MyKhaya Home Screen widgets (Phase 5) =="
bash scripts/install-widget-sources.sh

echo "== 5d. Inspect APNs and App Group entitlements (signing is not changed by this script) =="
for ENTITLEMENTS_FILE in ios/App/App/AppDebug.entitlements ios/App/App/AppRelease.entitlements; do
  if [ -f "$ENTITLEMENTS_FILE" ]; then
    grep -E 'aps-environment|application-groups|MYKHAYA' "$ENTITLEMENTS_FILE" || {
      echo "WARNING: $ENTITLEMENTS_FILE has no aps-environment/App Group value"
    }
  else
    echo "WARNING: $ENTITLEMENTS_FILE not found; verify Push Notifications capability/signing in Xcode"
  fi
done

echo "== 5e. Validate the DEV and PROD configurations (expanded by xcodebuild) =="
sh scripts/validate-ios-environments.sh

echo "== 6. Capacitor config written by sync (the app's live frontend comes from its build configuration instead) =="
grep -A2 '"server"' ios/App/App/capacitor.config.json || true
echo "^ confirm cleartext:false; the server URL here is not used by either app"

echo "== 7. Pick an already-installed iPhone simulator (do not download a new runtime) =="
xcrun simctl list devices available | grep -i "iPhone" | head -20
echo "^ pick one of the above; the rest of this script uses the first available iPhone runtime found"
# `xcrun simctl list devices` indents every line (typically 4 spaces) under
# each runtime heading — strip leading whitespace *first*, then cut at the
# first "(" (the UDID). Deliberately not `\s` in the sed pattern: macOS
# ships BSD sed, which doesn't understand the GNU/PCRE `\s` escape at all —
# it silently fails to match, which is exactly how a previous version of
# this script ended up with "    iPhone 16 Pro" (leading whitespace intact)
# as $SIM_NAME. [[:space:]] is the POSIX class BSD sed actually supports.
SIM_NAME=$(
  xcrun simctl list devices available \
    | grep -i "iPhone" \
    | head -1 \
    | sed -E 's/^[[:space:]]+//' \
    | sed -E 's/[[:space:]]*\(.*$//'
)
echo "Using simulator: '$SIM_NAME'"

echo "== 8. Build for the simulator (no signing required for simulator builds) =="
# Capacitor 8 generates a plain ios/App/App.xcodeproj here, not an
# .xcworkspace — this project has no CocoaPods plugin dependencies of its
# own (apps/ios-shell's package.json lists only @capacitor/core/@capacitor/ios;
# native plugins like @capacitor/browser and @aparajita/capacitor-secure-storage
# are dependencies of apps/web, not apps/ios-shell — see the completion
# report's note on this), so `cap sync` never runs `pod install` and never
# generates the .xcworkspace CocoaPods normally would. If a future plugin
# add changes that, `npx cap sync ios`'s own output will say so, and this
# line would need to switch to `-workspace ios/App/App.xcworkspace`.
xcodebuild \
  -project ios/App/App.xcodeproj \
  -scheme "$SCHEME" \
  -configuration "$CONFIGURATION" \
  -sdk iphonesimulator \
  -destination "platform=iOS Simulator,name=$SIM_NAME" \
  build

echo "== 9. Boot the simulator, install, and launch =="
xcrun simctl boot "$SIM_NAME" 2>/dev/null || echo "(already booted)"
open -a Simulator
# Both apps' products are named App.app; the configuration folder tells them apart.
APP_PATH=$(find ~/Library/Developer/Xcode/DerivedData -name "App.app" -path "*/$CONFIGURATION-iphonesimulator/*" -print -quit)
echo "App bundle: $APP_PATH"
xcrun simctl install "$SIM_NAME" "$APP_PATH"
xcrun simctl launch "$SIM_NAME" "$BUNDLE_ID"

echo ""
echo "== Done. The Simulator app should now be showing MyKhaya. =="
echo "Now do the manual verification pass from docs/mobile/ios-shell-mac-checklist.md"
echo "Steps 6-7 (navigation/security checks, persistent-login test)."
echo ""
echo "Useful follow-up commands:"
echo "  Force-kill the app:      xcrun simctl terminate \"$SIM_NAME\" $BUNDLE_ID"
echo "  Relaunch it:             xcrun simctl launch \"$SIM_NAME\" $BUNDLE_ID"
echo "  Reboot the simulator:    xcrun simctl shutdown \"$SIM_NAME\" && xcrun simctl boot \"$SIM_NAME\""
echo "  Stream device console:   xcrun simctl spawn \"$SIM_NAME\" log stream --predicate 'processImagePath contains \"App\"'"
