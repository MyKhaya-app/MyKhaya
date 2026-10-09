# iOS Shell — Native Asset Inventory (Phase 3)

Survey of what exists today, for a future Phase 4 iOS AppIcon/launch-screen
generation pass. No new artwork or brand decisions are made here — this is
an inventory and a note on how to turn what exists into what Xcode needs.

## What exists today

- **Icons are generated, not static files.** `apps/web/app/icon.tsx` and
  `apps/web/app/apple-icon.tsx` are Next.js route handlers using
  `next/og`'s `ImageResponse` to render an inline SVG at request time —
  there is no static `icon.png` anywhere in the repo to just copy.
  `app/icons/icon-192`, `icon-512`, `icon-maskable-512` are the same
  pattern at PWA manifest sizes.
- **The mark itself**: a simple geometric "home" glyph — a roof stroke plus
  four rounded rectangles — defined inline in `app/icon.tsx`:
  ```
  roof:              #7D8F7A (sage green — MyKhaya's theme colour)
  bottom-left tile:  #E07A5F (terracotta)
  bottom-right tile: #F2EDE3 (cream)
  lower-left tile:   #7D8F7A
  lower-right tile:  #E9B44C (gold)
  ```
- **Theme/background colours** (from `apps/web/app/manifest.ts`):
  `theme_color: "#7D8F7A"`, `background_color: "#FAF7F1"` (warm off-white).
- **Splash/loading state**: `apps/ios-shell/www/index.html` (this phase)
  uses the same background colour (`#FAF7F1`) so the brief moment before
  `server.url` finishes loading doesn't flash a mismatched colour.
- No dedicated logo lockup/wordmark file exists beyond
  `apps/web/public/mykhaya-email-logo.png` (used in transactional email,
  not the app icon).

## Why this can't be finished without macOS

An iOS `AppIcon.appiconset` needs a fixed set of static PNGs at specific
pixel sizes (20pt–1024pt, various @2x/@3x scales) baked into the Xcode
asset catalog inside `ios/App/App/Assets.xcassets` — a folder that doesn't
exist until `npx cap add ios` has been run (Mac-only, see the
[Mac checklist](./ios-shell-mac-checklist.md)). Generating and placing
those files is therefore inherently a Phase 4, on-the-Mac step.

## What Phase 4 should actually do, so it isn't guessing

1. Fetch the existing route handlers once to get real static PNGs to feed
   an icon generator, instead of re-drawing the mark by hand:
   ```sh
   curl https://dev.mykhaya.app/icons/icon-512 -o mykhaya-icon-512.png
   ```
   (or run `apps/web` locally and hit `http://localhost:3000/icons/icon-512`).
2. Feed that PNG into any standard iOS icon-set generator (e.g. Xcode's own
   "New App Icon" asset in Assets.xcassets accepts a single 1024×1024
   source and can be filled from there manually, or a CLI tool such as
   `cap-icon`/`capacitor-assets` if a Capacitor-native path is preferred).
3. Use `#FAF7F1` as the launch-screen background colour — do not
   introduce a different background for the native launch screen than the
   PWA already uses.

Nothing in this list requires new design work — it's mechanical generation
from assets that already exist.
