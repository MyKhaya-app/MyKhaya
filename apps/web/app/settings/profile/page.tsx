"use client";
import { ChangeEvent, FormEvent, useCallback, useEffect, useRef, useState } from "react";
import type { Member, User } from "@mykhaya/shared-types";
import type { ColourKey } from "@mykhaya/design-tokens";
import { api, ApiError } from "@mykhaya/api-client";
import { Bell, Camera, ChevronRight, Shield, Trash2 } from "lucide-react";
import Link from "next/link";
import { Avatar } from "@/components/avatar";
import { ColourSwatchPicker } from "@/components/colour-swatch-picker";
import { BottomSheet } from "@/components/bottom-sheet";
import { SettingsPage } from "@/components/settings-page";
import { Toast } from "@/components/toast";
import { useActiveHome } from "@/components/use-active-home";
import { emitUserUpdated } from "@/components/user-events";
import { normalizeAvatarFile, isImageFormatRejection } from "@/components/avatar-upload";
import { isNativeShell } from "@/components/native-runtime";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const MAX_AVATAR_BYTES = 5 * 1024 * 1024;

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
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function handleAvatarSelected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    // Reset so choosing the same file again (e.g. after fixing it) still fires onChange.
    event.target.value = "";
    // No file: either the user cancelled the native picker (Photo Library or
    // Take Photo) or, for the camera specifically, iOS denied/never granted
    // camera permission — both surface identically here (no change event
    // fires, or files is empty), and both should silently return rather than
    // show an error, per the existing "cancel is not a failure" behaviour.
    if (!file) return;

    setAvatarError("");
    setPhotoSheetOpen(false);
    if (file.size > MAX_AVATAR_BYTES) {
      setAvatarError("That photo is too large. Please choose one under 5 MB.");
      return;
    }

    setAvatarBusy(true);
    try {
      const normalized = await normalizeAvatarFile(file);
      const updated = await api.uploadAvatar(normalized);
      setUser(updated);
      emitUserUpdated(updated);
      setMessage("Your photo was updated.");
    } catch (cause) {
      // TEMPORARY diagnostic for the iOS HEIC investigation — see
      // components/avatar-upload.ts's logAvatarDiagnostic.
      console.debug("[avatar-upload] upload-rejected", {
        native: isNativeShell(),
        status: cause instanceof ApiError ? cause.status : undefined,
        message: cause instanceof ApiError ? cause.message : String(cause),
      });
      if (cause instanceof ApiError && isImageFormatRejection(cause)) {
        // IMAGE PROCESSING FAILURE — the backend's own wording ("...JPEG,
        // PNG or WebP") is meant for troubleshooting, not an ordinary iPhone
        // photo owner who doesn't know (and shouldn't need to know) what
        // HEIC is.
        setAvatarError("We couldn't process that photo. Please try another image.");
      } else if (cause instanceof ApiError) {
        // UPLOAD FAILURE with a specific, already user-appropriate reason
        // (rate limit, auth, etc.) — existing behaviour, unchanged.
        setAvatarError(cause.message);
      } else {
        // UPLOAD FAILURE with no specific reason available (network error).
        setAvatarError("Could not upload that photo. Please try again.");
      }
    } finally {
      setAvatarBusy(false);
    }
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
    <SettingsPage title="Your profile" className="profile-page">
      <p className="profile-supporting-line">Keep your details up to date</p>
      {user && (
        <section className="card profile-identity-card">
          <div className="profile-identity-main">
            <Avatar
              id={user.id}
              name={user.display_name}
              colour={membership?.colour}
              avatarVersion={user.avatar_version}
              size="xl"
            />
            <div className="profile-identity-copy">
              <h2>{user.display_name}</h2>
              <p>{activeHome?.name ?? "Your Home"}</p>
              {membership && roleLabel(membership.relationship) && (
                <span className="profile-role-pill">{roleLabel(membership.relationship)}</span>
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
                {avatarBusy ? "Working…" : "Change photo"}
              </button>
              {user.avatar_version && (
                <button
                  type="button"
                  className="tertiary"
                  onClick={handleRemoveAvatar}
                  disabled={avatarBusy}
                >
                  Remove photo
                </button>
              )}
          </div>
          <input
            ref={libraryInputRef}
            type="file"
            // Deliberately does NOT list image/heic or image/heif here. On iOS,
            // WKWebView/Safari auto-transcodes a HEIC Photos-library asset to
            // JPEG before handing it to the page ONLY when the input's accept
            // list doesn't itself claim to accept HEIC/HEIF — declaring those
            // types (as the previous version of this input did) tells iOS the
            // page wants the original bytes, which suppresses that built-in
            // conversion and is why real iPhone photos were arriving as raw
            // HEIC and being rejected. Photos are not filtered out of the
            // picker by this narrower list; iOS matches by broad image
            // conformance and still offers HEIC-source photos, it just
            // converts them for us on the way out. normalizeAvatarFile()
            // below remains a client-side fallback for the rare case a raw
            // HEIC/HEIF file still arrives (Files app, older iOS, non-Apple
            // devices), and the server's pillow-heif decode is the final,
            // authoritative fallback either way.
            accept="image/jpeg,image/png,image/webp"
            style={{ display: "none" }}
            onChange={handleAvatarSelected}
          />
          <input
            ref={cameraInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            capture="environment"
            style={{ display: "none" }}
            onChange={handleAvatarSelected}
          />
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
            Used for your avatar and anywhere you show up as yourself in{" "}
            {activeHome?.name ?? "your Home"} — not your calendar events, which take
            their colour from their Calendar Tag (or the calendar itself, if untagged).
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

      <section className="card profile-info-card">
        <h2>Account details</h2>
        <dl>
          <div>
            <dt>Name</dt>
            <dd>{user?.display_name ?? "—"}</dd>
          </div>
          <div>
            <dt>Email</dt>
            <dd>{user?.email ?? "—"}</dd>
          </div>
          <div>
            <dt>Email status</dt>
            <dd>{user?.email_verified ? "Verified" : "Verification needed"}</dd>
          </div>
          {membership && roleLabel(membership.relationship) && (
            <div>
              <dt>Role</dt>
              <dd>{roleLabel(membership.relationship)}</dd>
            </div>
          )}
        </dl>
      </section>

      <section className="profile-settings-links" aria-label="Profile settings">
        <Link className="card profile-settings-row" href="/settings/security">
          <span className="profile-settings-icon"><Shield size={19} aria-hidden="true" /></span>
          <span><strong>Security</strong><small>Password and account protection</small></span>
          <ChevronRight size={19} aria-hidden="true" />
        </Link>
        <Link className="card profile-settings-row" href="/settings/notifications">
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
      {user && (
        <form className="card profile-birthday-card" onSubmit={saveBirthday}>
          <h2>Your birthday</h2>
          <p>
            Shared with your household so they can wish you well and MyKhaya can remind
            everyone. We never calculate or show your age from this.
          </p>
          <label>
            Month
            <select name="birth_month" defaultValue={user.birth_month ?? ""}>
              <option value="">Not set</option>
              {MONTHS.map((name, index) => (
                <option key={name} value={index + 1}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Day
            <input
              type="number"
              name="birth_day"
              min={1}
              max={31}
              defaultValue={user.birth_day ?? ""}
            />
          </label>
          <button disabled={saving}>{saving ? "Saving…" : "Save birthday"}</button>
        </form>
      )}

      {photoSheetOpen && user && (
        <BottomSheet title="Change your photo" onDismiss={() => setPhotoSheetOpen(false)}>
          <div className="profile-photo-sheet">
            <p className="muted">Choose a clear photo for your MyKhaya profile.</p>
            <button type="button" className="secondary" onClick={() => cameraInputRef.current?.click()}>
              <Camera size={18} aria-hidden="true" /> Take photo
            </button>
            <button type="button" className="secondary" onClick={() => libraryInputRef.current?.click()}>
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
