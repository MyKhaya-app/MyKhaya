# Driveway Providers: DVLA and DVSA

Driveway uses two complementary UK government providers. Both are disabled by
default, both keep credentials in deployment configuration only, and neither
overwrites data the other owns.

| | DVLA Vehicle Enquiry Service | DVSA MOT History API |
|---|---|---|
| Purpose | Vehicle details and tax (Add Vehicle lookup) | MOT status and test history |
| Owns | `tax_status`, `tax_due_date` (and suggested make/model/colour on Add Vehicle) | `inspection_status`, `inspection_due_date`, `mot_*` columns, `vehicle_mot_tests`, `vehicle_mot_defects` |
| Input | The registration the user types on Add Vehicle | A **stored** vehicle's registration, read through `registration_for_provider` |
| Config | `MYKHAYA_DVLA_*`; see [deployment.md](deployment.md#driveway--dvla-integration-uat) | `MYKHAYA_DVSA_*` (below) |
| PCC toggle | `driveway_dvla_enabled` | `driveway_dvsa_enabled` ("DVSA MOT history checks") |

DVSA is authoritative for MOT data for GB vehicles once enabled and successfully
refreshed. Nothing a user submits writes the MOT columns.

## DVSA MOT History API

### Authentication (confirmed against the official documentation)

Source: <https://documentation.history.mot.api.gov.uk/> (Authentication, Rate limits
and Error codes pages, checked 12 October 2026).

- OAuth 2.0 **client credentials** issued by **Microsoft Entra ID**. The client sends a
  form-encoded `POST` of `grant_type=client_credentials`, `client_id`,
  `client_secret` and `scope` to the **token URL from the DVSA credentials email**.
  That URL has the form `https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token`.
- Scope: `https://tapi.dvsa.gov.uk/.default`.
- Every API request sends `Authorization: Bearer <access token>` **and**
  `X-API-Key: <api key>`.
- Access tokens last 60 minutes. MyKhaya caches one per process and refreshes it two
  minutes early. On a rejected or expired token (`MOTH-FB-02`), it refreshes once and
  retries.
- Client secrets expire every **2 years**. An API key unused for **90 days** is
  revoked by DVSA.

### Endpoint

- Base URL: `https://history.mot.api.gov.uk/v1/trade/vehicles`
- Lookup: `GET {base}/registration/{VRM}`. The VRM is upper-case with no spaces.
  Anything outside `[A-Z0-9]` is rejected before any request is made.

DVSA does not document a separate sandbox base URL. Credentials are issued per
registration. `MYKHAYA_DVSA_ENVIRONMENT` is therefore a label shown in PCC, telling
operators which credential set is installed. It never changes the host that is called.

### Rate limits (DVSA)

15 requests/second average, burst 10, 500,000 requests/day. Exceeding a limit returns
`429` (`MOTH-RL-01` daily, `MOTH-RL-02` short-term), and exceeding the daily quota
restricts the key for 24 hours. MyKhaya never retries a `429`. It also limits each
user to `MYKHAYA_DVSA_REFRESH_RATE_LIMIT` refreshes per hour (default 30), and never
calls DVSA just because a page was opened while the stored data is fresh.

### Configuration

| Variable | Default | Notes |
|---|---|---|
| `MYKHAYA_DVSA_ENABLED` | `false` | Deployment kill switch |
| `MYKHAYA_DVSA_ENVIRONMENT` | unset | `development` / `production`; PCC label only |
| `MYKHAYA_DVSA_TOKEN_URL` | unset | From the DVSA email; must be `https://login.microsoftonline.com/…` |
| `MYKHAYA_DVSA_CLIENT_ID` | unset | Secret |
| `MYKHAYA_DVSA_CLIENT_SECRET` | unset | Secret; rotate before the 2-year expiry |
| `MYKHAYA_DVSA_API_KEY` | unset | Secret |
| `MYKHAYA_DVSA_SCOPE` | `https://tapi.dvsa.gov.uk/.default` | |
| `MYKHAYA_DVSA_API_BASE_URL` | `https://history.mot.api.gov.uk/v1/trade/vehicles` | Must be `https://*.api.gov.uk` |
| `MYKHAYA_DVSA_TIMEOUT_SECONDS` | `10` | Per request |
| `MYKHAYA_DVSA_REFRESH_HOURS` | `24` | How long stored MOT data counts as fresh |
| `MYKHAYA_DVSA_REFRESH_RATE_LIMIT` | `30` | Refreshes per user per hour |

The provider runs only when **all** of these hold: `MYKHAYA_DVSA_ENABLED=true`, every
credential is set, and the PCC setting "DVSA MOT history checks" is on. Credentials
are never stored in the database, returned by any API, shown in PCC, logged or
included in audit records. PCC shows only enabled/disabled state, "Configured / Not
configured", the environment label, health, the last success time and the last
failure *category*.

### Eligibility

GB vehicles only (`country_code = "GB"`). Every other country refuses with a clear
message and never contacts DVSA. **Northern Ireland:** DVSA's bulk data includes DVA
NI tests (`dataSource: "dva ni"`), but live-API coverage and field completeness for NI
vehicles have not been confirmed with real credentials. The parser tolerates missing
optional fields, but NI behaviour must be verified during DEV commissioning before it
is relied on.

### Refresh behaviour and caching

- `GET /homes/{home}/vehicles/{vehicle}/mot` returns stored data only and **never**
  calls DVSA.
- `POST …/mot/refresh` operates on the **stored** vehicle only. There is no way to
  look up an arbitrary registration. The sequence is:
  1. Home authorization;
  2. eligibility check;
  3. registration read through `registration_for_provider` (ciphertext-first when
     Phase 2D reads are on);
  4. provider-availability check;
  5. freshness rules;
  6. a per-vehicle Redis lock (concurrent viewers never cause concurrent DVSA calls);
  7. the DVSA call, with **no database transaction held open**;
  8. one transaction that re-checks the registration, replaces the history, updates
     the summary, syncs the reminder and writes the audit record.
- `mode=if_stale` (sent automatically by the vehicle page): no DVSA call while the data
  is younger than `MYKHAYA_DVSA_REFRESH_HOURS`, or within 15 minutes of a failed
  attempt.
- `mode=force` (the Refresh button): bypasses staleness, but not a 60-second
  per-vehicle cooldown or the per-user rate limit.
- **Retries:** timeouts, connection errors and `5xx` are retried once. `429`, auth
  failures, not-found and other `4xx` responses are never retried.
- **Registration changes:** if a vehicle's registration changes, or it moves out of
  GB, its stored MOT history is cleared, because it described the old registration.
- **Background refresh:** there is none in Phase 1. The service is designed so a
  later scheduler can refresh stale GB vehicles, but it should be added only with a
  documented request budget against DVSA's limits.

### Data mapping (DVSA → MyKhaya)

| DVSA | MyKhaya |
|---|---|
| `motTests[].completedDate` (ISO or `YYYY.MM.DD HH:MM:SS`) | `completed_at`, `test_date` |
| `motTests[].testResult` `PASSED` / `FAILED` | `result` `passed` / `failed` (anything else `other`) |
| `motTests[].expiryDate` | `expiry_date` |
| `motTests[].odometerValue` / `odometerUnit` / `odometerResultType` | `odometer_value` (int), `odometer_unit` `mi`/`km`, `odometer_result` `read`/`no_odometer`/`unreadable` |
| `motTests[].motTestNumber` | `test_number` |
| `defects[].type` `DANGEROUS`/`MAJOR`/`MINOR`/`ADVISORY`/`PRS` (legacy `FAIL`, `USER ENTERED`) | `category` `dangerous`/`major`/`minor`/`advisory`/`prs`/`fail`/`user_entered` |
| `defects[].dangerous`, `defects[].text` | `dangerous`, `text` |
| `motTestDueDate` (vehicles not yet tested) | `mot_first_due_date` |

Not stored: the registration, make, model, colour, fuel, recall flag and any raw
payload.

The summary status is computed from history:
- **`valid`:** some passed test expires today or later. The latest passed expiry is
  used, so a later fail does not cancel it.
- **`expired`:** no passed test is still in date.
- **`not_yet_due`:** no tests yet, and the first MOT is due in the future.
- **`no_record`:** DVSA has no record for this registration.

`inspection_due_date` holds the expiry, or the first-due date for a vehicle not yet
tested.

### Reminders

A successful refresh keeps **one** managed reminder per vehicle (Driveway
`source_event=inspection`, owned by the vehicle owner) on the MOT due date. It is
titled "MOT due", or "First MOT due" for a vehicle not yet tested. Repeated refreshes
update the same reminder and never create duplicates. If the date changes, the
reminder moves. If DVSA returns no date, the existing reminder is left as it is,
matching existing Driveway reminder conventions. Manual reminders are never touched.

#### MOT nudge plan

"Set MOT reminder" (vehicle page and MOT history) opens a pre-filled Nudges form
that saves the owner's **MOT nudge plan** (`PUT …/vehicles/{vehicle}/mot/nudges`,
stored in `vehicles.mot_nudge_plan`; see `mykhaya/driveway_mot_nudges.py`):

- The owner picks any of 30, 14 or 7 days before, or on the day. Each choice is an
  ordinary Nudges reminder (`source_event=inspection_lead_<days>`), so it shows in
  Nudges like any other reminder. Lead days already in the past are skipped.
- While a plan exists it replaces the automatic "MOT due" reminder.
- **Recipients are always the vehicle owner.** The form shows the owner only and
  the API accepts no recipient field, matching the vehicle-reminder privacy rule
  (owner or Home Admin can view or save a plan; anyone else gets 404).
- "Repeat every year" on: after the next pass moves the expiry, the next refresh
  re-dates the same reminders. Off: the plan is used up by the next pass, its
  reminders stay where they were, and the automatic "MOT due" reminder resumes.
- Saving is audited as `driveway.vehicle.mot_nudges_saved` with the chosen days and
  the repeat flag only. The title and registration are not audited.
- Home Migration carries the plan with the vehicle (it is user intent, not provider
  cache). Imported Driveway reminders are re-linked to the imported vehicle
  (`reminders.source_id` is not a foreign key, so the importer remaps it).
- **Deleting from Nudges** keeps the plan in step, so an MOT refresh never brings
  a deleted nudge back:
  - "Remove this reminder" (or any delete of one plan nudge) drops that lead day
    from the plan. Deleting the last one turns MOT nudges off.
  - "Remove MOT reminder plan" (`DELETE …/vehicles/{vehicle}/mot/nudges`, audited
    as `driveway.vehicle.mot_nudges_removed`) deletes the plan and every MOT
    reminder for the vehicle, and stores `{"off": true}`. Refreshes then create
    nothing, not even the automatic "MOT due" reminder, until a new plan is saved.
- Editing a plan nudge in Nudges opens this pre-filled screen (`?from=nudges`).

#### The Driveway category in Nudges

Every Home has a fixed system Nudges category, **Driveway**
(`todo_categories.managed_source = 'driveway'`). It is seeded when a Home is created,
and by migration `0118_driveway_nudge_category` for existing Homes; the migration
also renames the old "Vehicles" category or adopts a Home's own "Driveway" one.

- Every Driveway-sourced reminder (`reminders.source_type = 'driveway'`: plan
  nudges, the automatic "MOT due" reminder, future tax/service/insurance ones) is
  filed in it when created, and stays there when edited.
- It can't be renamed or deleted, and it can't be picked by hand for an ordinary
  routine, reminder or to-do. The API exposes it as `category.system = "driveway"`.
- Nudges shows it, with a car icon, only once it holds something. Its cards read
  "Reminder · Driveway · BMW i4 (AP22 OOJ) · 26 Jul 2027", with the vehicle
  linking to its page.
- One-off reminders report their own due date as their next date however far
  ahead it is. Nudges lists anything more than 60 days out in a collapsed "Later"
  section, which opens automatically when you search.

### Failure modes

| Situation | Behaviour |
|---|---|
| Disabled, unconfigured or PCC toggle off | Refresh returns 503 "MOT checks aren't available right now."; the card says so and hides Refresh |
| Non-GB vehicle / no registration | 409 with a clear message; no provider call |
| Vehicle not found (`404`, `MOTH-NF-01`, `MOTH-IV-03`) | Status `no_record`; old history cleared; "We couldn't find an MOT record for this registration." |
| Auth failure (`401`/`403`, token endpoint rejection) | Stored data kept; generic message; PCC health records `auth_failed` |
| Rate limited (`429`, `MOTH-RL-*`) | Stored data kept; "MOT checks are busy right now…"; PCC records `rate_limited` |
| Timeout / `5xx` | One retry, then stored data kept; PCC records `unavailable` |
| Malformed response | Stored data kept; PCC records `malformed` |
| Database failure while saving | Whole transaction rolled back; previous history intact; lock released |

Logs carry only `provider=dvsa`, `operation=mot_refresh`, `outcome`, `duration_ms` and
`test_count`. Audit (`driveway.vehicle.mot_refreshed`) records the outcome, test count
and mode. Neither ever contains the registration, VIN, ciphertext, credentials, tokens
or defect text.

### Home Migration

MOT history tables and the derived MOT columns are not carried in packages. An
imported vehicle starts "not yet checked" and refreshes in the target environment.

## Rollout

**DEV commissioning** (not yet done; needs DEV credentials):

1. Put the DEV credential set in the DEV `.env` (`MYKHAYA_DVSA_TOKEN_URL`,
   `_CLIENT_ID`, `_CLIENT_SECRET`, `_API_KEY`, `MYKHAYA_DVSA_ENVIRONMENT=development`)
   and set `MYKHAYA_DVSA_ENABLED=true`. Restart api, worker and scheduler through
   `dev-deploy.sh`.
2. In PCC → Settings → Driveway integrations, confirm "Credentials: Configured", turn
   on "DVSA MOT history checks", and run "Test DVSA connection" with a test
   registration.
3. Use a documented DVSA test registration if DVSA provides one; otherwise a vehicle
   you own.
4. Confirm the normalised MOT response.
5. Save a test vehicle and press Refresh.
6. Verify the MOT card, the MOT history page and the managed "MOT due" reminder.
7. Confirm, by searching the logs for the test registration, that no registration or
   credential appears.
8. Verify a Northern Ireland vehicle if available.

**Production** requires the production credential set, a security review of this
integration, physical-phone review of the MOT UI (iPhone and Android), and the
existing production gates. Do not enable it in production until those are recorded.
