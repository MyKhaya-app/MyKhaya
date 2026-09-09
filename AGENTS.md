# MyKhaya contributor and agent rules

Before making any UI, layout, navigation, responsive, mobile, tablet, desktop,
PWA or native-shell change, read the relevant standards and architecture records:

1. `docs/engineering/engineering-standards.md`
2. `docs/engineering/ui-platform-standards.md`
3. `docs/engineering/frontend-standards.md`
4. `docs/engineering/mobile-standards.md`
5. `docs/design/layout-and-navigation.md`
6. `docs/design/design-system.md`
7. `docs/design/visual-identity.md`
8. `docs/engineering/definition-of-done.md`
9. `docs/architecture/adr/0012-capacitor-ios-shell.md`
10. `docs/architecture/adr/0013-hybrid-web-and-native-presentation.md`

The current native/mobile UI is the protected baseline. Desktop and tablet work
must not alter mobile geometry, safe areas, fixed navigation, sheets, viewport
scaling or touch behaviour. Mobile work must not constrain desktop/tablet to a
narrow phone-width layout.

Every user-facing UI change must verify both presentation families. Shared
CSS/layout changes require an explicit mobile/native and web/tablet/desktop
impact assessment before implementation.

MyKhaya has one primary consumer frontend: `apps/web`. Keep business logic,
API access, authentication, permissions, entitlements, domain state and data
models shared. Use `isNativeShell()` and `nativePlatform()` from
`apps/web/components/native-runtime.ts` for genuinely native behaviour; do not
scatter direct Capacitor checks or user-agent detection.

The Platform Control Centre (PCC) is a separate desktop-first administrative
surface. Consumer mobile layout rules must not be applied to PCC unless a task
explicitly requests it.

Governing shorthand:

> Mobile is fixed and app-like. Desktop is adaptive and spacious. Neither is
> allowed to compromise the other.
