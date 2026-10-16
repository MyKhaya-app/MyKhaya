# Managed Demo & Test Homes

Managed Demo/Test Homes are explicit PCC-managed non-customer environments for
Apple review, demos, QA/UAT and training. PCC operators find them at
`Operations → Demo & Test Homes`. Mutations use the existing PCC operator boundary
(`PlatformRole.owner`/`administrator`), MFA-complete sessions, recent-auth checks,
CSRF protection and platform audit logging; the project has no separate granular
PCC permission registry, so introducing `demo_test_homes.manage` would otherwise
create a parallel authorization model.

The `managed_demo_homes` record is authoritative for fixture ownership and the
stable `fixture_key`; Home names and emails are display data only. Apple Review is
registered as `apple-review` and uses the existing complimentary Family
subscription path with reason `Apple TestFlight review fixture`. It creates no
Stripe subscription. The managed record and subscription are scoped to the same
Home and are removed together by the managed delete path.

Supported types are `apple_review`, `demo` (Family Demo), `ultimate_demo`,
`qa_test`, and `free_demo`. PCC offers Apple Review, Family Demo, Ultimate Demo
and Free Plan Demo for new Homes. QA Test stays supported for existing fixtures.
Apple Review currently uses the existing canonical sample content. The PCC create
endpoint provisions a verified normal Home Admin account and Home;
template-specific content should be seeded by the corresponding managed
template before external review.

`apple_review`, `demo` and `qa_test` all resolve to a complimentary Family
subscription. `ultimate_demo` resolves to a complimentary Ultimate subscription.
`free_demo` ("Free Plan Demo") resolves
to the real Free plan through the normal subscription/entitlement path (see
`ManagedDemoService.create`), a single-person Home with exactly one Personal
Calendar and exactly two Lists (the Free plan's `lists.max_lists` limit) — a
fixture for validating the actual Free product experience, not a Family demo
with Free-looking data. `ManagedDemoHomeResponse.access` reflects whichever
plan a given fixture actually resolved to ("family", "ultimate" or "free"),
not a hardcoded value. None of these subscriptions involve Stripe.

## Showcase Demo Homes (Family Demo and Ultimate Demo)

Family Demo and Ultimate Demo are showcase Homes for App Store and Google Play
screenshots, the marketing site and product demos. They're populated with
**the Parker family**, a fictional household seeded by `mykhaya.showcase`:

- **Members:** Emma (the sign-in account), James, Sophie and Oliver.
- **Calendar:** around 40 events with categories, repeating series and birthdays.
- **Nudges:** routines, reminders and to-dos with completed, due, upcoming and
  overdue items.
- **Meals:** 20 recipes with images, ingredients and steps, plus a two-week meal
  plan.
- **Lists and Wishlists.**
- **Emma's Calendar and notification preferences.**

Ultimate Demo adds Budget and Driveway on top of the same dataset:

- **Budget:** previous, current and next month, with about 90–120 transactions.
- **Driveway:** three vehicles with linked reminders.

**How modules are chosen.** Seeding uses the plan the Home actually resolves
to. A module is seeded only when that plan grants its entitlement (see
`mykhaya.showcase.registry`), so Ultimate-only data can never appear in a
Family Home. To add showcase content for a newly released module, add one
`ShowcaseModule` entry with its entitlement key.

**Dates.** All content is relative to a reference date, so cross-module stories
stay consistent. For example, Sophie's birthday is on the calendar, on her
wishlist, in a "Buy birthday present" reminder, in the meal plan, and in Budget
spending. There are two modes:

- **Rolling** (default): dates are relative to the day the Home was seeded or
  reset.
- **Pinned** (screenshot mode): dates are relative to a chosen reference date.
  Resetting with the same date reproduces the same content, so capture sessions
  match.

**Create options.** "Populate with showcase data" is on by default. Turn it off
to get a clean Home on the same plan for engineering tests.

**Reset Showcase Data.** Available on a showcase Home's PCC page.

- **Who:** owners and administrators, with a recent re-authentication, a
  reason and a destructive-action confirmation. The action is platform-audited
  as `managed_demo.showcase_reset`, including failed attempts.
- **What it replaces:** the Home's content, its fixture members and their
  images, and Emma's Budget and preferences. It restores the curated (or clean)
  state in one transaction.
- **What it keeps:** the Home, the managed record, the owner account, its
  password and sessions, the subscription, module overrides and the MFA policy.
- **Where it's allowed:** the server refuses the reset for anything that isn't
  a registered showcase fixture. That includes Apple Review, Free Plan Demo and
  every ordinary customer Home.
- **Refusal:** if the owner account belongs to another Home, the reset is
  refused rather than touching personal data outside the fixture.

**Safety.**

- Only Emma has credentials.
- Children have no sign-in.
- Member emails use reserved domains that can never deliver: `example.com`
  for adults and `managed.mykhaya.invalid` for children.
- Email notifications stay off.
- Registrations use the "Z" area letter, which the DVLA doesn't issue as a
  current-format memory tag.
- Tax and MOT status are seeded locally and are never shown as a DVLA or DVSA
  result.
- The server refuses DVSA MOT refreshes and DVLA lookups for every showcase
  Home (`mykhaya.showcase.guards`).

**Images.** Recipe, vehicle and profile images are original illustrations
rendered by `mykhaya.showcase.images`. They're stored through the normal
avatar, meal-image and vehicle-photo pipelines, never as external URLs. To use
licensed photography instead, follow `apps/api/mykhaya/showcase/assets/README.md`.

PCC's global module flags stay authoritative. If Calendar, Meals, Budget or
Driveway is disabled platform-wide, the data is seeded but the module stays
hidden until it's enabled.

Expiry is processed by the existing scheduler: it marks the managed record
`expired`, disables only its owner account, and retains Home data and audit history.
It is idempotent. Refreshes must not reactivate an expired/disabled account unless
an operator explicitly enables it.

The fixture is opt-in and is never created during application startup or a migration.
Run it against the intended review environment from the API container:

```text
MYKHAYA_APPLE_REVIEW_PASSWORD='use-a-secret-manager-value' \
  python -m mykhaya.apple_review_fixture create
```

The same command is safe to repeat and refreshes the fixture's relative dates and
sample records. `refresh` is an explicit alias. The account is
`apple-review@mykhaya.app`; the password is only the value supplied through
`MYKHAYA_APPLE_REVIEW_PASSWORD` and is not documented or logged by the command.

To remove it, run:

```text
python -m mykhaya.apple_review_fixture remove
```

Removal is guarded by the stable fixture Home marker and the owner email. It does
not remove a Home with an unrelated marker/name, and it removes fixture users only
when they have no remaining memberships. The review account is a normal Home Admin
(`Role.owner`/`PermissionProfile.home_admin`), not a platform administrator.
Email verification is explicitly satisfied on this fixture user; global email
verification settings are unchanged. No password, token, or bypass is included in
this document. Enter the email and the operator-managed password in App Store
Connect's review information.
