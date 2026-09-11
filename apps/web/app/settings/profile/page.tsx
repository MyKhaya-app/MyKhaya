"use client";
import { ChangeEvent, FormEvent, useCallback, useEffect, useRef, useState } from "react";
import type { Member, User } from "@mykhaya/shared-types";
import type { ColourKey } from "@mykhaya/design-tokens";
import { api, ApiError } from "@mykhaya/api-client";
import { Bell, Camera, ChevronRight, Home, Shield, Trash2, UserRound } from "lucide-react";
import Link from "next/link";
import { Avatar } from "@/components/avatar";
import { ColourSwatchPicker } from "@/components/colour-swatch-picker";
import { BottomSheet } from "@/components/bottom-sheet";
import { SettingsPage } from "@/components/settings-page";
import { Toast } from "@/components/toast";
import { useActiveHome } from "@/components/use-active-home";
import { emitUserUpdated } from "@/components/user-events";
import { isNativeShell } from "@/components/native-runtime";
import {
  AvatarProcessingError,
  classifyAvatarBackendFailure,
  isImageFormatRejection,
  logAvatarDiagnostic,
  normalizeAvatarFile,
} from "@/components/avatar-upload";
import {
  NativeAvatarPickerError,
  pickAvatarFromCamera,
  pickAvatarFromGallery,
} from "@/components/native-avatar-picker";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function roleLabel(relationship?: Member["relationship"]) {
  switch (relationship) {
    case "home_admin": return "Home admin";
    case "partner": return "Partner";
    case "child": return "Child";
    case "extended_family": return "Extended family";
    case "friend": return "Friend";
    case "adult": return "Adult";
    default: return undefined;
  }
}

// "6 February" — day first, full month name, per the profile summary's
// natural-language presentation (see profile-info-card below). Both fields
// are required for a formatted date; a month or day saved on its own (the
// two selects are independent) reads as "Not set" rather than a partial,
// confusing date.
function birthdayLabel(user: User | null) {
  if (!user?.birth_month || !user?.birth_day) return "Not set";
  return `${user.birth_day} ${MONTHS[user.birth_month - 1]}`;
}

export default function Profile() {
  const { activeHomeId, activeHome } = useActiveHome();
  const [user, setUser] = useState<User | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [avatarBusy, setAvatarBusy] = useState(false);
  const [avatarError, setAvatarError] = useState("");
  const [membership, setMembership] = useState<Member | null>(null);
  const [colourBusy, setColourBusy] = useState(false);
  const [colourError, setColourError] = useState("");
  const [photoSheetOpen, setPhotoSheetOpen] = useState(false);
  const [editingBirthday, setEditingBirthday] = useState(false);
  const libraryInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.me().then(setUser);
  }, []);

  useEffect(() => {
    if (!activeHomeId || !user) return;
    api
      .members(activeHomeId)
      .then((rows) => setMembership(rows.find((row) => row.user_id === user.id) ?? null));
  }, [activeHomeId, user]);

  async function changeColour(colour: ColourKey) {
    if (!activeHomeId || !user || colourBusy) return;
    setColourError("");
    setColourBusy(true);
    try {
      const updated = await api.updateMemberColour(activeHomeId, user.id, colour);
      setMembership(updated);
      setMessage("Your colour was updated.");
    } catch (cause) {
      setColourError(
        cause instanceof ApiError ? cause.message : "Could not update your colour.",
      );
    } finally {
      setColourBusy(false);
    }
  }

  async function saveBirthday(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");
    const form = new FormData(event.currentTarget);
    const month = form.get("birth_month");
    const day = form.get("birth_day");
    try {
      const updated = await api.updateMyBirthday({
        birth_month: month ? Number(month) : null,
        birth_day: day ? Number(day) : null,
      });
      setUser(updated);
      setMessage("Your birthday was saved.");
      setEditingBirthday(false);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setSaving(false);
    }
  }

  // Shared by both selection paths (HTML file input for web/PWA, Capacitor
  // Camera plugin for the native iOS shell — see native-avatar-picker.ts and
  // ADR 0013's native/browser avatar selection boundary): once a File has
  // been obtained by whichever path, everything from here on is identical —
  // the backend is the single image-processing authority regardless of
  // where the File came from.
  async function uploadAvatarFile(
    file: File,
    meta: { source: string; sourceType: string; uriScheme: string },
  ) {
    logAvatarDiagnostic("picker-returned-to-profile", {
      selectedAssetAvailable: true,
      ...meta,
      constructor: file.constructor?.name || "unknown",
      name: file.name,
      extension: file.name.match(/\.([^.]+)$/)?.[1]?.toLowerCase() || "(none)",
      type: file.type || "(empty)",
      size: file.size,
    });

    setAvatarError("");
    setPhotoSheetOpen(false);
    setAvatarBusy(true);
    try {
      const normalized = await normalizeAvatarFile(file);
      logAvatarDiagnostic("upload-request-prepared", {
        name: normalized.name,
        type: normalized.type || "(empty)",
        size: normalized.size,
      });
      const updated = await api.uploadAvatar(normalized);
      setUser(updated);
      emitUserUpdated(updated);
      setMessage("Your photo was updated.");
    } catch (cause) {
      logAvatarDiagnostic("upload-failed", {
        category:
          cause instanceof AvatarProcessingError
            ? cause.category
            : cause instanceof ApiError
              ? classifyAvatarBackendFailure(cause) ?? (cause.status >= 500 ? "server" : "upload")
              : "network",
        errorName: cause instanceof Error ? cause.name : "UnknownError",
        status: cause instanceof ApiError ? cause.status : undefined,
        message: cause instanceof Error ? cause.message : String(cause),
      });
      if (cause instanceof AvatarProcessingError) {
        setAvatarError(
          cause.category === "unsupported"
            ? "This image format isn’t supported. Please choose a JPEG, PNG or another supported photo."
            : cause.category === "read"
              ? "We couldn’t read that photo from your device. Please try selecting it again."
              : "We couldn’t prepare that photo for upload. Please try another image.",
        );
      } else if (cause instanceof ApiError && cause.status === 413) {
        setAvatarError(
          /too large to process/i.test(cause.message)
            ? "That photo is too large to process. Please choose another image."
            : "This photo is too large to upload. Please choose a smaller image.",
        );
      } else if (cause instanceof ApiError && isImageFormatRejection(cause)) {
        // IMAGE PROCESSING FAILURE — the backend's own wording ("...JPEG,
        // PNG or WebP") is meant for troubleshooting, not an ordinary iPhone
        // photo owner who doesn't know (and shouldn't need to know) what
        // HEIC is.
        setAvatarError("This photo format isn’t supported. Please choose another photo.");
      } else if (cause instanceof ApiError && classifyAvatarBackendFailure(cause) === "read") {
        setAvatarError("We couldn’t read that photo from your device. Please try selecting it again.");
      } else if (cause instanceof ApiError) {
        // UPLOAD FAILURE with a specific, already user-appropriate reason
        // (rate limit, auth, etc.) — existing behaviour, unchanged.
        setAvatarError(
          cause.status >= 500
            ? "Your photo couldn’t be saved right now. Please try again shortly."
            : cause.status === 401 || cause.status === 403
              ? "Please sign in again before changing your photo."
              : "We couldn’t update your photo. Please try again.",
        );
      } else {
        setAvatarError("We couldn’t upload your photo. Please check your connection and try again.");
      }
    } finally {
      setAvatarBusy(false);
    }
  }

  // Web/PWA path only — the native iOS shell never invokes this hidden
  // input (see the bottom-sheet buttons below and native-avatar-picker.ts).
  async function handleAvatarSelected(
    event: ChangeEvent<HTMLInputElement>,
    source: "camera" | "photo-library",
  ) {
    const file = event.target.files?.[0];
    // Reset so choosing the same file again (e.g. after fixing it) still fires onChange.
    event.target.value = "";
    // No file: the user cancelled the native OS picker (Photo Library or
    // Take Photo) — silently return rather than show an error, matching the
    // native Capacitor path's own cancel behaviour below.
    if (!file) return;
    await uploadAvatarFile(file, {
      source,
      sourceType: "browser-file",
      uriScheme: "(not exposed by HTML file input)",
    });
  }

  // Native iOS shell path only — uses the Capacitor Camera plugin's native
  // Photos/Camera picker instead of the HTML file input (ADR 0013). Cancel
  // returns null (no error, matching the HTML path); every other failure is
  // a NativeAvatarPickerError with an already user-appropriate message.
  async function handleNativeAvatarPick(source: "camera" | "photos") {
    setAvatarError("");
    let file: File | null;
    try {
      file = source === "camera" ? await pickAvatarFromCamera() : await pickAvatarFromGallery();
    } catch (cause) {
      setPhotoSheetOpen(false);
      setAvatarError(
        cause instanceof NativeAvatarPickerError
          ? cause.message
          : "We couldn’t upload your photo. Please check your connection and try again.",
      );
      return;
    }
    if (!file) return;
    await uploadAvatarFile(file, {
      source,
      sourceType: "capacitor-camera-plugin",
      uriScheme: "webPath (Capacitor local scheme, fetched then converted to Blob)",
    });
  }

  async function handleRemoveAvatar() {
    setAvatarError("");
    setAvatarBusy(true);
    try {
      const updated = await api.removeAvatar();
      setUser(updated);
      emitUserUpdated(updated);
      setPhotoSheetOpen(false);
      setMessage("Your photo was removed.");
    } catch (cause) {
      setAvatarError(
        cause instanceof ApiError
          ? cause.message
          : "Could not remove your photo. Please try again.",
      );
    } finally {
      setAvatarBusy(false);
    }
  }

  const dismissMessage = useCallback(() => setMessage(""), []);

  return (
    <SettingsPage title="Your profile" className="profile-page module-page">
      <p className="profile-supporting-line">Keep your details up to date</p>
      {user && (
        <section className="card profile-identity-card">
          <div className="profile-identity-main">
            <span className="profile-avatar-wrap">
              <Avatar
                id={user.id}
                name={user.display_name}
                colour={membership?.colour}
                avatarVersion={user.avatar_version}
                size="xl"
              />
            </span>
            <div className="profile-identity-copy">
              <h2>{user.display_name}</h2>
              <p className="profile-home-line"><Home size={16} aria-hidden="true" /> {activeHome?.name ?? "Your Home"}</p>
              {membership && roleLabel(membership.relationship) && (
                <span className="profile-role-pill"><UserRound size={14} aria-hidden="true" /> {roleLabel(membership.relationship)}</span>
              )}
            </div>
          </div>
          <div className="profile-photo-actions">
              <button
                type="button"
                className="secondary"
                onClick={() => setPhotoSheetOpen(true)}
                disabled={avatarBusy}
              >
                <Camera size={17} aria-hidden="true" />
                {avatarBusy ? "Working…" : "Change photo"}
              </button>
              {user.avatar_version && (
                <button
                  type="button"
                  className="tertiary"
                  onClick={handleRemoveAvatar}
                  disabled={avatarBusy}
                >
                  <Trash2 size={17} aria-hidden="true" />
                  Remove photo
                </button>
              )}
          </div>
          {/* Web/PWA only — the native iOS shell uses the Capacitor Camera
              plugin's native picker instead (native-avatar-picker.ts) and
              never renders or invokes this hidden input at all; the
              unreliable WKWebView Photos-library <input type="file"> path
              this replaced is exactly why that split exists — see ADR
              0013's native/browser avatar selection boundary. */}
          {!isNativeShell() && (
            <>
              <input
                ref={libraryInputRef}
                type="file"
                // "Allow the user to choose an image" — never an enumerated
                // MIME list. WKWebView's Photos-library transcoding
                // behaviour is sensitive to *which* image MIME types accept
                // declares: explicitly listing image/heic,image/heif
                // alongside others has been observed to change whether iOS
                // hands the picker a transcoded JPEG or the original
                // HEIC/HEIF bytes for a given asset. image/* asks for "any
                // image" without taking a position on that, and the server
                // owns real image decoding/validation regardless of what
                // bytes actually arrive — see ADR 0013's "Shared binary
                // upload processing" for the full rationale.
                accept="image/*"
                style={{ display: "none" }}
                onChange={(event) => handleAvatarSelected(event, "photo-library")}
              />
              <input
                ref={cameraInputRef}
                type="file"
                accept="image/*"
                capture="environment"
                style={{ display: "none" }}
                onChange={(event) => handleAvatarSelected(event, "camera")}
              />
            </>
          )}
          {avatarError && (
            <p className="notice error" role="alert">
              {avatarError}
            </p>
          )}
        </section>
      )}

      {user && membership && (
        <section className="card profile-colour-card">
          <h2>Your colour</h2>
          <p className="muted">
            Used for your avatar and anywhere you show up in {activeHome?.name ?? "your Home"}.
          </p>
          <ColourSwatchPicker
            value={membership.colour}
            onChange={changeColour}
            groupLabel="Your colour"
            disabled={colourBusy}
          />
          {colourError && (
            <p className="notice error" role="alert">
              {colourError}
            </p>
          )}
        </section>
      )}

      <section className="card details profile-info-card">
        <h2>Account details</h2>
        <dl>
          <div>
            <dt>Name</dt>
            <dd>{user?.display_name ?? "—"}</dd>
          </div>
          <div>
            <dt>Email</dt>
            <dd className="profile-detail-value">
              <span>{user?.email ?? "—"}</span>
              {user && (
                <span className={`profile-verified-pill${user.email_verified ? "" : " unverified"}`}>
                  {user.email_verified ? "Verified" : "Verification needed"}
                </span>
              )}
            </dd>
          </div>
          <div>
            <dt>Home role</dt>
            <dd>{(membership && roleLabel(membership.relationship)) ?? "—"}</dd>
          </div>
          <div>
            <dt>Birthday</dt>
            <dd className="profile-detail-value">
              <span>{birthdayLabel(user)}</span>
              {!editingBirthday && (
                <button type="button" className="tertiary" onClick={() => setEditingBirthday(true)}>
                  Edit
                </button>
              )}
            </dd>
          </div>
        </dl>
        <p className="muted profile-birthday-hint">
          Shared with your household so they can wish you well.
        </p>
        {editingBirthday && user && (
          <form className="profile-birthday-edit" onSubmit={saveBirthday}>
            <div className="profile-birthday-fields">
              <label>
                Month
                <select name="birth_month" defaultValue={user.birth_month ?? ""}>
                  <option value="">Not set</option>
                  {MONTHS.map((name, index) => (
                    <option key={name} value={index + 1}>{name}</option>
                  ))}
                </select>
              </label>
              <label>
                Day
                <input type="number" name="birth_day" min={1} max={31} defaultValue={user.birth_day ?? ""} />
              </label>
            </div>
            <div className="profile-birthday-edit-actions">
              <button type="submit" disabled={saving}>
                {saving ? "Saving…" : "Save"}
              </button>
              <button
                type="button"
                className="tertiary"
                onClick={() => {
                  setEditingBirthday(false);
                  setError("");
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </section>

      <section className="card profile-settings-links" aria-label="Profile settings">
        <Link className="profile-settings-row" href="/settings/security">
          <span className="profile-settings-icon"><Shield size={19} aria-hidden="true" /></span>
          <span><strong>Security</strong><small>Password and account protection</small></span>
          <ChevronRight size={19} aria-hidden="true" />
        </Link>
        <Link className="profile-settings-row" href="/settings/notifications">
          <span className="profile-settings-icon"><Bell size={19} aria-hidden="true" /></span>
          <span><strong>Notifications</strong><small>Choose how MyKhaya keeps you informed</small></span>
          <ChevronRight size={19} aria-hidden="true" />
        </Link>
      </section>

      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {photoSheetOpen && user && (
        <BottomSheet title="Change your photo" onDismiss={() => setPhotoSheetOpen(false)}>
          <div className="profile-photo-sheet">
            <p className="muted">Choose a clear photo for your MyKhaya profile.</p>
            {/* Structured selection logic (ADR 0013): native iOS uses the
                Capacitor Camera plugin; web/PWA uses the hidden HTML file
                input. Same two visible actions either way — only what
                happens behind them differs. */}
            <button type="button" className="secondary" onClick={() => {
              if (isNativeShell()) {
                void handleNativeAvatarPick("camera");
                return;
              }
              logAvatarDiagnostic("picker-opened", { source: "camera" });
              cameraInputRef.current?.click();
            }}>
              <Camera size={18} aria-hidden="true" /> Take photo
            </button>
            <button type="button" className="secondary" onClick={() => {
              if (isNativeShell()) {
                void handleNativeAvatarPick("photos");
                return;
              }
              logAvatarDiagnostic("picker-opened", { source: "photo-library" });
              libraryInputRef.current?.click();
            }}>
              Choose from library
            </button>
            {user.avatar_version && (
              <button type="button" className="tertiary" onClick={handleRemoveAvatar} disabled={avatarBusy}>
                <Trash2 size={18} aria-hidden="true" /> Remove photo
              </button>
            )}
            <button type="button" className="tertiary" onClick={() => setPhotoSheetOpen(false)}>
              Cancel
            </button>
          </div>
        </BottomSheet>
      )}

      <Toast message={message} onDismiss={dismissMessage} />
    </SettingsPage>
  );
}
