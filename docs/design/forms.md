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

## A new form, by default

1. **Container.** In a sheet, use a `FormSheet`: primary action then
   Cancel in the footer, and `busy` while saving so no dismissal path
   orphans the save. On a page, use a `FormLayout` card.
2. **Fields.** Every control sits in a `FormField` with a visible label,
   help text as its `hint`, and its check as its `error`. Group related
   fields in a `FormSection`, and fields that belong side by side in a
   `FormRow` sized for its contents (see "Grouping fields").
3. **Dates, times and money.** Dates and times go inside a `FormField`
   (the `.consumer-date-time-control` treatment, 16px text). Money uses a
   number input with the field's own `min` and `step="0.01"`, as Budget's
   `BudgetAmountField` does.
4. **Checks.** Give checked controls a `name` and their native
   constraints. On submit, `useFormFieldErrors` shows each failure under
   its field and moves focus to the first. A blank value is an error, never
   a silent 0 or an empty save.
5. **Saving.** Ignore a second submit while saving. A failed save shows in
   the form (at the top of a sheet's form, or just before a page form's
   button), keeps every value, and re-enables Save and Cancel.
6. **Accessibility.** Labels are programmatic (`FormField` does this). An
   icon-only button has an accessible name that contains any visible text.
   Nothing is only a placeholder.
7. **Verify.** Add the form's states to the responsive audit (empty,
   filled with long text, validation, failed save) and run it with the
   layout harness.

Departing from this needs one of the reasons under "Coverage and
exceptions".

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
- Pick `minColumnWidth` from what the row holds. The consumer root font
  size is 15px (`--font-body` on `html`), so 1rem is 15px.
  - Times and short text fields can use the default.
  - A row with a date uses `10rem` (150px), so it stacks at 320px, where a
    date beside another control is clipped.
  - A row whose selects have long options uses `14rem` (210px), so it
    stacks on every phone and sits side by side only in wider sheets and
    panels. Examples are "Personal — only reminds you", "Hourly until
    completed" and "Plug-in hybrid".
  - A cut-off select option is a defect, not a layout.
- Checkbox settings rows (`.check-row`, or a checkbox with a title and
  description) are not `FormField`s: the label wraps the checkbox and its
  text. Put them straight into the `FormSection`.
- On a page rather than a sheet, a `FormSection` can take the page's own
  heading as its title (`title={<h2>Quiet hours</h2>}`), so the page keeps
  its heading outline and each group is still named by it.
- Show a save error inside the sheet that is open, at the top of its form,
  not on the page behind the sheet. On a page form, show it directly before
  the save button, where the person is looking when it fails.
- Show what the form checks itself as each field's `error`, not as one
  banner ("Add a title and a due date"). After a submit that fails those
  checks, move focus to the first invalid field so its error is announced
  (`useFocusFirstInvalid` in `components/form-layout.tsx`).
  - A group of choice chips has no `aria-invalid`. Describe the group by
    its error and focus its first chip.
  - Render a form-level error notice with `role="alert"` only while there
    is an error. An always-present empty status region adds a grid gap.
- Checks a form makes before saving mirror the API's own rules and never
  replace them. The API stays the authority.
- `FormLayout` sets `noValidate` by default, for forms that validate
  themselves, like Copy Event. A form that relies on the browser's own
  `required` and `min` checks passes `noValidate={false}`.
- To show a form's own constraints as field errors, use
  `useFormFieldErrors` (`components/form-field-errors.ts`) rather than
  writing the checks again. Give each checked control a `name` and keep its
  `required`, `min`, `max`, `step` and `type`. On submit, `check()` reads
  each control's `validity` and returns the errors by name, in plain
  wording. It then moves focus to the first invalid control.
  - Pass a field's wording as `missing`, and, for a value the form trims
    before saving, `blank` (spaces alone).
  - Because the errors come from the controls' own constraints, the form
    checks exactly what the browser would. Nothing new is enforced.
  - Budget, Meal Plans, Lists and Wishlists use it.

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
  `FormActions`. It checks the API's two birthday rules before saving, so a
  missing Month or Day, or a day past the end of the month, is shown as that
  field's `error`. Editing either field clears both. A failed save shows
  inside the editor and keeps the entered values. The browser's own 1–31
  check on Day stays, and the API remains the authority.
- The Members invitation is migrated; see "Help & Support, Calendar
  sharing, Calendar Tags and Members" below.
- Not migrated:
  - Calendar settings, whose sentence-style rows ("Remind me [30 minutes]
    before events I'm attending") are their own design.
  - Security (MFA, passkeys, password and re-authentication), which is
    credential handling, not a presentation migration.
  - Billing, which has no data-entry form: plan choices are buttons that
    hand off to Stripe Checkout or the Customer Portal.
  - The Members row actions (change relationship, approve a join request,
    a child's photo), which act at once and carry permission rules.

## Driveway

- Add vehicle and Edit details render the same fields from one component,
  `VehicleFields` (`apps/web/app/driveway/vehicle-fields.tsx`). It holds
  Country, Registration, Owner, Nickname, Make and Model, Year and Fuel
  type, Colour and Engine size, First registration date, and VIN.
  - The fields only render values, report changes and show errors. Each
    page keeps its own state, registration normalisation, payload, save and
    navigation.
  - Add vehicle passes its lookup actions and result into the
    `afterRegistration` slot. It shows Registration and the rest of the
    fields only once a lookup or manual entry applies.
  - Edit details requires a nickname. Both pages show the VIN only to the
    vehicle's owner and a Home Admin, with the privacy note as its hint.
  - `vehicleFieldErrors` holds both pages' checks: country, registration,
    owner, the Edit nickname, a 1900–2200 year, and an unreadable first
    registration date.
- The vehicle Add reminder sheet is a `FormSheet` (Add reminder and Cancel
  in the footer). Title is on its own row, then Due date and Due time in a
  `10rem` row. Title and Due date show their own errors; a failed save
  shows inside the sheet and keeps the draft.
- The MOT nudge keeps its own cards, Nudge me chips, Repeat switch and
  saved view. Only Reminder and MOT expires are `FormField`s. That replaced
  its 15px `.drv-input`, which outranked the 16px phone rule and made iOS
  zoom on focus.
- Not migrated: the Remove vehicle and Change photo sheets, which are an
  action and a confirmation, not forms.

## Budget

Budget's data-entry sheets are `FormSheet`s (save and Cancel in the footer,
dismissal locked while saving). The helpers are in
`apps/web/app/budget/_components/budget-form-fields.tsx`.

- **Money.** `BudgetAmountField` is a `FormField` around a number input
  with two decimal places (`step="0.01"`). Its minimum is the field's
  existing one: `0` for planned, fixed-cost and income amounts, and `0.01`
  for spending entries, which the API requires to be above zero.
  - There is no currency symbol inside the input, so nothing overlaps the
    value. The page shows the formatted amount (`£1,234.56`) elsewhere.
  - The value stays the string the person typed. Each form converts it
    exactly as before, and a blank amount is an error, never 0.
- **Checks.** The forms are `noValidate`, but every control keeps the
  `required`, `min`, `max` and `step` it always had.
  `useBudgetFieldErrors` (the shared `useFormFieldErrors`) reads each
  control's own `validity` on submit and shows the result as that field's
  `error`. The checks are therefore exactly the browser's, now shown in the
  field, with focus on the first one. A name the form already trimmed
  before saving (an income source, a planned item) also rejects spaces
  alone. The API stays the authority.
- **Dates and months.** A date or month that sits beside another control
  goes in a `10rem` `FormRow`: Amount and Date; Received date and Budget
  month; Start month and End month. Each one stacks at 320px. "Leave empty
  for no end date" is End month's `hint`, and an end month before the start
  month is End month's error.
- **Choices.** Fixed or variable is chosen in the + Add menu, not in a
  field. Repeat monthly, Recurring income and the month-copy choices are
  checkbox rows (`.budget-sheet-toggle`) placed straight in the form. These
  rows are styled outside `.budget-page` too, because the + Add sheets on
  Overview and Income render outside the page's `<main>`.
- **Paid and unpaid.** A fixed item is paid by recording a spending entry
  linked to it ("Mark as paid" opens Add spending entry with the item, its
  name and its planned amount filled in). Edit spending entry sends the link
  back unchanged unless the category changes. There is no paid/unpaid field.
- **Month actions.** Set up next month (the month copy) is a `FormSheet`
  whose primary action names the month it creates. Its three copy choices
  keep their defaults: fixed costs and income on, variable budgets off.
- **Delete and archive.** These stay as a danger link at the end of the
  edit form. Delete income source and Delete spending entry still open
  their own confirmation sheet.
- **Planned and actual amounts.** These are set per category for the
  month in view, from the category's Quick actions.
  - Edit planned amount and Update actual amount are separate sheets, and
    each owns one draft. The draft starts from the stored value and only
    typing changes it, so a re-render cannot reset it. Save sends exactly
    what is shown.
  - Update actual amount starts from the category's own amount: its
    `fixed_actual`, else a legacy row's `manual_actual`, else 0. The API adds
    spending entries to that amount, so the entries total is never offered
    as the starting value; saving it would count those entries twice.
- **Add category** asks only for the name. Creating a category does not
  take a planned amount, so the form does not offer one; it is set
  afterwards with Edit planned amount.
- Not migrated:
  - the + Add menu, the planned item's detail sheet and the Settings and
    Partner sharing pickers, which are lists of actions;
  - the delete confirmations.

## Meal Plans, Lists and Wishlists

Every data-entry sheet in these modules is a `FormSheet`. Save and Cancel
are in the footer, dismissal is locked while saving, a failed save shows at
the top of the form and keeps the draft, and each checked field shows its
own error (`useFormFieldErrors`). Payloads and API calls are unchanged.

- **Meal Plans** (`app/meal-plans/page.tsx`):
  - **Add/Edit planned meal:**
    - The Saved meal / Quick meal toggle keeps its own buttons.
    - The meal, the quick-meal name and Date are each a field.
    - Date has its own row, then Meal and Time share a row.
    - Who's eating is a `FormSection` around the existing check rows and
      member rows, then Cooking and Makes leftovers.
  - **Add/Edit saved meal** (full height):
    - Name and Description are fields, and Category and Favourite share a
      row.
    - The Timing & servings, Method and More details disclosures hold a
      plain `FormLayout`. Prep, Cook and Servings are a three-column row
      that stacks on phones.
    - The photo picker (preview, native gallery, file input) and the
      ingredient cards (quantity, unit, name, remove) keep their own markup
      as the form's specialist controls.
    - The picker's file input is `.visually-hidden`. That utility sets
      `min-height: 0`, because otherwise a hidden input keeps the global
      47px control height as an invisible box that a short landscape sheet
      has to scroll to.
  - **Import recipe:** a URL field. After a failure, Add manually and Try
    another link stay in the form.
  - **Plan this meal:** Date and Meal keep their icon-in-field look
    (`.plan-meal-field`) inside shared fields, in a `10rem` row. Those
    controls now have 16px text on phones, so iOS does not zoom them.
  - **Add ingredients to list:** a `FormSheet` around a form without
    `onSubmit`, so Enter in the new-list name does not add the
    ingredients. The ingredients are a `FormSection`.
- **Lists** (`app/lists/page.tsx`, `app/lists/[id]/page.tsx`):
  - New list and Rename list share List name and Icon (`ListNameFields`).
  - **New/Edit template:** the section editor (named sections,
    reordering, default items) is a repeatable specialist control inside a
    `FormSection` titled Sections. Its inputs have accessible names
    ("Section 1 name", "Section 1 default item 1").
  - **Edit item:** Quantity and Assign to share a `10rem` row. Move up,
    Move down and Remove item act at once, not on Save, and stay in the
    form body.
  - The inline "Add an item…" row on a list is a quick-entry control, not
    a form, and stays as it is.
- **Wishlists** (`app/wish-lists/page.tsx`,
  `app/wish-lists/[id]/page.tsx`):
  - New wishlist and Edit wishlist render the same fields from
    `app/wish-lists/wishlist-fields.tsx`: Title, then Occasion and Date
    in a `10rem` row, then Description.
  - Add item and Edit item share `WishlistItemFields`: Item name, then the
    link with Find product details and its preview, then Price, Currency
    and Quantity in a three-column row, then Note. The link, its button and
    the preview are one group (`.wishlists-link-field`).
  - **Share wishlist:** the Home switch and Manage people stay above the
    form, because they act at once. Name and Email are fields, and an
    invalid email is Email's error.
  - The owner's sheets never touch reservation data. Reserve, Mark as bought
    and their states are the viewer's row actions, unchanged.
- Not migrated, because they are actions, confirmations or one-time
  displays, not forms:
  - the planned meal and saved meal views, the action menus and Add meal's
    choice sheet;
  - Copy previous week, and the duplicate and result screens of Add
    ingredients;
  - the at-limit New list screen and the move-scope confirmation;
  - Wishlist actions, the matched-account confirmation, the one-time guest
    link and PIN screens, and Manage sharing.

## Help & Support, Calendar sharing, Calendar Tags and Members

- **Help & Support** (`app/help-support/contact-support`, `report-bug`,
  `requests/[id]`):
  - These are page forms (`FormLayout` cards).
  - Subject and message, or summary and description, show their own
    errors. They used to share one banner.
  - Report a bug's character count is its summary's `hint`. Its severity
    choices keep their card-style radio rows inside a `FormSection`.
  - The screenshot picker keeps its own control.
  - A failed send shows directly before the send button and keeps the
    draft.
- **Calendar's calendars** (`app/calendar/calendars/page.tsx`):
  - Add a Home calendar is a page form, so a name of spaces alone is now
    its field's error.
  - The share invitation inside Manage sharing is a `FormLayout`:
    - Email address, then Access, then What to share as a `FormSection`.
    - "They don't need a MyKhaya account yet" is Email's `hint`. The
      sharing API's own errors are Email's `error`, where they were shown
      before.
  - Manage sharing stays a `BottomSheet`, not a `FormSheet`. It is a
    management sheet: its share list, permission changes and Delete
    calendar act at once, and the invitation is one form within it.
- **Calendar Tags** (`components/calendar-tags-manager.tsx`):
  - The New Calendar Tag form is a `FormLayout`.
  - The colour swatch and picker are its specialist control.
  - Add stays disabled until a name is typed.
  - Renaming in the tag list is inline and stays as it is.
- **Members invitation** (`app/settings/members/page.tsx`):
  - A `FormLayout` whose handler still reads the email and Family access
    from `FormData` by name, exactly as before.
  - The relationship's explanation is Relationship's `hint`, and Email
    shows a missing or invalid address as its error.
  - The child-profile hand-off, the Family access row and Advanced
    permissions keep their own markup.
- **A check row with a title and a description**
  (`<label class="check-row check-row-described"><input>
  <span><strong>…</strong><small>…</small></span></label>`):
  - Add the `check-row-described` modifier, which keeps the checkbox full
    size beside long text and puts the title above the description.
  - Without it, a long description squeezes the checkbox to nothing.
- **A page form with one action and no Cancel** (the page's back link is
  the way out):
  - Its button stays a direct child of the form, full width, rather than
    in `FormActions`, which is for Save beside Cancel.

## Coverage and exceptions

Every consumer data-entry form is on the shared primitives, except these,
which are deliberate:

| Form | Why it keeps its own layout |
|---|---|
| Sign-in, child sign-in, register, forgot and reset password, MFA, onboarding, waitlist | Authentication and account-creation flows: credential handling is out of scope for a presentation migration. The sign-in password adornment is still checked by the audit. |
| Security settings (MFA, passkeys, password) | Credential and session handling. |
| Billing | No data-entry form: plan buttons hand off to Stripe. |
| Calendar settings | Sentence-style rows are their own design. |
| Guest wishlist PIN (`/wishlist/share/[token]`) | A public, unauthenticated guest gate. |
| Beta enrolment and founding-beta pages | Marketing and enrolment flows, not account data. |
| Members row actions, calendar share acceptance, share list rows | Actions that apply at once, not forms. |
| Inline quick-entry rows (Lists' "Add an item…", Calendar Tags' rename) | Single-field rows inside a list. |

New consumer forms use the shared primitives by default. A new exception
needs a reason that fits this table.

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
- On a short screen (520px tall or less, which means a phone in landscape),
  the sheet fills the height below the backdrop's top inset. The footer pads
  by the home-indicator inset or 0.75rem, whichever is larger, rather than
  their sum. Taller screens keep the portrait allowances.
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
  pattern. It also runs the inspector's self-tests: small pages with a known
  answer, including overlaps that must still fail.
- `pnpm --filter @mykhaya/web audit:responsive` runs the same inspector
  against a running app, signed in, across every consumer route and each
  module's create sheet. It also opens the migrated forms in filled states:
  - Copy Event, on one fixture event served in the audit's own browser
    (`routeCopyEvent`). It is a one-off owned by the signed-in user, placed
    inside whatever window the calendar asks for, so every viewport has an
    event to copy whatever the date or the account's own events, and no
    event is written;
  - the Calendar event editor (Add and Edit);
  - the Routine, Reminder and To-do editors, an Edit, and a Reminder save
    that the audit rejects in the browser, so nothing reaches the API;
  - Notification preferences with both custom times shown, and the
    Profile birthday editor;
  - Driveway, on fixed fixture vehicles served in the audit's own browser
    (`routeDriveway`), so the result does not depend on the platform flag
    or the Home, and nothing is written:
    - the vehicle page;
    - Edit details filled, with validation errors, and with a failed save;
    - Add vehicle with validation errors;
    - the MOT nudge with validation errors and with a failed save;
    - the Add reminder sheet with validation errors and with a failed save.

    The `/driveway` and `/driveway/add` route checks use the same fixtures.
    A separate section serves Driveway as off and passes only when the
    unavailable screen renders. Any state that cannot be set up is NOT
    TESTED, never passed.
  - Budget, on fixture data served in the audit's own browser
    (`routeBudget`), with long names and pence amounts. Every write is
    rejected in the browser, so no financial record is touched. It covers:
    - Add income empty, and Edit income filled;
    - income validation and an income failed save;
    - Add fixed cost with validation and with a failed save;
    - Add spending entry with validation, and Edit spending entry with a
      failed save;
    - planned item edit with validation;
    - the Mark as paid sheet;
    - an Edit planned amount failed save;
    - Update actual amount filled, and with validation;
    - a Set up next month failed save;
    - Add category with validation.
  - Meal Plans, Lists and Wishlists, on fixture data served in the audit's
    own browser (`routeHomeModules`), with long names, nine ingredients and
    a sectioned list. Every write is rejected in the browser, and the
    wishlist is the signed-in member's own, so only the owner view, which
    has no reservation fields, is served. It covers 22 states:
    - planned meal Add (empty and with validation), Edit filled, and a
      failed save;
    - saved meal Add (empty and with validation), Edit with every
      disclosure open, and a failed save;
    - Import recipe with an invalid link and with a failed import;
    - Plan this meal with validation, and Add ingredients to list;
    - New wishlist with validation, Edit wishlist filled, Add item filled,
      an Edit item failed save, and Share with validation;
    - New list with validation, a template with several sections, a Rename
      list failed save, and Edit list item filled and with validation.
  - The remaining forms, on the account's own pages, with every API write
    rejected in the audit's browser for the whole section, so no ticket,
    calendar, share, tag or invitation is created and no email is sent.
    Support is served as enabled. It covers 8 states:
    - Contact support and Report a bug, each with validation and with a
      failed send;
    - Add a Home calendar with validation, and the share invitation with
      an invalid email;
    - New Calendar Tag filled with its colour picker open;
    - the Members invitation with an invalid email. This state also checks
      that the Family access checkbox keeps its size.
- Each route is measured after its first requests settle (network idle,
  capped at 5 seconds), so a slow page is not measured as its loading
  screen.
  - The sign-in page's three states, each in a fresh signed-out browser:
    the password form, the password shown, and the remembered account.
    The remembered account uses a mocked local hint and a virtual WebAuthn
    authenticator, never a real passkey.
- Some controls sit inside their input by design, such as the sign-in
  "Show password" button. Mark such a button with `data-input-adornment`
  and name its input with `aria-controls`. The inspector then allows its
  overlap with that one input and checks it instead:
  - it stays inside the input's wrapper;
  - the input's padding keeps text from running under it;
  - it is reachable from the keyboard;
  - a `password-visibility` adornment is named "Show password" or "Hide
    password" to match the field.

  Overlap with anything else still fails.
- Both are Chromium with simulated safe areas. WebKit on iOS sizes native
  controls differently, so a physical iPhone review is still required
  ([mobile standards](../engineering/mobile-standards.md)).
