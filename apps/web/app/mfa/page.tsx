"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import QRCode from "qrcode";
import { api, ApiError } from "@mykhaya/api-client";
import type { User } from "@mykhaya/shared-types";
import { AuthCard } from "@/components/auth-card";
import { FormStatus } from "@/components/form-status";
import { useAuth } from "@/components/auth-provider";

type Method = "totp" | "email";
type Options = { methods: Method[]; destination: string | null; onboarding: boolean };
type Start = {
  method: Method;
  destination?: string | null;
  provisioning_uri?: string | null;
  manual_key?: string | null;
  enrolling: boolean;
};

export default function MfaPage() {
  const router = useRouter();
  const params = useSearchParams();
  const transaction = params.get("transaction") ?? "";
  const { setAuthenticatedUser } = useAuth();
  const [options, setOptions] = useState<Options | null>(null);
  const [method, setMethod] = useState<Method>("email");
  const [start, setStart] = useState<Start | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!transaction) {
      setError("This sign-in attempt has expired. Please sign in again.");
      return;
    }
    api
      .get<Options>(`/auth/mfa/options?transaction_id=${encodeURIComponent(transaction)}`)
      .then((value) => {
        setOptions(value);
        setMethod(value.methods[0] ?? "email");
      })
      .catch((reason: ApiError) => setError(reason.message));
  }, [transaction]);

  async function begin(selected: Method = method) {
    setBusy(true);
    setError("");
    setStart(null);
    try {
      const value = await api.post<Start>("/auth/mfa/start", {
        transaction_id: transaction,
        method: selected,
      });
      setStart(value);
      setQr(value.provisioning_uri ? await QRCode.toDataURL(value.provisioning_uri, { margin: 1, width: 220 }) : null);
      setMethod(selected);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not start verification.");
    } finally {
      setBusy(false);
    }
  }

  async function verify() {
    setBusy(true);
    setError("");
    try {
      const user = await api.post<User>("/auth/mfa/verify", {
        transaction_id: transaction,
        method,
        code,
      });
      setAuthenticatedUser(user);
      router.push(options?.onboarding ? "/onboarding" : "/home");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not verify the code.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title="Verify it’s you" intro="Choose a secure way to finish signing in.">
      {options && options.methods.length > 1 && (
        <div className="auth-mfa-methods" role="group" aria-label="Verification method">
          {options.methods.map((item) => (
            <button
              key={item}
              type="button"
              className={method === item ? "active" : "tertiary"}
              onClick={() => void begin(item)}
              disabled={busy}
            >
              {item === "totp" ? "Authenticator app" : "Email code"}
            </button>
          ))}
        </div>
      )}
      {method === "totp" && start?.enrolling && qr && (
        <div>
          <p>Scan this QR code, then enter the six-digit code from your authenticator app.</p>
          <img src={qr} alt="Authenticator setup QR code" className="auth-mfa-qr" />
          <p>Manual setup key: <code>{start.manual_key}</code></p>
        </div>
      )}
      {method === "email" && start && (
        <p>We sent a six-digit code to {start.destination ?? options?.destination}.</p>
      )}
      <FormStatus error={error} />
      {start ? (
        <form onSubmit={(event) => { event.preventDefault(); void verify(); }}>
          <label>
            Verification code
            <input value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" required />
          </label>
          <button disabled={busy || code.length !== 6}>{busy ? "Checking…" : "Verify"}</button>
          {method === "email" && <button type="button" className="tertiary" onClick={() => void begin("email")} disabled={busy}>Resend code</button>}
        </form>
      ) : (
        <button type="button" onClick={() => void begin()} disabled={busy || !options}>{busy ? "Starting…" : "Continue"}</button>
      )}
    </AuthCard>
  );
}
