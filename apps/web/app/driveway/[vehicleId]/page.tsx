"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChangeEvent, KeyboardEvent, use, useCallback, useEffect, useRef, useState } from "react";
import { Bell, Camera, ChevronLeft, ChevronRight, Pencil, ShieldAlert, ShieldCheck, Trash2 } from "lucide-react";
import type { Member, Vehicle, VehicleMot } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { BottomSheet } from "@/components/bottom-sheet";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";
import { useAuth } from "@/components/auth-provider";
import { VehiclePhoto } from "@/components/vehicle-photo";
import { isNativeShell } from "@/components/native-runtime";
import { AvatarProcessingError, classifyAvatarBackendFailure, isImageFormatRejection, normalizeAvatarFile } from "@/components/avatar-upload";
import { NativeAvatarPickerError, pickAvatarFromCamera, pickAvatarFromGallery } from "@/components/native-avatar-picker";
import { countryName } from "../countries";
import { MotPill, PlateChip, RefreshButton, useMotRefresh } from "../driveway-ui";
import {
  checkedAgo,
  firstName,
  formatMileage,
  formatPlate,
  formatShortDate,
  lastMileage,
  motDaysText,
  motExpiryText,
  motNeedsAttention,
  motPillLabel,
  motState,
  testSummary,
  vehicleName,
  type MotState,
} from "../vehicle-display";

// Driveway vehicle: Overview | MOT | Details. The selected tab is kept in
// the URL (?tab=mot) so "back" from MOT history lands on the MOT tab.

type Tab = "overview" | "mot" | "details";
const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "mot", label: "MOT" },
  { id: "details", label: "Details" },
];

function tabFromUrl(): Tab {
  if (typeof window === "undefined") return "overview";
  const value = new URLSearchParams(window.location.search).get("tab");
  return value === "mot" || value === "details" ? value : "overview";
}

function loadErrorMessage(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError && cause.status === 404) return "That vehicle could not be found.";
  return cause instanceof ApiError ? cause.message : fallback;
}

function noMotText(mot: VehicleMot | null): string {
  if (!mot) return "Checking MOT…";
  if (!mot.has_registration) return "Add this vehicle's registration to check its MOT.";
  if (mot.summary.status === "no_record") return "We couldn't find an MOT record for this registration.";
  if (!mot.provider_available) return "MOT checks aren't available right now.";
  return "We haven't checked this vehicle's MOT yet.";
}

function KeyValues({ rows }: { rows: { label: string; value: React.ReactNode }[] }) {
  return (
    <dl className="drv-card drv-kv">
      {rows.map((row) => (
        <div key={row.label}>
          <dt>{row.label}</dt>
          <dd>{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function VehicleDetailPage({ params }: { params: Promise<{ vehicleId: string }> }) {
  const { vehicleId } = use(params);
  const { activeHomeId, activeHome } = useActiveHome();
  const { user } = useAuth();
  const router = useRouter();
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [mot, setMot] = useState<VehicleMot | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [tab, setTab] = useState<Tab>("overview");
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [photoSheetOpen, setPhotoSheetOpen] = useState(false);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoError, setPhotoError] = useState("");
  const libraryInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => setTab(tabFromUrl()), []);

  useEffect(() => {
    if (!activeHomeId) return;
    setNotFound(false);
    api
      .vehicle(activeHomeId, vehicleId)
      .then(setVehicle)
      .catch((cause) => {
        if (cause instanceof ApiError && cause.status === 404) setNotFound(true);
        else setError(loadErrorMessage(cause, "Could not load this vehicle."));
      });
    api.members(activeHomeId).then(setMembers).catch(() => setMembers([]));
  }, [activeHomeId, vehicleId]);

  // MOT data applies to UK vehicles only (DVSA).
  const motEligible = vehicle?.country_code === "GB";
  useEffect(() => {
    if (!activeHomeId || !motEligible) {
      setMot(null);
      return;
    }
    let cancelled = false;
    api
      .vehicleMot(activeHomeId, vehicleId)
      .then((next) => {
        if (!cancelled) setMot(next);
      })
      .catch(() => {
        if (!cancelled) setMot(null);
      });
    return () => {
      cancelled = true;
    };
  }, [activeHomeId, vehicleId, motEligible]);

  const onMotChange = useCallback((next: VehicleMot) => setMot(next), []);
  const motRefresh = useMotRefresh(activeHomeId, vehicleId, mot, onMotChange);

  function selectTab(next: Tab) {
    setTab(next);
    const url = new URL(window.location.href);
    if (next === "overview") url.searchParams.delete("tab");
    else url.searchParams.set("tab", next);
    window.history.replaceState(window.history.state, "", url.toString());
  }

  function onTabKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    const next = event.key === "Home" ? 0 : event.key === "End" ? TABS.length - 1 : (index + step + TABS.length) % TABS.length;
    selectTab(TABS[next]!.id);
    tabRefs.current[next]?.focus();
  }

  async function removeVehicle() {
    if (!activeHomeId || !vehicle) return;
    setDeleteBusy(true);
    setDeleteError("");
    try {
      await api.deleteVehicle(activeHomeId, vehicle.id);
      router.push("/driveway");
    } catch (cause) {
      setDeleteError(cause instanceof ApiError ? cause.message : "Could not remove this vehicle.");
      setDeleteBusy(false);
    }
  }

  async function uploadPhoto(file: File) {
    if (!activeHomeId || !vehicle || photoBusy) return;
    setPhotoBusy(true);
    setPhotoError("");
    try {
      const normalized = await normalizeAvatarFile(file);
      const updated = await api.uploadVehiclePhoto(activeHomeId, vehicle.id, normalized);
      setVehicle(updated);
      setPhotoSheetOpen(false);
    } catch (cause) {
      setPhotoError(
        cause instanceof AvatarProcessingError
          ? cause.message
          : cause instanceof ApiError && (cause.status === 413 || isImageFormatRejection(cause) || classifyAvatarBackendFailure(cause) === "read")
            ? cause.message
            : "We couldn’t update the vehicle photo. Please try again.",
      );
    } finally {
      setPhotoBusy(false);
    }
  }

  async function handlePhotoSelected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) await uploadPhoto(file);
  }

  async function handleNativePhotoPick(source: "camera" | "photos") {
    setPhotoError("");
    try {
      const file = source === "camera" ? await pickAvatarFromCamera() : await pickAvatarFromGallery();
      if (file) await uploadPhoto(file);
    } catch (cause) {
      setPhotoError(cause instanceof NativeAvatarPickerError ? cause.message : "We couldn’t read that photo. Please try another image.");
    }
  }

  if (notFound) {
    return (
      <AppShellContent>
        <main className="standard-page module-page drv-page">
          <Link className="drv-back" href="/driveway">
            <ChevronLeft size={18} aria-hidden="true" /> Driveway
          </Link>
          <p className="empty-mini">That vehicle could not be found.</p>
        </main>
      </AppShellContent>
    );
  }

  if (!activeHomeId || !vehicle) {
    return (
      <AppShellContent>
        <main className="standard-page module-page drv-page">
          <Link className="drv-back" href="/driveway">
            <ChevronLeft size={18} aria-hidden="true" /> Driveway
          </Link>
          <FormStatus error={error} />
          {!error && <p role="status">Loading vehicle…</p>}
        </main>
      </AppShellContent>
    );
  }

  const name = vehicleName(vehicle);
  const isMine = vehicle.owner_user_id === user?.id;
  const owner = members.find((member) => member.user_id === vehicle.owner_user_id);
  const ownerLabel = isMine ? "You" : owner ? firstName(owner.display_name) : "Home member";
  // Only the owner or a Home Admin can set MOT reminders (the API enforces
  // the same rule; this only avoids offering a button that can't work).
  const canNudge = motEligible && (isMine || activeHome?.relationship === "home_admin");
  const state: MotState = mot ? motState(mot.summary.status, mot.summary.due_date) : motState(null, null);
  const hasMotDate = state.daysLeft !== null;
  const checked = checkedAgo(mot?.summary.refreshed_at);
  const reminderHref = `/driveway/${vehicle.id}/mot/reminder`;
  const mileage = mot ? lastMileage(mot.tests) : null;

  const facts = [
    { label: "Year", value: vehicle.year ? String(vehicle.year) : null },
    { label: "Fuel", value: vehicle.fuel_type },
    { label: "Colour", value: vehicle.colour },
    { label: "Last recorded mileage", value: mileage },
  ].filter((row): row is { label: string; value: string } => Boolean(row.value));

  const details = [
    { label: "Make / model", value: [vehicle.make, vehicle.model].filter(Boolean).length ? name : null },
    { label: "Registration", value: formatPlate(vehicle.registration) },
    { label: "Year", value: vehicle.year ? String(vehicle.year) : null },
    { label: "Fuel", value: vehicle.fuel_type },
    { label: "Colour", value: vehicle.colour },
    { label: "Country", value: countryName(vehicle.country_code) },
    { label: "Driver", value: isMine ? "You" : owner?.display_name ?? null },
    {
      label: "Vehicle tax",
      value: vehicle.tax_status
        ? `${vehicle.tax_status}${vehicle.tax_due_date ? ` · due ${formatShortDate(vehicle.tax_due_date)}` : ""}`
        : null,
    },
  ].filter((row): row is { label: string; value: string } => Boolean(row.value));

  const recentTests = mot?.tests.slice(0, 3) ?? [];
  const oldestTestId = mot?.tests[mot.tests.length - 1]?.id;

  return (
    <AppShellContent>
      <main className="standard-page module-page drv-page drv-vehicle-page">
        <Link className="drv-back" href="/driveway">
          <ChevronLeft size={18} aria-hidden="true" /> Driveway
        </Link>

        <div className="drv-vehicle-header">
          <div className={`drv-vehicle-photo${vehicle.photo_version ? "" : " drv-vehicle-photo-empty"}`}>
            <VehiclePhoto homeId={activeHomeId} vehicleId={vehicle.id} version={vehicle.photo_version} label={`${name} photo`} />
            <button
              type="button"
              className="drv-photo-button"
              aria-label="Change vehicle photo"
              onClick={() => setPhotoSheetOpen(true)}
              disabled={photoBusy}
            >
              <Camera size={15} strokeWidth={2.2} aria-hidden="true" />
            </button>
          </div>
          <div className="drv-vehicle-heading">
            <p className="drv-eyebrow">Vehicle</p>
            <h1 className="drv-title drv-title-vehicle">{name}</h1>
            <div className="drv-vehicle-tags">
              <PlateChip registration={vehicle.registration} size="md" />
              <span className="drv-owner-chip">{ownerLabel}</span>
            </div>
          </div>
        </div>
        {!isNativeShell() && (
          <>
            <input ref={libraryInputRef} type="file" accept="image/*" hidden onChange={handlePhotoSelected} />
            <input ref={cameraInputRef} type="file" accept="image/*" capture="environment" hidden onChange={handlePhotoSelected} />
          </>
        )}
        {photoError && (
          <p className="notice error" role="alert">
            {photoError}
          </p>
        )}
        <FormStatus error={error} />

        <div className="rr-segmented drv-tabs" role="tablist" aria-label="Vehicle sections">
          {TABS.map((item, index) => (
            <button
              key={item.id}
              ref={(node) => {
                tabRefs.current[index] = node;
              }}
              type="button"
              role="tab"
              id={`drv-tab-${item.id}`}
              aria-controls={`drv-panel-${item.id}`}
              aria-selected={tab === item.id}
              tabIndex={tab === item.id ? 0 : -1}
              className={`rr-segment${tab === item.id ? " rr-segment-active" : ""}`}
              onClick={() => selectTab(item.id)}
              onKeyDown={(event) => onTabKey(event, index)}
            >
              {item.label}
            </button>
          ))}
        </div>

        {tab === "overview" && (
          <div className="drv-panel drv-overview" role="tabpanel" id="drv-panel-overview" aria-labelledby="drv-tab-overview">
            {motEligible && (
              <section className="drv-card drv-mot-card" aria-label="MOT">
                <div className="drv-mot-row">
                  <span className={`drv-status-tile drv-status-tile-${state.tone}`} aria-hidden="true">
                    {motNeedsAttention(state) ? <ShieldAlert size={26} strokeWidth={1.9} /> : <ShieldCheck size={26} strokeWidth={1.9} />}
                  </span>
                  <div className="drv-mot-copy">
                    <MotPill tone={state.tone}>{motPillLabel(state)}</MotPill>
                    {hasMotDate ? (
                      <>
                        <span className="drv-mot-expiry">{motExpiryText(state)}</span>
                        <span className="drv-muted-small">{[motDaysText(state), checked ? `checked ${checked}` : null].filter(Boolean).join(" · ")}</span>
                      </>
                    ) : (
                      <span className="drv-muted-small">{noMotText(mot)}</span>
                    )}
                  </div>
                  {motRefresh.canRefresh && <RefreshButton busy={motRefresh.busy} onClick={() => void motRefresh.refresh()} />}
                </div>
                {motRefresh.message && (
                  <p className="drv-muted-small" role="status">
                    {motRefresh.message}
                  </p>
                )}
                {canNudge && motNeedsAttention(state) && (
                  <Link className="drv-button drv-button-danger drv-button-compact-height" href={`${reminderHref}?from=vehicle`}>
                    <Bell size={18} aria-hidden="true" /> Set MOT reminder
                  </Link>
                )}
              </section>
            )}
            {facts.length > 0 && <KeyValues rows={facts} />}
          </div>
        )}

        {tab === "mot" && (
          <div className="drv-panel" role="tabpanel" id="drv-panel-mot" aria-labelledby="drv-tab-mot">
            {!motEligible ? (
              <p className="empty-mini">MOT history is only available for vehicles registered in the UK.</p>
            ) : (
              <>
                <div className="drv-mot-head">
                  <div className="drv-mot-copy">
                    <MotPill tone={state.tone}>{motPillLabel(state)}</MotPill>
                    <span className="drv-muted">
                      {hasMotDate
                        ? [motExpiryText(state), checked ? `checked ${checked}` : null].filter(Boolean).join(" · ")
                        : noMotText(mot)}
                    </span>
                  </div>
                  {motRefresh.canRefresh && <RefreshButton busy={motRefresh.busy} onClick={() => void motRefresh.refresh()} />}
                </div>
                {motRefresh.message && (
                  <p className="drv-muted-small" role="status">
                    {motRefresh.message}
                  </p>
                )}
                {recentTests.length > 0 && (
                  <ul className="drv-card drv-tests" aria-label="Recent MOT tests">
                    {recentTests.map((test, index) => {
                      const mileageText = formatMileage(test);
                      const first = test.id === oldestTestId;
                      const summary = first && test.defects.length === 0 ? "first MOT" : first ? `first MOT · ${testSummary(test)}` : testSummary(test);
                      return (
                        <li key={test.id} className="drv-test">
                          <span className={`drv-test-dot${index === 0 ? " drv-test-dot-latest" : ""}`} aria-hidden="true" />
                          <div className="drv-test-body">
                            <div className="drv-test-top">
                              <span className="drv-test-date">{formatShortDate(test.test_date)}</span>
                              <span className={`drv-result drv-result-${test.result}`}>
                                {test.result === "passed" ? "Passed" : test.result === "failed" ? "Failed" : "Result unavailable"}
                              </span>
                            </div>
                            <span className="drv-muted">{[mileageText, summary].filter(Boolean).join(" · ")}</span>
                            {index === 0 && test.test_number && <span className="drv-muted-small">Test no. {test.test_number}</span>}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
                {canNudge && (
                  <Link className="drv-button drv-button-primary" href={`${reminderHref}?from=vehicle-mot`}>
                    <Bell size={18} aria-hidden="true" /> Set MOT reminder
                  </Link>
                )}
                {(mot?.tests.length ?? 0) > 0 && (
                  <Link className="drv-text-link" href={`/driveway/${vehicle.id}/mot`}>
                    View full MOT history <ChevronRight size={16} strokeWidth={2.2} aria-hidden="true" />
                  </Link>
                )}
              </>
            )}
          </div>
        )}

        {tab === "details" && (
          <div className="drv-panel" role="tabpanel" id="drv-panel-details" aria-labelledby="drv-tab-details">
            <KeyValues rows={details} />
            <Link className="drv-button drv-button-secondary" href={`/driveway/${vehicle.id}/details`}>
              <Pencil size={18} aria-hidden="true" /> Edit details
            </Link>
            <button type="button" className="drv-remove" onClick={() => setConfirmingDelete(true)}>
              <Trash2 size={18} aria-hidden="true" /> Remove vehicle
            </button>
          </div>
        )}

        {confirmingDelete && (
          <BottomSheet
            title="Remove vehicle?"
            onDismiss={() => {
              if (!deleteBusy) setConfirmingDelete(false);
            }}
          >
            <p>This will remove {name} from Driveway.</p>
            {deleteError && (
              <p className="notice error" role="alert">
                {deleteError}
              </p>
            )}
            <div className="sheet-actions">
              <button type="button" className="secondary" onClick={() => setConfirmingDelete(false)} disabled={deleteBusy}>
                Cancel
              </button>
              <button type="button" className="danger" onClick={() => void removeVehicle()} disabled={deleteBusy}>
                {deleteBusy ? "Removing…" : "Remove vehicle"}
              </button>
            </div>
          </BottomSheet>
        )}
        {photoSheetOpen && (
          <BottomSheet
            title={vehicle.photo_version ? "Change vehicle photo" : "Add vehicle photo"}
            onDismiss={() => {
              if (!photoBusy) setPhotoSheetOpen(false);
            }}
          >
            <div className="profile-photo-sheet">
              <p className="muted">Choose a clear photo of {name}.</p>
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  if (isNativeShell()) void handleNativePhotoPick("camera");
                  else cameraInputRef.current?.click();
                }}
                disabled={photoBusy}
              >
                <Camera size={18} aria-hidden="true" /> Take photo
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  if (isNativeShell()) void handleNativePhotoPick("photos");
                  else libraryInputRef.current?.click();
                }}
                disabled={photoBusy}
              >
                Choose from library
              </button>
              <button type="button" className="tertiary" onClick={() => setPhotoSheetOpen(false)} disabled={photoBusy}>
                Cancel
              </button>
            </div>
          </BottomSheet>
        )}
      </main>
    </AppShellContent>
  );
}
