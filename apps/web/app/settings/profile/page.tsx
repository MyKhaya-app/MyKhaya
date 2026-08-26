"use client";
import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import type { Member, User } from "@mykhaya/shared-types";
import type { ColourKey } from "@mykhaya/design-tokens";
import { api, ApiError } from "@mykhaya/api-client";
import { Avatar } from "@/components/avatar";
import { ColourSwatchPicker } from "@/components/colour-swatch-picker";
import { SettingsPage } from "@/components/settings-page";
import { useActiveHome } from "@/components/use-active-home";
import { emitUserUpdated } from "@/components/user-events";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const MAX_AVATAR_BYTES = 5 * 1024 * 1024;

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
  const fileInputRef = useRef<HTMLInputElement>(null);

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
      setMessage("Birthday saved.");
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
    if (!file) return;

    setAvatarError("");
    if (file.size > MAX_AVATAR_BYTES) {
      setAvatarError("That photo is too large. Please choose one under 5 MB.");
      return;
    }

    setAvatarBusy(true);
    try {
      const updated = await api.uploadAvatar(file);
      setUser(updated);
      emitUserUpdated(updated);
    } catch (cause) {
      setAvatarError(
        cause instanceof ApiError
          ? cause.message
          : "Could not upload that photo. Please try again.",
      );
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

  return (
    <SettingsPage title="Your profile">
      {user && (
        <section className="card details avatar-editor">
          <h2>Your photo</h2>
          <div className="avatar-editor-row">
            <Avatar
              id={user.id}
              name={user.display_name}
              colour={membership?.colour}
              avatarVersion={user.avatar_version}
              size="xl"
            />
            <div className="avatar-editor-actions">
              <button
                type="button"
                className="secondary"
                onClick={() => fileInputRef.current?.click()}
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
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/heic,image/heif"
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
        <section className="card details">
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

      <section className="card details">
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
        </dl>
      </section>

      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}

      {user && (
        <form className="card details" onSubmit={saveBirthday}>
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
    </SettingsPage>
  );
}
