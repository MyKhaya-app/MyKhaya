"use client";
import { FormEvent, useEffect, useState } from "react";
import type { User } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { SettingsPage } from "@/components/settings-page";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export default function Profile() {
  const [user, setUser] = useState<User | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.me().then(setUser);
  }, []);

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

  return (
    <SettingsPage title="Your profile">
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
