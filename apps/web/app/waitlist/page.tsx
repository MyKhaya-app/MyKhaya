"use client";

import { FormEvent, useState } from "react";
import { api, ApiError } from "@mykhaya/api-client";
import { AuthCard } from "@/components/auth-card";
import { FormStatus } from "@/components/form-status";
import Link from "next/link";

export default function Waitlist() {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const data = new FormData(event.currentTarget);
    const text = (key: string) => {
      const value = data.get(key);
      return typeof value === "string" ? value : "";
    };
    try {
      await api.joinBetaWaitlist({
        name: text("name"),
        email: text("email"),
        country: text("country").toUpperCase(),
        household_size: data.get("household_size") ? Number(data.get("household_size")) : undefined,
        use_case: text("use_case") || undefined,
        marketing_consent: data.get("marketing_consent") === "on",
      });
      setDone(true);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "We couldn’t join the waitlist. Please try again.");
    } finally {
      setBusy(false);
    }
  }
  if (done) {
    return <AuthCard title="You’re on the waitlist" intro="We’ve recorded your interest in the Founding Beta."><p>Joining the waitlist does not reserve a place. We’ll contact you if a place becomes available.</p><Link className="button full" href="/">Return to MyKhaya</Link></AuthCard>;
  }
  return (
    <AuthCard title="Join the Founding Beta waitlist" intro="Tell us a little about your household. Joining the waitlist does not reserve a place.">
      <form onSubmit={submit}>
        <label>Name<input name="name" autoComplete="name" required maxLength={160} /></label>
        <label>Email<input name="email" type="email" autoComplete="email" required maxLength={320} /></label>
        <label>Country<input name="country" placeholder="GB" required minLength={2} maxLength={2} /></label>
        <label>Household size <small>Optional</small><input name="household_size" type="number" min={1} max={100} /></label>
        <label>How would you use MyKhaya? <small>Optional</small><textarea name="use_case" maxLength={500} rows={4} /></label>
        <label className="check-row"><input name="marketing_consent" type="checkbox" /> <span>Send me occasional product updates and Beta news.</span></label>
        <p className="hint">Please review our <Link href="/legal/privacy">Privacy Notice</Link> before submitting.</p>
        <FormStatus error={error} />
        <button disabled={busy}>{busy ? "Joining…" : "Join the waitlist"}</button>
      </form>
    </AuthCard>
  );
}
