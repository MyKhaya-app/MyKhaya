#!/usr/bin/env bash
set -euo pipefail

# Capacitor's generated Main.storyboard owns the bridge controller. Removing
# the duplicate programmatic window/root assignment is essential: replacing
# the storyboard controller during scene connection leaves the WKWebView at
# about:blank. Keep the window property because UIKit may populate it from
# the storyboard, and preserve all SceneDelegateProxy forwarding.
SCENE_DELEGATE="${1:-ios/App/App/SceneDelegate.swift}"

if [ ! -f "$SCENE_DELEGATE" ]; then
  echo "ERROR: SceneDelegate.swift not found: $SCENE_DELEGATE" >&2
  exit 1
fi

if grep -q 'rootViewController = CAPBridgeViewController' "$SCENE_DELEGATE" || \
   grep -q 'makeKeyAndVisible' "$SCENE_DELEGATE"; then
  perl -0pi -e 's/\n        window = UIWindow\(windowScene: windowScene\)\n        window\?\.rootViewController = CAPBridgeViewController\(\)\n        window\?\.makeKeyAndVisible\(\)\n//' "$SCENE_DELEGATE"
fi

if grep -q 'rootViewController = CAPBridgeViewController' "$SCENE_DELEGATE" || \
   grep -q 'makeKeyAndVisible' "$SCENE_DELEGATE"; then
  echo "ERROR: SceneDelegate still replaces the storyboard bridge: $SCENE_DELEGATE" >&2
  exit 1
fi

grep -q 'SceneDelegateProxy.shared.scene' "$SCENE_DELEGATE" || {
  echo "ERROR: SceneDelegateProxy forwarding is missing: $SCENE_DELEGATE" >&2
  exit 1
}

echo "Storyboard-owned Capacitor scene lifecycle confirmed: $SCENE_DELEGATE"
