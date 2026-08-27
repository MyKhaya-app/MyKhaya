# Mobile Standards

> MyKhaya ships as a single responsive PWA (`apps/web`), not a separate native app — see [ADR 0011](../architecture/adr/0011-single-pwa-retire-mobile-app.md). These standards govern the mobile experience of that one codebase, not a distinct mobile client.

## Physical-device review is mandatory

No UI change may be merged into MyKhaya unless it has been reviewed on a physical phone (iPhone and Android where possible) and meets the project's visual quality standard — not just functional correctness. Desktop browser responsive mode (dev tools device emulation) is a useful development aid but is **not** sufficient validation on its own: it does not reveal real safe-area behaviour, real touch-target feel, real font rendering, real shadow/elevation perception, or the difference between "technically responsive" and "feels like a native app." This mirrors the equivalent rule already in place for Kaya.

Screenshots taken via automated tooling (Playwright, etc.) are useful for catching layout regressions and are not a substitute for this review — they confirm the markup renders, not that it meets the quality bar.

- Design mobile-first: build and verify the phone layout before widening for tablet/desktop, not the reverse.
- Store reusable credentials (session tokens) only via secure, HttpOnly cookies for the browser/PWA client — this remains unchanged and is not migrated to any other storage. A future native (Capacitor) shell around this same PWA uses the separate bearer-token mechanism in [ADR 0010](../architecture/adr/0010-mobile-bearer-session-tokens.md) instead, stored via the native-session-store abstraction in `packages/api-client` (in-memory only until an iOS Keychain adapter exists) — this is a second, narrowly-scoped transport for that one future shell, not a general-purpose mobile credential store, and does not change how the browser/PWA client authenticates.
- Request browser permissions (notifications, etc.) only when a feature needs them, with clear just-in-time explanation.
- Design for intermittent connectivity and PWA offline support via the service worker.
- Keep bottom navigation purpose-built for touch rather than a shrunk desktop layout.
- Design and verify the signed-in web app at 320, 375, 390 and 430 CSS pixels before widening it for 768, 1024 and 1440. Pages must not require horizontal scrolling.
- Use a fixed, safe-area-aware bottom navigation on phones, limited to exactly four primary destinations (Home, Calendar, Family, More). Less-frequent destinations (e.g. the Khaya Control Centre for Home Admins) live under More/Settings rather than crowding the bar.
- Interactive controls must be at least 44 by 44 CSS pixels, keyboard reachable and visibly focused. Bottom sheets trap focus, close with Escape, restore focus and leave room for the on-screen keyboard and device safe areas.
- Calendar month cells use compact event indicators on narrow phones. Selecting a day opens a readable day sheet; event creation and editing use a full-height sheet rather than a squeezed desktop form.
- Prefer stacked cards and disclosure panels to wide tables. Text, names and event metadata must wrap without breaking the viewport.
- Respect `prefers-reduced-motion`; never make animation necessary to understand state.
- Follow OWASP Mobile Top 10 2024 as an awareness baseline alongside the main security standards.
