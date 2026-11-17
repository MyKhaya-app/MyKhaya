# Driveway VED calculation feasibility

Status: assessed 17 November 2026. No VED calculator is implemented.

## Finding

The current DVLA Vehicle Enquiry Service response is sufficient to display
authoritative vehicle tax status, due date, vehicle status/SORN information,
CO₂ emissions and the additional-rate end date. It does not provide the full
tax-class/rate decision or the original list price needed to calculate every
vehicle's current VED reliably. The existing Tax tab therefore displays only
returned provider fields and links to GOV.UK for the payable amount.

## Rules reviewed

The current GOV.UK tables distinguish first-licence rates from subsequent rates,
use registration date and CO₂ bands, apply fuel/RDE2 differences, and include an
expensive-car supplement. The official 2026–27 tables also show that zero-emission
vehicles are no longer universally exempt. Rates and rules are time-versioned and
can change independently of an application release.

Sources:

- https://www.gov.uk/vehicle-tax-rate-tables
- https://www.gov.uk/guidance/vehicle-tax-for-electric-and-low-emissions-vehicles
- https://www.gov.uk/government/publications/rates-of-vehicle-tax-v149

## Feasibility boundary

An application calculator could be made reliable only with a versioned official
rate table and a clearly defined input contract covering at least registration
date, CO₂ measurement, fuel/RDE2 status, vehicle category/tax class, applicable
first/subsequent licence rules, and original list price where the expensive-car
supplement may apply. The current provider payload and vehicle model do not
contain all of those inputs, so a number calculated from the present fields could
be materially wrong. Any future calculator needs a separate design/security review,
rate-data update process, test fixtures per tax year, and explicit handling for
unknown inputs; it must never replace DVLA's live tax status or due date.

Tax reminders were also reviewed: the current Driveway reminder model and
automatic synchronisation are MOT-specific. No tax reminder is created by this
change. A future tax reminder would need an explicit product decision about
provider-owned due-date changes, stale data, user edits, duplicate suppression and
notification ownership before implementation.
