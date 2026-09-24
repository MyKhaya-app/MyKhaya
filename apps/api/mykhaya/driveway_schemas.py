"""Pydantic contracts for the Driveway vehicle-management module.

Phase 2 core vehicle model only — no documents/service/insurance/compliance
fields yet (later phases), no official-lookup provider state (Phase 5).
"""

import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, Field

from mykhaya.models import ReminderCadence, ReminderRepeat, RoutineScope
from mykhaya.schemas import StrictModel


class VehicleCreate(StrictModel):
    nickname: str = Field(min_length=1, max_length=120)
    scope: RoutineScope = RoutineScope.household
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
    scope: RoutineScope
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
    # Omitted (not just null) for a viewer who isn't the vehicle's own owner
    # or a home_admin — see routers.driveway._vehicle_response.
    vin: str | None = None
    archived: bool
    created_at: datetime
    updated_at: datetime


class VehicleListResponse(BaseModel):
    items: list[VehicleResponse]


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
