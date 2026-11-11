"use client";
export const dynamic = "force-dynamic";
import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Check, CreditCard, Eye, EyeOff, Gift, Users } from "lucide-react";
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
import { socialRegistrationStartUrl } from "./registration-urls";
import "@/app/brand-fonts.css";
import "./register.css";

const LEGAL_PAGE_BY_KEY: Record<string, string> = {
  terms: "/legal/terms",
  privacy: "/legal/privacy",
  children_privacy: "/legal/children",
  cookies: "/legal/cookies",
  founding_beta_terms: "/legal/founding-beta-terms",
};

const BENEFITS = [
  { title: "Complimentary Ultimate for life", detail: "Full access to all features.", icon: Gift },
  { title: "No payment card required", detail: "Join without any payment details.", icon: CreditCard },
  { title: "Limited places while we test", detail: "A small number of households.", icon: Users },
] as const;

function HouseStarIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 11l9-7 9 7" />
      <path d="M5 10v9a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-9" />
      <path d="M12 11.5l.9 1.9 2.1.3-1.5 1.4.4 2.1-1.9-1-1.9 1 .4-2.1-1.5-1.4 2.1-.3z" />
    </svg>
  );
}

function AppleIcon() {
  return <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M16.37 12.6c-.02-2.3 1.88-3.4 1.96-3.46-1.07-1.56-2.73-1.78-3.32-1.8-1.41-.14-2.76.83-3.47.83-.72 0-1.82-.81-3-.79-1.54.02-2.96.9-3.76 2.28-1.6 2.78-.41 6.9 1.15 9.15.76 1.1 1.67 2.34 2.86 2.3 1.15-.05 1.58-.74 2.97-.74 1.38 0 1.77.74 2.98.72 1.23-.02 2.01-1.12 2.76-2.23.87-1.28 1.23-2.52 1.25-2.58-.03-.01-2.4-.92-2.38-3.68zM14.1 5.86c.63-.77 1.06-1.83.94-2.89-.91.04-2.01.61-2.66 1.37-.58.67-1.09 1.76-.95 2.8 1.01.08 2.04-.51 2.67-1.28z" /></svg>;
}

function GoogleIcon() {
  return <svg aria-hidden="true" width="18" height="18" viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" /><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" /><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" /><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" /></svg>;
}

function RegisterBrandPanel({ beta }: { beta: boolean }) {
  const steps = beta
    ? ["Create your account", "Verify your email", "Accept the Beta Terms and enrol your Home"]
    : ["Create your account", "Verify your email", "Set up your Home"];
  return (
    <section className="register-brand-panel" aria-label="About MyKhaya">
      <a className="register-brand-logo" href="/">
        <img src="/images/mykhaya-logo.png" alt="" />
        <span>MyKhaya</span>
      </a>
      {beta ? (
        <div className="register-brand-message register-brand-message--beta">
          <span className="register-beta-pill">★&nbsp; Founding Beta</span>
          <h2>Help shape a calmer home.</h2>
          <p>Join a small group of households testing and improving MyKhaya.</p>
          <ul className="register-benefits">
            {BENEFITS.map(({ title, detail, icon: Icon }) => (
              <li key={title}>
                <span className="register-benefit-tile" aria-hidden="true"><Icon size={22} strokeWidth={1.8} /></span>
                <span><strong>{title}</strong><small>{detail}</small></span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="register-brand-message">
          <p className="register-eyebrow">Your family’s digital home</p>
          <h2>Life feels lighter when everyone knows the plan.</h2>
        </div>
      )}
      <div className="register-brand-steps">
        <p>Three calm steps</p>
        <ol>
          {steps.map((step, index) => (
            <li key={step} className={index === 0 ? "active" : ""}>
              <span>{index + 1}</span><strong>{step}</strong>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

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
  const requiredContractualDocuments = legalDocuments.filter(
    (document) =>
      document.audience === "adult" &&
      document.acceptance_required &&
      document.action_verb === "accept" &&
      document.scope === "global",
  );
  const contractualAcceptanceComplete =
    !legalLoading &&
    !legalLoadFailed &&
    requiredContractualDocuments.every(
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
  return (
    <main className={`register-page${betaRequested ? " register-page--beta" : ""}`}>
      <RegisterBrandPanel beta={betaRequested} />
      <section className="register-form-area">
        <div className="register-form-column">
          <a className="register-mobile-logo" href="/"><img src="/images/mykhaya-logo.png" alt="" /><span>MyKhaya</span></a>
          <div className="register-mobile-steps" aria-label={betaRequested ? "Founding Beta, step 1 of 3" : "Step 1 of 3, then verify your email"}>
            <span className="register-step-pill" /><span /><span />
            <strong>{betaRequested ? "Founding Beta · step 1 of 3" : "Step 1 of 3 · then verify your email"}</strong>
          </div>
          <header className="register-heading"><h1>Create your account</h1><p>A calm, private place for the people closest to you.</p></header>
          {betaRequested && (
            <section className="register-beta-card" aria-labelledby="register-beta-heading">
              <div className="register-beta-card-top">
                <span className="register-beta-icon"><HouseStarIcon /></span>
                <span><strong id="register-beta-heading">You&rsquo;re joining the Founding Beta</strong><span>After you verify your email, you&rsquo;ll finish enrolment and receive complimentary Ultimate access.</span></span>
              </div>
              <ul>{BENEFITS.map(({ title }) => <li key={title}><Check size={16} aria-hidden="true" />{title}</li>)}</ul>
            </section>
          )}
      {unavailableReason && (
        <p className="register-context-card" role="status">
          {unavailableReason}
        </p>
      )}
      {unavailableReason && signupState?.signup_mode === "beta_only" && !betaRequested && (
        <Link className="register-pill-button register-pill-button--secondary" href="/founding-beta">
          Continue to Founding Beta
        </Link>
      )}
      {inviteContext && (
        <p className="register-context-card register-context-card--success">
          {inviteContext.invited_by_display_name} invited you to join {inviteContext.group_name}.
        </p>
      )}
      {shareContext && (
        <p className="register-context-card register-context-card--success">
          {shareContext.source_group_name} wants to share the &ldquo;{shareContext.calendar_name}
          &rdquo; calendar with you. Create a free account to view it — Family isn&rsquo;t needed.
        </p>
      )}
      {(socialProviders.apple || socialProviders.google) && !invitation && !calendarShare && (
        <div className="register-social">
          <div className="register-social-actions">
            {socialProviders.apple && (
              <button type="button" className="register-social-button register-social-button--apple" onClick={() => startSocialRegistration("apple")} disabled={busy}>
                <AppleIcon />
                {betaRequested ? "Join Beta with Apple" : "Continue with Apple"}
              </button>
            )}
            {socialProviders.google && (
              <button type="button" className="register-social-button register-social-button--google" onClick={() => startSocialRegistration("google")} disabled={busy}>
                <GoogleIcon />
                {betaRequested ? "Join Beta with Google" : "Continue with Google"}
              </button>
            )}
          </div>
          <div className="register-divider" role="separator"><span />{betaRequested ? "or join Beta with email" : "or create your account with email"}<span /></div>
        </div>
      )}
      {!inviteContext && !shareContext && intent && intent.plan !== "free" && (
        <p className="register-context-card register-context-card--success">
          You selected Family ({intervalName(intent.interval)} billing) — you&rsquo;ll confirm this
          after creating your Home.
        </p>
      )}
      {registrationClosed ? (
        <section className="register-closed" aria-labelledby="registration-closed-heading">
          <h2 id="registration-closed-heading">Registration is currently closed</h2>
          <p>
            New MyKhaya accounts are not available right now. If you already have an account, you
            can still sign in.
          </p>
          {signupState?.waitlist_available && <Link className="register-pill-button" href="/waitlist">Join the waitlist</Link>}
          <Link className="register-pill-button register-pill-button--secondary" href="/login">Sign in</Link>
        </section>
      ) : <form className="register-form" onSubmit={submit}>
        <div className="register-field">
          <label htmlFor="register-name">Your name</label>
          <input id="register-name" name="name" autoComplete="name" placeholder="e.g. Thandi Mokoena" required maxLength={100} />
        </div>
        <div className="register-field">
          <label htmlFor="register-email">Email</label>
          <input id="register-email" name="email" type="email" defaultValue={inviteContext?.email ?? shareContext?.recipient_email ?? ""} autoComplete="email" placeholder="you@example.com" required maxLength={320} />
        </div>
        <div className="register-field">
          <div className="register-label-row"><label htmlFor="register-password">Password</label><small>At least 12 characters</small></div>
          <div className="register-password-wrap">
            <input id="register-password" name="password" type={passwordVisible ? "text" : "password"} autoComplete="new-password" required minLength={12} maxLength={128} />
            <button type="button" className="register-password-toggle" aria-label={passwordVisible ? "Hide passwords" : "Show passwords"} onClick={() => setPasswordVisible((visible) => !visible)}>{passwordVisible ? <EyeOff size={20} aria-hidden="true" /> : <Eye size={20} aria-hidden="true" />}</button>
          </div>
        </div>
        <div className="register-field">
          <label htmlFor="register-confirm">Confirm password</label>
          <input id="register-confirm" name="confirm" type={passwordVisible ? "text" : "password"} autoComplete="new-password" required minLength={12} maxLength={128} />
        </div>
        {legalDocuments.length > 0 && (
          <fieldset className="register-legal">
            <legend>Before you continue</legend>
            {requiredContractualDocuments.length > 0 && (
              <>
                <p>
                  <strong>Required contractual acceptance</strong>
                </p>
                {requiredContractualDocuments.map((document) => (
                  <label className="check-row" key={document.key}>
                    <input
                      type="checkbox"
                      required
                      aria-label={`I accept the ${document.display_name} (version ${document.current_version ?? "current"})`}
                      checked={legalChecked[document.key] === true}
                      onChange={(event) =>
                        setLegalChecked((current) => ({
                          ...current,
                          [document.key]: event.target.checked,
                        }))
                      }
                    />
                    <span>
                      I accept the{" "}
                      <Link href={LEGAL_PAGE_BY_KEY[document.key] ?? `/legal/${document.key}`}>
                        {document.display_name}
                      </Link>{" "}
                      (version {document.current_version ?? "current"})
                    </span>
                  </label>
                ))}
              </>
            )}
            <p className="register-legacy-info">
              <strong>Informational notices</strong>
            </p>
            <p className="muted">
              <Link href="/legal/privacy">Privacy Notice</Link> ·{" "}
              <Link href="/legal/children">Family &amp; Children&rsquo;s Privacy Notice</Link> ·{" "}
              <Link href="/legal/cookies">Cookie Policy</Link>
            </p>
            {betaRequested && <p className="register-beta-terms-note">You&rsquo;ll review the <Link href="/legal/founding-beta-terms">Founding Beta Terms</Link> after verifying your email.</p>}
            <p className="register-info-line">
              By creating an account, you confirm that these notices have been made available to
              you.
            </p>
          </fieldset>
        )}
        <FormStatus error={error} />
        <button className="register-submit" disabled={formDisabled}>
          {busy ? "Creating account…" : betaRequested ? "Create account and continue" : "Create account"}
        </button>
        {showLegalHint && <p className="register-legal-hint">Accept the Terms &amp; Conditions to continue.</p>}
      </form>}
          <footer className="register-footer">
            <p>Already have an account? <Link href={signInHref}>Sign in</Link></p>
            {betaRequested && <p>Not joining the Beta? <Link href="/signup-choice"><span className="register-beta-footer-wide">See other ways to join</span><span className="register-beta-footer-mobile">Other ways to join</span></Link></p>}
          </footer>
        </div>
      </section>
    </main>
  );
}
