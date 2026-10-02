"use client";
export const dynamic = "force-dynamic";
import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@mykhaya/api-client";
import { Avatar } from "@/components/avatar";
import { AuthCard } from "@/components/auth-card";
import { FormStatus } from "@/components/form-status";
import {
  forgetChildAccount,
  getRememberedChildAccounts,
  rememberChildAccount,
  type RememberedChildAccount,
} from "@/components/child-login-client";
import { isNativeShell } from "@/components/native-runtime";
import { nativeChildLogin } from "@/components/native-auth";
import { recordLoginFailureDiagnostic } from "@/components/auth-diagnostics";

// Matches mykhaya.security.generate_home_code() exactly (8 chars, from a
// fixed alphabet) — every real Home code is this length, so the input must
// accept the whole thing rather than an arbitrary shorter/looser bound.
const HOME_CODE_LENGTH = 8;

function formText(data: FormData, name: string) {
  const value = data.get(name);
  return typeof value === "string" ? value : "";
}

function initialAccounts() {
  return getRememberedChildAccounts();
}

export default function ChildLogin() {
  const router = useRouter();
  const [accounts, setAccounts] = useState<RememberedChildAccount[]>(initialAccounts);
  const [selected, setSelected] = useState<RememberedChildAccount | null>(() => {
    const remembered = initialAccounts();
    return remembered.length === 1 ? remembered[0]! : null;
  });
  const [manualMode, setManualMode] = useState(() => initialAccounts().length === 0);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);

  function useDifferentAccount() {
    setError("");
    setSelected(null);
    setManualMode(true);
  }

  function backToSavedAccounts() {
    setError("");
    setManualMode(false);
    setSelected(accounts.length === 1 ? accounts[0]! : null);
  }

  function forget(account: RememberedChildAccount) {
    forgetChildAccount(account.homeCode, account.username);
    const remaining = getRememberedChildAccounts();
    setAccounts(remaining);
    setSelected(remaining.length === 1 ? remaining[0]! : null);
    setManualMode(remaining.length === 0);
    setError("");
  }

  async function submitManual(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const d = new FormData(e.currentTarget);
    const home_code = formText(d, "home_code").trim().toUpperCase();
    const username = formText(d, "username").trim();
    const pin = formText(d, "pin");
    try {
      // Native source of truth: /auth/mobile/child/login + Keychain, never
      // the browser cookie /auth/child/login — see app/login/page.tsx's
      // submit() for the same split on the adult sign-in path.
      const user = isNativeShell()
        ? await nativeChildLogin(home_code, username, pin)
        : await api.childLogin({ home_code, username, pin });
      rememberChildAccount({
        homeCode: home_code,
        username: username.toLowerCase(),
        userId: user.id,
        displayName: user.display_name,
        avatarVersion: user.avatar_version,
        lastUsedAt: new Date().toISOString(),
      });
      router.push("/home");
    } catch (err) {
      recordLoginFailureDiagnostic(isNativeShell() ? "native_child_login" : "browser_child_login", err);
      setError(
        err instanceof ApiError
          ? err.message
          : "We couldn’t sign you in. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function submitReturning(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!selected) return;
    setBusy(true);
    setError("");
    const d = new FormData(e.currentTarget);
    const pin = formText(d, "pin");
    try {
      const user = isNativeShell()
        ? await nativeChildLogin(selected.homeCode, selected.username, pin)
        : await api.childLogin({
            home_code: selected.homeCode,
            username: selected.username,
            pin,
          });
      rememberChildAccount({
        ...selected,
        userId: user.id,
        displayName: user.display_name,
        avatarVersion: user.avatar_version,
        lastUsedAt: new Date().toISOString(),
      });
      router.push("/home");
    } catch (err) {
      recordLoginFailureDiagnostic(isNativeShell() ? "native_child_login" : "browser_child_login", err);
      setError(
        err instanceof ApiError
          ? err.message
          : "We couldn’t sign you in. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  // More than one remembered child on this device: pick which one before
  // asking for a PIN — still no Home code/username retyping either way.
  if (!manualMode && !selected && accounts.length > 1) {
    return (
      <AuthCard title="Welcome back" intro="Choose your account to continue.">
        <div className="auth-biometric">
          <div className="child-account-list">
            {accounts.map((account) => (
              <button
                key={`${account.homeCode}:${account.username}`}
                type="button"
                className="child-account-row"
                onClick={() => setSelected(account)}
              >
                <Avatar
                  id={account.userId}
                  name={account.displayName}
                  avatarVersion={account.avatarVersion}
                  size="md"
                />
                <span className="child-account-copy">
                  <strong>{account.displayName}</strong>
                  <small>Home {account.homeCode}</small>
                </span>
              </button>
            ))}
          </div>
          <button type="button" className="tertiary" onClick={useDifferentAccount}>
            Use a different account or Home
          </button>
        </div>
      </AuthCard>
    );
  }

  // A single remembered child (or one just picked above): the normal
  // returning-child screen — name + recognised Home + PIN only.
  if (!manualMode && selected) {
    return (
      <AuthCard title="Welcome back" intro="Enter your PIN to continue.">
        <form onSubmit={submitReturning} className="auth-biometric">
          <Avatar
            id={selected.userId}
            name={selected.displayName}
            avatarVersion={selected.avatarVersion}
            size="xl"
          />
          <p className="auth-biometric-name">{selected.displayName}</p>
          <p className="muted">Home {selected.homeCode}</p>
          <label>
            PIN
            <input
              name="pin"
              type="password"
              inputMode="numeric"
              pattern="[0-9]*"
              autoComplete="off"
              autoFocus
              required
              minLength={4}
              maxLength={6}
            />
          </label>
          <FormStatus error={error} />
          <button className="auth-biometric-button" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
          <button type="button" className="tertiary" onClick={useDifferentAccount}>
            Use a different account or Home
          </button>
          <button type="button" className="tertiary" onClick={() => forget(selected)}>
            Forget this account
          </button>
        </form>
      </AuthCard>
    );
  }

  // First-time sign-in, or "Use a different account or Home" from above.
  return (
    <AuthCard
      title="Child sign in"
      intro="Ask a grown-up for your Home code if you don’t know it."
      footer={
        <span>
          Not a child? <Link href="/login">Back to sign in</Link>
        </span>
      }
    >
      {accounts.length > 0 && (
        <button type="button" className="tertiary" onClick={backToSavedAccounts}>
          Back to saved accounts
        </button>
      )}
      <form onSubmit={submitManual}>
        <label>
          Home code
          <input
            name="home_code"
            autoComplete="off"
            autoCapitalize="characters"
            required
            minLength={HOME_CODE_LENGTH}
            maxLength={HOME_CODE_LENGTH}
          />
        </label>
        <label>
          Username
          <input
            name="username"
            autoComplete="off"
            required
            minLength={1}
            maxLength={24}
          />
        </label>
        <label>
          PIN
          <input
            name="pin"
            type="password"
            inputMode="numeric"
            pattern="[0-9]*"
            autoComplete="off"
            required
            minLength={4}
            maxLength={6}
          />
        </label>
        <FormStatus error={error} />
        <button disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </AuthCard>
  );
}
