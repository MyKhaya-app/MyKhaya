"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import {
  startAuthentication,
  type PublicKeyCredentialRequestOptionsJSON,
} from "@simplewebauthn/browser";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { resolveLoginDestination } from "@/components/platform-mfa-logic";
import type { PlatformActor } from "@/components/platform-types";

type Step = "password" | "verify";
type VerifyMethod = "passkey" | "totp" | "recovery";
type Factor = "passkey" | "totp" | "recovery_code";

export default function PlatformLogin() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("password");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [method, setMethod] = useState<VerifyMethod>("passkey");
  const [availableFactors, setAvailableFactors] = useState<Factor[]>([]);

  function proceed(actor: PlatformActor) {
    const destination = resolveLoginDestination(actor.session_status);
    if (destination === "home") router.replace("/");
    else if (destination === "setup-mfa") router.replace("/setup-mfa");
    else {
      const factors = actor.available_factors ?? [];
      setAvailableFactors(factors);
      setMethod(factors.includes("passkey") ? "passkey" : "totp");
      setStep("verify");
    }
  }

  async function submitPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      const actor = await platformApi.post<PlatformActor>("/auth/login", {
        email: data.get("email"),
        password: data.get("password"),
      });
      proceed(actor);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Administrator sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  async function signInWithPasskey() {
    setBusy(true);
    setError("");
    try {
      const options = await platformApi.post<{ options_json: string }>(
        "/auth/mfa/webauthn/login/options",
        {},
      );
      const credential = await startAuthentication({
        optionsJSON: JSON.parse(options.options_json) as PublicKeyCredentialRequestOptionsJSON,
      });
      const actor = await platformApi.post<PlatformActor>("/auth/mfa/webauthn/login/verify", {
        credential_json: JSON.stringify(credential),
      });
      proceed(actor);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        // No passkey registered for this account — fall back quietly.
        setMethod("totp");
        return;
      }
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Your passkey could not be used to sign in. Try again or use another method.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function submitTotp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      const actor = await platformApi.post<PlatformActor>("/auth/mfa/totp/login-verify", {
        code: data.get("code"),
      });
      proceed(actor);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "That code is not correct.");
    } finally {
      setBusy(false);
    }
  }

  async function submitRecoveryCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      const actor = await platformApi.post<PlatformActor>(
        "/auth/mfa/recovery-codes/login-verify",
        { code: data.get("code") },
      );
      proceed(actor);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "That recovery code is not valid.");
    } finally {
      setBusy(false);
    }
  }

  if (step === "verify") {
    return (
      <main className="platform-login">
        <section>
          <p className="platform-kicker">Restricted management plane</p>
          <h1>Verify it&rsquo;s you</h1>
          <p>This administrator account requires a second step to finish signing in.</p>
          {error && (
            <p className="notice error" role="alert">
              {error}
            </p>
          )}

          {method === "passkey" && (
            <div className="mfa-method">
              <button onClick={signInWithPasskey} disabled={busy}>
                {busy ? "Waiting for your passkey…" : "Sign in with passkey"}
              </button>
              {availableFactors.includes("totp") && (
                <button type="button" className="tertiary" onClick={() => setMethod("totp")}>
                  Use an authenticator app instead
                </button>
              )}
            </div>
          )}

          {method === "totp" && (
            <form onSubmit={submitTotp} className="mfa-method">
              <label>
                6-digit authenticator code
                <input
                  name="code"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  autoComplete="one-time-code"
                  minLength={6}
                  maxLength={6}
                  autoFocus
                  required
                />
              </label>
              <button disabled={busy}>{busy ? "Verifying…" : "Verify"}</button>
              {availableFactors.includes("passkey") && (
                <button type="button" className="tertiary" onClick={() => setMethod("passkey")}>
                  Use my passkey instead
                </button>
              )}
            </form>
          )}

          {method === "recovery" && (
            <form onSubmit={submitRecoveryCode} className="mfa-method">
              <label>
                Recovery code
                <input
                  name="code"
                  autoComplete="off"
                  autoCapitalize="off"
                  autoFocus
                  required
                  maxLength={32}
                />
              </label>
              <button disabled={busy}>{busy ? "Verifying…" : "Verify"}</button>
            </form>
          )}

          {method !== "recovery" && availableFactors.includes("recovery_code") && (
            <p className="mfa-recovery-link">
              <button type="button" className="link-button" onClick={() => setMethod("recovery")}>
                Use a recovery code instead
              </button>
            </p>
          )}
        </section>
      </main>
    );
  }

  return (
    <main className="platform-login">
      <section>
        <p className="platform-kicker">Restricted management plane</p>
        <h1>MyKhaya Platform Control Centre</h1>
        <p>Use your separate operator credentials. Household accounts cannot sign in here.</p>
        <form onSubmit={submitPassword}>
          <label>
            Operator email
            <input name="email" type="email" autoComplete="username" required maxLength={320} />
          </label>
          <label>
            Password
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
              maxLength={128}
            />
          </label>
          {error && (
            <p className="notice error" role="alert">
              {error}
            </p>
          )}
          <button disabled={busy}>{busy ? "Signing in…" : "Sign in to Control Centre"}</button>
        </form>
        <small>Access is logged. Mandatory MFA is required by production policy.</small>
      </section>
    </main>
  );
}
