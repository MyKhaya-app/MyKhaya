#!/bin/sh
# Validates that a MyKhaya iOS build is consistently DEV or consistently PROD:
# bundle IDs, App Group, widget deep-link scheme, live frontend host, display
# name and APNs environment must all belong to the same environment, and the
# widget extension must agree with its app.
#
#   Xcode build phase (App and MyKhayaWidgets targets):
#       sh "$SRCROOT/../../scripts/validate-ios-environments.sh" --build-phase
#     Checks the build settings Xcode exports for the target being built and
#     fails the build on any mismatch, so a wrong combination can never be
#     installed (e.g. a target-level override typed into Xcode's GUI).
#
#   Mac Terminal, from apps/ios-shell (also run by mac-bootstrap.sh):
#       sh scripts/validate-ios-environments.sh
#     Expands every build configuration of both targets with
#     `xcodebuild -showBuildSettings` and checks each one, plus the shared
#     schemes.
#
# The expected values are the agreed environment matrix
# (docs/mobile/ios-environments.md). The same matrix is checked against the
# committed files on any OS by src/ios-environments.test.ts.
set -eu

FAILURES=0

fail() {
  echo "error: MyKhaya iOS environment: $*" >&2
  FAILURES=$((FAILURES + 1))
}

expect() {
  # expect <label> <actual> <expected>
  if [ "$2" != "$3" ]; then
    fail "$CONTEXT: $1 is '$2', expected '$3'"
  fi
}

# check <configuration> <target product type: app|appex> <settings...>
# Settings are read from the variables below, set by the caller.
check() {
  configuration="$1"
  kind="$2"
  CONTEXT="$configuration / $kind"

  case "$configuration" in
    *-Dev) env=development; bundle=app.mykhaya.mobile; group=group.app.mykhaya.mobile
           url_scheme=mykhaya; host=dev.mykhaya.app; display=MyKhaya-Dev ;;
    *-Prod) env=production; bundle=app.mykhaya.mobile.prod; group=group.app.mykhaya.mobile.prod
            url_scheme=mykhaya-prod; host=mykhaya.app; display=MyKhaya ;;
    *) fail "$CONTEXT: unknown build configuration (expected Debug-Dev, Release-Dev, Debug-Prod or Release-Prod)"; return ;;
  esac
  apns=
  case "$configuration" in
    Debug-*) apns=development ;;
    Release-*) apns=production ;;
    *) fail "$CONTEXT: build configuration must start with Debug- or Release-" ;;
  esac

  expect MYKHAYA_ENVIRONMENT "$S_ENVIRONMENT" "$env"
  expect MYKHAYA_APP_BUNDLE_ID "$S_APP_BUNDLE_ID" "$bundle"
  expect MYKHAYA_APP_GROUP "$S_APP_GROUP" "$group"
  expect MYKHAYA_URL_SCHEME "$S_URL_SCHEME" "$url_scheme"
  expect MYKHAYA_SERVER_HOST "$S_SERVER_HOST" "$host"
  expect MYKHAYA_DISPLAY_NAME "$S_DISPLAY_NAME" "$display"
  expect MYKHAYA_APNS_BUILD_ENVIRONMENT "$S_APNS" "$apns"
  if [ "$kind" = appex ]; then
    expect PRODUCT_BUNDLE_IDENTIFIER "$S_PRODUCT_BUNDLE_IDENTIFIER" "$bundle.widgets"
  else
    expect PRODUCT_BUNDLE_IDENTIFIER "$S_PRODUCT_BUNDLE_IDENTIFIER" "$bundle"
  fi
}

if [ "${1:-}" = "--build-phase" ]; then
  S_ENVIRONMENT="${MYKHAYA_ENVIRONMENT:-}"
  S_APP_BUNDLE_ID="${MYKHAYA_APP_BUNDLE_ID:-}"
  S_APP_GROUP="${MYKHAYA_APP_GROUP:-}"
  S_URL_SCHEME="${MYKHAYA_URL_SCHEME:-}"
  S_SERVER_HOST="${MYKHAYA_SERVER_HOST:-}"
  S_DISPLAY_NAME="${MYKHAYA_DISPLAY_NAME:-}"
  S_APNS="${MYKHAYA_APNS_BUILD_ENVIRONMENT:-}"
  S_PRODUCT_BUNDLE_IDENTIFIER="${PRODUCT_BUNDLE_IDENTIFIER:-}"
  if [ "${WRAPPER_EXTENSION:-}" = appex ]; then kind=appex; else kind=app; fi
  check "${CONFIGURATION:-}" "$kind"
  if [ "$FAILURES" -gt 0 ]; then
    echo "error: MyKhaya iOS environment check failed for ${TARGET_NAME:-target} (${CONFIGURATION:-?}). See docs/mobile/ios-environments.md." >&2
    exit 1
  fi
  echo "MyKhaya iOS environment OK: ${TARGET_NAME:-target} ${CONFIGURATION:-} -> ${PRODUCT_BUNDLE_IDENTIFIER:-} ($MYKHAYA_ENVIRONMENT, $MYKHAYA_SERVER_HOST)"
  exit 0
fi

# ---- Mac Terminal mode -----------------------------------------------------

if [ "$(uname)" != "Darwin" ]; then
  echo "This mode needs Xcode (macOS). On other systems run: pnpm --filter @mykhaya/ios-shell test" >&2
  exit 1
fi
cd "$(dirname "$0")/.."
PROJECT=ios/App/App.xcodeproj

setting() {
  # setting <name> <showBuildSettings output>
  printf '%s\n' "$2" | sed -n "s/^ *$1 = //p" | head -1
}

for configuration in Debug-Dev Release-Dev Debug-Prod Release-Prod; do
  for target in App MyKhayaWidgets; do
    settings=$(xcodebuild -project "$PROJECT" -target "$target" -configuration "$configuration" -showBuildSettings 2>/dev/null) || {
      fail "$configuration / $target: xcodebuild -showBuildSettings failed (does the configuration exist?)"
      continue
    }
    S_ENVIRONMENT=$(setting MYKHAYA_ENVIRONMENT "$settings")
    S_APP_BUNDLE_ID=$(setting MYKHAYA_APP_BUNDLE_ID "$settings")
    S_APP_GROUP=$(setting MYKHAYA_APP_GROUP "$settings")
    S_URL_SCHEME=$(setting MYKHAYA_URL_SCHEME "$settings")
    S_SERVER_HOST=$(setting MYKHAYA_SERVER_HOST "$settings")
    S_DISPLAY_NAME=$(setting MYKHAYA_DISPLAY_NAME "$settings")
    S_APNS=$(setting MYKHAYA_APNS_BUILD_ENVIRONMENT "$settings")
    S_PRODUCT_BUNDLE_IDENTIFIER=$(setting PRODUCT_BUNDLE_IDENTIFIER "$settings")
    if [ "$target" = MyKhayaWidgets ]; then kind=appex; else kind=app; fi
    check "$configuration" "$kind"
    echo "checked $configuration / $target -> $S_PRODUCT_BUNDLE_IDENTIFIER ($S_ENVIRONMENT, $S_SERVER_HOST, $S_APP_GROUP, $S_URL_SCHEME://)"
  done
done

SCHEMES="$PROJECT/xcshareddata/xcschemes"
for env in Dev Prod; do
  for scheme in "MyKhaya-$env" "MyKhayaWidgets-$env"; do
    file="$SCHEMES/$scheme.xcscheme"
    if [ ! -f "$file" ]; then
      fail "missing shared scheme $scheme"
      continue
    fi
    other=Prod; [ "$env" = Prod ] && other=Dev
    if grep -q "buildConfiguration = \"[A-Za-z]*-$other\"" "$file"; then
      fail "scheme $scheme uses a $other build configuration"
    fi
    grep -q "buildConfiguration = \"Debug-$env\"" "$file" || fail "scheme $scheme does not run Debug-$env"
    grep -q "buildConfiguration = \"Release-$env\"" "$file" || fail "scheme $scheme does not archive Release-$env"
  done
done

if [ "$FAILURES" -gt 0 ]; then
  echo "MyKhaya iOS environment validation FAILED ($FAILURES problem(s))." >&2
  exit 1
fi
echo "MyKhaya iOS environment validation passed: DEV and PROD are consistent."
