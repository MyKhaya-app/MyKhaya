"use client";
export const dynamic = "force-dynamic";
import { FormEvent, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Eye, EyeOff } from "lucide-react";
import { api, ApiError } from "@mykhaya/api-client";
import type { User } from "@mykhaya/shared-types";
import { Avatar } from "@/components/avatar";
import { AuthBrandPanel, AuthCard } from "@/components/auth-card";
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
import { getLastNativeLoginDiagnostic, nativeLogin, runNativeNetworkDiagnostics } from "@/components/native-auth";
import { recordLoginFailureDiagnostic } from "@/components/auth-diagnostics";
import { useAuth } from "@/components/auth-provider";
import type { SignupStateValue } from "@/components/public-signup";
import { SignInCard } from "./signin-card";
import "@/app/brand-fonts.css";
import "./signin.css";

type BrowserAuthResult =
  | User
  | {
      authentication_state: "additional_auth_required";
      transaction_id: string;
    };

export default function Login() {
  const router = useRouter(),
    params = useSearchParams();
  const signInInFlight = useRef(false);
  const invitation = params.get("invitation");
  const beta = params.get("beta") === "1";
  const betaInvitation = params.get("beta_invitation");
  const calendarShare = params.get("calendar_share");
  const appleResult = params.get("apple");
  const mfaExpired = params.get("mfa_error") === "expired";
  const { setAuthenticatedUser } = useAuth();
  // Set by AppShell when it bounces an expired/invalid session to /login —
  // the exact protected path (e.g. a calendar-share accept link's
  // ?token=...) the user was trying to reach, so a plain expired-session
  // redirect doesn't silently drop it. Validated as an internal path only:
  // this must never become an open redirect to an attacker-supplied URL.
  const nextParam = params.get("next");
  const next = isSafeInternalPath(nextParam) ? nextParam : null;
  const [error, setError] = useState(mfaExpired ? "Your verification session has expired. Please sign in again." : ""),
    [nativeDiagnostic, setNativeDiagnostic] = useState<string | null>(null),
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
    } | null>(null),
    [appleEnabled, setAppleEnabled] = useState(false),
    [passwordVisible, setPasswordVisible] = useState(false),
    // undefined while loading, null if it failed: both show the normal card.
    [signupState, setSignupState] = useState<SignupStateValue>(undefined);

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

  useEffect(() => {
    if (isNativeShell()) return;
    api
      .authProviders()
      .then((result) =>
        setAppleEnabled(
          result.providers.some((item) => item.provider === "apple" && item.enabled),
        ),
      )
      .catch(() => setAppleEnabled(false));
  }, []);

  useEffect(() => {
    const context = {
      transport: isNativeShell() ? "native" : "browser",
      path: "/public/signup-state",
      invitationOverride: Boolean(invitation || calendarShare),
    };
    api
      .publicSignupState()
      .then((state) => {
        console.info("[signin] signup state loaded", {
          ...context,
          beta_joining_available: state.beta_joining_available,
        });
        setSignupState(state);
      })
      .catch((reason: unknown) => {
        // The normal card is the safe fallback, but never a silent one.
        console.warn("[signin] signup state request failed; showing the normal card", {
          ...context,
          status: reason instanceof ApiError ? reason.status : null,
          message: reason instanceof Error ? reason.message : String(reason),
        });
        setSignupState(null);
      });
  }, [invitation, calendarShare]);

  function startAppleSignIn() {
    const query = next ? `?next_path=${encodeURIComponent(next)}` : "";
    window.location.assign(`/api/v1/auth/apple/start${query}`);
  }

  async function afterSignedIn(user: User) {
    await setAuthenticatedUser(user);
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
      const continuation = await api.betaContinuation().catch(() => null);
      if (continuation?.pending && !continuation.enrolled) {
        router.push("/onboarding?beta=1");
        return;
      }
      router.push("/home");
      return;
    }
    // An account created through the Founding Beta resumes the Beta
    // continuation on its first sign-in — decided by the server-side Beta
    // intent, not by this page's URL (the emailed verification link carries
    // no Beta marker). Never the commercial plan/payment onboarding.
    const continuation = await api.betaContinuation().catch(() => null);
    if (beta || (continuation?.pending && !continuation.enrolled)) {
      if (continuation && !continuation.enrolled) {
        router.push(
          `/onboarding?beta=1${betaInvitation ? `&invitation=${encodeURIComponent(betaInvitation)}` : ""}`,
        );
        return;
      }
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
    // One authoritative in-flight guard (a ref, so it is set synchronously -
    // `busy` state only updates on the next render, and a second submit event
    // in the same tick would otherwise slip through). A sign-in attempt is
    // rate-limited server-side, so a duplicate submit costs the user allowance.
    if (signInInFlight.current) return;
    signInInFlight.current = true;
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
      const result: BrowserAuthResult = isNativeShell()
        ? await nativeLogin(email, password)
        : await api.post<BrowserAuthResult>("/auth/login", { email, password });
      if ("authentication_state" in result) {
        router.push(`/mfa?transaction=${encodeURIComponent(result.transaction_id)}`);
        return;
      }
      await afterSignedIn(result);
    } catch (err) {
      // The user-facing message stays generic on purpose (never reveal
      // which layer failed to a potential attacker) — recordLoginFailureDiagnostic
      // is the operator/dev-facing signal that distinguishes invalid
      // credentials from a server/network/CORS-configuration failure. See
      // components/auth-diagnostics.ts's docstring for exactly what each
      // category means; no credential or token value is ever recorded.
      recordLoginFailureDiagnostic(isNativeShell() ? "native_login" : "browser_login", err);
      if (isNativeShell() && window.location.hostname === "dev.mykhaya.app") {
        setNativeDiagnostic(getLastNativeLoginDiagnostic());
        // Transport probes run only AFTER a failure that never reached the
        // server (network/CORS), never before every sign-in, and never against
        // an authentication endpoint.
        if (!(err instanceof ApiError)) {
          void runNativeNetworkDiagnostics().then((results) =>
            setNativeDiagnostic(
              `${getLastNativeLoginDiagnostic() ?? ""}; probe: ${results.join(" | ")}`,
            ),
          );
        }
      }
      setError(
        err instanceof ApiError
          ? err.message
          : "We couldn’t sign you in. Please try again.",
      );
    } finally {
      signInInFlight.current = false;
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

  const registerHref = invitation
    ? `/register?invitation=${encodeURIComponent(invitation)}`
    : calendarShare
      ? `/register?calendar_share=${encodeURIComponent(calendarShare)}`
      : "/register";
  // The Founding Beta card replaces "New to MyKhaya?" only once the signup
  // state says Beta joining is open. Someone arriving with a household or
  // calendar-share invitation keeps the invitation-carrying register link.
  const showBetaCard =
    signupState?.beta_joining_available === true && !invitation && !calendarShare;

  return (
    <main className="signin-page">
      <AuthBrandPanel />
      <div className="signin">
        <div className="signin-column">
          <Link href="/" className="signin-brand">
            <img src="/images/mykhaya-logo.png" alt="" aria-hidden="true" />
            <span>MyKhaya</span>
          </Link>
          <h1>Welcome back</h1>
          <p className="signin-intro">Sign in to see what’s happening at Home.</p>
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
          {appleResult === "link_required" && (
            <p className="notice">
              Sign in with your existing account first. Apple can then be linked from your security settings.
            </p>
          )}
          {appleResult === "registration_unavailable" && (
            <p className="notice">
              New accounts can’t be created with Apple right now. If you already have a MyKhaya account, sign in with your password.
            </p>
          )}
          {appleResult === "error" && (
            <p className="notice">Apple sign-in could not be completed. Please try again or use your password.</p>
          )}
          <form className="signin-form" onSubmit={submit}>
            <div className="signin-field">
              <label htmlFor="signin-email">Email</label>
              <input
                id="signin-email"
                name="email"
                type="email"
                autoComplete="email"
                placeholder="your@email.com"
                required
                maxLength={320}
              />
            </div>
            <div className="signin-field">
              <label htmlFor="signin-password">Password</label>
              <div className="signin-password">
                <input
                  id="signin-password"
                  name="password"
                  type={passwordVisible ? "text" : "password"}
                  autoComplete="current-password"
                  placeholder="Enter your password"
                  required
                  maxLength={128}
                />
                <button
                  type="button"
                  className="signin-password-toggle"
                  aria-label={passwordVisible ? "Hide password" : "Show password"}
                  onClick={() => setPasswordVisible((visible) => !visible)}
                >
                  {passwordVisible ? (
                    <EyeOff size={20} strokeWidth={1.8} aria-hidden="true" />
                  ) : (
                    <Eye size={20} strokeWidth={1.8} aria-hidden="true" />
                  )}
                </button>
              </div>
            </div>
            <FormStatus error={error} />
            {nativeDiagnostic && (
              <p className="notice" role="status">Auth diagnostic: {nativeDiagnostic}</p>
            )}
            <button className="signin-submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
          </form>
          {appleEnabled && (
            <button type="button" className="apple-sign-in" onClick={startAppleSignIn} disabled={busy}>
              Continue with Apple
            </button>
          )}
          <Link href="/forgot-password" className="signin-link signin-forgot">
            Forgot password?
          </Link>
          {showBetaCard ? (
            <SignInCard variant="beta" href="/founding-beta" />
          ) : (
            <SignInCard variant="new" href={registerHref} />
          )}
          <p className="signin-child">
            Signing in as a child?{" "}
            <Link href="/login/child" className="signin-link">Child sign in</Link>
          </p>
        </div>
      </div>
    </main>
  );
}
