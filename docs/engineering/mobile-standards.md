# Mobile Standards

> MyKhaya has one shared frontend (`apps/web`) consumed by the browser/PWA and
> by the live Capacitor shell in `apps/ios-shell` — see [ADR 0012](../architecture/adr/0012-capacitor-ios-shell.md)
> and [ADR 0013](../architecture/adr/0013-hybrid-web-and-native-presentation.md).
> These standards govern the protected mobile/native presentation of that one
> codebase, not a duplicated feature frontend.

## Protected architecture

The current mobile/native UI is the protected baseline. The Capacitor shell
loads the deployed frontend inside WKWebView; ordinary feature work remains in
`apps/web`. Desktop or tablet work must not bleed into the native shell, and
mobile work must not force the browser experience to remain phone-width.

## Physical-device review is mandatory

No UI change may be merged into MyKhaya unless it has been reviewed on a physical phone (iPhone and Android where possible) and meets the project's visual quality standard — not just functional correctness. Desktop browser responsive mode (dev tools device emulation) is a useful development aid but is **not** sufficient validation on its own: it does not reveal real safe-area behaviour, real touch-target feel, real font rendering, real shadow/elevation perception, or the difference between "technically responsive" and "feels like a native app." This mirrors the equivalent rule already in place for Kaya.

Screenshots taken via automated tooling (Playwright, etc.) are useful for catching layout regressions and are not a substitute for this review — they confirm the markup renders, not that it meets the quality bar.

- Design mobile-first: build and verify the phone layout before widening for tablet/desktop, not the reverse.
- Store reusable credentials (session tokens) only via secure, HttpOnly cookies for the browser/PWA client — this remains unchanged and is not migrated to any other storage. A future native (Capacitor) shell around this same PWA uses the separate bearer-token mechanism in [ADR 0010](../architecture/adr/0010-mobile-bearer-session-tokens.md) instead, stored via the native-session-store abstraction in `packages/api-client` (in-memory only until an iOS Keychain adapter exists) — this is a second, narrowly-scoped transport for that one future shell, not a general-purpose mobile credential store, and does not change how the browser/PWA client authenticates.
- Request browser permissions (notifications, etc.) only when a feature needs them, with clear just-in-time explanation.
- Design for intermittent connectivity and PWA offline support via the service worker.
- Keep bottom navigation purpose-built for touch rather than a shrunk desktop layout.
- Preserve the current warm header, fixed safe-area-aware bottom navigation,
  compact content width, spacing, FAB clearance, sticky/fixed behaviour,
  bottom-sheet/full-height-sheet behaviour and keyboard handling unless a task
  explicitly requests a mobile/native change.
- Mobile/native must not develop horizontal scrolling, zoomed-out pages,
  desktop sidebars or canvases, fixed-header overlap, bottom-nav overlap,
  safe-area clipping, hidden content or desktop breakpoint leakage into WKWebView.
- Use `isNativeShell()` and `nativePlatform()` from
  `apps/web/components/native-runtime.ts` for native-specific behaviour. Do not
  scatter direct Capacitor checks or user-agent detection.
- Persistent login, biometrics, native push and secure native session handling
  must not regress because of responsive or layout work.
- Design and verify the signed-in web app at 320, 375, 390 and 430 CSS pixels before widening it for 768, 1024 and 1440. Pages must not require horizontal scrolling.
- Use a fixed, safe-area-aware bottom navigation on phones, limited to exactly four primary destinations (Home, Calendar, Family, More). Less-frequent destinations (e.g. the Khaya Control Centre for Home Admins) live under More/Settings rather than crowding the bar.
- Interactive controls must be at least 44 by 44 CSS pixels, keyboard reachable and visibly focused. Bottom sheets trap focus, close with Escape, restore focus and leave room for the on-screen keyboard and device safe areas.
- Calendar month cells use compact event indicators on narrow phones. Selecting a day opens a readable day sheet; event creation and editing use a full-height sheet rather than a squeezed desktop form.
- Prefer stacked cards and disclosure panels to wide tables. Text, names and event metadata must wrap without breaking the viewport.
- Respect `prefers-reduced-motion`; never make animation necessary to understand state.
- Follow OWASP Mobile Top 10 2024 as an awareness baseline alongside the main security standards.

Desktop/tablet enhancements must be additive and scoped. Verify the phone
baseline at 320, 375, 390 and 430px before widening to 768, 1024 and 1440px.
Physical iPhone review is mandatory before release for changes capable of
affecting the native shell; browser emulation and screenshots do not replace
that review.
