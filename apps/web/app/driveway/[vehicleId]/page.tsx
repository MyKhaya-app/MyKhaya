"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChangeEvent, use, useEffect, useRef, useState } from "react";
import { Bell, Camera, Car, ChevronLeft, Info, Trash2 } from "lucide-react";
import type { Vehicle } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { BottomSheet } from "@/components/bottom-sheet";
import { FormStatus } from "@/components/form-status";
import { useActiveHome } from "@/components/use-active-home";
import { countryName } from "../countries";
import { fetchNativeImage } from "@/components/native-auth";
import { isNativeShell } from "@/components/native-runtime";
import { AvatarProcessingError, classifyAvatarBackendFailure, isImageFormatRejection, normalizeAvatarFile } from "@/components/avatar-upload";
import { NativeAvatarPickerError, pickAvatarFromCamera, pickAvatarFromGallery } from "@/components/native-avatar-picker";

function vehiclePhotoPath(homeId: string, vehicleId: string, version: string): string {
  return `/homes/${encodeURIComponent(homeId)}/vehicles/${encodeURIComponent(vehicleId)}/photo?v=${encodeURIComponent(version)}`;
}

function VehiclePhoto({ homeId, vehicleId, version, label }: { homeId: string; vehicleId: string; version: string | null; label: string }) {
  const [nativeUrl, setNativeUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setFailed(false);
    setNativeUrl(null);
    if (!isNativeShell() || !version) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    void fetchNativeImage(vehiclePhotoPath(homeId, vehicleId, version)).then((blob) => {
      if (cancelled) return;
      objectUrl = URL.createObjectURL(blob);
      setNativeUrl(objectUrl);
    }).catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [homeId, vehicleId, version]);
  if (!version || failed || (isNativeShell() && !nativeUrl)) return <Car size={42} aria-hidden="true" />;
  return <img src={isNativeShell() ? nativeUrl ?? undefined : `/api/v1${vehiclePhotoPath(homeId, vehicleId, version)}`} alt={label} onError={() => setFailed(true)} />;
}

function loadErrorMessage(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError && cause.status === 404) {
    return "That vehicle could not be found.";
  }
  return cause instanceof ApiError ? cause.message : fallback;
}

export default function VehicleDetailPage({ params }: { params: Promise<{ vehicleId: string }> }) {
  const { vehicleId } = use(params);
  const { activeHomeId } = useActiveHome();
  const router = useRouter();
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
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
  }, [activeHomeId, vehicleId]);

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
      setPhotoError(cause instanceof AvatarProcessingError
        ? cause.message
        : cause instanceof ApiError && (cause.status === 413 || isImageFormatRejection(cause) || classifyAvatarBackendFailure(cause) === "read")
          ? cause.message
          : "We couldn’t update the vehicle photo. Please try again.");
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
        <main className="standard-page">
          <Link className="tertiary" href="/driveway">
            <ChevronLeft size={16} aria-hidden="true" /> Driveway
          </Link>
          <p className="empty-mini">That vehicle could not be found.</p>
        </main>
      </AppShellContent>
    );
  }

  if (!activeHomeId || !vehicle) {
    return (
      <AppShellContent>
        <main className="standard-page">
          <p role="status">Loading vehicle…</p>
        </main>
      </AppShellContent>
    );
  }

  const rows: { label: string; value: string }[] = [
    { label: "Make / model", value: [vehicle.make, vehicle.model].filter(Boolean).join(" ") },
    { label: "Registration", value: vehicle.registration ?? "" },
    { label: "Year", value: vehicle.year ? String(vehicle.year) : "" },
    { label: "Fuel", value: vehicle.fuel_type ?? "" },
    { label: "Colour", value: vehicle.colour ?? "" },
    { label: "Country", value: countryName(vehicle.country_code) },
  ].filter((row) => row.value);

  return (
    <AppShellContent>
      <main className="standard-page driveway-detail-page">
        <Link className="tertiary" href="/driveway">
          <ChevronLeft size={16} aria-hidden="true" /> Driveway
        </Link>
        <div className="page-heading">
          <div>
            <p className="eyebrow">Vehicle</p>
            <h1>{vehicle.nickname}</h1>
            {vehicle.registration && <p className="muted">{vehicle.registration}</p>}
          </div>
        </div>
        <FormStatus error={error} />

        <section className="card vehicle-photo-card">
          <div className="vehicle-photo-preview">
            <VehiclePhoto homeId={activeHomeId} vehicleId={vehicle.id} version={vehicle.photo_version} label={`${vehicle.nickname} vehicle`} />
          </div>
          <div className="vehicle-photo-copy">
            <strong>{vehicle.photo_version ? "Vehicle photo" : "Add a vehicle photo"}</strong>
            <p className="muted">Keep a clear photo of your car with its details.</p>
            <button type="button" className="secondary" onClick={() => setPhotoSheetOpen(true)} disabled={photoBusy}>
              <Camera size={17} aria-hidden="true" /> {photoBusy ? "Working…" : vehicle.photo_version ? "Change photo" : "Add photo"}
            </button>
          </div>
          {!isNativeShell() && <>
            <input ref={libraryInputRef} type="file" accept="image/*" style={{ display: "none" }} onChange={handlePhotoSelected} />
            <input ref={cameraInputRef} type="file" accept="image/*" capture="environment" style={{ display: "none" }} onChange={handlePhotoSelected} />
          </>}
          {photoError && <p className="notice error" role="alert">{photoError}</p>}
        </section>

        <div className="card-stack">
          {rows.length > 0 && (
            <section className="card details">
              <dl>
                {rows.map((row) => (
                  <div key={row.label}>
                    <dt>{row.label}</dt>
                    <dd>{row.value}</dd>
                  </div>
                ))}
              </dl>
            </section>
          )}

          <section className="card more-group">
            <div className="more-group-rows">
              <Link className="more-row" href={`/driveway/${vehicle.id}/details`}>
                <span className="more-icon-tile sage" aria-hidden="true">
                  <Info size={20} strokeWidth={1.75} />
                </span>
                <span className="more-row-text">
                  <h2>Vehicle details</h2>
                  <p>Edit make, model, registration and more</p>
                </span>
                <span className="more-row-chevron" aria-hidden="true">
                  ›
                </span>
              </Link>
              <Link className="more-row" href={`/driveway/${vehicle.id}/reminders`}>
                <span className="more-icon-tile blue" aria-hidden="true">
                  <Bell size={20} strokeWidth={1.75} />
                </span>
                <span className="more-row-text">
                  <h2>Reminders</h2>
                  <p>MOT, tax, service and anything else to keep an eye on</p>
                </span>
                <span className="more-row-chevron" aria-hidden="true">
                  ›
                </span>
              </Link>
            </div>
          </section>

          <button type="button" className="danger-link" onClick={() => setConfirmingDelete(true)}>
            <Trash2 size={16} aria-hidden="true" /> Remove vehicle
          </button>
        </div>

        {confirmingDelete && (
          <BottomSheet
            title="Remove vehicle?"
            onDismiss={() => {
              if (!deleteBusy) setConfirmingDelete(false);
            }}
          >
            <p>This will remove {vehicle.nickname} from Driveway.</p>
            {deleteError && (
              <p className="notice error" role="alert">
                {deleteError}
              </p>
            )}
            <div className="sheet-actions">
              <button
                type="button"
                className="secondary"
                onClick={() => setConfirmingDelete(false)}
                disabled={deleteBusy}
              >
                Cancel
              </button>
              <button type="button" className="danger" onClick={() => void removeVehicle()} disabled={deleteBusy}>
                {deleteBusy ? "Removing…" : "Remove vehicle"}
              </button>
            </div>
          </BottomSheet>
        )}
        {photoSheetOpen && (
          <BottomSheet title={vehicle.photo_version ? "Change vehicle photo" : "Add vehicle photo"} onDismiss={() => { if (!photoBusy) setPhotoSheetOpen(false); }}>
            <div className="profile-photo-sheet">
              <p className="muted">Choose a clear photo of {vehicle.nickname}.</p>
              <button type="button" className="secondary" onClick={() => { if (isNativeShell()) void handleNativePhotoPick("camera"); else cameraInputRef.current?.click(); }} disabled={photoBusy}>
                <Camera size={18} aria-hidden="true" /> Take photo
              </button>
              <button type="button" className="secondary" onClick={() => { if (isNativeShell()) void handleNativePhotoPick("photos"); else libraryInputRef.current?.click(); }} disabled={photoBusy}>
                Choose from library
              </button>
              <button type="button" className="tertiary" onClick={() => setPhotoSheetOpen(false)} disabled={photoBusy}>Cancel</button>
            </div>
          </BottomSheet>
        )}
      </main>
    </AppShellContent>
  );
}
