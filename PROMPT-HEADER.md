# Mandatory MyKhaya UI prompt header

Before making any UI, layout, navigation, responsive, mobile, tablet, desktop,
PWA or native-shell change, read:

- `AGENTS.md`
- `docs/engineering/ui-platform-standards.md`
- `docs/engineering/frontend-standards.md`
- `docs/engineering/mobile-standards.md`
- `docs/design/layout-and-navigation.md`
- `docs/engineering/definition-of-done.md`
- `docs/architecture/adr/0012-capacitor-ios-shell.md`
- `docs/architecture/adr/0013-hybrid-web-and-native-presentation.md`

The current native/mobile UI is the protected baseline unless the prompt
explicitly requests a mobile change. Desktop/tablet changes must not alter
mobile geometry, safe areas, fixed navigation, sheets, viewport scaling or touch
behaviour. Mobile changes must not constrain desktop to a phone-width layout.

Verify both mobile/native and web/tablet/desktop before declaring completion.

## PCC addendum

PCC is desktop-first. Do not apply consumer mobile layout rules to PCC unless
the prompt explicitly requests that change.
