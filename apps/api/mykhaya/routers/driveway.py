"""Driveway — premium (Ultimate-only) vehicle management. Phase 2 shipped the
core vehicle model and basic CRUD; Phase 4 adds Nudges reminder integration
(see mykhaya.driveway_reminders) — still no documents/service/insurance/
compliance records or official-lookup provider integration (Phase 5+).

Reuses FeatureKey.driveway's module slot and the "driveway.enabled"
entitlement in mykhaya.entitlements.PLAN_DEFINITIONS (Ultimate only — see
docs/architecture/commercial-entitlements.md).

Permissions: `driveway_view`/`driveway_manage`, the same "view vs manage"
shape Lists/Meal Plans use for Household-scoped rows. A Personal-scoped
vehicle additionally requires the caller to be its own owner (or
home_admin) — mirroring routers.lists' list-template ownership check.

Sensitive fields (VIN) default to Personal visibility even on a
Household-scoped vehicle, per the Phase 1.5 decision: normal MyKhaya access
controls for now (no new encryption subsystem), but the value is never
serialised to a viewer who isn't the vehicle's own owner or a home_admin,
and never written into audit metadata or logs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.attachments.processing import (
    OUTPUT_CONTENT_TYPE,
    AttachmentResourceError,
    UnsupportedImageError,
    process_attachment_upload,
)
from mykhaya.audit import audit
from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.driveway_providers import (
    UKDVLAProvider,
    VehicleLookupNotFound,
    VehicleLookupUnavailable,
)
from mykhaya.driveway_reminders import (
    DrivewayReminderEventType,
    delete_reminders_for_vehicle,
    reminders_for_vehicle,
    sync_reminder_scope_to_vehicle,
    upsert_driveway_reminder,
)
from mykhaya.driveway_schemas import (
    VehicleCreate,
    VehicleListResponse,
    VehicleLookupRequest,
    VehicleLookupResult,
    VehicleReminderCreate,
    VehicleResponse,
    VehicleUpdate,
)
from mykhaya.entitlements import require_entitlement
from mykhaya.features import require_feature
from mykhaya.household_permissions import Capability, require_capability
from mykhaya.models import (
    FeatureKey,
    HouseholdRelationship,
    Membership,
    PlatformSetting,
    RoutineScope,
    Vehicle,
)
from mykhaya.rate_limit import enforce_rate_limit
from mykhaya.routers.reminders import _to_response as _reminder_response
from mykhaya.schemas import ReminderListResponse, ReminderResponse
from mykhaya.vehicle_photo_storage import get_vehicle_photo_storage, vehicle_photo_filename


async def _require_driveway(home_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    await require_feature(db, FeatureKey.driveway, home_id)
    await require_entitlement(db, home_id, "driveway.enabled")


router = APIRouter(prefix="/homes", tags=["driveway"], dependencies=[Depends(_require_driveway)])


def _may_see_sensitive_fields(vehicle: Vehicle, auth: AuthContext, membership: Membership) -> bool:
    if vehicle.owner_user_id == auth.user.id:
        return True
    return membership.relationship == HouseholdRelationship.home_admin


def _vehicle_response(vehicle: Vehicle, auth: AuthContext, membership: Membership) -> VehicleResponse:
    reveal_sensitive = _may_see_sensitive_fields(vehicle, auth, membership)
    return VehicleResponse(
        id=vehicle.id,
        group_id=vehicle.group_id,
        owner_user_id=vehicle.owner_user_id,
        scope=vehicle.scope,
        nickname=vehicle.nickname,
        make=vehicle.make,
        model=vehicle.model,
        colour=vehicle.colour,
        year=vehicle.year,
        fuel_type=vehicle.fuel_type,
        engine_size=vehicle.engine_size,
        country_code=vehicle.country_code,
        registration=vehicle.registration,
        first_registration_date=vehicle.first_registration_date,
        vin=vehicle.vin if reveal_sensitive else None,
        lookup_provider=vehicle.lookup_provider,
        lookup_status=vehicle.lookup_status,
        last_successful_lookup=vehicle.last_successful_lookup,
        tax_status=vehicle.tax_status,
        tax_due_date=vehicle.tax_due_date,
        inspection_status=vehicle.inspection_status,
        inspection_due_date=vehicle.inspection_due_date,
        photo_version=vehicle.photo_key,
        archived=vehicle.archived_at is not None,
        created_at=vehicle.created_at,
        updated_at=vehicle.updated_at,
    )


async def _get_vehicle(
    db: AsyncSession, home_id: uuid.UUID, vehicle_id: uuid.UUID, *, for_update: bool = False
) -> Vehicle:
    query = select(Vehicle).where(
        Vehicle.id == vehicle_id,
        Vehicle.group_id == home_id,
        Vehicle.archived_at.is_(None),
    )
    if for_update:
        query = query.with_for_update()
    row = await db.scalar(query)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That vehicle could not be found")
    return row


async def _record_lookup_health(db: AsyncSession, *, success: bool, summary: str) -> None:
    row = await db.scalar(
        select(PlatformSetting).where(PlatformSetting.key == "driveway_dvla_enabled").with_for_update()
    )
    if row is None:
        row = PlatformSetting(key="driveway_dvla_enabled", value={"value": True})
        db.add(row)
    health = dict(row.value.get("health") or {})
    health.update({"state": "Healthy" if success else "Degraded", "last_result": summary})
    row.value = {**row.value, "health": health}
    await db.commit()


async def _require_vehicle_owner_or_household_manage(
    db: AsyncSession, home_id: uuid.UUID, row: Vehicle, auth: AuthContext
) -> None:
    if row.scope == RoutineScope.personal and row.owner_user_id != auth.user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You do not have permission to edit that vehicle."
        )
    await require_capability(home_id, Capability.driveway_manage, auth, db)


def _audit_metadata(vehicle: Vehicle) -> dict[str, object]:
    """Never includes vin/registration — see module docstring."""
    return {"scope": vehicle.scope.value, "country_code": vehicle.country_code}


@router.get("/{home_id}/vehicles", response_model=VehicleListResponse)
async def list_vehicles(
    home_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> VehicleListResponse:
    membership = await require_capability(home_id, Capability.driveway_view, auth, db)
    filters = [Vehicle.group_id == home_id, Vehicle.archived_at.is_(None)]
    filters.append(
        (Vehicle.scope == RoutineScope.household)
        | ((Vehicle.scope == RoutineScope.personal) & (Vehicle.owner_user_id == auth.user.id))
    )
    rows = (
        await db.scalars(select(Vehicle).where(*filters).order_by(Vehicle.created_at.asc()))
    ).all()
    return VehicleListResponse(
        items=[_vehicle_response(row, auth, membership) for row in rows]
    )


@router.post("/{home_id}/vehicles/lookup", response_model=VehicleLookupResult)
async def lookup_vehicle(
    home_id: uuid.UUID,
    body: VehicleLookupRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> VehicleLookupResult:
    await require_capability(home_id, Capability.driveway_view, auth, db)
    await enforce_rate_limit(
        request, settings, f"driveway-lookup:{auth.user.id}", settings.driveway_lookup_rate_limit, 300
    )
    country = body.country_code.upper()
    if country != "GB":
        return VehicleLookupResult(
            found=False,
            manual_entry_required=True,
            message="Automatic vehicle lookup isn't available for this country yet, but you can still add the vehicle manually.",
        )
    if settings.dvla_api_key is None:
        return VehicleLookupResult(
            found=False,
            manual_entry_required=True,
            message="We can't check vehicle details right now. You can try again later or add the vehicle manually.",
        )
    enabled = await db.scalar(
        select(PlatformSetting.value).where(PlatformSetting.key == "driveway_dvla_enabled")
    )
    if enabled is None or enabled.get("value") is not True:
        return VehicleLookupResult(
            found=False,
            manual_entry_required=True,
            message="Automatic UK vehicle lookup is temporarily unavailable. You can still add the vehicle manually.",
        )
    provider = UKDVLAProvider(settings.dvla_api_key, settings.dvla_api_url)
    try:
        result = await provider.lookup(body.registration)
    except VehicleLookupNotFound:
        await _record_lookup_health(db, success=True, summary="Vehicle registration not found")
        return VehicleLookupResult(found=False, manual_entry_required=True, message="We couldn't find that registration. Check it and try again, or add the vehicle manually.")
    except VehicleLookupUnavailable:
        await _record_lookup_health(db, success=False, summary="Provider unavailable")
        return VehicleLookupResult(found=False, manual_entry_required=True, message="We can't check vehicle details right now. You can try again later or add the vehicle manually.")
    await _record_lookup_health(db, success=True, summary="Vehicle lookup succeeded")
    return VehicleLookupResult(
        found=True,
        provider=provider.name,
        registration=result.registration,
        make=result.make,
        model=result.model,
        colour=result.colour,
        year=result.year,
        fuel_type=result.fuel_type,
        engine_size=result.engine_size,
        first_registration_date=result.first_registration_date,
        tax_status=result.tax_status,
        tax_due_date=result.tax_due_date,
        inspection_status=result.inspection_status,
        inspection_due_date=result.inspection_due_date,
        capabilities=list(result.capabilities),
    )


@router.post("/{home_id}/vehicles", response_model=VehicleResponse, status_code=201)
async def create_vehicle(
    home_id: uuid.UUID,
    body: VehicleCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> VehicleResponse:
    membership = await require_capability(home_id, Capability.driveway_manage, auth, db)
    row = Vehicle(
        group_id=home_id,
        owner_user_id=auth.user.id,
        scope=body.scope,
        nickname=" ".join(body.nickname.strip().split()),
        make=body.make.strip() if body.make else None,
        model=body.model.strip() if body.model else None,
        colour=body.colour.strip() if body.colour else None,
        year=body.year,
        fuel_type=body.fuel_type.strip() if body.fuel_type else None,
        engine_size=body.engine_size.strip() if body.engine_size else None,
        country_code=body.country_code.upper(),
        registration=body.registration.strip() if body.registration else None,
        first_registration_date=body.first_registration_date,
        vin=body.vin.strip() if body.vin else None,
    )
    db.add(row)
    await db.flush()
    audit(
        db, request, "driveway.vehicle.created", auth.user.id, home_id, "vehicle", row.id,
        _audit_metadata(row),
    )
    await db.commit()
    await db.refresh(row)
    return _vehicle_response(row, auth, membership)


@router.get("/{home_id}/vehicles/{vehicle_id}", response_model=VehicleResponse)
async def get_vehicle(
    home_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> VehicleResponse:
    membership = await require_capability(home_id, Capability.driveway_view, auth, db)
    row = await _get_vehicle(db, home_id, vehicle_id)
    if row.scope == RoutineScope.personal and row.owner_user_id != auth.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That vehicle could not be found")
    return _vehicle_response(row, auth, membership)


@router.post("/{home_id}/vehicles/{vehicle_id}/photo", response_model=VehicleResponse)
async def upload_vehicle_photo(
    home_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> VehicleResponse:
    await enforce_rate_limit(request, settings, "vehicle-photo-upload", 20, 3600)
    row = await _get_vehicle(db, home_id, vehicle_id, for_update=True)
    await _require_vehicle_owner_or_household_manage(db, home_id, row, auth)
    membership = await require_capability(home_id, Capability.driveway_view, auth, db)
    raw = await file.read(settings.vehicle_photo_max_upload_bytes + 1)
    if len(raw) > settings.vehicle_photo_max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "That photo is too large to upload.",
        )
    if not raw:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No file was uploaded.")
    try:
        processed = process_attachment_upload(raw)
    except AttachmentResourceError as cause:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "That photo is too large to process.",
        ) from cause
    except UnsupportedImageError as cause:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(cause)) from cause

    storage = get_vehicle_photo_storage(settings)
    new_key = vehicle_photo_filename()
    await storage.save(new_key, processed)
    previous_key = row.photo_key
    row.photo_key = new_key
    row.photo_updated_at = datetime.now(UTC)
    audit(db, request, "driveway.vehicle_photo.uploaded", auth.user.id, home_id, "vehicle", row.id)
    await db.commit()
    await db.refresh(row)
    if previous_key:
        await storage.delete(previous_key)
    return _vehicle_response(row, auth, membership)


@router.get("/{home_id}/vehicles/{vehicle_id}/photo")
async def get_vehicle_photo(
    home_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    await require_capability(home_id, Capability.driveway_view, auth, db)
    row = await _get_vehicle(db, home_id, vehicle_id)
    if row.scope == RoutineScope.personal and row.owner_user_id != auth.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That vehicle could not be found")
    if not row.photo_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No vehicle photo set.")
    data = await get_vehicle_photo_storage(settings).load(row.photo_key)
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No vehicle photo set.")
    return Response(
        content=data,
        media_type=OUTPUT_CONTENT_TYPE,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.delete("/{home_id}/vehicles/{vehicle_id}/photo", response_model=VehicleResponse)
async def delete_vehicle_photo(
    home_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> VehicleResponse:
    row = await _get_vehicle(db, home_id, vehicle_id, for_update=True)
    await _require_vehicle_owner_or_household_manage(db, home_id, row, auth)
    membership = await require_capability(home_id, Capability.driveway_view, auth, db)
    previous_key = row.photo_key
    row.photo_key = None
    row.photo_updated_at = None
    audit(db, request, "driveway.vehicle_photo.deleted", auth.user.id, home_id, "vehicle", row.id)
    await db.commit()
    if previous_key:
        await get_vehicle_photo_storage(settings).delete(previous_key)
    return _vehicle_response(row, auth, membership)


@router.patch("/{home_id}/vehicles/{vehicle_id}", response_model=VehicleResponse)
async def update_vehicle(
    home_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    body: VehicleUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> VehicleResponse:
    row = await _get_vehicle(db, home_id, vehicle_id, for_update=True)
    await _require_vehicle_owner_or_household_manage(db, home_id, row, auth)
    membership = await require_capability(home_id, Capability.driveway_view, auth, db)
    if row.updated_at != body.expected_updated_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "This vehicle changed. Reload and try again.")
    scope_changed = row.scope != body.scope
    row.scope = body.scope
    row.nickname = " ".join(body.nickname.strip().split())
    row.make = body.make.strip() if body.make else None
    row.model = body.model.strip() if body.model else None
    row.colour = body.colour.strip() if body.colour else None
    row.year = body.year
    row.fuel_type = body.fuel_type.strip() if body.fuel_type else None
    row.engine_size = body.engine_size.strip() if body.engine_size else None
    row.country_code = body.country_code.upper()
    row.registration = body.registration.strip() if body.registration else None
    row.first_registration_date = body.first_registration_date
    # A viewer who cannot see this vehicle's VIN (not its owner, not a
    # home_admin — see _may_see_sensitive_fields) never receives it in the
    # form they're editing, so a full-replace PATCH must not let their
    # always-empty field silently clear an existing value. Only a viewer
    # who could see the real value may overwrite it.
    if _may_see_sensitive_fields(row, auth, membership):
        row.vin = body.vin.strip() if body.vin else None
    if scope_changed:
        # Linked managed reminders follow the vehicle's own scope; a
        # standalone reminder is never touched (see docstring on
        # sync_reminder_scope_to_vehicle).
        await sync_reminder_scope_to_vehicle(db, row)
    audit(
        db, request, "driveway.vehicle.updated", auth.user.id, home_id, "vehicle", row.id,
        _audit_metadata(row),
    )
    await db.commit()
    await db.refresh(row)
    return _vehicle_response(row, auth, membership)


@router.delete("/{home_id}/vehicles/{vehicle_id}", status_code=204)
async def delete_vehicle(
    home_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await _get_vehicle(db, home_id, vehicle_id, for_update=True)
    await _require_vehicle_owner_or_household_manage(db, home_id, row, auth)
    row.archived_at = datetime.now(UTC)
    # Reminder has no soft-delete of its own (see routers.reminders.
    # delete_reminder) — a managed reminder must never keep pointing at a
    # vehicle that's gone from every Driveway listing, so it's hard-deleted
    # in the same transaction rather than left orphaned.
    await delete_reminders_for_vehicle(db, home_id, row.id)
    audit(
        db, request, "driveway.vehicle.deleted", auth.user.id, home_id, "vehicle", row.id,
        _audit_metadata(row),
    )
    await db.commit()


def _require_vehicle_visible(vehicle: Vehicle, auth: AuthContext) -> None:
    if vehicle.scope == RoutineScope.personal and vehicle.owner_user_id != auth.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That vehicle could not be found")


@router.get("/{home_id}/vehicles/{vehicle_id}/reminders", response_model=ReminderListResponse)
async def list_vehicle_reminders(
    home_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ReminderListResponse:
    """Only reminders linked to this vehicle — a dedicated indexed query
    (see reminders_for_vehicle), never the full Home reminder list filtered
    client-side. Vehicle access is checked before any reminder is
    touched, so a Personal vehicle's reminders stay exactly as private as
    the vehicle itself — this route can never be used to enumerate or
    infer another member's personal reminders."""
    await require_capability(home_id, Capability.driveway_view, auth, db)
    vehicle = await _get_vehicle(db, home_id, vehicle_id)
    _require_vehicle_visible(vehicle, auth)
    rows = await reminders_for_vehicle(db, home_id, vehicle.id)
    return ReminderListResponse(items=[await _reminder_response(db, row) for row in rows])


@router.post(
    "/{home_id}/vehicles/{vehicle_id}/reminders",
    response_model=ReminderResponse,
    status_code=201,
)
async def create_vehicle_reminder(
    home_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    body: VehicleReminderCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ReminderResponse:
    """Creates a normal Reminder row (source_event=manual — see
    DrivewayReminderEventType), linked to this vehicle, in the vehicle's
    own scope/category (see upsert_driveway_reminder). Vehicle access is
    required first; the actual reminder-management authorization reuses
    the identical capability routers.reminders.create_reminder checks, so
    this is never a weaker path to creating a Reminder than Nudges itself."""
    await require_capability(home_id, Capability.driveway_view, auth, db)
    vehicle = await _get_vehicle(db, home_id, vehicle_id)
    _require_vehicle_visible(vehicle, auth)
    await require_capability(home_id, Capability.household_manage_reminders, auth, db)
    reminder, _created = await upsert_driveway_reminder(
        db,
        group_id=home_id,
        vehicle=vehicle,
        event_type=DrivewayReminderEventType.manual,
        due_date=body.due_date,
        due_time=body.due_time,
        title=" ".join(body.title.strip().split()),
        description=body.description,
        repeat=body.repeat,
        cadence=body.cadence,
        created_by=auth.user.id,
    )
    audit(
        db, request, "driveway.reminder.created", auth.user.id, home_id, "reminder", reminder.id,
        {"vehicle_id": str(vehicle.id), "source_event": reminder.source_event},
    )
    await db.commit()
    await db.refresh(reminder)
    return await _reminder_response(db, reminder)
