# Mobile Standards

- Use Expo and React Native; do not wrap the web app in a WebView.
- Share design tokens, API client, validation and domain types where suitable.
- Store reusable credentials only in platform secure storage.
- Request device permissions only when a feature needs them, with clear just-in-time explanation.
- Design for intermittent connectivity and eventual offline support.
- Keep mobile navigation native and purpose-built rather than duplicating desktop layouts.
- Design and verify the signed-in web app at 320, 375, 390 and 430 CSS pixels before widening it for 768, 1024 and 1440. Pages must not require horizontal scrolling.
- Use a fixed, safe-area-aware bottom navigation on phones. Only enabled modules may appear. Keep primary destinations to five or fewer and provide a direct Home Admin path to the Khaya Control Centre.
- Interactive controls must be at least 44 by 44 CSS pixels, keyboard reachable and visibly focused. Bottom sheets trap focus, close with Escape, restore focus and leave room for the on-screen keyboard and device safe areas.
- Calendar month cells use compact event indicators on narrow phones. Selecting a day opens a readable day sheet; event creation and editing use a full-height sheet rather than a squeezed desktop form.
- Prefer stacked cards and disclosure panels to wide tables. Text, names and event metadata must wrap without breaking the viewport.
- Respect `prefers-reduced-motion`; never make animation necessary to understand state.
- Follow OWASP Mobile Top 10 2024 as an awareness baseline alongside the main security standards.
