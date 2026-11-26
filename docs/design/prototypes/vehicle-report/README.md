# Vehicle Report: HTML/CSS design prototype

**Status:** visual design approved by the Owner on 18 Nov 2026, with the photo-fit
correction since applied. Not wired to the API. Integration is proposed in
[`integration-plan.md`](integration-plan.md) and awaits approval.
Nothing here changes routes, data models, permissions, report signing, email
delivery or provider controls.

## What this is

A reusable HTML/CSS template for the Driveway **Vehicle Report** PDF, rendered
with WeasyPrint 70.0. It replaces the hand-drawn PDF operators in
`apps/api/mykhaya/vehicle_report_pdf.py`, which caused the rejected output:
Helvetica Type 1 text with no font metrics (overlapping header text), no layout
engine (no keep-together, no tables), and `{:,}` applied to the year ("2,018").

| File | Purpose |
|---|---|
| `vehicle-report.html.j2` | Jinja2 template (autoescaped). One template, two formats (`full`, `essential`), two sources (`saved`, `lookup`). |
| `vehicle-report.css` | A4 print stylesheet. Colours are `packages/design-tokens` values; fonts are the self-hosted brand faces. |
| `render.py` | The view model (`build_context`) holds all formatting rules, plus a QA renderer that writes HTML, PDF and per-page PNGs. |
| `scenarios.py` | Eight synthetic scenarios in the real `VehicleResponse` / `VehicleMotResponse` payload shape, including portrait and square photos. |
| `renderer.Dockerfile` | QA renderer on the API's runtime base image (`python:3.13.5-slim-bookworm`). |
| `integration-plan.md` | Dependency and security assessment, plus the integration plan. |

## Rendering locally

```sh
docker build -t mykhaya-report-proto:qa - < docs/design/prototypes/vehicle-report/renderer.Dockerfile
docker run --rm --network none -e SOURCE_DATE_EPOCH=0 \
  -v "$PWD/docs/design/prototypes/vehicle-report:/proto:ro" \
  -v "$PWD/apps/web/public:/brand:ro" \
  -v "<photo folder>:/photos:ro" \
  -v "<output folder>:/out" \
  -w /proto mykhaya-report-proto:qa python render.py /out
```

`--network none` is deliberate: it proves the template loads nothing external.
`SOURCE_DATE_EPOCH` makes the output byte-for-byte reproducible.
Sample vehicle photos are never stored in this public repository. Mount a folder
containing `sample-vehicle-photo.jpg` (plus `-portrait` and `-square` variants)
at `/photos`, or omit it to render the no-photo state.

## Design decisions

- **Page 1 of both formats follows the approved mockups.** The order is masthead, hero (photo, name, plate, chip), then
  *Vehicle details* beside *Tax and status* with the VED highlight. The Full
  report continues with *MOT summary* beside *Additional vehicle details* and a
  data-sources band. The Essential report continues with a wide *MOT history* card,
  two-column additional details and a privacy-and-disclaimer band.
- **The Full report flows; it doesn't force pages.** The complete MOT history follows page 1,
  then the VED explainer and the closing disclaimer. Content flows naturally,
  with no forced page breaks, so no page holds only a stray section. The history
  heading stays with its first test, and the explainer stays with the disclaimer.
- **The Essential report is always one page** (bounded content: three most recent tests).
- **Missing data collapses calmly.** Rows without values are omitted, and
  empty cards show a short, plain sentence. The report never shows "Unknown".
- **Numbers:** years have no separator, mileage is `30,599 mi`, engine capacity is
  `1596 cc` (as in the mockup), money is `£200` or `£17.50`, and dates are `14 Mar 2027`.
  First registration respects its stored precision (`Mar 2021`).
- **Running header on pages 2+:** brand, title, plate and vehicle name. The footer
  shows the generated date, `Page X of Y` (Full only) and `mykhaya.app`.
- **Wording:** every document is a *Vehicle Report*. There are no sale or buyer references.
- **Photos are never cropped.** The whole photograph is fitted inside the rounded frame
  (`object-fit: contain`) at its own aspect ratio, centred. Any unused space
  shows the same sand surface as the no-photo state. Landscape, portrait and square
  photos are covered by fixtures 01, 04, 07 and 08.
- **No-photo state** reuses the Driveway UI pattern: a sand tile with the lucide
  car icon.
- **Payment options** use the approved mockup's labels: "Monthly (12 payments)" and
  "6-monthly (2 payments)".

## Integration

See [`integration-plan.md`](integration-plan.md) for the dependency and
security assessment, what stays unchanged, the implementation steps and the
decisions needed. The plan includes the separate VED six-month payment fix and
the open question on the saved-vehicle nickname and photo.
