#!/usr/bin/env bash
# Run this after mac-bootstrap.sh (and after the manual verification pass in
# docs/mobile/ios-shell-mac-checklist.md) to commit the generated iOS
# project. Review the diff before committing — this script stops for you to
# read `git status` rather than committing blind.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "== Files that would be committed =="
git add apps/ios-shell/ios
git status

echo ""
echo "Review the file list above. It should be almost entirely new files"
echo "under apps/ios-shell/ios/ (the generated Xcode project). It should"
echo "NOT include: *.xcuserstate, xcuserdata/, DerivedData, .p12/.mobileprovision"
echo "files, or anything under ~/Library. If you see any of those, run:"
echo "  git reset apps/ios-shell/ios"
echo "and add an ios/.gitignore entry before retrying (see"
echo "docs/mobile/ios-shell-mac-checklist.md for the expected exclusions)."
echo ""
read -p "Looks correct — commit now? [y/N] " CONFIRM
if [ "$CONFIRM" != "y" ]; then
  echo "Not committing. Staged but uncommitted — re-run this script when ready."
  exit 0
fi

git commit -m "$(cat <<'EOF'
feat: generate iOS Xcode project for the Capacitor shell

Generated via `npx cap add ios` + `npx cap sync ios` from apps/ios-shell,
per docs/mobile/ios-shell-mac-checklist.md. Live-frontend server.url,
cleartext:false, and the non-wildcard allowNavigation list carried through
sync unchanged from apps/ios-shell/capacitor.config.ts.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"

echo ""
echo "Committed. Push when ready:  git push origin dev"
