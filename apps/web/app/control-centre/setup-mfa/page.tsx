"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import QRCode from "qrcode";
import {
  startRegistration,
  type PublicKeyCredentialCreationOptionsJSON,
} from "@simplewebauthn/browser";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { resolveLoginDestination } from "@/components/platform-mfa-logic";
import type { PlatformActor } from "@/components/platform-types";

type Stage = "loading" | "choose" | "passkey" | "totp" | "recovery-codes" | "done";

export default function SetupMfa() {
  const router = useRouter();
  const [stage, setStage] = useState<Stage>("loading");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [totpSecret, setTotpSecret] = useState<{ secret: string; qr: string } | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);

  useEffect(() => {
    platformApi
      .get<PlatformActor>("/auth/me")
      .then((actor) => {
        const destination = resolveLoginDestination(actor.session_status);
        if (destination === "setup-mfa") setStage("choose");
        else if (destination === "home") router.replace("/");
        else router.replace("/login");
      })
      .catch(() => router.replace("/login"));
  }, [router]);

  // The backend generates recovery codes atomically with whichever request
  // completes the administrator's *first* MFA factor (see
  // routers.platform._issue_recovery_codes_if_first_factor) and returns them
  // on that same response — there is no separate follow-up call that could
  // be interrupted (closed tab, dropped network) and leave the account fully
  // "MFA enrolled" with zero recovery codes.
  function afterFirstFactorEnrolled(actor: PlatformActor) {
    if (actor.recovery_codes && actor.recovery_codes.length > 0) {
      setRecoveryCodes(actor.recovery_codes);
      setStage("recovery-codes");
    } else {
      setStage("done");
    }
  }

  async function startPasskeySetup() {
    setStage("passkey");
    setBusy(true);
    setError("");
    try {
      const options = await platformApi.post<{ options_json: string }>(
        "/auth/mfa/webauthn/register/options",
        {},
      );
      const credential = await startRegistration({
        optionsJSON: JSON.parse(options.options_json) as PublicKeyCredentialCreationOptionsJSON,
      });
      const actor = await platformApi.post<PlatformActor>("/auth/mfa/webauthn/register/verify", {
        label: "My passkey",
        credential_json: JSON.stringify(credential),
      });
      afterFirstFactorEnrolled(actor);
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Setting up your passkey didn't complete. You can try again or use an authenticator app.",
      );
      setStage("choose");
    } finally {
      setBusy(false);
    }
  }

  async function startTotpSetup() {
    setStage("totp");
    setError("");
    try {
      const result = await platformApi.post<{ secret: string; provisioning_uri: string }>(
        "/auth/mfa/totp/setup",
        {},
      );
      const qr = await QRCode.toDataURL(result.provisioning_uri, { margin: 1, width: 220 });
      setTotpSecret({ secret: result.secret, qr });
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not start authenticator setup.");
      setStage("choose");
    }
  }

  async function verifyTotp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      const actor = await platformApi.post<PlatformActor>("/auth/mfa/totp/verify", {
        code: data.get("code"),
      });
      afterFirstFactorEnrolled(actor);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "That code is not correct.");
    } finally {
      setBusy(false);
    }
  }

  function downloadCodes() {
    const blob = new Blob([recoveryCodes.join("\n") + "\n"], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "mykhaya-recovery-codes.txt";
    link.click();
    URL.revokeObjectURL(url);
  }

  if (stage === "loading") {
    return (
      <main className="platform-login">
        <section>
          <p role="status">Loading…</p>
        </section>
      </main>
    );
  }

  if (stage === "recovery-codes" || stage === "done") {
    return (
      <main className="platform-login">
        <section>
          <p className="platform-kicker">Restricted management plane</p>
          <h1>Save your recovery codes</h1>
          {stage === "recovery-codes" ? (
            <>
              <p>
                Each code signs you in once if you lose access to your passkey or authenticator
                app. They are shown only now — store them somewhere safe.
              </p>
              <ul className="recovery-code-list">
                {recoveryCodes.map((code) => (
                  <li key={code}>{code}</li>
                ))}
              </ul>
              <div className="platform-modal-actions">
                <button type="button" className="secondary" onClick={downloadCodes}>
                  Download codes
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => navigator.clipboard.writeText(recoveryCodes.join("\n"))}
                >
                  Copy codes
                </button>
              </div>
              <button onClick={() => router.replace("/")}>I&rsquo;ve saved these — continue</button>
            </>
          ) : (
            <>
              <p>Your account is secured. You can generate recovery codes any time from Security.</p>
              <button onClick={() => router.replace("/")}>Continue to Control Centre</button>
            </>
          )}
        </section>
      </main>
    );
  }

  return (
    <main className="platform-login">
      <section>
        <p className="platform-kicker">Restricted management plane</p>
        <h1>Secure your administrator account</h1>
        <p>MyKhaya requires multi-factor authentication for platform administrators.</p>
        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}

        {stage === "choose" && (
          <div className="mfa-choice-grid">
            <button className="mfa-choice-card" onClick={startPasskeySetup} disabled={busy}>
              <strong>Set up a passkey</strong>
              <span className="mfa-recommended">Recommended</span>
              <p>Use Windows Hello, Touch ID, Face ID, or a security key.</p>
            </button>
            <button className="mfa-choice-card" onClick={startTotpSetup} disabled={busy}>
              <strong>Use an authenticator app</strong>
              <p>Google Authenticator, 1Password, Authy, or similar.</p>
            </button>
          </div>
        )}

        {stage === "passkey" && <p role="status">Waiting for your passkey…</p>}

        {stage === "totp" && totpSecret && (
          <form onSubmit={verifyTotp} className="mfa-method">
            <img src={totpSecret.qr} alt="Scan with your authenticator app" width={220} height={220} />
            <p>
              Can&rsquo;t scan? Enter this key manually: <code>{totpSecret.secret}</code>
            </p>
            <label>
              6-digit code from your app
              <input
                name="code"
                inputMode="numeric"
                pattern="[0-9]*"
                minLength={6}
                maxLength={6}
                autoComplete="one-time-code"
                autoFocus
                required
              />
            </label>
            <button disabled={busy}>{busy ? "Verifying…" : "Verify and continue"}</button>
            <button type="button" className="tertiary" onClick={() => setStage("choose")}>
              Choose a different method
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
