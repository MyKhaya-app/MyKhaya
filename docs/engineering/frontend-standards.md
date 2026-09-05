# Frontend Standards

- Use Next.js App Router and strict TypeScript.
- Use generated API clients and explicit response models.
- Use central design tokens; never scatter raw brand colours.
- Components must be accessible, responsive and keyboard usable.
- Authentication secrets must not be stored in browser localStorage.
- Protected routes do not replace API authorisation.
- Avoid generic dashboard templates and third-party design systems that conflict with the approved design.
- Implement loading, empty, success and failure states deliberately.
- Do not use broad CSP exceptions to fix implementation problems.
- Test critical journeys with Playwright.

## Shared module controls

Reuse established MyKhaya interaction patterns across modules. Segmented
selectors use the shared `.rr-segmented` container and `.rr-segment` buttons,
with the appropriate active-state class. A module's primary create action uses
the shared `.rr-fab` floating `+ Add` control, including its bottom-navigation
and safe-area clearance. Do not introduce an inline module-specific `+ New`
variant when the module has a single primary creation flow; preserve the
existing search, content width, and module-specific content around these
shared controls.
