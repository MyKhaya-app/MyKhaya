"use client";
export const dynamic = "force-dynamic";
import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Check, Eye, EyeOff } from "lucide-react";
import {
  api,
  ApiError,
  type PublicLegalDocumentSummary,
  type PublicSignupState,
} from "@mykhaya/api-client";
import { FormStatus } from "@/components/form-status";
import { intervalName } from "@/components/billing-logic";
import { parseIntentFromParams, saveOnboardingIntent } from "@/components/onboarding-intent";
import { nativeRegister } from "@/components/native-auth";
import { isNativeShell, nativePlatform } from "@/components/native-runtime";
import { isMaintenanceError } from "@/components/maintenance";
import { registrationUnavailableReason } from "@/components/registration-availability";
import { AppleMark, GoogleMark } from "@/components/provider-marks";
import { BETA_BENEFITS, SignupBrandPanel, signupSteps } from "@/components/signup-brand-panel";
import { SignupLegalConsent, requiredContractualDocuments } from "@/components/signup-legal-consent";
import { socialRegistrationStartUrl } from "./registration-urls";
import "@/app/brand-fonts.css";
import "@/app/auth-tokens.css";
import "@/app/signup-screen.css";
import "./register.css";

export default function Register() {
  const router = useRouter(),
    params = useSearchParams();
  const invitation = params.get("invitation");
  const betaInvitation = params.get("beta_invitation");
  const betaRequested = params.get("beta") === "1" || Boolean(betaInvitation);
  const calendarShare = params.get("calendar_share");
  // Plan/interval carried from the public pricing section (or a direct
  // /signup?plan=family&interval=year link) are untrusted onboarding intent
  // only — see components/onboarding-intent.ts. An invited member joins an
  // existing Home and never gets asked to choose a plan for it, so intent is
  // ignored entirely on the invite path. Same reasoning for a calendar-share
  // recipient: a free account is all that's needed to accept one — see
  // docs on external Calendar Sharing.
  const intent =
    invitation || calendarShare || betaRequested
      ? null
      : parseIntentFromParams(params.get("plan"), params.get("interval"));
  const [error, setError] = useState(""),
    [legalDocuments, setLegalDocuments] = useState<PublicLegalDocumentSummary[]>([]),
    [legalLoading, setLegalLoading] = useState(true),
    [legalLoadFailed, setLegalLoadFailed] = useState(false),
    [legalChecked, setLegalChecked] = useState<Record<string, boolean>>({}),
    [busy, setBusy] = useState(false),
    [inviteContext, setInviteContext] = useState<{
      group_name: string;
      invited_by_display_name: string;
      email: string;
    } | null>(null),
    [shareContext, setShareContext] = useState<{
      calendar_name: string;
      source_group_name: string;
      invited_by_display_name: string;
      recipient_email: string;
    } | null>(null);
  const [signupState, setSignupState] = useState<PublicSignupState | null>(null),
    [signupStateLoaded, setSignupStateLoaded] = useState(false),
    [maintenance, setMaintenance] = useState(false);
  const [socialProviders, setSocialProviders] = useState({ apple: false, google: false });
  const [passwordVisible, setPasswordVisible] = useState(false);
  useEffect(() => {
    api.authProviders().then((result) => {
      setSocialProviders({
        apple: result.providers.some((item) => item.provider === "apple" && item.enabled),
        google: result.providers.some((item) => item.provider === "google" && item.enabled),
      });
    }).catch(() => setSocialProviders({ apple: false, google: false }));
  }, []);
  useEffect(() => {
    // Display-only: the API enforces registration regardless. A failed lookup
    // never blocks the form — the server's own rejection is the authority.
    api
      .publicSignupState()
      .then(setSignupState)
      .catch((cause) => setMaintenance(isMaintenanceError(cause)))
      .finally(() => setSignupStateLoaded(true));
  }, []);
  function startSocialRegistration(provider: "apple" | "google") {
    const context = betaRequested
      ? `/register?beta=1${betaInvitation ? `&beta_invitation=${encodeURIComponent(betaInvitation)}` : ""}`
      : "/register";
    if (isNativeShell()) {
      router.push(`/login?social=${provider}${betaRequested ? `&beta=1${betaInvitation ? `&beta_invitation=${encodeURIComponent(betaInvitation)}` : ""}` : ""}`);
      return;
    }
    window.location.assign(socialRegistrationStartUrl(provider, context));
  }
  useEffect(() => {
    api
      .publicLegalDocuments()
      .then(setLegalDocuments)
      .catch(() => {
        setLegalDocuments([]);
        setLegalLoadFailed(true);
      })
      .finally(() => setLegalLoading(false));
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
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const d = new FormData(e.currentTarget);
    if (d.get("password") !== d.get("confirm")) {
      setError("The passwords do not match.");
      setBusy(false);
      return;
    }
    try {
      // Account creation needs the global documents only — also on the
      // Founding Beta path. The Founding Beta Terms are accepted after email
      // verification, in the authenticated Beta continuation.
      const requiredLegal = legalDocuments.filter(
        (document) =>
          document.audience === "adult" &&
          document.acceptance_required &&
          document.action_verb === "accept" &&
          document.scope === "global",
      );
      const missingLegal = requiredLegal.filter(
        (document) => !document.current_version_id || !legalChecked[document.key],
      );
      if (legalLoading) {
        setError("Please wait while the current legal documents load.");
        setBusy(false);
        return;
      }
      if (legalLoadFailed) {
        setError("The current legal documents could not be loaded. Please try again.");
        setBusy(false);
        return;
      }
      if (missingLegal.length) {
        setError("Please review and confirm the required legal documents before continuing.");
        setBusy(false);
        return;
      }
      const body = {
        email: d.get("email"),
        display_name: d.get("name"),
        password: d.get("password"),
        invitation_token: invitation,
        legal_acceptances: requiredLegal.map((document) => ({
          document_key: document.key,
          document_version_id: document.current_version_id!,
        })),
        platform: isNativeShell()
          ? nativePlatform() === "ios" || nativePlatform() === "android"
            ? nativePlatform()
            : "web"
          : "web",
        // Only the Beta intent: recorded server-side so it survives email
        // verification and first sign-in without relying on this URL.
        beta: betaRequested || undefined,
        beta_invitation_token: betaRequested ? betaInvitation : undefined,
      };
      const result = isNativeShell()
        ? await nativeRegister(body)
        : await api.post<{
            message: string;
            verification_required: boolean;
          }>("/auth/register", body);
      if (intent && intent.plan !== "free") saveOnboardingIntent(intent);
      const carry = betaRequested
        ? `beta=1${betaInvitation ? `&beta_invitation=${encodeURIComponent(betaInvitation)}` : ""}`
        : invitation
        ? `invitation=${encodeURIComponent(invitation)}`
        : calendarShare
          ? `calendar_share=${encodeURIComponent(calendarShare)}`
          : "";
      router.push(
        result.verification_required
          ? carry
            ? `/verify-email?${carry}`
            : "/verify-email"
          : carry
            ? `/login?${carry}`
            : "/login",
      );
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "We couldn’t create your account. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }
  const unavailableReason = maintenance
    ? "MyKhaya is undergoing maintenance. Please try again shortly."
    : betaRequested
      ? registrationUnavailableReason(signupState, Boolean(betaInvitation), true)
      : registrationUnavailableReason(signupState, Boolean(invitation));
  const requiredDocuments = requiredContractualDocuments(legalDocuments);
  const contractualAcceptanceComplete =
    !legalLoading &&
    !legalLoadFailed &&
    requiredDocuments.every(
      (document) => Boolean(document.current_version_id && legalChecked[document.key]),
    );
  const registrationClosed =
    signupStateLoaded &&
    !maintenance &&
    Boolean(signupState) &&
    !signupState!.registration_open &&
    !(betaRequested && Boolean(betaInvitation));
  const signInHref = invitation
    ? `/login?invitation=${encodeURIComponent(invitation)}`
    : calendarShare
      ? `/login?calendar_share=${encodeURIComponent(calendarShare)}`
      : "/login";
  const formDisabled = busy || Boolean(unavailableReason) || !contractualAcceptanceComplete;
  const showLegalHint = !busy && !unavailableReason && !contractualAcceptanceComplete && !legalLoading && !legalLoadFailed;
  const showSocial = (socialProviders.apple || socialProviders.google) && !invitation && !calendarShare;
  return (
    <main className={`signup-screen register-page${betaRequested ? " register-page--beta is-beta" : ""}`}>
      <SignupBrandPanel beta={betaRequested} steps={signupSteps(betaRequested, "email")} current={0} />
      <div className="signup-main">
        <div className="signup-topbar">
          <a className="signup-wordmark" href="/">
            <img src="/images/mykhaya-logo.png" alt="" />
            <span>MyKhaya</span>
          </a>
          <p className="signup-topbar-link">
            <span className="signup-topbar-lead">Already have an account? </span>
            <Link href={signInHref}>Sign in</Link>
          </p>
        </div>
        <div className="signup-body">
          <div className="signup-column">
            <header className="signup-heading">
              <h1>Create your account</h1>
              <p>A calm, private place for the people closest to you.</p>
            </header>
            <p className="signup-progress register-mobile-steps">
              <span className="signup-progress-bars" aria-hidden="true">
                <span className="is-done" />
                <span />
                <span />
              </span>
              {betaRequested ? "Founding Beta · step 1 of 3" : "Step 1 of 3 · then verify your email"}
            </p>
            {betaRequested && (
              <>
                {/* Phone: the brand panel is hidden, so the benefits live here. */}
                <section className="register-beta-card" aria-labelledby="register-beta-heading">
                  <p id="register-beta-heading" className="register-beta-eyebrow">Founding Beta</p>
                  <ul>
                    {BETA_BENEFITS.map(({ title }) => (
                      <li key={title}>
                        <Check size={18} strokeWidth={2.5} aria-hidden="true" />
                        {title}
                      </li>
                    ))}
                  </ul>
                </section>
                {/* Wide: the brand panel carries the benefits; one line here. */}
                <p className="signup-notice signup-notice--beta register-beta-line">
                  <strong>Founding Beta.</strong> Verify your email to unlock complimentary Ultimate access.
                </p>
              </>
            )}
            {unavailableReason && (
              <p className="signup-notice" role="status">
                {unavailableReason}
              </p>
            )}
            {unavailableReason && signupState?.signup_mode === "beta_only" && !betaRequested && (
              <Link className="signup-pill-link signup-pill-link--secondary" href="/founding-beta">
                Continue to Founding Beta
              </Link>
            )}
            {inviteContext && (
              <p className="signup-notice signup-notice--success">
                {inviteContext.invited_by_display_name} invited you to join {inviteContext.group_name}.
              </p>
            )}
            {shareContext && (
              <p className="signup-notice signup-notice--success">
                {shareContext.source_group_name} wants to share the &ldquo;{shareContext.calendar_name}
                &rdquo; calendar with you. Create a free account to view it — Family isn&rsquo;t needed.
              </p>
            )}
            {!inviteContext && !shareContext && intent && intent.plan !== "free" && (
              <p className="signup-notice signup-notice--success">
                You selected Family ({intervalName(intent.interval)} billing) — you&rsquo;ll confirm this
                after creating your Home.
              </p>
            )}
            {showSocial && (
              <>
                <div className="signup-social">
                  {socialProviders.apple && (
                    <button type="button" className="signup-social-button signup-social-button--apple" onClick={() => startSocialRegistration("apple")} disabled={busy}>
                      <AppleMark size={18} />
                      {betaRequested ? "Join Beta with Apple" : "Continue with Apple"}
                    </button>
                  )}
                  {socialProviders.google && (
                    <button type="button" className="signup-social-button signup-social-button--google" onClick={() => startSocialRegistration("google")} disabled={busy}>
                      <GoogleMark size={18} />
                      {betaRequested ? "Join Beta with Google" : "Continue with Google"}
                    </button>
                  )}
                </div>
                <div className="signup-divider" role="separator">
                  <span />
                  {betaRequested ? "or join Beta with email" : "or create your account with email"}
                  <span />
                </div>
              </>
            )}
            {registrationClosed ? (
              <section className="register-closed" aria-labelledby="registration-closed-heading">
                <h2 id="registration-closed-heading">Registration is currently closed</h2>
                <p>
                  New MyKhaya accounts are not available right now. If you already have an account, you
                  can still sign in.
                </p>
                {signupState?.waitlist_available && <Link className="signup-pill-link" href="/waitlist">Join the waitlist</Link>}
                <Link className="signup-pill-link signup-pill-link--secondary" href="/login">Sign in</Link>
              </section>
            ) : (
              <form className="signup-form register-form" onSubmit={submit}>
                <div className="signup-fields">
                  <div className="signup-field">
                    <label htmlFor="register-name">Your name</label>
                    <input id="register-name" name="name" autoComplete="name" placeholder="e.g. Thandi Mokoena" required maxLength={100} />
                  </div>
                  <div className="signup-field">
                    <label htmlFor="register-email">Email</label>
                    <input id="register-email" name="email" type="email" inputMode="email" defaultValue={inviteContext?.email ?? shareContext?.recipient_email ?? ""} autoComplete="email" placeholder="you@example.com" required maxLength={320} />
                  </div>
                  <div className="signup-field">
                    <label htmlFor="register-password">Password</label>
                    <div className="signup-password">
                      <input id="register-password" name="password" type={passwordVisible ? "text" : "password"} autoComplete="new-password" aria-describedby="register-password-hint" required minLength={12} maxLength={128} />
                      <button
                        type="button"
                        className="signup-password-toggle"
                        // Drawn inside the password field by design.
                        data-input-adornment="password-visibility"
                        aria-controls="register-password register-confirm"
                        aria-label={passwordVisible ? "Hide passwords" : "Show passwords"}
                        onClick={() => setPasswordVisible((visible) => !visible)}
                      >
                        {passwordVisible ? <EyeOff size={20} aria-hidden="true" /> : <Eye size={20} aria-hidden="true" />}
                      </button>
                    </div>
                    <p id="register-password-hint" className="signup-field-hint">At least 12 characters</p>
                  </div>
                  <div className="signup-field">
                    <label htmlFor="register-confirm">Confirm password</label>
                    <input id="register-confirm" name="confirm" type={passwordVisible ? "text" : "password"} autoComplete="new-password" required minLength={12} maxLength={128} />
                  </div>
                </div>
                {legalDocuments.length > 0 && (
                  <SignupLegalConsent
                    documents={legalDocuments}
                    checked={legalChecked}
                    onChange={(key, value) => setLegalChecked((current) => ({ ...current, [key]: value }))}
                    required
                    betaTermsNote={betaRequested ? "email" : undefined}
                    noticeConfirmation
                  />
                )}
                <FormStatus error={error} />
                <button className="signup-primary register-submit" disabled={formDisabled}>
                  {busy ? "Creating account…" : betaRequested ? "Create account and continue" : "Create account"}
                </button>
                {showLegalHint && <p className="signup-after-primary register-legal-hint">Accept the Terms &amp; Conditions to continue.</p>}
              </form>
            )}
            {betaRequested && (
              <p className="signup-footer-line register-footer">
                Not joining the Beta? <Link href="/signup-choice">See other ways to join</Link>
              </p>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
