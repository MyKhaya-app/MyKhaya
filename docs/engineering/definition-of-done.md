# Definition of Done

A change is done only when:

- Requirements and acceptance criteria are met.
- Server-side authentication and authorisation are correct.
- Cross-Home behaviour is tested.
- Input, output and resource limits are explicit.
- Errors fail safely.
- Logs are useful and contain no secrets.
- Tests, type checks, linting and builds pass.
- Database migration and rollback implications are understood.
- Security and threat-model documentation is updated where relevant.
- Design remains faithful to the canonical MyKhaya reference.
- No unresolved high or critical security issue remains without an approved risk record.
- Any user-facing UI change has been reviewed on a physical phone (iPhone and Android where possible) against the visual quality standard — see `docs/engineering/mobile-standards.md`. Desktop browser responsive mode alone is not sufficient evidence.

## UI platform completion gate

Every UI change must be classified as one of:

- mobile-only;
- wide-screen-only;
- shared behaviour; or
- shared component with presentation-specific layout.

The change must include phone verification, tablet verification where
applicable, and desktop verification. Confirm no horizontal scroll, viewport
scaling, mobile/native bleed-over, desktop phone-width squeeze, keyboard/focus
regression or safe-area/bottom-navigation overlap. Physical iPhone verification
is required where the native shell can be affected. A wide-screen-only change
must explicitly confirm that the protected mobile/native baseline is unchanged.
