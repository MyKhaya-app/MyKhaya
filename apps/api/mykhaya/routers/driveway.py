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

Registration/VIN writes AND reads go only through mykhaya.driveway_sensitive:
writes also maintain the ciphertext columns (Phase 2B, behind
MYKHAYA_DRIVEWAY_FIELD_ENCRYPTION_WRITE); reads are ciphertext-first with a
NULL-ciphertext plaintext fallback (Phase 2D, behind
MYKHAYA_DRIVEWAY_FIELD_ENCRYPTION_READ). The ciphertext columns are never
serialised.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import structlog
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
from mykhaya.dependencies import AuthContext, auth_context, membership_for
from mykhaya.driveway_mot import (
    MotRefreshRefused,
    clear_mot_data,
    is_mot_eligible,
    mot_view,
    refresh_vehicle_mot,
)
from mykhaya.driveway_mot_nudges import MotNudgePlan, apply_plan, read_plan, remove_plan
from mykhaya.driveway_providers import (
    UKDVLAProvider,
    VehicleLookupAuthFailed,
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
    VehicleMotNudgePlanRequest,
    VehicleMotNudgePlanResponse,
    VehicleMotNudgesResponse,
    VehicleMotRefreshRequest,
    VehicleMotRefreshResult,
    VehicleMotResponse,
    VehicleReminderCreate,
    VehicleResponse,
    VehicleUpdate,
)
from mykhaya.driveway_sensitive import (
    DrivewayFieldEncryptionUnavailable,
    DrivewaySensitiveReadError,
    get_vehicle_registration,
    get_vehicle_vin,
    new_vehicle_id,
    set_vehicle_registration,
    set_vehicle_vin,
    vehicle_sensitive_ciphertexts,
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
from mykhaya.showcase.guards import is_showcase_home
from mykhaya.vehicle_photo_storage import get_vehicle_photo_storage, vehicle_photo_filename


async def _require_driveway(
    home_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    # Membership first: a caller who isn't an active member of this Home gets
    # the same "Home could not be found" 404 for every Home ID, before any
    # feature/entitlement state (or vehicle row) is looked at — so Driveway
    # can't be used to learn whether an arbitrary Home has Ultimate.
    await membership_for(home_id, auth, db)
    await require_feature(db, FeatureKey.driveway, home_id)
    await require_entitlement(db, home_id, "driveway.enabled")


router = APIRouter(prefix="/homes", tags=["driveway"], dependencies=[Depends(_require_driveway)])
log = structlog.get_logger()


def _may_see_sensitive_fields(vehicle: Vehicle, auth: AuthContext, membership: Membership) -> bool:
    if vehicle.owner_user_id == auth.user.id:
        return True
    return membership.relationship == HouseholdRelationship.home_admin


def _vehicle_response(
    vehicle: Vehicle, auth: AuthContext, membership: Membership, settings: Settings
) -> VehicleResponse:
    # Visibility is decided BEFORE any VIN is read: get_vehicle_vin (which
    # decrypts when the Phase 2D read flag is on) is only ever called for a
    # viewer already entitled to the VIN — never speculatively.
    reveal_sensitive = _may_see_sensitive_fields(vehicle, auth, membership)
    try:
        registration = get_vehicle_registration(vehicle, settings)
        vin = get_vehicle_vin(vehicle, settings) if reveal_sensitive else None
    except DrivewaySensitiveReadError as exc:
        # An existing ciphertext that will not decrypt is an integrity
        # failure: no plaintext fallback, and a generic error with no value,
        # envelope or ID (details are logged as an error class only).
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Vehicle details can't be loaded right now. Please try again later.",
        ) from exc
    return VehicleResponse(
        id=vehicle.id,
        group_id=vehicle.group_id,
        owner_user_id=vehicle.owner_user_id,
        nickname=vehicle.nickname,
        make=vehicle.make,
        model=vehicle.model,
        colour=vehicle.colour,
        year=vehicle.year,
        fuel_type=vehicle.fuel_type,
        engine_size=vehicle.engine_size,
        country_code=vehicle.country_code,
        registration=registration,
        first_registration_date=vehicle.first_registration_date,
        vin=vin,
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
    """Best-effort health tracking for PCC's Driveway integrations card
    (last successful/failed lookup + sanitised summary). `summary` must
    already be a safe, generic string — never a raw provider response,
    header, or API key (see mykhaya.driveway_providers' exception types,
    which never carry response bodies). A failure here is logged and
    swallowed rather than raised, so a monitoring write can never break the
    actual vehicle lookup the caller is waiting on."""
    try:
        row = await db.scalar(
            select(PlatformSetting)
            .where(PlatformSetting.key == "driveway_dvla_enabled")
            .with_for_update()
        )
        if row is None:
            row = PlatformSetting(key="driveway_dvla_enabled", value={"value": True})
            db.add(row)
        health = dict(row.value.get("health") or {})
        now = datetime.now(UTC).isoformat()
        health["state"] = "Healthy" if success else "Degraded"
        if success:
            health["last_success_at"] = now
            health["last_success_summary"] = summary
        else:
            health["last_failure_at"] = now
            health["last_failure_summary"] = summary
        row.value = {**row.value, "health": health}
        await db.commit()
    except Exception:
        await db.rollback()
        log.warning("driveway.dvla.health_record_failed")


async def _require_vehicle_manage(db: AsyncSession, home_id: uuid.UUID, auth: AuthContext) -> None:
    """Checked *before* any vehicle row is loaded or locked: authorization
    first, then the row, so a caller without manage access can neither take a
    row lock nor learn whether a vehicle ID exists from a 403-vs-404 split."""
    await require_capability(home_id, Capability.driveway_manage, auth, db)


async def _require_home_member_owner(
    db: AsyncSession, home_id: uuid.UUID, owner_user_id: uuid.UUID
) -> Membership:
    membership = await db.scalar(
        select(Membership).where(
            Membership.group_id == home_id,
            Membership.user_id == owner_user_id,
            Membership.removed_at.is_(None),
        )
    )
    if membership is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The vehicle owner must be an active member of this Home."
        )
    return membership


@contextmanager
def _field_encryption_guard() -> Iterator[None]:
    """Turns an unusable keyring (dual-write on) into a 503 *before* commit,
    so the request's transaction is rolled back and no plaintext-only change
    is persisted. The message is generic; details are logged by
    mykhaya.driveway_sensitive as an error class only."""
    try:
        yield
    except DrivewayFieldEncryptionUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Vehicle details can't be saved right now. Please try again later.",
        ) from exc


def _audit_metadata(vehicle: Vehicle) -> dict[str, object]:
    """Never includes vin/registration — see module docstring."""
    return {"owner_user_id": str(vehicle.owner_user_id), "country_code": vehicle.country_code}


@router.get("/{home_id}/vehicles", response_model=VehicleListResponse)
async def list_vehicles(
    home_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> VehicleListResponse:
    membership = await require_capability(home_id, Capability.driveway_view, auth, db)
    filters = [Vehicle.group_id == home_id, Vehicle.archived_at.is_(None)]
    rows = (
        await db.scalars(select(Vehicle).where(*filters).order_by(Vehicle.created_at.asc()))
    ).all()
    return VehicleListResponse(
        items=[_vehicle_response(row, auth, membership, settings) for row in rows]
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
        request,
        settings,
        f"driveway-lookup:{auth.user.id}",
        settings.driveway_lookup_rate_limit,
        300,
    )
    country = body.country_code.upper()
    if await is_showcase_home(db, home_id):
        # Showcase Demo Homes never contact government services.
        return VehicleLookupResult(
            found=False,
            manual_entry_required=True,
            message="Vehicle lookup isn't available in demo Homes. You can add the vehicle"
            " manually.",
        )
    if country != "GB":
        return VehicleLookupResult(
            found=False,
            manual_entry_required=True,
            message="Automatic vehicle lookup isn't available for this country yet, but you can"
            " still add the vehicle manually.",
        )
    if not settings.dvla_configured:
        return VehicleLookupResult(
            found=False,
            manual_entry_required=True,
            message="We can't check vehicle details right now. You can try again later or add"
            " the vehicle manually.",
        )
    enabled = await db.scalar(
        select(PlatformSetting.value).where(PlatformSetting.key == "driveway_dvla_enabled")
    )
    if enabled is None or enabled.get("value") is not True:
        return VehicleLookupResult(
            found=False,
            manual_entry_required=True,
            message="Automatic UK vehicle lookup is temporarily unavailable. You can still add"
            " the vehicle manually.",
        )
    assert settings.dvla_active_api_key is not None and settings.dvla_active_endpoint is not None
    provider = UKDVLAProvider(settings.dvla_active_api_key, settings.dvla_active_endpoint)
    try:
        result = await provider.lookup(body.registration)
    except VehicleLookupNotFound:
        await _record_lookup_health(db, success=True, summary="Vehicle registration not found")
        return VehicleLookupResult(
            found=False,
            manual_entry_required=True,
            message="We couldn't find that registration. Check it and try again, or add the"
            " vehicle manually.",
        )
    except VehicleLookupAuthFailed:
        await _record_lookup_health(db, success=False, summary="Provider authentication failed")
        return VehicleLookupResult(
            found=False,
            manual_entry_required=True,
            message="We can't check vehicle details right now. You can try again later or add"
            " the vehicle manually.",
        )
    except VehicleLookupUnavailable:
        await _record_lookup_health(db, success=False, summary="Provider unavailable")
        return VehicleLookupResult(
            found=False,
            manual_entry_required=True,
            message="We can't check vehicle details right now. You can try again later or add"
            " the vehicle manually.",
        )
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
    settings: Settings = Depends(get_settings),
) -> VehicleResponse:
    membership = await require_capability(home_id, Capability.driveway_manage, auth, db)
    await _require_home_member_owner(db, home_id, body.owner_user_id)
    registration = body.registration.strip() if body.registration else None
    vin = body.vin.strip() if body.vin else None
    # The id is assigned up front (not left to the flush-time default) because
    # the ciphertext's associated data binds it to this exact row.
    vehicle_id = new_vehicle_id()
    with _field_encryption_guard():
        ciphertexts = vehicle_sensitive_ciphertexts(
            vehicle_id, registration=registration, vin=vin, settings=settings
        )
    row = Vehicle(
        id=vehicle_id,
        group_id=home_id,
        owner_user_id=body.owner_user_id,
        scope=RoutineScope.household,
        nickname=" ".join(body.nickname.strip().split()),
        make=body.make.strip() if body.make else None,
        model=body.model.strip() if body.model else None,
        colour=body.colour.strip() if body.colour else None,
        year=body.year,
        fuel_type=body.fuel_type.strip() if body.fuel_type else None,
        engine_size=body.engine_size.strip() if body.engine_size else None,
        country_code=body.country_code.upper(),
        registration=registration,
        first_registration_date=body.first_registration_date,
        vin=vin,
        **ciphertexts,
    )
    db.add(row)
    await db.flush()
    audit(
        db,
        request,
        "driveway.vehicle.created",
        auth.user.id,
        home_id,
        "vehicle",
        row.id,
        _audit_metadata(row),
    )
    await db.commit()
    await db.refresh(row)
    return _vehicle_response(row, auth, membership, settings)


@router.get("/{home_id}/vehicles/{vehicle_id}", response_model=VehicleResponse)
async def get_vehicle(
    home_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> VehicleResponse:
    membership = await require_capability(home_id, Capability.driveway_view, auth, db)
    row = await _get_vehicle(db, home_id, vehicle_id)
    return _vehicle_response(row, auth, membership, settings)


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
    membership = await require_capability(home_id, Capability.driveway_view, auth, db)
    await _require_vehicle_manage(db, home_id, auth)
    row = await _get_vehicle(db, home_id, vehicle_id, for_update=True)
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
    return _vehicle_response(row, auth, membership, settings)


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
    if not row.photo_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No vehicle photo set.")
    data = await get_vehicle_photo_storage(settings).load(row.photo_key)
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No vehicle photo set.")
    return Response(
        content=data,
        media_type=OUTPUT_CONTENT_TYPE,
        # Private household media: never storable by a shared cache/CDN/proxy,
        # and only briefly reusable by this browser (the URL is versioned by
        # photo_version, so a changed photo still refreshes immediately). The
        # previous "public, max-age=31536000, immutable" let any intermediary
        # keep an authenticated photo for a year and outlive sign-out.
        headers={"Cache-Control": "private, max-age=300"},
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
    membership = await require_capability(home_id, Capability.driveway_view, auth, db)
    await _require_vehicle_manage(db, home_id, auth)
    row = await _get_vehicle(db, home_id, vehicle_id, for_update=True)
    previous_key = row.photo_key
    row.photo_key = None
    row.photo_updated_at = None
    audit(db, request, "driveway.vehicle_photo.deleted", auth.user.id, home_id, "vehicle", row.id)
    await db.commit()
    # Reload server-generated columns (updated_at) before serialising, as the
    # other write handlers do; without it the expired attribute triggered a
    # lazy load outside the async greenlet and the response failed with a 500
    # even though the photo had been removed.
    await db.refresh(row)
    if previous_key:
        await get_vehicle_photo_storage(settings).delete(previous_key)
    return _vehicle_response(row, auth, membership, settings)


@router.patch("/{home_id}/vehicles/{vehicle_id}", response_model=VehicleResponse)
async def update_vehicle(
    home_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    body: VehicleUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> VehicleResponse:
    membership = await require_capability(home_id, Capability.driveway_view, auth, db)
    await _require_vehicle_manage(db, home_id, auth)
    row = await _get_vehicle(db, home_id, vehicle_id, for_update=True)
    if row.updated_at != body.expected_updated_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "This vehicle changed. Reload and try again.")
    await _require_home_member_owner(db, home_id, body.owner_user_id)
    owner_changed = row.owner_user_id != body.owner_user_id
    row.owner_user_id = body.owner_user_id
    row.nickname = " ".join(body.nickname.strip().split())
    row.make = body.make.strip() if body.make else None
    row.model = body.model.strip() if body.model else None
    row.colour = body.colour.strip() if body.colour else None
    row.year = body.year
    row.fuel_type = body.fuel_type.strip() if body.fuel_type else None
    row.engine_size = body.engine_size.strip() if body.engine_size else None
    country_was_mot_eligible = is_mot_eligible(row)
    row.country_code = body.country_code.upper()
    row.first_registration_date = body.first_registration_date
    with _field_encryption_guard():
        registration_changed = set_vehicle_registration(
            row, body.registration.strip() if body.registration else None, settings
        )
        # A viewer who cannot see this vehicle's VIN (not its owner, not a
        # home_admin — see _may_see_sensitive_fields) never receives it in the
        # form they're editing, so a full-replace PATCH must not let their
        # always-empty field silently clear an existing value. Only a viewer
        # who could see the real value may overwrite it.
        if _may_see_sensitive_fields(row, auth, membership):
            set_vehicle_vin(row, body.vin.strip() if body.vin else None, settings)
    if registration_changed or (country_was_mot_eligible and not is_mot_eligible(row)):
        # Stored MOT history describes the previous registration/country.
        await clear_mot_data(db, row)
    if owner_changed:
        # Linked managed reminders follow the vehicle to its new owner (see
        # sync_reminder_scope_to_vehicle) rather than staying with the previous one.
        await sync_reminder_scope_to_vehicle(db, row)
    audit(
        db,
        request,
        "driveway.vehicle.updated",
        auth.user.id,
        home_id,
        "vehicle",
        row.id,
        _audit_metadata(row),
    )
    await db.commit()
    await db.refresh(row)
    return _vehicle_response(row, auth, membership, settings)


@router.delete("/{home_id}/vehicles/{vehicle_id}", status_code=204)
async def delete_vehicle(
    home_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_vehicle_manage(db, home_id, auth)
    row = await _get_vehicle(db, home_id, vehicle_id, for_update=True)
    row.archived_at = datetime.now(UTC)
    # Reminder has no soft-delete of its own (see routers.reminders.
    # delete_reminder) — a managed reminder must never keep pointing at a
    # vehicle that's gone from every Driveway listing, so it's hard-deleted
    # in the same transaction rather than left orphaned.
    await delete_reminders_for_vehicle(db, home_id, row.id)
    audit(
        db,
        request,
        "driveway.vehicle.deleted",
        auth.user.id,
        home_id,
        "vehicle",
        row.id,
        _audit_metadata(row),
    )
    await db.commit()


def _require_vehicle_visible(vehicle: Vehicle, auth: AuthContext, membership: Membership) -> None:
    """A vehicle's reminders are as private as its sensitive fields: only its owner
    or a Home Admin (see _may_see_sensitive_fields) may list or add to them. Anyone
    else gets the same 404 as for a vehicle that does not exist, so this can never
    be used to enumerate or infer another member's personal reminders."""
    if not _may_see_sensitive_fields(vehicle, auth, membership):
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
    membership = await require_capability(home_id, Capability.driveway_view, auth, db)
    vehicle = await _get_vehicle(db, home_id, vehicle_id)
    _require_vehicle_visible(vehicle, auth, membership)
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
    membership = await require_capability(home_id, Capability.driveway_view, auth, db)
    vehicle = await _get_vehicle(db, home_id, vehicle_id)
    _require_vehicle_visible(vehicle, auth, membership)
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
        db,
        request,
        "driveway.reminder.created",
        auth.user.id,
        home_id,
        "reminder",
        reminder.id,
        {"vehicle_id": str(vehicle.id), "source_event": reminder.source_event},
    )
    await db.commit()
    await db.refresh(reminder)
    return await _reminder_response(db, reminder)


# --- MOT (Driveway MOT Phase 1) ------------------------------------------------------

_MOT_REFUSALS = {
    "unsupported_country": (
        status.HTTP_409_CONFLICT,
        "MOT history is only available for vehicles registered in the UK.",
    ),
    "no_registration": (
        status.HTTP_409_CONFLICT,
        "Add this vehicle's registration to check its MOT.",
    ),
    "provider_unavailable": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "MOT checks aren't available right now.",
    ),
}
_MOT_REFRESH_MESSAGES = {
    "not_found": "We couldn't find an MOT record for this registration.",
    "busy": "We're already checking this vehicle's MOT. Try again in a moment.",
    "rate_limited": "MOT checks are busy right now. Please try again in a few minutes.",
    "auth_failed": "We couldn't check the MOT right now. Please try again later.",
    "unavailable": "We couldn't check the MOT right now. Please try again later.",
    "malformed": "We couldn't check the MOT right now. Please try again later.",
    "not_configured": "MOT checks aren't available right now.",
}


@router.get("/{home_id}/vehicles/{vehicle_id}/mot", response_model=VehicleMotResponse)
async def get_vehicle_mot(
    home_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> VehicleMotResponse:
    """Persisted MOT summary and history — never calls the provider."""
    await require_capability(home_id, Capability.driveway_view, auth, db)
    row = await _get_vehicle(db, home_id, vehicle_id)
    return VehicleMotResponse.model_validate(
        await mot_view(db, settings, home_id=home_id, vehicle=row)
    )


@router.post("/{home_id}/vehicles/{vehicle_id}/mot/refresh", response_model=VehicleMotResponse)
async def refresh_vehicle_mot_endpoint(
    home_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    request: Request,
    body: VehicleMotRefreshRequest | None = None,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> VehicleMotResponse:
    """Refreshes the STORED vehicle's MOT from the provider. There is no
    way to look up an arbitrary registration here: the registration always
    comes from the vehicle itself, via the sensitive-field read path, after
    Home authorization."""
    await require_capability(home_id, Capability.driveway_view, auth, db)
    await enforce_rate_limit(
        request,
        settings,
        f"dvsa-mot-refresh:{auth.user.id}",
        settings.dvsa_refresh_rate_limit,
        3600,
    )
    mode = body.mode if body is not None else "force"
    row = await _get_vehicle(db, home_id, vehicle_id)
    try:
        outcome = await refresh_vehicle_mot(
            db,
            request,
            settings,
            home_id=home_id,
            vehicle=row,
            actor_id=auth.user.id,
            mode=mode,
        )
    except MotRefreshRefused as refused:
        status_code, message = _MOT_REFUSALS[refused.reason]
        raise HTTPException(status_code, message) from refused
    # The refresh may have ended the request transaction; reload rather than
    # reuse a possibly-expired instance.
    fresh = await _get_vehicle(db, home_id, vehicle_id)
    view = await mot_view(db, settings, home_id=home_id, vehicle=fresh)
    kind = outcome.error.category if outcome.error is not None else outcome.kind
    view["refresh"] = VehicleMotRefreshResult(outcome=kind, message=_MOT_REFRESH_MESSAGES.get(kind))
    return VehicleMotResponse.model_validate(view)


def _plan_response(plan: MotNudgePlan | None) -> VehicleMotNudgesResponse:
    if plan is None:
        return VehicleMotNudgesResponse(plan=None)
    return VehicleMotNudgesResponse(
        plan=VehicleMotNudgePlanResponse(
            title=plan.title,
            due_date=plan.due_date,
            offsets=list(plan.offsets),
            repeat=plan.repeat,
            scheduled=plan.scheduled_dates(datetime.now(UTC).date()),
        )
    )


@router.get("/{home_id}/vehicles/{vehicle_id}/mot/nudges", response_model=VehicleMotNudgesResponse)
async def get_vehicle_mot_nudges(
    home_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> VehicleMotNudgesResponse:
    """The vehicle's MOT nudge plan, if any. As private as the vehicle's
    reminders: owner or Home Admin only, 404 for everyone else."""
    membership = await require_capability(home_id, Capability.driveway_view, auth, db)
    vehicle = await _get_vehicle(db, home_id, vehicle_id)
    _require_vehicle_visible(vehicle, auth, membership)
    return _plan_response(read_plan(vehicle))


@router.put("/{home_id}/vehicles/{vehicle_id}/mot/nudges", response_model=VehicleMotNudgesResponse)
async def save_vehicle_mot_nudges(
    home_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    body: VehicleMotNudgePlanRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> VehicleMotNudgesResponse:
    """Creates or replaces the MOT nudge plan and its reminders (ordinary
    Driveway-linked Reminder rows for the vehicle owner — see
    mykhaya.driveway_mot_nudges). Same authorization as adding any vehicle
    reminder: vehicle visibility, then the Nudges reminder capability."""
    membership = await require_capability(home_id, Capability.driveway_view, auth, db)
    vehicle = await _get_vehicle(db, home_id, vehicle_id, for_update=True)
    _require_vehicle_visible(vehicle, auth, membership)
    await require_capability(home_id, Capability.household_manage_reminders, auth, db)
    if not is_mot_eligible(vehicle):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "MOT reminders are only available for vehicles registered in the UK.",
        )
    today = datetime.now(UTC).date()
    if not today - timedelta(days=366) <= body.due_date <= today + timedelta(days=366 * 4):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose the date this MOT expires."
        )
    plan = MotNudgePlan(
        title=" ".join(body.title.strip().split()),
        offsets=tuple(sorted(set(body.offsets), reverse=True)),
        repeat=body.repeat,
        due_date=body.due_date,
    )
    if not plan.title:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Give the reminder a name.")
    await apply_plan(db, vehicle, plan, actor_id=auth.user.id, today=today)
    audit(
        db,
        request,
        "driveway.vehicle.mot_nudges_saved",
        auth.user.id,
        home_id,
        "vehicle",
        vehicle.id,
        {"offsets": list(plan.offsets), "repeat": plan.repeat},
    )
    await db.commit()
    return _plan_response(plan)


@router.delete("/{home_id}/vehicles/{vehicle_id}/mot/nudges", status_code=204)
async def delete_vehicle_mot_nudges(
    home_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Removes the MOT nudge plan and every MOT reminder for the vehicle,
    and records that MOT nudges are off so a refresh recreates nothing (see
    mykhaya.driveway_mot_nudges.remove_plan). Same authorization as saving."""
    membership = await require_capability(home_id, Capability.driveway_view, auth, db)
    vehicle = await _get_vehicle(db, home_id, vehicle_id, for_update=True)
    _require_vehicle_visible(vehicle, auth, membership)
    await require_capability(home_id, Capability.household_manage_reminders, auth, db)
    await remove_plan(db, vehicle)
    audit(
        db,
        request,
        "driveway.vehicle.mot_nudges_removed",
        auth.user.id,
        home_id,
        "vehicle",
        vehicle.id,
        {},
    )
    await db.commit()
