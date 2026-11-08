"use client";
export const dynamic = "force-dynamic";
import { FormEvent, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { App } from "@capacitor/app";
import { Browser } from "@capacitor/browser";
import { Eye, EyeOff } from "lucide-react";
import { api, ApiError, type PublicLegalDocumentSummary } from "@mykhaya/api-client";
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
import { isNativeShell, nativePlatform } from "@/components/native-runtime";
import {
  cancelNativeMfa,
  getLastNativeLoginDiagnostic,
  nativeExternalAssertion,
  nativeExternalBrowserStart,
  nativeExternalExchange,
  nativeExternalRedeem,
  nativeExternalRecoveryLink,
  nativeExternalRecoveryRegister,
  nativeExternalStart,
  nativeLogin,
  nativeMfaOptions,
  nativeMfaStart,
  nativeMfaVerify,
  runNativeNetworkDiagnostics,
} from "@/components/native-auth";
import { recordLoginFailureDiagnostic } from "@/components/auth-diagnostics";
import { useAuth } from "@/components/auth-provider";
import type { SignupStateValue } from "@/components/public-signup";
import { SignInCard, signInCard } from "./signin-card";
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
  const social = params.get("social");
  const calendarShare = params.get("calendar_share");
  const additionalAuth = params.get("auth") === "additional";
  const additionalTransaction = additionalAuth ? params.get("transaction") : null;
  const appleResult = params.get("apple");
  const appleTransaction = params.get("transaction");
  const googleResult = params.get("google");
  const googleTransaction = params.get("transaction");
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
    [showBiometric, setShowBiometric] = useState(
      () => !isNativeShell() && !additionalAuth && !mfaExpired && getBiometricHint() !== null,
    ),
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
    [appleRecovery, setAppleRecovery] = useState<{
      can_register: boolean;
      provider_email: string | null;
      display_name: string;
    } | null>(null),
    [appleLinking, setAppleLinking] = useState(false),
    [appleRegistrationRequested, setAppleRegistrationRequested] = useState(false),
    [appleLegalDocuments, setAppleLegalDocuments] = useState<PublicLegalDocumentSummary[]>([]),
    [appleLegalChecked, setAppleLegalChecked] = useState<Record<string, boolean>>({}),
    [appleLegalLoading, setAppleLegalLoading] = useState(false),
    [appleLegalLoadFailed, setAppleLegalLoadFailed] = useState(false),
    [googleEnabled, setGoogleEnabled] = useState(false),
    [googleRecovery, setGoogleRecovery] = useState<{
      can_register: boolean;
      provider_email: string | null;
      display_name: string;
    } | null>(null),
    [googleLinking, setGoogleLinking] = useState(false),
    [googleRegistrationRequested, setGoogleRegistrationRequested] = useState(false),
    [googleLegalDocuments, setGoogleLegalDocuments] = useState<PublicLegalDocumentSummary[]>([]),
    [googleLegalChecked, setGoogleLegalChecked] = useState<Record<string, boolean>>({}),
    [googleLegalLoading, setGoogleLegalLoading] = useState(false),
    [googleLegalLoadFailed, setGoogleLegalLoadFailed] = useState(false),
    [nativeRecovery, setNativeRecovery] = useState<{
      transaction_id: string;
      provider: "apple" | "google";
      provider_email: string | null;
      display_name: string;
      can_register: boolean;
    } | null>(null),
    [nativeLegalDocuments, setNativeLegalDocuments] = useState<PublicLegalDocumentSummary[]>([]),
    [nativeLegalChecked, setNativeLegalChecked] = useState<Record<string, boolean>>({}),
    [nativeRegistrationRequested, setNativeRegistrationRequested] = useState(false),
    [nativeMfaTransaction, setNativeMfaTransaction] = useState<string | null>(null),
    [nativeMfaMethods, setNativeMfaMethods] = useState<("totp" | "email")[]>([]),
    [nativeMfaMethod, setNativeMfaMethod] = useState<"totp" | "email">("email"),
    [nativeMfaCode, setNativeMfaCode] = useState(""),
    [nativeMfaStarted, setNativeMfaStarted] = useState(false),
    [nativeMfaEnrolmentKey, setNativeMfaEnrolmentKey] = useState<string | null>(null),
    [passwordVisible, setPasswordVisible] = useState(false),
    // undefined while loading, null if it failed: both show the normal card.
    [signupState, setSignupState] = useState<SignupStateValue>(undefined);

  const hint = getBiometricHint();
  // While a native MFA challenge is open it is the only thing on the card:
  // the password form, provider buttons and recovery choices are hidden so a
  // second primary sign-in cannot be started underneath the challenge.
  const nativeMfaActive = isNativeShell() && nativeMfaTransaction !== null;

  useEffect(() => {
    if (!isNativeShell() || (social !== "apple" && social !== "google") || appleResult || googleResult) return;
    void startNativeProvider(social);
  }, [social, appleResult, googleResult]);

  useEffect(() => {
    if (!additionalAuth) return;
    if (isNativeShell()) {
      router.replace("/login?mfa_error=expired");
      return;
    }
    if (additionalTransaction) {
      router.replace(`/mfa?transaction=${encodeURIComponent(additionalTransaction)}`);
    } else {
      router.replace("/login?mfa_error=expired");
    }
  }, [additionalAuth, additionalTransaction, router]);

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
    if (appleResult !== "choose" || !appleTransaction) return;
    setAppleLegalLoading(true);
    Promise.all([api.appleRecoveryOptions(appleTransaction), api.publicLegalDocuments()])
      .then(([options, documents]) => {
        setAppleRecovery(options);
        setAppleLegalDocuments(documents);
      })
      .catch(() => {
        setAppleLegalLoadFailed(true);
        setError("This Apple sign-in attempt or its legal documents have expired. Please try again.");
      })
      .finally(() => setAppleLegalLoading(false));
  }, [appleResult, appleTransaction]);

  useEffect(() => {
    if (googleResult !== "choose" || !googleTransaction) return;
    setGoogleLegalLoading(true);
    Promise.all([api.googleRecoveryOptions(googleTransaction), api.publicLegalDocuments()])
      .then(([options, documents]) => {
        setGoogleRecovery(options);
        setGoogleLegalDocuments(documents);
      })
      .catch(() => {
        setGoogleLegalLoadFailed(true);
        setError("This Google sign-in attempt or its legal documents have expired. Please try again.");
      })
      .finally(() => setGoogleLegalLoading(false));
  }, [googleResult, googleTransaction]);

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
        {
          setAppleEnabled(result.providers.some((item) => item.provider === "apple" && item.enabled));
          setGoogleEnabled(result.providers.some((item) => item.provider === "google" && item.enabled));
        },
      )
      .catch(() => {
        setAppleEnabled(false);
        setGoogleEnabled(false);
      });
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

  useEffect(() => {
    if (!isNativeShell()) return;
    let disposed = false;
    const listener = App.addListener("appUrlOpen", (event) => {
      try {
        const url = new URL(event.url);
        const transaction = url.searchParams.get("transaction");
        const production = window.location.hostname === "mykhaya.app";
        const expectedScheme = nativePlatform() === "ios"
          ? `${production ? "mykhaya-prod" : "mykhaya"}:`
          : `${production ? "app.mykhaya.mobile.prod" : "app.mykhaya.mobile"}:`;
        if (!transaction || url.protocol !== expectedScheme || url.host !== "auth" || url.pathname !== "/callback") return;
        void (async () => {
          setBusy(true);
          const result = await nativeExternalRedeem(transaction);
          if (disposed) return;
          if ("id" in result) await afterSignedIn(result);
          else if ("message" in result) throw new Error(result.message);
          else if (result.authentication_state === "account_choice") setNativeRecovery(result);
          else await enterNativeMfa(result.transaction_id);
        })().catch((cause) => setError(cause instanceof ApiError ? cause.message : "The provider callback could not be completed.")).finally(() => setBusy(false));
      } catch {
        setError("The provider callback was invalid.");
      }
    });
    return () => { disposed = true; void listener.then((handle) => handle.remove()); };
  }, []);

  function startAppleSignIn() {
    const query = next ? `?next_path=${encodeURIComponent(next)}` : "";
    window.location.assign(`/api/v1/auth/apple/start${query}`);
  }

  function startGoogleSignIn() {
    const query = next ? `?next_path=${encodeURIComponent(next)}` : "";
    window.location.assign(`/api/v1/auth/google/start${query}`);
  }

  async function startNativeProvider(provider: "apple" | "google") {
    setBusy(true);
    setError("");
    try {
      const useBrowser = (provider === "google" && nativePlatform() === "ios") || (provider === "apple" && nativePlatform() === "android");
      if (useBrowser) {
        const started = await nativeExternalBrowserStart(provider);
        await Browser.open({ url: started.authorization_url });
        return;
      }
      const started = await nativeExternalStart(provider);
      const assertion = await nativeExternalAssertion(provider, started.nonce, started.client_id);
      const result = await nativeExternalExchange(started.transaction_id, assertion.identity_token);
      if ("id" in result) {
        await afterSignedIn(result);
      } else if ("authentication_state" in result && result.authentication_state === "additional_auth_required") {
        await enterNativeMfa(result.transaction_id);
      } else if ("authentication_state" in result) {
        setNativeRecovery(result);
      }
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : `${provider === "apple" ? "Apple" : "Google"} sign-in could not be completed.`);
    } finally {
      setBusy(false);
    }
  }

  /** Native sign-in reached pre-authentication: the consumer MFA policy must
   * be satisfied before any session exists. The sign-in form is replaced by
   * the challenge (never stacked beneath it). */
  async function enterNativeMfa(transactionId: string) {
    setError("");
    setNativeMfaStarted(false);
    setNativeMfaCode("");
    setNativeMfaEnrolmentKey(null);
    setNativeMfaTransaction(transactionId);
    const options = await nativeMfaOptions(transactionId);
    setNativeMfaMethods(options.methods);
    setNativeMfaMethod(options.preferred_method ?? options.methods[0] ?? "email");
  }

  function leaveNativeMfa() {
    if (nativeMfaTransaction) cancelNativeMfa(nativeMfaTransaction);
    setNativeMfaTransaction(null);
    setNativeMfaStarted(false);
    setNativeMfaCode("");
    setNativeMfaEnrolmentKey(null);
    setError("");
  }

  async function startNativeMfa() {
    if (!nativeMfaTransaction) return;
    setBusy(true);
    setError("");
    try {
      const started = await nativeMfaStart(nativeMfaTransaction, nativeMfaMethod);
      setNativeMfaEnrolmentKey(started.enrolling && started.manual_key ? started.manual_key : null);
      setNativeMfaStarted(true);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not start verification.");
    } finally {
      setBusy(false);
    }
  }

  async function verifyNativeMfa() {
    if (!nativeMfaTransaction || nativeMfaCode.length !== 6 || busy) return;
    setBusy(true);
    setError("");
    try {
      const user = await nativeMfaVerify(nativeMfaTransaction, nativeMfaMethod, nativeMfaCode);
      // A provider-linking password sign-in links only after MFA completes.
      if (nativeRecovery) {
        await nativeExternalRecoveryLink(nativeRecovery.transaction_id);
        setNativeRecovery(null);
      }
      await afterSignedIn(user);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The verification code could not be accepted.");
    } finally {
      setBusy(false);
    }
  }

  async function chooseNativeRegistration() {
    setNativeRegistrationRequested(true);
    try {
      setNativeLegalDocuments(await api.publicLegalDocuments());
    } catch {
      setError("The current legal documents could not be loaded.");
    }
  }

  async function registerNativeProvider() {
    if (!nativeRecovery) return;
    const requiredLegal = nativeLegalDocuments.filter((document) =>
      document.audience === "adult" && document.acceptance_required && document.action_verb === "accept" && document.scope === "global",
    );
    if (requiredLegal.some((document) => !document.current_version_id || !nativeLegalChecked[document.key])) {
      setError("Please review and accept the required legal documents before continuing.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await nativeExternalRecoveryRegister({
        transaction_id: nativeRecovery.transaction_id,
        display_name: nativeRecovery.display_name,
        legal_acceptances: requiredLegal.map((document) => ({ document_key: document.key, document_version_id: document.current_version_id! })),
        platform: nativePlatform() === "android" ? "android" : "ios",
      });
      if ("authentication_state" in result) {
        await enterNativeMfa(result.transaction_id);
      } else {
        await afterSignedIn(result);
      }
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The account could not be created.");
    } finally {
      setBusy(false);
    }
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
      if ("authentication_state" in user) {
        router.push(`/mfa?transaction=${encodeURIComponent(user.transaction_id)}`);
        return;
      }
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
      if ("authentication_state" in result && isNativeShell()) {
        // Native MFA stays in-app on the bearer transport; the browser /mfa
        // page is cookie-based and never used inside the native shell.
        await enterNativeMfa(result.transaction_id);
        return;
      }
      if ("authentication_state" in result) {
        const linkQuery = appleLinking && appleTransaction
          ? `&apple_link_transaction=${encodeURIComponent(appleTransaction)}`
          : googleLinking && googleTransaction
            ? `&google_link_transaction=${encodeURIComponent(googleTransaction)}`
            : "";
        router.push(`/mfa?transaction=${encodeURIComponent(result.transaction_id)}${linkQuery}`);
        return;
      }
      if (appleLinking && appleTransaction) {
        await api.appleRecoveryLink(appleTransaction);
      }
      if (nativeRecovery) {
        await nativeExternalRecoveryLink(nativeRecovery.transaction_id);
        setNativeRecovery(null);
      }
      if (googleLinking && googleTransaction) {
        await api.googleRecoveryLink(googleTransaction);
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

  async function registerWithApple() {
    if (!appleTransaction) return;
    const requiredLegal = appleLegalDocuments.filter(
      (document) =>
        document.audience === "adult" &&
        document.acceptance_required &&
        document.action_verb === "accept" &&
        document.scope === "global",
    );
    if (
      appleLegalLoading ||
      appleLegalLoadFailed ||
      requiredLegal.some((document) => !document.current_version_id || !appleLegalChecked[document.key])
    ) {
      setError("Please review and confirm the required legal documents before continuing.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api.appleRecoveryRegister(appleTransaction, {
        legal_acceptances: requiredLegal.map((document) => ({
          document_key: document.key,
          document_version_id: document.current_version_id!,
        })),
        platform: "web",
        ...(beta ? { beta: true, beta_invitation_token: betaInvitation } : {}),
      });
      if ("authentication_state" in result) {
        router.push(`/mfa?transaction=${encodeURIComponent(result.transaction_id)}`);
        return;
      }
      await afterSignedIn(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn't create your account with Apple.");
    } finally {
      setBusy(false);
    }
  }

  async function registerWithGoogle() {
    if (!googleTransaction) return;
    const requiredLegal = googleLegalDocuments.filter(
      (document) => document.audience === "adult" && document.acceptance_required && document.action_verb === "accept" && document.scope === "global",
    );
    if (googleLegalLoading || googleLegalLoadFailed || requiredLegal.some((document) => !document.current_version_id || !googleLegalChecked[document.key])) {
      setError("Please review and confirm the required legal documents before continuing.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api.googleRecoveryRegister(googleTransaction, {
        legal_acceptances: requiredLegal.map((document) => ({ document_key: document.key, document_version_id: document.current_version_id! })),
        platform: "web",
        ...(beta ? { beta: true, beta_invitation_token: betaInvitation } : {}),
      });
      if ("authentication_state" in result) {
        router.push(`/mfa?transaction=${encodeURIComponent(result.transaction_id)}`);
        return;
      }
      await afterSignedIn(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn't create your account with Google.");
    } finally {
      setBusy(false);
    }
  }

  if (additionalAuth) {
    return (
      <AuthCard title="Continue signing in" intro="Taking you to the required verification step…">
        <p className="muted">Please wait while we securely continue your sign-in.</p>
      </AuthCard>
    );
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
  const card = signInCard(signupState, {
    invitation,
    calendarShare,
    invitationValid: inviteContext !== null,
  });

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
          {appleResult === "choose" && appleTransaction && (
            <section className="notice" aria-labelledby="apple-recovery-heading">
              <h2 id="apple-recovery-heading">Continue with Apple</h2>
              <p>
                Apple sign-in is ready. Choose whether to connect it to an existing MyKhaya
                account or create a new account. We will not merge accounts automatically.
              </p>
              <div className="signin-recovery-actions">
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setAppleLinking(true)}
                  disabled={busy}
                >
                  Link to an existing account
                </button>
                {appleRecovery?.can_register && (
                  <button
                    type="button"
                    className="tertiary"
                    onClick={() => setAppleRegistrationRequested(true)}
                    disabled={busy}
                  >
                    Create a new account
                  </button>
                )}
              </div>
              {appleRegistrationRequested && appleRecovery?.can_register && (
                <div className="auth-legal-consent">
                  <p><strong>Before you create your account</strong></p>
                  <p className="muted">Please review and accept the current Terms and Privacy documents.</p>
                  {appleLegalDocuments
                    .filter(
                      (document) =>
                        document.audience === "adult" &&
                        document.acceptance_required &&
                        document.action_verb === "accept" &&
                        document.scope === "global",
                    )
                    .map((document) => (
                      <label className="check-row" key={document.key}>
                        <input
                          type="checkbox"
                          checked={appleLegalChecked[document.key] === true}
                          onChange={(event) =>
                            setAppleLegalChecked((current) => ({
                              ...current,
                              [document.key]: event.target.checked,
                            }))
                          }
                        />
                        <span>
                          I accept the <Link href={`/legal/${document.key}`}>{document.display_name}</Link>{" "}
                          (version {document.current_version ?? "current"})
                        </span>
                      </label>
                    ))}
                  <button type="button" onClick={() => void registerWithApple()} disabled={busy || appleLegalLoading}>
                    {busy ? "Creating account…" : "Accept and create account"}
                  </button>
                </div>
              )}
              {appleLinking && (
                <p>
                  Sign in below with your existing MyKhaya email and password. Apple will be
                  linked only after that authentication succeeds.
                </p>
              )}
            </section>
          )}
          {appleResult === "registration_unavailable" && (
            <p className="notice">
              New accounts can’t be created with Apple right now. If you already have a MyKhaya account, sign in with your password.
            </p>
          )}
          {appleResult === "error" && (
            <p className="notice">Apple sign-in could not be completed. Please try again or use your password.</p>
          )}
          {googleResult === "choose" && googleTransaction && (
            <section className="notice" aria-labelledby="google-recovery-heading">
              <h2 id="google-recovery-heading">Continue with Google</h2>
              <p>Google sign-in is ready. Choose an existing MyKhaya account or create a new one. We will not merge accounts automatically.</p>
              <div className="signin-recovery-actions">
                <button type="button" className="secondary" onClick={() => setGoogleLinking(true)} disabled={busy}>Link to an existing account</button>
                {googleRecovery?.can_register && <button type="button" className="tertiary" onClick={() => setGoogleRegistrationRequested(true)} disabled={busy}>Create a new account</button>}
              </div>
              {googleRegistrationRequested && googleRecovery?.can_register && (
                <div className="auth-legal-consent">
                  <p><strong>Before you create your account</strong></p>
                  <p className="muted">Please review and accept the current Terms and Privacy documents.</p>
                  {googleLegalDocuments.filter((document) => document.audience === "adult" && document.acceptance_required && document.action_verb === "accept" && document.scope === "global").map((document) => (
                    <label className="check-row" key={document.key}>
                      <input type="checkbox" checked={googleLegalChecked[document.key] === true} onChange={(event) => setGoogleLegalChecked((current) => ({ ...current, [document.key]: event.target.checked }))} />
                      <span>I accept the <Link href={`/legal/${document.key}`}>{document.display_name}</Link> (version {document.current_version ?? "current"})</span>
                    </label>
                  ))}
                  <button type="button" onClick={() => void registerWithGoogle()} disabled={busy || googleLegalLoading}>{busy ? "Creating account…" : "Accept and create account"}</button>
                </div>
              )}
              {googleLinking && <p>Sign in below with your existing MyKhaya email and password. Google will be linked only after that authentication succeeds.</p>}
            </section>
          )}
          {googleResult === "error" && <p className="notice">Google sign-in could not be completed. Please try again or use your password.</p>}
          {isNativeShell() && nativeRecovery && !nativeMfaActive && (
            <section className="notice" aria-labelledby="native-recovery-heading">
              <h2 id="native-recovery-heading">Continue with {nativeRecovery.provider === "apple" ? "Apple" : "Google"}</h2>
              <p>Choose whether to link this provider to an existing MyKhaya account or create a new one. Accounts are never merged automatically.</p>
              <div className="signin-recovery-actions">
                <button type="button" className="secondary" onClick={() => setError("Sign in with your existing password below. The provider will be linked after that authentication succeeds.")} disabled={busy}>Link to an existing account</button>
                {nativeRecovery.can_register && <button type="button" className="tertiary" onClick={() => void chooseNativeRegistration()} disabled={busy}>Create a new account</button>}
              </div>
              {nativeRegistrationRequested && nativeRecovery.can_register && (
                <div className="auth-legal-consent">
                  <p><strong>Before you create your account</strong></p>
                  <p className="muted">Please review and accept the current Terms and Privacy documents.</p>
                  {nativeLegalDocuments.filter((document) => document.audience === "adult" && document.acceptance_required && document.action_verb === "accept" && document.scope === "global").map((document) => (
                    <label className="check-row" key={document.key}>
                      <input type="checkbox" checked={nativeLegalChecked[document.key] === true} onChange={(event) => setNativeLegalChecked((current) => ({ ...current, [document.key]: event.target.checked }))} />
                      <span>I accept the <Link href={`/legal/${document.key}`}>{document.display_name}</Link> (version {document.current_version ?? "current"})</span>
                    </label>
                  ))}
                  <button type="button" onClick={() => void registerNativeProvider()} disabled={busy}>Accept and create account</button>
                </div>
              )}
            </section>
          )}
          {nativeMfaActive && (
            <section className="notice" aria-labelledby="native-mfa-heading" data-testid="native-mfa-challenge">
              <h2 id="native-mfa-heading">Additional verification required</h2>
              <p>Your account requires a second verification step before you can continue.</p>
              <label htmlFor="native-mfa-method">Verification method</label>
              <select id="native-mfa-method" value={nativeMfaMethod} disabled={nativeMfaStarted} onChange={(event) => setNativeMfaMethod(event.target.value as "totp" | "email")}>
                {nativeMfaMethods.map((method) => <option key={method} value={method}>{method === "totp" ? "Authenticator app" : "Email code"}</option>)}
              </select>
              {nativeMfaEnrolmentKey && (
                <p>
                  Add MyKhaya to your authenticator app with this setup key, then enter the 6-digit code:{" "}
                  <code>{nativeMfaEnrolmentKey}</code>
                </p>
              )}
              {!nativeMfaStarted ? <button type="button" className="secondary" onClick={() => void startNativeMfa()} disabled={busy}>Start verification</button> : (
                // A form so the keyboard's Go/Enter key submits the code.
                <form onSubmit={(event) => { event.preventDefault(); void verifyNativeMfa(); }}>
                  <input aria-label="MFA code" inputMode="numeric" autoComplete="one-time-code" autoFocus maxLength={6} value={nativeMfaCode} onChange={(event) => setNativeMfaCode(event.target.value.replace(/\D/g, ""))} />
                  <button type="submit" disabled={busy || nativeMfaCode.length !== 6}>Verify and continue</button>
                </form>
              )}
              <FormStatus error={error} />
              <button type="button" className="tertiary" onClick={leaveNativeMfa} disabled={busy}>Use a different sign-in method</button>
            </section>
          )}
          {!nativeMfaActive && (<>
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
          {(appleEnabled || isNativeShell()) && !nativeRecovery && (
            <button type="button" className="apple-sign-in" onClick={() => isNativeShell() ? void startNativeProvider("apple") : startAppleSignIn()} disabled={busy}>
              Continue with Apple
            </button>
          )}
          {(googleEnabled || isNativeShell()) && !nativeRecovery && (
            <button type="button" className="google-sign-in" onClick={() => isNativeShell() ? void startNativeProvider("google") : startGoogleSignIn()} disabled={busy}>
              Continue with Google
            </button>
          )}
          <Link href="/forgot-password" className="signin-link signin-forgot">
            Forgot password?
          </Link>
          {card === "beta" && <SignInCard variant="beta" href="/founding-beta" />}
          {card === "new" && <SignInCard variant="new" href={registerHref} />}
          <p className="signin-child">
            Signing in as a child?{" "}
            <Link href="/login/child" className="signin-link">Child sign in</Link>
          </p>
          </>)}
        </div>
      </div>
    </main>
  );
}
