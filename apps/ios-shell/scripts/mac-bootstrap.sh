#!/usr/bin/env bash
# Phase 4 Mac bootstrap for the MyKhaya Capacitor iOS shell.
# Paste this whole file into a Terminal on the Mac (or `bash mac-bootstrap.sh`
# from apps/ios-shell/scripts/ after `git pull`). It is CLI-only end to end —
# no Xcode GUI interaction is required to reach a running simulator build.
# The only steps that genuinely need Xcode's GUI (real Apple Developer Team
# signing, for a physical device rather than the simulator) are called out
# in a separate, short list at the bottom of this file — they are NOT part
# of this script.
set -euo pipefail

# Phase 4 development bootstrap: this must point at the dev live frontend
# (dev.mykhaya.app). The config also defaults safely to development; set
# production explicitly when making a production archive, e.g.:
#   MYKHAYA_IOS_ENV=production bash mac-bootstrap.sh
export MYKHAYA_IOS_ENV="${MYKHAYA_IOS_ENV:-development}"
echo "== MYKHAYA_IOS_ENV=$MYKHAYA_IOS_ENV =="
echo "Production requires MYKHAYA_IOS_ENV=production explicitly."

echo "== 0. Tool versions (record these in the completion report) =="
sw_vers
xcodebuild -version
node -v
pnpm -v
git --version

echo "== 1. Repo state =="
cd "$(git rev-parse --show-toplevel)"
git status --porcelain
git branch --show-current
git fetch origin dev
git pull --ff-only
echo "HEAD is now: $(git rev-parse HEAD)"

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
npx cap sync ios

echo "== 6. Verify the live-frontend config survived sync intact =="
grep -A2 '"server"' ios/App/App/capacitor.config.json || true
echo "^ confirm cleartext:false and allowNavigation is present and non-wildcard"

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
  -scheme App \
  -configuration Debug \
  -sdk iphonesimulator \
  -destination "platform=iOS Simulator,name=$SIM_NAME" \
  build

echo "== 9. Boot the simulator, install, and launch =="
xcrun simctl boot "$SIM_NAME" 2>/dev/null || echo "(already booted)"
open -a Simulator
APP_PATH=$(find ~/Library/Developer/Xcode/DerivedData -name "App.app" -path "*iphonesimulator*" -print -quit)
echo "App bundle: $APP_PATH"
xcrun simctl install "$SIM_NAME" "$APP_PATH"
xcrun simctl launch "$SIM_NAME" app.mykhaya.mobile

echo ""
echo "== Done. The Simulator app should now be showing MyKhaya. =="
echo "Now do the manual verification pass from docs/mobile/ios-shell-mac-checklist.md"
echo "Steps 6-7 (navigation/security checks, persistent-login test)."
echo ""
echo "Useful follow-up commands:"
echo "  Force-kill the app:      xcrun simctl terminate \"$SIM_NAME\" app.mykhaya.mobile"
echo "  Relaunch it:             xcrun simctl launch \"$SIM_NAME\" app.mykhaya.mobile"
echo "  Reboot the simulator:    xcrun simctl shutdown \"$SIM_NAME\" && xcrun simctl boot \"$SIM_NAME\""
echo "  Stream device console:   xcrun simctl spawn \"$SIM_NAME\" log stream --predicate 'processImagePath contains \"App\"'"
