#!/bin/sh
# Validates that a MyKhaya iOS build is consistently DEV or consistently PROD:
# bundle IDs, App Group, widget deep-link scheme, live frontend host, display
# name and APNs environment must all belong to the same environment, and the
# widget extension must agree with its app. Version and build numbers come
# only from Config/Environment-<Dev|Prod>.xcconfig, so the app and its widget
# always match, and PROD's version is never ahead of DEV's.
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

env_setting() {
  # env_setting <Dev|Prod> <name>: a value from Config/Environment-<env>.xcconfig
  sed -n "s/^$2 *= *\([^ ]*\).*/\1/p" "$CONFIG_DIR/Environment-$1.xcconfig" | head -1
}

version_at_least() {
  # version_at_least <a> <b>: whether MAJOR.MINOR.PATCH version a >= b
  awk -v a="$1" -v b="$2" 'BEGIN {
    split(a, x, "."); split(b, y, ".")
    for (i = 1; i <= 3; i++) { if (x[i] + 0 > y[i] + 0) exit 0; if (x[i] + 0 < y[i] + 0) exit 1 }
    exit 0
  }'
}

check_versions() {
  CONTEXT="version numbers"
  for suffix in Dev Prod; do
    version=$(env_setting "$suffix" MARKETING_VERSION)
    build=$(env_setting "$suffix" CURRENT_PROJECT_VERSION)
    printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' ||
      fail "$CONTEXT: Environment-$suffix.xcconfig MARKETING_VERSION is '$version', expected MAJOR.MINOR.PATCH"
    printf '%s\n' "$build" | grep -Eq '^[1-9][0-9]*$' ||
      fail "$CONTEXT: Environment-$suffix.xcconfig CURRENT_PROJECT_VERSION is '$build', expected a whole number from 1"
  done
  dev_version=$(env_setting Dev MARKETING_VERSION)
  prod_version=$(env_setting Prod MARKETING_VERSION)
  version_at_least "$dev_version" "$prod_version" ||
    fail "$CONTEXT: PROD MARKETING_VERSION $prod_version is ahead of DEV $dev_version (DEV may lead PROD, never trail it)"
}

# check <configuration> <target product type: app|appex> <settings...>
# Settings are read from the variables below, set by the caller.
check() {
  configuration="$1"
  kind="$2"
  CONTEXT="$configuration / $kind"

  case "$configuration" in
    *-Dev) suffix=Dev; env=development; bundle=app.mykhaya.mobile; group=group.app.mykhaya.mobile
           url_scheme=mykhaya; host=dev.mykhaya.app; display=MyKhaya-Dev ;;
    *-Prod) suffix=Prod; env=production; bundle=app.mykhaya.mobile.prod; group=group.app.mykhaya.mobile.prod
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
  # Any other value is a target-level override (e.g. typed into Xcode's
  # General tab), which would let the app and its widget drift apart.
  expect MARKETING_VERSION "$S_MARKETING_VERSION" "$(env_setting "$suffix" MARKETING_VERSION)"
  expect CURRENT_PROJECT_VERSION "$S_BUILD" "$(env_setting "$suffix" CURRENT_PROJECT_VERSION)"
  if [ "$kind" = appex ]; then
    expect PRODUCT_BUNDLE_IDENTIFIER "$S_PRODUCT_BUNDLE_IDENTIFIER" "$bundle.widgets"
  else
    expect PRODUCT_BUNDLE_IDENTIFIER "$S_PRODUCT_BUNDLE_IDENTIFIER" "$bundle"
  fi
}

if [ "${1:-}" = "--build-phase" ]; then
  CONFIG_DIR="${SRCROOT:-.}/Config"
  S_ENVIRONMENT="${MYKHAYA_ENVIRONMENT:-}"
  S_APP_BUNDLE_ID="${MYKHAYA_APP_BUNDLE_ID:-}"
  S_APP_GROUP="${MYKHAYA_APP_GROUP:-}"
  S_URL_SCHEME="${MYKHAYA_URL_SCHEME:-}"
  S_SERVER_HOST="${MYKHAYA_SERVER_HOST:-}"
  S_DISPLAY_NAME="${MYKHAYA_DISPLAY_NAME:-}"
  S_APNS="${MYKHAYA_APNS_BUILD_ENVIRONMENT:-}"
  S_PRODUCT_BUNDLE_IDENTIFIER="${PRODUCT_BUNDLE_IDENTIFIER:-}"
  S_MARKETING_VERSION="${MARKETING_VERSION:-}"
  S_BUILD="${CURRENT_PROJECT_VERSION:-}"
  if [ "${WRAPPER_EXTENSION:-}" = appex ]; then kind=appex; else kind=app; fi
  check_versions
  check "${CONFIGURATION:-}" "$kind"
  if [ "$FAILURES" -gt 0 ]; then
    echo "error: MyKhaya iOS environment check failed for ${TARGET_NAME:-target} (${CONFIGURATION:-?}). See docs/mobile/ios-environments.md." >&2
    exit 1
  fi
  echo "MyKhaya iOS environment OK: ${TARGET_NAME:-target} ${CONFIGURATION:-} -> ${PRODUCT_BUNDLE_IDENTIFIER:-} $MARKETING_VERSION ($CURRENT_PROJECT_VERSION) ($MYKHAYA_ENVIRONMENT, $MYKHAYA_SERVER_HOST)"
  exit 0
fi

# ---- Mac Terminal mode -----------------------------------------------------

if [ "$(uname)" != "Darwin" ]; then
  echo "This mode needs Xcode (macOS). On other systems run: pnpm --filter @mykhaya/ios-shell test" >&2
  exit 1
fi
cd "$(dirname "$0")/.."
PROJECT=ios/App/App.xcodeproj
CONFIG_DIR=ios/App/Config

setting() {
  # setting <name> <showBuildSettings output>
  printf '%s\n' "$2" | sed -n "s/^ *$1 = //p" | head -1
}

check_versions

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
    S_MARKETING_VERSION=$(setting MARKETING_VERSION "$settings")
    S_BUILD=$(setting CURRENT_PROJECT_VERSION "$settings")
    if [ "$target" = MyKhayaWidgets ]; then kind=appex; else kind=app; fi
    check "$configuration" "$kind"
    echo "checked $configuration / $target -> $S_PRODUCT_BUNDLE_IDENTIFIER $S_MARKETING_VERSION ($S_BUILD) ($S_ENVIRONMENT, $S_SERVER_HOST, $S_APP_GROUP, $S_URL_SCHEME://)"
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
