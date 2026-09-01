"use client";
export const dynamic = "force-dynamic";
import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError } from "@mykhaya/api-client";
import type { User } from "@mykhaya/shared-types";
import { Avatar } from "@/components/avatar";
import { AuthCard } from "@/components/auth-card";
import { FormStatus } from "@/components/form-status";
import {
  authenticateWithPasskey,
  biometricLabel,
  biometricSignInAvailable,
  clearBiometricHint,
  getBiometricHint,
  passkeyWasCancelled,
  setBiometricHint,
} from "@/components/passkey-client";
import { isSafeInternalPath } from "@/components/internal-path";
import { isNativeShell } from "@/components/native-runtime";
import { nativeLogin } from "@/components/native-auth";

export default function Login() {
  const router = useRouter(),
    params = useSearchParams();
  const invitation = params.get("invitation");
  const calendarShare = params.get("calendar_share");
  // Set by AppShell when it bounces an expired/invalid session to /login —
  // the exact protected path (e.g. a calendar-share accept link's
  // ?token=...) the user was trying to reach, so a plain expired-session
  // redirect doesn't silently drop it. Validated as an internal path only:
  // this must never become an open redirect to an attacker-supplied URL.
  const nextParam = params.get("next");
  const next = isSafeInternalPath(nextParam) ? nextParam : null;
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [biometricBusy, setBiometricBusy] = useState(false),
    // Starts optimistic (whatever the local hint already says) so a
    // returning, still-enrolled user sees the biometric screen immediately
    // rather than a flash of the password form — biometricSignInAvailable()
    // then confirms (or, rarely, corrects) it once the async platform check
    // resolves. The hint is a UX shortcut only; nothing security-sensitive
    // ever depends on it — a failed/declined biometric prompt always falls
    // back to the password form below.
    // Never optimistic inside the native shell — native passkeys/Face ID
    // login are not implemented yet (see components/quick-sign-in.tsx for
    // the separate, already-native Settings → Security → Quick Sign-In
    // feature). This screen's biometric-first flow is the browser/PWA
    // WebAuthn passkey path; the native shell must never attempt it.
    [showBiometric, setShowBiometric] = useState(() => !isNativeShell() && getBiometricHint() !== null),
    [biometricLabelText, setBiometricLabelText] = useState("biometrics"),
    [inviteContext, setInviteContext] = useState<{
      group_name: string;
      invited_by_display_name: string;
      email: string;
    } | null>(null),
    [shareContext, setShareContext] = useState<{
      calendar_name: string;
      source_group_name: string;
    } | null>(null);

  const hint = getBiometricHint();

  // Reads the hint itself (rather than closing over the `hint` above) so
  // this effect has no dependency on a value that gets a fresh object
  // identity every render — it only ever needs to run once, on mount, and
  // only ever narrows showBiometric from true to false, never the reverse.
  useEffect(() => {
    // The native shell never invokes browser WebAuthn (isUserVerifyingPlatformAuthenticatorAvailable
    // et al) — that API is unsupported/unconfigured inside the Capacitor
    // WKWebView and has been observed to hang the native app rather than
    // resolve. Native Quick Sign-In is a wholly separate feature (Settings →
    // Security), never reachable from this screen.
    if (isNativeShell()) {
      setShowBiometric(false);
      return;
    }
    setBiometricLabelText(biometricLabel());
    if (getBiometricHint() === null) {
      setShowBiometric(false);
      return;
    }
    biometricSignInAvailable().then((available) => {
      if (!available) {
        clearBiometricHint();
        setShowBiometric(false);
      }
    });
  }, []);

  useEffect(() => {
    if (!invitation) return;
    api
      .previewInvitation(invitation)
      .then((result) => setInviteContext(result))
      .catch((reason: ApiError) => setError(reason.message));
  }, [invitation]);

  useEffect(() => {
    if (!calendarShare) return;
    api
      .previewCalendarShare(calendarShare)
      .then((result) => setShareContext(result))
      .catch((reason: ApiError) => setError(reason.message));
  }, [calendarShare]);

  async function afterSignedIn(user: User) {
    setBiometricHint({
      userId: user.id,
      displayName: user.display_name,
      avatarVersion: user.avatar_version,
    });
    // Invitation/calendar-share acceptance and the has-a-Home check below
    // are all cookie-authenticated calls (see packages/api-client's
    // MyKhayaClient) — meaningless over the native bearer transport, which
    // never establishes a session cookie. Native login always lands
    // straight on /home; AppShell's own native bootstrap (see
    // components/app-shell.tsx) re-establishes the session there. Fully
    // wiring invitations/calendar-shares/onboarding into the native
    // transport is out of scope for this task.
    if (isNativeShell()) {
      router.push("/home");
      return;
    }
    if (invitation) await api.post("/invitations/accept", { token: invitation });
    // A calendar share, unlike a household invitation, isn't auto-accepted
    // here — the recipient chooses notification/briefing preferences as
    // part of accepting (see app/calendar-shares/accept/page.tsx), so this
    // sends them straight there instead of the Home dashboard.
    if (calendarShare) {
      router.push(`/calendar-shares/accept?token=${encodeURIComponent(calendarShare)}`);
      return;
    }
    if (next) {
      router.push(next);
      return;
    }
    router.push((await api.homes()).length ? "/home" : "/onboarding");
  }

  async function signInWithBiometrics() {
    setBiometricBusy(true);
    setError("");
    try {
      const options = await api.passkeyLoginOptions();
      const credential = await authenticateWithPasskey(options.options_json);
      const user = await api.passkeyLoginVerify(JSON.stringify(credential));
      await afterSignedIn(user);
    } catch (err) {
      if (passkeyWasCancelled(err)) {
        // Cancelling the prompt isn't a failure worth an error banner —
        // just drop back to the normal form, the same as tapping
        // "Sign in another way" would.
        setShowBiometric(false);
      } else {
        setError(
          err instanceof ApiError
            ? err.message
            : "We couldn't verify you. Try again or sign in with your password.",
        );
      }
    } finally {
      setBiometricBusy(false);
    }
  }

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const d = new FormData(e.currentTarget);
    const email = ((d.get("email") as string | null) ?? "").trim();
    const password = (d.get("password") as string | null) ?? "";
    try {
      // Native source of truth: inside Capacitor this is a bearer-token
      // sign-in against /auth/mobile/login, persisted to the iOS Keychain
      // (see components/native-auth.ts) — never the browser cookie
      // /auth/login. The two transports are never merged.
      const user = isNativeShell()
        ? await nativeLogin(email, password)
        : await api.post<User>("/auth/login", { email, password });
      await afterSignedIn(user);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "We couldn’t sign you in. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (showBiometric && hint) {
    return (
      <AuthCard title="Welcome back" intro="Sign in to see what’s happening at Home.">
        <div className="auth-biometric">
          <Avatar
            id={hint.userId}
            name={hint.displayName}
            avatarVersion={hint.avatarVersion}
            size="xl"
          />
          <p className="auth-biometric-name">{hint.displayName}</p>
          <FormStatus error={error} />
          <button
            type="button"
            className="auth-biometric-button"
            disabled={biometricBusy}
            onClick={() => void signInWithBiometrics()}
          >
            {biometricBusy ? "Checking…" : `Use ${biometricLabelText}`}
          </button>
          <button
            type="button"
            className="tertiary"
            onClick={() => setShowBiometric(false)}
          >
            Sign in another way
          </button>
        </div>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Welcome back"
      intro="Sign in to see what’s happening at Home."
      footer={
        <>
          <Link href="/forgot-password">Forgot password?</Link>
          <span>
            New here?{" "}
            <Link
              href={
                invitation
                  ? `/register?invitation=${encodeURIComponent(invitation)}`
                  : calendarShare
                    ? `/register?calendar_share=${encodeURIComponent(calendarShare)}`
                    : "/register"
              }
            >
              Create an account
            </Link>
          </span>
          <span>
            Signing in as a child? <Link href="/login/child">Child sign in</Link>
          </span>
        </>
      }
    >
      {inviteContext && (
        <p className="notice success">
          Continue signing in to join {inviteContext.group_name}.
        </p>
      )}
      {shareContext && (
        <p className="notice success">
          Continue signing in to view &ldquo;{shareContext.calendar_name}&rdquo;, shared by{" "}
          {shareContext.source_group_name}.
        </p>
      )}
      <form onSubmit={submit}>
        <label>
          Email
          <input
            name="email"
            type="email"
            autoComplete="email"
            required
            maxLength={320}
          />
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
        <FormStatus error={error} />
        <button disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </AuthCard>
  );
}
