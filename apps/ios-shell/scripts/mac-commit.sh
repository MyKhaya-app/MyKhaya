#!/usr/bin/env bash
# Safety-check helper for committing changes under apps/ios-shell/ios/,
# apps/ios-shell/native/, and apps/ios-shell/scripts/. The native Xcode
# project is committed to this repository (see
# docs/mobile/ios-shell-mac-checklist.md) — this is no longer a one-time
# "commit the freshly generated project" script, it's a review step for any
# ordinary native-project change (a new widget, an entitlement change, a
# plugin update). It stages, then RUNS CHECKS on what's staged, then shows
# you the result — it never commits without your explicit confirmation, and
# it refuses to proceed if any check fails.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "== Staging apps/ios-shell/ios, apps/ios-shell/native, apps/ios-shell/scripts =="
git add apps/ios-shell/ios apps/ios-shell/native apps/ios-shell/scripts

STAGED_FILES=$(git diff --cached --name-only -- apps/ios-shell/ios apps/ios-shell/native apps/ios-shell/scripts)

if [ -z "$STAGED_FILES" ]; then
  echo "Nothing staged under apps/ios-shell/{ios,native,scripts} — nothing to do."
  exit 0
fi

FAIL=0

check_absent() {
  local pattern="$1" description="$2"
  local hits
  hits=$(echo "$STAGED_FILES" | grep -E "$pattern" || true)
  if [ -n "$hits" ]; then
    echo "FAIL: $description — staged:"
    echo "$hits" | sed 's/^/    /'
    FAIL=1
  fi
}

check_present() {
  local pattern="$1" description="$2"
  local hits
  hits=$(echo "$STAGED_FILES" | grep -E "$pattern" || true)
  if [ -z "$hits" ]; then
    echo "WARNING: $description — no staged file matched. If this is a fresh/recovered project, confirm this is expected before committing."
  fi
}

echo ""
echo "== Checks: things that must NOT be staged =="
check_absent 'xcuserdata/' "xcuserdata (per-user IDE state)"
check_absent '\.xcuserstate$' "*.xcuserstate"
check_absent '(^|/)DerivedData/' "DerivedData"
check_absent '\.xcarchive(/|$)' "Xcode archive"
check_absent '\.ipa$' "IPA build output"
check_absent '\.mobileprovision$' "provisioning profile"
check_absent '\.(p12|p8|cer)$' "certificate/private key file"

echo ""
echo "== Checks: absolute machine-specific paths in staged text files =="
ABS_PATH_HITS=""
while IFS= read -r f; do
  [ -z "$f" ] && continue
  if git show ":$f" 2>/dev/null | grep -qaE "/Users/[a-zA-Z0-9_-]+|/home/[a-zA-Z0-9_-]+"; then
    ABS_PATH_HITS="$ABS_PATH_HITS$f"$'\n'
  fi
done <<< "$STAGED_FILES"
if [ -n "$ABS_PATH_HITS" ]; then
  echo "FAIL: absolute machine-specific paths found in:"
  echo "$ABS_PATH_HITS" | sed 's/^/    /'
  FAIL=1
fi

echo ""
echo "== Checks: obvious secret material in staged text files =="
SECRET_HITS=""
while IFS= read -r f; do
  [ -z "$f" ] && continue
  if git show ":$f" 2>/dev/null | grep -qaiE "BEGIN (RSA|EC|PRIVATE) KEY|bearer [a-zA-Z0-9._-]{10,}|api[_-]?key\s*[:=]|password\s*[:=]"; then
    SECRET_HITS="$SECRET_HITS$f"$'\n'
  fi
done <<< "$STAGED_FILES"
if [ -n "$SECRET_HITS" ]; then
  echo "FAIL: possible secret material found in:"
  echo "$SECRET_HITS" | sed 's/^/    /'
  FAIL=1
fi

echo ""
echo "== Checks: expected files present (only meaningful if ios/ itself is staged) =="
if echo "$STAGED_FILES" | grep -q '^apps/ios-shell/ios/'; then
  check_present 'App\.xcodeproj/project\.pbxproj$' "project.pbxproj"
  check_present 'App/AppDelegate\.swift$' "AppDelegate.swift"
  check_present '\.entitlements$' "an entitlements file"
  check_present 'xcschemes/MyKhayaWidgets\.xcscheme$' "MyKhayaWidgets shared scheme (widget target)"
fi

echo ""
if [ "$FAIL" -ne 0 ]; then
  echo "One or more checks FAILED — not proceeding to commit."
  echo "Unstage the offending files (git restore --staged <file>), fix the"
  echo "underlying issue (e.g. add a .gitignore rule, remove the secret,"
  echo "make a path repo-relative), and re-run this script."
  exit 1
fi

echo "All checks passed. Files staged for commit:"
git status --short -- apps/ios-shell/ios apps/ios-shell/native apps/ios-shell/scripts

echo ""
read -p "Looks correct — commit now? [y/N] " CONFIRM
if [ "$CONFIRM" != "y" ]; then
  echo "Not committing. Staged but uncommitted — re-run this script (or commit manually) when ready."
  exit 0
fi

read -p "Commit message summary (one line): " SUMMARY
if [ -z "$SUMMARY" ]; then
  echo "No summary given — not committing. Staged but uncommitted."
  exit 0
fi

git commit -m "$SUMMARY"

echo ""
echo "Committed. Push when ready:  git push origin $(git branch --show-current)"
