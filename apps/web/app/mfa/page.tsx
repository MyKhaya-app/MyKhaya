"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
  const [resendCooldown, setResendCooldown] = useState(0);
  const autoStartAttempted = useRef(false);

  const returnToLogin = useCallback(() => {
    router.replace("/login?mfa_error=expired");
  }, [router]);

  useEffect(() => {
    if (!transaction) {
      returnToLogin();
      return;
    }
    api
      .get<Options>(`/auth/mfa/options?transaction_id=${encodeURIComponent(transaction)}`)
      .then((value) => {
        setOptions(value);
        setMethod(value.methods[0] ?? "email");
      })
      .catch(() => returnToLogin());
  }, [returnToLogin, transaction]);

  const begin = useCallback(async (selected: Method = method) => {
    setBusy(true);
    setError("");
    setStart(null);
    setCode("");
    try {
      const value = await api.post<Start>("/auth/mfa/start", {
        transaction_id: transaction,
        method: selected,
      });
      setStart(value);
      setQr(
        value.provisioning_uri
          ? await QRCode.toDataURL(value.provisioning_uri, { margin: 1, width: 220 })
          : null,
      );
      setMethod(selected);
      if (selected === "email") setResendCooldown(30);
    } catch (reason) {
      setError(
        reason instanceof ApiError && reason.status === 429
          ? "Too many requests. Please wait a moment and try again."
          : "We couldn't start verification. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }, [method, transaction]);

  useEffect(() => {
    if (options?.methods.length === 1 && !autoStartAttempted.current) {
      autoStartAttempted.current = true;
      void begin(options.methods[0]);
    }
  }, [begin, options]);

  useEffect(() => {
    if (resendCooldown <= 0) return;
    const timer = window.setInterval(
      () => setResendCooldown((value) => Math.max(0, value - 1)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [resendCooldown]);

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
      if (reason instanceof ApiError && reason.status === 400 && /sign-in attempt has expired/i.test(reason.message)) {
        returnToLogin();
        return;
      }
      setError(
        reason instanceof ApiError && reason.status === 429
          ? "Too many attempts. Please wait a moment and try again."
          : reason instanceof ApiError && /invalid|incorrect/i.test(reason.message)
            ? "That code isn't correct. Please try again."
            : "We couldn't verify that code. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title="Verify it’s you" intro="For your security, we need to verify your identity.">
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
      {method === "totp" && start?.enrolling && (
        <div className="auth-mfa-setup">
          <p>Scan this QR code, then enter the 6-digit code from your authenticator app.</p>
          {qr && <img src={qr} alt="Scan with your authenticator app" className="auth-mfa-qr" />}
          <p>Can't scan? Enter this setup key manually: <code>{start.manual_key}</code></p>
        </div>
      )}
      {method === "email" && start && (
        <p>We've sent a verification code to {start.destination ?? options?.destination}.</p>
      )}
      <FormStatus error={error} />
      {start ? (
        <form onSubmit={(event) => { event.preventDefault(); void verify(); }}>
          <label htmlFor="mfa-code">
            Verification code
            <input
              id="mfa-code"
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              required
              autoFocus
            />
          </label>
          <button disabled={busy || code.length !== 6}>{busy ? "Checking…" : "Verify"}</button>
          {method === "email" && (
            <button
              type="button"
              className="tertiary"
              onClick={() => void begin("email")}
              disabled={busy || resendCooldown > 0}
            >
              {resendCooldown > 0 ? `Resend code in ${resendCooldown}s` : "Resend code"}
            </button>
          )}
        </form>
      ) : (
        <button type="button" onClick={() => void begin()} disabled={busy || !options}>{busy ? "Starting…" : "Continue"}</button>
      )}
    </AuthCard>
  );
}
