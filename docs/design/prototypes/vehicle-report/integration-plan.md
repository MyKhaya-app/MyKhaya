# Vehicle Report: dependency assessment and integration plan

- **Status:** approved with the Owner's decisions in section 4, and implemented on
  `dev` (uncommitted); see section 5.
- **Date:** 18 Nov 2026
- **Scope:** replace the hand-drawn PDF generator behind the existing Vehicle
  Report endpoints with the approved HTML/CSS template (this folder),
  rendered by WeasyPrint.

## 1. Dependency assessment

### What is added

| Component | Version | Licence | Why |
|---|---|---|---|
| `weasyprint` | 70.0 (8 Sep 2026) | BSD-3-Clause | HTML/CSS to PDF layout engine |
| `jinja2` | 3.1.6 | BSD-3-Clause | Autoescaped HTML templating |
| `markupsafe` | 3.0.x | BSD-3-Clause | Jinja2 escaping |
| `pydyf`, `tinycss2`, `cssselect2`, `tinyhtml5`, `pyphen`, `webencodings`, `cffi`, `pycparser` | Pulled in by WeasyPrint | BSD / MIT / LGPL-2.1+ (pyphen dictionaries are MPL/LGPL) | PDF writer, CSS/HTML parsing, hyphenation, FFI |
| `fonttools` | 4.6x | MIT | Font subsetting (WeasyPrint dependency) |
| `pillow` | Already a dependency | | Image decoding |
| `libpango-1.0-0`, `libpangoft2-1.0-0`, `libharfbuzz-subset0` (Debian bookworm) | 1.50.12, 6.0.0 | LGPL / MIT | Text shaping and layout |

`brotli` isn't needed: the woff2 brand fonts embed correctly without it
(verified with `pdffonts`).

| Measurement | Value |
|---|---|
| Runtime image size | +32 MB uncompressed (44 → 76 MB, measured on `python:3.13.5-slim-bookworm`) |
| Render time, 1 CPU | 0.23–0.79 s per report across the 8 fixtures |
| Peak memory | < 100 MB |
| Output size | 88–180 KiB (limit stays `vehicle_report_max_pdf_bytes`, 10 MiB) |

### Known advisories

| Advisory | Affects | Fixed in | Relevance to MyKhaya |
|---|---|---|---|
| CVE-2025-68616: SSRF bypass through HTTP redirects in the default fetcher | ≤ 67 | 68.0 | Not reachable: we never fetch over HTTP. Fixed by pinning 70.0. |
| CVE-2026-55073: `stylesheets=` / `xmp_metadata=` ignore a custom `url_fetcher` | ≤ 69 | 70.0 | Not reachable: we pass neither. Fixed by pinning 70.0. |
| CVE-2026-106443: image bytes reach Pillow's EPS plugin, which calls Ghostscript | ≤ 69 | 70.0 | Not reachable: no Ghostscript in the image, and photos are re-encoded WebP. Fixed by pinning 70.0. |
| CVE-2026-49452 (PYSEC-2026-3412): CSS injection through HTML presentational hints | ≤ 68.1 | 69.0 | Not reachable either way: needs `presentational_hints=True`, which we never set. Fixed by pinning 70.0. |

**Correction (18 Nov 2026).** The first version of this assessment said
PYSEC-2026-3412 had no fix and proposed a `pip-audit` exception. That was wrong.
The audit had been run against 66.0, and the OSV record gives
`last_affected: 68.1` with no explicit `fixed` event, which `pip-audit`
displays as an empty fix version. The Owner caught this. `pip-audit` against
`weasyprint==70.0` and `jinja2==3.1.6` reports **no known vulnerabilities**, so
no exception is needed and none was added.

### Security design for the renderer

- **No external resources:**
  `URLFetcher(allowed_protocols={"data"}, allow_redirects=False, fail_on_errors=True)`.
  `file:`, `http(s):` and redirects are refused, and a refused resource fails the
  render instead of being skipped. Verified: `file:///etc/passwd` and the cloud
  metadata address both raise `FatalURLFetchingError`. Fonts, logo and photo are
  embedded as `data:` URIs from files inside the image.
- **Trusted template, untrusted values:** Jinja2 autoescape is on. The only
  `Markup` value is a constant (the CO₂ label). Provider strings (DVSA defect
  text, DVLA fields) are always escaped. `presentational_hints` stays off, and a
  test asserts it.
- **Photo handling (saved vehicles only):** the photo is loaded through the existing
  `vehicle_photo_storage.load(photo_key)` after the existing `driveway_view`
  check. Uploads are already metadata-stripped WebP. Before embedding, the
  renderer re-opens the photo with Pillow, accepts only WebP, JPEG or PNG,
  downsizes it to at most 1200 px and re-encodes it as JPEG. A failure falls
  back to the no-photo placeholder rather than failing the report.
- **Resource use:** WeasyPrint is CPU-bound and synchronous. Rendering runs off the event
  loop (`anyio.to_thread.run_sync`) behind a process-wide limiter of 2
  concurrent renders. This avoids the stall that synchronous rendering would cause
  on the async API.
- **Reproducible output:** fontTools stamps the current time into embedded font
  subsets. With `SOURCE_DATE_EPOCH` set, identical input gives byte-identical
  PDFs (verified on all 8 fixtures). This preserves the existing email
  deduplication fallback (`sha256(pdf)` when no `Idempotency-Key` is sent).
- **Fonts:** no system fonts are installed. Every glyph must come from the brand
  fonts. A test asserts that `pdffonts`-equivalent output contains only Bricolage
  Grotesque and Figtree. This caught a real issue: "₂" would have printed as a
  missing-glyph box in production.

### Gaps found (not caused by this change)

- **No container image scanning:** the supply-chain policy calls for it, but CI
  runs `trivy fs` on the repository, not on the built API image. New OS libraries
  (Pango, HarfBuzz, FreeType) would not be scanned. Recommendation: add a
  `trivy image` job. This is a CI security-gate change, so it needs your approval.
- **No rate limit on PDF downloads:** the two `…/report/pdf` endpoints have none.
  Email has 3 per hour. Rendering now costs up to about 0.8 s of CPU, so I
  recommend a per-user limit (for example 30 per hour) using the existing
  `enforce_rate_limit`. This is a new user-visible limit, so it needs your approval.
- **Email render order:** the email path renders the PDF before checking the email rate
  limit. Moving the check ahead of rendering changes no rule, only the order.

## 2. What stays exactly as it is

- Routes, request and response shapes:
  `POST …/vehicles/{id}/report/pdf|email` and `POST …/vehicles/lookup/report/pdf|email`.
- `driveway_view` capability checks and Home-scoped vehicle lookup.
- HMAC-signed one-off lookup tokens (`_sign_lookup_report` and
  `_verify_lookup_report`), including expiry and user/Home binding.
- Email: verified-account-email-only recipient, 3-per-hour limit, size cap,
  idempotency, `notify()` as the only sender, `attachment_cleanup=True` and the
  worker's `vehicle_report` storage cleanup.
- Audit events (`driveway.vehicle.report.generated`, `driveway.lookup.report.generated`,
  `driveway.vehicle.report.email_queued`).
- `dvsa_arbitrary_lookup_enabled` defaults to `False` and isn't touched. Lookup
  reports show the "MOT history wasn't available" state.
- DEV/PROD separation: no new settings, secrets, hosts or environment-specific
  behaviour.
- VIN, owner details and internal IDs are never passed to the template, which
  receives the presenter's view model, not the raw payload.

## 3. Implementation steps (after approval)

Each step is a separate change on `dev`, with tests, committed only when you say so.

1. **VED six-month payment fix (separate change, before the report work).**
   In `driveway_tax.py`, the 2026–27 schedule values feed
   `six_month_direct_debit_payment = 110` and `six_month_single_payment = 105`,
   and `six_month_direct_debit_total` reuses the monthly total. Correct the field
   mapping, derive each total from its own payment (`payment × instalments`), and
   confirm every figure against GOV.UK's published 2026–27 rate tables before
   changing numbers. Tests: per-schedule unit tests asserting total = payment ×
   count for every option, plus regression tests pinning the published figures.
2. **Dependencies and image.**
   - Add `weasyprint>=70.0,<71` and `jinja2>=3.1.6,<4` to `apps/api/pyproject.toml`.
   - Add the three Pango/HarfBuzz packages to the runtime stage of `apps/api/Dockerfile`,
     and to the builder stage so the test image can render.
   - Copy the brand fonts and logo from `apps/web/public` into the image (copied, never fetched).
   - Set `ENV SOURCE_DATE_EPOCH=0`.
   - Record the pip-audit triage decision if you approve it.
3. **Renderer module.**
   - Move the template and CSS into `apps/api/mykhaya/report_templates/vehicle_report/`.
   - Port `build_context` as the presenter.
   - Keep `build_vehicle_report_pdf(vehicle, mot, format, generated_at)` as the entry
     point, adding `source` and an optional pre-validated `photo` argument.
   - Remove the hand-drawn PDF operator code. `sanitise_report_filename` is unchanged.
4. **Router wiring (no permission or flow changes).**
   - Saved reports pass `source="saved"` and the validated photo.
   - Lookup reports pass `source="lookup"` and no photo.
   - Rendering runs through the thread limiter.
   - Move the email rate-limit check ahead of rendering.
5. **Tests.**
   - Rewrite `apps/api/tests/test_vehicle_report_pdf.py` around the presenter and
     rendered HTML: content, sensitive-field exclusion, formatting rules (year,
     mileage, money, dates, precision), and Full/Essential/saved/lookup/sparse cases.
   - At the PDF level: page counts from `document.pages`, brand-only fonts,
     determinism, fetcher refusal, and that `presentational_hints` is off.
   - Keep the existing router tests for permissions, HMAC tokens, email restrictions
     and attachment cleanup, and run them unchanged.
6. **Verification.**
   - Full API suite in the CI-equivalent container.
   - Render the eight fixtures from the integrated code path and compare them with
     the approved previews.
   - Live DEV: download and email both formats for a saved vehicle and a one-off lookup.
   - Print one copy and open the email attachment on a phone.
   - Report results before any commit.

## 4. Owner decisions (18 Nov 2026)

1. **Approved:** WeasyPrint 70.0, Jinja2 3.1.6 and the Debian text-layout
   libraries, pinned, security-validated and rendered in isolation.
2. **No `pip-audit` exception.** Rechecked: 70.0 isn't affected (see the correction above).
3. **Approved:** 30 PDF downloads per authenticated user per hour, one budget
   across both report services and both formats. Email keeps its 3 per hour.
4. **Approved:** container-image vulnerability scanning in the `security`
   workflow, reporting findings without suppression.
5. **Approved:** the saved vehicle's photo and nickname in both formats, with
   the nickname clearly marked as user-entered and a way to leave both out of a
   report meant for sharing.

Outbound report email and external sharing of real provider data stay switched
off pending further approval. Arbitrary DVSA lookup stays disabled.

## 5. Implementation status (18 Nov 2026, uncommitted on `dev`)

- **VED fix (`driveway_tax.py`):** the 2026–27 six-month Direct Debit
  instalment is £105 (×2 = £210) and the single six-month payment is £110
  (×2 = £220), per DVLA V149 (rates from 1 April 2026). Each total is now derived
  from its own instalment. Every 2026–27 band and rate is pinned by regression
  tests in `tests/test_driveway_tax.py`.
- **Renderer:** `mykhaya/vehicle_report_pdf.py` plus
  `mykhaya/report_templates/`, ported from this prototype. It uses a data-only URL
  fetcher, autoescaping and `presentational_hints=False`. Photos are re-encoded
  as JPEG of at most 1200 px. Rendering runs on worker threads, at most two at a
  time.
- **Endpoints:** the 30-per-hour download budget is keyed on the user alone
  (`enforce_rate_limit(..., per_client=False)`).
- **Household details:** `include_household_details` (default `true`) on
  `VehicleReportRequest`. Nickname and photo appear only for saved vehicles when
  it is true. The nickname carries a "Nickname" label, and the disclaimer says
  that household-added details aren't provider data. The web report page has an
  "Include nickname and photo" checkbox.
- **Email:** `vehicle_report_email_enabled` (default `false`) refuses both
  email endpoints with 403 before anything is rendered. When enabled, the
  verified-email check and 3-per-hour limit also run before rendering.
- **Image:** Pango/HarfBuzz in the builder and runtime stages. Brand assets are
  copied from `apps/web/public`. `SOURCE_DATE_EPOCH=0` gives reproducible PDFs,
  and the fontconfig cache is on the `/tmp` tmpfs because the root filesystem is
  read-only.
- **CI:** a `container-image` job in `security.yml`, mirrored in `make security-check`.

## 6. Security remediation (18 Nov 2026)

- **API base image:** `python:3.13.5-slim-bookworm` → `python:3.13.18-slim-bookworm`.
  This is a CPython patch release on the same Debian 12. It clears every fixable
  Debian finding (OpenSSL, GnuTLS, Perl, SQLite, PCRE2, apt, gpgv, libcap2).
- **API runtime image:** no `pip`. Packages are installed only in the builder
  stage, and `pip`'s vendored libraries (`msgpack`, `urllib3` and a `setuptools`
  `pkg_resources` copy) were the last fixable findings.
- **Web runtime image:** no `npm`, `npx` or `corepack`. It runs only
  `node server.js`, and the bundled npm CLI carried every fixable finding. The
  Node base stays at `22.23.4-alpine3.24`, because `22.23.5` changes nothing in the scan.
- **Result:** no fixable HIGH or CRITICAL findings remain in either image.
  Findings with no released fix stay visible in the CI report artifacts.
- **Python 3.13.18 decodes base64 strictly.** That exposed a latent font-placeholder
  collision (`figtree_latin` was a prefix of `figtree_latin_ext`). Placeholders are
  now replaced as whole `url("FONT:…")` tokens, and a test strictly decodes every
  embedded font.
- **Text handling (HarfBuzz CVE-2023-25193):** the quadratic case needs long runs
  of stacked combining marks, so each run is capped at 4 marks after NFC
  normalisation, and legitimate text keeps its full content. Ordinary long text is
  linear (240,000 characters of defects render in about 6 s). Per-item ceilings are
  4,000 characters per MOT defect and 300 per field, ending with a visible "…
  [shortened from N characters]" marker when exceeded. A report-wide budget of
  150,000 characters of defect text applies: every test stays listed, and a test
  beyond the budget shows an explicit "reached its length limit" note instead of
  its details.
- **The new text-layout libraries' unfixed findings** (GLib, Expat, HarfBuzz)
  were assessed individually for the Owner. The assessment is held outside this
  public repository. None may reach production without explicit Owner approval.

## 7. Later enhancement: two-key enablement of report email and sharing

Out of scope for this release, which keeps the server-level
`vehicle_report_email_enabled` setting (default `false`) and needs no migration.

A later change should require **both** keys before report email or external
sharing works, so that neither can enable it alone:

1. **Environment approval:** a deployment setting (today's
   `vehicle_report_email_enabled`, plus an equivalent for sharing). It is set
   per environment, so DEV and PROD stay independent.
2. **PCC enablement:** a Platform Control Centre feature flag evaluated through
   `mykhaya.features.is_feature_enabled`, so it is audited, platform-wide and
   can be narrowed per Home. It needs a `FeatureKey` value, a migration and the
   module-registry entry.

The effective rule is `environment_approved AND pcc_enabled`. PCC can't switch
the feature on in an environment that hasn't approved it, and the environment
setting can't bypass PCC being off. The web app learns availability from the API
instead of a hard-coded constant. The recipient rule is unchanged: a report only
ever goes to the requesting user's own verified account email, never to an
address supplied in the request.

## 8. Decisions resolved (18 Nov 2026)

- **Report email and notification preferences.** "Email me" is a requested
  transactional email (`REQUESTED_EMAIL_TYPES`, see
  `docs/architecture/notification-engine.md`). It's delivered even with routine
  email off, but only to the user's own verified address, email-only, and still
  behind `vehicle_report_email_enabled` (off).
- **DVLA field precedence.** At creation, a value the user submitted (usually
  DVLA-prefilled, then corrected) wins, and DVLA and DVSA data only fill gaps. A
  refresh only fills gaps in general details and updates DVLA-owned fields such as
  tax. Manual edits survive. The model is never taken from DVLA unless DVLA
  returned one, and its vehicle enquiry service doesn't.

## 9. DEV configuration (fails closed)

DEV needs **no new variables**. These defaults apply when a variable is absent:

| Setting | Default | DEV |
|---|---|---|
| `MYKHAYA_VEHICLE_REPORT_EMAIL_ENABLED` | `false`: both email endpoints answer 403 before rendering | Leave unset |
| `MYKHAYA_DVSA_ARBITRARY_LOOKUP_ENABLED` | `false`: one-off lookups never call DVSA | Leave unset |
| `MYKHAYA_VEHICLE_REPORT_ASSETS_DIR` | `/opt/mykhaya/report-assets` (populated by the image build) | Leave unset |

If the brand assets are missing, report endpoints answer 503 ("Vehicle Reports are
temporarily unavailable") rather than rendering without them. The web app
disables "Email me" and "Share" independently of the API.
