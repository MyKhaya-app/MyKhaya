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
- A notice about a field the form corrected for the user (for example, End
  moved to stay after Start) is that field's `hint`, so it is announced with
  the field.
- Optional, less-used fields can sit in a closed `<details>` disclosure
  after the main fields. Put a plain `FormLayout` (no `onSubmit`) inside it
  for the same spacing.
- Pick `minColumnWidth` from what the row holds. Times can use the
  default. A row with a date uses `10rem`, so it stacks at 320px, where a
  date beside another control is clipped. A row whose selects have long
  options (for example "Personal — only reminds you" or "Hourly until
  completed") uses `14rem`, so it stacks on every phone and sits side by
  side only in wider sheets and panels. A cut-off select option is a
  defect, not a layout.
- Checkbox settings rows (`.check-row`, or a checkbox with a title and
  description) are not `FormField`s: the label wraps the checkbox and its
  text. Put them straight into the `FormSection`.
- On a page rather than a sheet, a `FormSection` can take the page's own
  heading as its title (`title={<h2>Quiet hours</h2>}`), so the page keeps
  its heading outline and each group is still named by it.
- Show a save error inside the sheet that is open, at the top of its form,
  not on the page behind the sheet.
- `FormLayout` sets `noValidate` by default, for forms that validate
  themselves, like Copy Event. A form that relies on the browser's own
  `required` and `min` checks passes `noValidate={false}`.

## Calendar event editor

The Calendar event editor (`EventForm` in `apps/web/app/calendar/page.tsx`)
is the full-size example:

- Add event is a `FormSheet`. Edit event stays a `BottomSheet` because the
  same sheet first shows the read-only event; its edit-mode footer is
  `FormActions` with Save changes and Cancel (back to the event).
- The form is a `FormLayout` that keeps browser validation and takes focus
  itself when it opens (`tabIndex={-1}`), so iOS does not zoom into a field.
- When is a `FormSection`: the All day switch, the date on its own row
  (Date, or Starts and Ends for a multi-day event), then Start time and End
  time in a `FormRow`.
- People is a `FormSection` around the shared member rows.
- Calendar, Calendar Tag and Location are `FormField`s with visible labels.
  The Personal and shared calendar notes are the Calendar field's hint.
- Reminder, Repeat, the recurrence end and Notes sit in the "Reminder, repeat
  and notes" disclosure, in `FormRow`s with `minColumnWidth="10rem"` so the
  selects stack on phones. The recurrence end date's validation is that
  field's `error`.

## Routines, Reminders and To-dos

The Routine, Reminder and To-do editors in Nudges
(`apps/web/app/settings/routines-reminders/page.tsx`):

- Each is a `FormSheet` (Routine and Reminder full height) whose form is a
  `FormLayout` with class `rr-form`, keeping the browser's `required`
  checks. A failed save shows its `.notice.error` at the top of that form;
  the page's own error notice is hidden while an editor is open.
- Plain `FormSection`s with `divider`: Routine, Schedule and
  Notifications & Home; Reminder, Who and When; To-do, When and who.
- Scope, assignee and category selects sit in `14rem` rows. Due date and
  time, Starts and Ends, and Every with the anchor date sit in `10rem`
  rows. The anchor date's explanation is its `hint`.
- The Repeat Daily/Weekly choice (`.routine-choice`) and the Critical and
  Pin checkboxes (`.routine-setting`) keep their own markup.
- Not migrated: the Add menu, the Choose category and Manage categories
  sheets (lists of actions, not forms) and the MOT plan delete
  confirmation.

## Settings

- Notification preferences (`app/settings/notifications/page.tsx`) is one
  `FormLayout` card. Each part is a `FormSection` titled by its existing
  `h2`, with `divider` between them. Delivery time and Custom time share a
  `14rem` row; quiet hours Start and End share a default row. The submit
  button is in `FormActions`.
- The Profile birthday editor (`app/settings/profile/page.tsx`) is a
  `FormLayout` with Month and Day in a `FormRow` and Save and Cancel in
  `FormActions`.
- Not migrated:
  - Calendar settings, whose sentence-style rows ("Remind me [30 minutes]
    before events I'm attending") are their own design.
  - Security (MFA and re-authentication), Billing and Members (invites,
    relationships and managed-child permissions), which are outside the
    scope of a presentation-only migration.

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
  against a running app, signed in, across every consumer route and each
  module's create sheet. It also opens the migrated forms in filled states:
  - Copy Event, and the Calendar event editor (Add and Edit);
  - the Routine, Reminder and To-do editors, an Edit, and a Reminder save
    that the audit rejects in the browser, so nothing reaches the API;
  - Notification preferences with both custom times shown, and the
    Profile birthday editor.
- Both are Chromium with simulated safe areas. WebKit on iOS sizes native
  controls differently, so a physical iPhone review is still required
  ([mobile standards](../engineering/mobile-standards.md)).
