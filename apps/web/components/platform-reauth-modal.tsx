"use client";

import { FormEvent, useState } from "react";
import { ApiError, platformApi } from "@mykhaya/api-client";

/**
 * Fresh-authentication gate for sensitive Control Centre actions. Confirms
 * the operator's password again (POST /auth/reauthenticate, which just bumps
 * the session's authenticated_at — no new cookie), then calls onVerified so
 * the caller can retry whatever action returned the 403 that triggered this.
 *
 * Use useReauthGuard below rather than rendering this directly in most cases.
 */
export function PlatformReauthModal({
  onVerified,
  onCancel,
}: {
  onVerified: () => void;
  onCancel: () => void;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      await platformApi.post("/auth/reauthenticate", { password: data.get("password") });
      onVerified();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Re-authentication failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="platform-modal-backdrop" role="presentation" onClick={onCancel}>
      <div
        className="platform-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="reauth-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="reauth-title">Confirm it&rsquo;s you</h2>
        <p>This action needs a recent sign-in. Enter your password to continue.</p>
        <form onSubmit={submit}>
          <label>
            Password
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              autoFocus
              required
              maxLength={128}
            />
          </label>
          {error && (
            <p className="notice error" role="alert">
              {error}
            </p>
          )}
          <div className="platform-modal-actions">
            <button type="button" className="secondary" onClick={onCancel} disabled={busy}>
              Cancel
            </button>
            <button disabled={busy}>{busy ? "Confirming…" : "Confirm"}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

/**
 * Wraps an async action so that a 403 "recent authentication required"
 * response transparently shows the reauth modal and retries the action once
 * confirmed, instead of every call site building its own retry plumbing.
 */
export function useReauthGuard() {
  const [pending, setPending] = useState<(() => void) | null>(null);

  function guarded<Args extends unknown[]>(action: (...args: Args) => Promise<void>) {
    return async (...args: Args) => {
      try {
        await action(...args);
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 403) {
          setPending(() => () => {
            void action(...args);
          });
          return;
        }
        throw cause;
      }
    };
  }

  const modal = pending ? (
    <PlatformReauthModal
      onVerified={() => {
        const retry = pending;
        setPending(null);
        retry?.();
      }}
      onCancel={() => setPending(null)}
    />
  ) : null;

  return { guarded, modal };
}
