"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, platformApi } from "@mykhaya/api-client";

export default function PlatformLogin() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const data = new FormData(event.currentTarget);
    try {
      await platformApi.post("/auth/login", { email: data.get("email"), password: data.get("password") });
      router.replace("/");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Administrator sign-in failed.");
    } finally { setBusy(false); }
  }
  return (
    <main className="platform-login">
      <section>
        <p className="platform-kicker">Restricted management plane</p>
        <h1>MyKhaya Platform Control Centre</h1>
        <p>Use your separate operator credentials. Household accounts cannot sign in here.</p>
        <form onSubmit={submit}>
          <label>Operator email<input name="email" type="email" autoComplete="username" required maxLength={320} /></label>
          <label>Password<input name="password" type="password" autoComplete="current-password" required maxLength={128} /></label>
          {error && <p className="notice error" role="alert">{error}</p>}
          <button disabled={busy}>{busy ? "Signing in…" : "Sign in to Control Centre"}</button>
        </form>
        <small>Access is logged. Mandatory MFA is required by production policy.</small>
      </section>
    </main>
  );
}
