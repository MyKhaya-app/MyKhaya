# Forms

Consumer forms use the shared layout primitives in
`apps/web/components/form-layout.tsx`. They exist because forms built with
bespoke grids kept overflowing on iPhone: Copy Event's date and time inputs
ran past their card on an iPhone Duo while every browser audit passed. New
forms use these primitives by default. Calendar Copy Event
(`apps/web/app/calendar/copy-event-sheet.tsx`) is the reference
implementation.

## The primitives

| Component | Use it for | Renders |
|---|---|---|
| `FormSheet` | Any form presented as a bottom sheet | `BottomSheet` with a pinned footer: primary action, then Cancel |
| `FormLayout` | The body of every form | A one-column grid; a `<form>` when given `onSubmit` |
| `FormSection` | A group of related fields with a heading | `<fieldset>` + `<legend>`; `framed` for repeatable cards, `divider` for a rule above |
| `FormRow` | Fields that belong side by side | Up to `columns` (2 by default) equal columns that stack when there is no room |
| `FormField` | Every label + control pair | Label, control, help text and error, all associated |
| `FormActions` | Actions outside a sheet footer | The shared `.sheet-actions` row |

`FormField` takes the control as a render function, so the `id`,
`aria-describedby` and `aria-invalid` wiring is always correct:

```tsx
<FormField label="Start time" hint="In the event's time zone" error={startError}>
  {(control) => <input {...control} type="time" value={start} onChange={onStart} />}
</FormField>
```

## Responsive behaviour

- Everything is contained: border-box, `min-width: 0` and `minmax(0, 1fr)`
  tracks throughout. A control can never be wider than its container.
- `FormRow` responds to the space it actually has, not the viewport. Each
  column is at least `minColumnWidth` (8.5rem by default, enough for a time
  input). When the row cannot fit its columns, it drops to fewer, down to one.
  The same markup therefore works in a 320px sheet, a Duo column and a
  desktop panel, with no breakpoints.
- Native date and time inputs get the shared `.consumer-date-time-control`
  treatment inside `FormField`: no platform appearance, 47px tall, 16px text
  (no iOS focus zoom). Outside `FormField`, a zero-specificity rule still
  removes their platform appearance on every consumer surface. It does not
  reach the Platform Control Centre (`.pcc-root`), which styles its own
  controls.

## Grouping fields

- Put a date on its own row and its start and end times in a two-column
  `FormRow`. Do not put date, start and end in one three-column row on
  phones.
- Use a `framed` `FormSection` for repeatable groups (destinations, line
  items), with the per-group action (Remove) in `actions`.
- Use plain sections, with `divider` where needed, for the parts of a long
  form. Do not nest framed sections.
- Show validation under the field it concerns (`error`). Use a
  `.notice.error` banner only for form-level or server errors.

## Sheet or dialog

The consumer app presents forms as bottom sheets on every width today;
`FormSheet` is that presentation. A desktop dialog presentation has not been
designed. Adding one changes every sheet on tablet and desktop, so it needs
its own design decision and is not part of this standard yet.

`FormSheet` behaviour, from the shared `BottomSheet`:

- The header stays fixed, the body scrolls, and the footer stays in the
  usable viewport. Every control in the body can be scrolled fully into view
  above the footer.
- The sheet stays out of the left and right safe areas. On the iPhone Duo
  the status indicator is drawn inside the right inset, over the sheet
  header's top-right corner.
- The footer always has Cancel as well as the header close button, so
  dismissal never depends on a corner that a system overlay can cover.
  Escape and the Android back gesture also dismiss.
- While the software keyboard is open, the sheet follows the visual viewport
  so the footer stays above the keyboard.
- While `busy`, every dismissal path is disabled so a save in flight is not
  orphaned.

## Anti-patterns

- Hiding overflow (`overflow-x: hidden` on a page, sheet or card) to get rid
  of a scrollbar. Fix the element that is too wide.
- Bare `1fr` or fixed-pixel columns around inputs. Use `FormRow`, or
  `minmax(0, 1fr)`.
- `display: grid` or `flex` directly on a `<fieldset>`. WebKit has ignored
  it; `FormSection` puts the grid on an inner element.
- Viewport breakpoints to stack fields. The same form appears in sheets,
  Duo columns and panels of different widths.
- A visible label plus an `aria-label` that says something different. The
  accessible name must contain the visible label.
- Putting the only dismissal control in a sheet's top-right corner.

## Verifying a form

- `pnpm --filter @mykhaya/web test:layout` renders the shared components in
  Chromium across phone, Duo-class, landscape, keyboard, tablet and desktop
  profiles. It measures containment, overlap, scroll-to-reveal reachability,
  footer and keyboard clearance, and the close button against the Duo status
  zone. Add a fixture to `scripts/form-layout-fixtures.tsx` for a new form
  pattern.
- `pnpm --filter @mykhaya/web audit:responsive` runs the same inspector
  against a running app, signed in, across every consumer route, each
  module's create sheet and Copy Event.
- Both are Chromium with simulated safe areas. WebKit on iOS sizes native
  controls differently, so a physical iPhone review is still required
  ([mobile standards](../engineering/mobile-standards.md)).
