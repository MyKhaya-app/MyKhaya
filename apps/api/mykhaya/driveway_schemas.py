"""Pydantic contracts for the Driveway vehicle-management module.

Phase 2 core vehicle model only — no documents/service/insurance/compliance
fields yet (later phases), no official-lookup provider state (Phase 5).
"""

import uuid
from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, Field

from mykhaya.models import ReminderCadence, ReminderRepeat
from mykhaya.schemas import StrictModel


class VehicleCreate(StrictModel):
    nickname: str = Field(min_length=1, max_length=120)
    owner_user_id: uuid.UUID
    make: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=80)
    colour: str | None = Field(default=None, max_length=40)
    year: int | None = Field(default=None, ge=1900, le=2200)
    fuel_type: str | None = Field(default=None, max_length=30)
    engine_size: str | None = Field(default=None, max_length=20)
    # ISO 3166-1 alpha-2 — the source of truth for which official lookup
    # provider (if any) applies. Always uppercase; a country with no
    # provider integration still works through manual entry.
    country_code: str = Field(min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")
    registration: str | None = Field(default=None, max_length=20)
    first_registration_date: date | None = None
    # Sensitive — see Vehicle's model docstring. Never echoed into audit
    # metadata or logs (routers.driveway strips it before calling audit()).
    vin: str | None = Field(default=None, max_length=32)


class VehicleUpdate(VehicleCreate):
    expected_updated_at: datetime


class VehicleResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    owner_user_id: uuid.UUID
    nickname: str
    make: str | None
    model: str | None
    colour: str | None
    year: int | None
    fuel_type: str | None
    engine_size: str | None
    country_code: str
    registration: str | None
    first_registration_date: date | None
    tax_status: str | None
    tax_due_date: date | None
    inspection_status: str | None
    inspection_due_date: date | None
    photo_version: str | None
    # Omitted (not just null) for a viewer who isn't the vehicle's own owner
    # or a home_admin — see routers.driveway._vehicle_response.
    vin: str | None = None
    archived: bool
    created_at: datetime
    updated_at: datetime


class VehicleListResponse(BaseModel):
    items: list[VehicleResponse]


class VehicleLookupRequest(StrictModel):
    country_code: str = Field(min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")
    registration: str = Field(min_length=2, max_length=20)


class VehicleLookupResult(BaseModel):
    found: bool
    manual_entry_required: bool = False
    provider: str | None = None
    registration: str | None = None
    make: str | None = None
    model: str | None = None
    colour: str | None = None
    year: int | None = None
    fuel_type: str | None = None
    engine_size: str | None = None
    first_registration_date: date | None = None
    tax_status: str | None = None
    tax_due_date: date | None = None
    inspection_status: str | None = None
    inspection_due_date: date | None = None
    capabilities: list[str] = []
    message: str | None = None


class VehicleReminderCreate(StrictModel):
    """A manual Driveway reminder linked to one vehicle (Phase 4).

    Scope and category are deliberately absent — a Driveway-created
    reminder always inherits the vehicle's own scope and always uses the
    managed "Vehicles" category (see mykhaya.driveway_reminders); the user
    is not asked to choose either in this phase. source_event is always
    "manual" for a reminder created through this route — structured event
    types are written only by a future upsert_driveway_reminder caller,
    never by direct user input.
    """

    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    due_date: date
    due_time: time = time(9, 0)
    repeat: ReminderRepeat = ReminderRepeat.never
    cadence: ReminderCadence = ReminderCadence.once


# --- MOT (Driveway MOT Phase 1) --------------------------------------------------
# Provider-neutral: the frontend never sees DVSA response structures or
# terminology beyond these normalised values.


class VehicleMotDefectResponse(BaseModel):
    text: str
    # dangerous | major | minor | advisory | prs | fail | user_entered | other
    category: str
    dangerous: bool


class VehicleMotTestResponse(BaseModel):
    id: uuid.UUID
    test_number: str | None
    test_date: date
    completed_at: datetime | None
    expiry_date: date | None
    # passed | failed | other
    result: str
    odometer_value: int | None
    # mi | km
    odometer_unit: str | None
    # read | no_odometer | unreadable | other
    odometer_result: str | None
    defects: list[VehicleMotDefectResponse]


class VehicleMotSummaryResponse(BaseModel):
    # valid | expired | not_yet_due | no_record | None (never checked)
    status: str | None
    due_date: date | None
    expiry_date: date | None
    first_mot_due_date: date | None
    last_test_date: date | None
    last_result: str | None
    source: str | None
    refreshed_at: datetime | None
    stale: bool
    last_attempt_at: datetime | None
    last_attempt_outcome: str | None


class VehicleMotRefreshResult(BaseModel):
    # refreshed | not_found | cached | busy | rate_limited | auth_failed |
    # unavailable | malformed
    outcome: str
    message: str | None = None


class VehicleMotResponse(BaseModel):
    eligible: bool
    provider_available: bool
    has_registration: bool
    summary: VehicleMotSummaryResponse
    tests: list[VehicleMotTestResponse]
    refresh: VehicleMotRefreshResult | None = None


class VehicleMotRefreshRequest(StrictModel):
    # force: an explicit user refresh (short server-side cooldown applies).
    # if_stale: the detail page's automatic check — no provider call while
    # the persisted data is still fresh.
    mode: Literal["if_stale", "force"] = "force"


# --- MOT nudges (see mykhaya.driveway_mot_nudges) ------------------------------------

MotNudgeOffset = Literal[30, 14, 7, 0]


class VehicleMotNudgePlanRequest(StrictModel):
    """The owner's MOT nudge plan. Recipients are deliberately absent: MOT
    nudges always go to the vehicle owner, like every Driveway reminder."""

    title: str = Field(min_length=1, max_length=160)
    due_date: date
    offsets: list[MotNudgeOffset] = Field(min_length=1, max_length=4)
    repeat: bool = True


class VehicleMotNudgePlanResponse(BaseModel):
    title: str
    due_date: date
    offsets: list[int]
    repeat: bool
    # Reminder dates that exist for this plan (lead days already in the past
    # are skipped), earliest first.
    scheduled: list[date]


class VehicleMotNudgesResponse(BaseModel):
    plan: VehicleMotNudgePlanResponse | None
