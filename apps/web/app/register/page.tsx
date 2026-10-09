"use client";
export const dynamic = "force-dynamic";
import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  api,
  ApiError,
  type PublicLegalDocumentSummary,
  type PublicSignupState,
} from "@mykhaya/api-client";
import { AuthCard } from "@/components/auth-card";
import { FormStatus } from "@/components/form-status";
import { intervalName } from "@/components/billing-logic";
import { parseIntentFromParams, saveOnboardingIntent } from "@/components/onboarding-intent";
import { nativeRegister } from "@/components/native-auth";
import { isNativeShell, nativePlatform } from "@/components/native-runtime";
import { isMaintenanceError } from "@/components/maintenance";
import { registrationUnavailableReason } from "@/components/registration-availability";

const LEGAL_PAGE_BY_KEY: Record<string, string> = {
  terms: "/legal/terms",
  privacy: "/legal/privacy",
  children_privacy: "/legal/children",
  cookies: "/legal/cookies",
  founding_beta_terms: "/legal/founding-beta-terms",
};

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
  useEffect(() => {
    // Display-only: the API enforces registration regardless. A failed lookup
    // never blocks the form — the server's own rejection is the authority.
    api
      .publicSignupState()
      .then(setSignupState)
      .catch((cause) => setMaintenance(isMaintenanceError(cause)))
      .finally(() => setSignupStateLoaded(true));
  }, []);
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
    signupStateLoaded && !maintenance && Boolean(signupState) && !signupState!.registration_open;
  return (
    <AuthCard
      title="Create your account"
      intro="A calm, private place for the people closest to you."
      footer={
        <span>
          Already have an account?{" "}
          <Link
            href={
              invitation
                ? `/login?invitation=${encodeURIComponent(invitation)}`
                : calendarShare
                  ? `/login?calendar_share=${encodeURIComponent(calendarShare)}`
                  : "/login"
            }
          >
            Sign in
          </Link>
        </span>
      }
    >
      {unavailableReason && (
        <p className="notice" role="status">
          {unavailableReason}
        </p>
      )}
      {unavailableReason && signupState?.signup_mode === "beta_only" && !betaRequested && (
        <Link className="button full" href="/founding-beta">
          Continue to Founding Beta
        </Link>
      )}
      {inviteContext && (
        <p className="notice success">
          {inviteContext.invited_by_display_name} invited you to join {inviteContext.group_name}.
        </p>
      )}
      {shareContext && (
        <p className="notice success">
          {shareContext.source_group_name} wants to share the &ldquo;{shareContext.calendar_name}
          &rdquo; calendar with you. Create a free account to view it — Family isn&rsquo;t needed.
        </p>
      )}
      {betaRequested && (
        <p className="notice success">
          You’re registering for the MyKhaya Founding Beta. After verifying your email, you’ll
          complete your Beta enrolment and receive complimentary Ultimate access.
        </p>
      )}
      {!inviteContext && !shareContext && intent && intent.plan !== "free" && (
        <p className="notice success">
          You selected Family ({intervalName(intent.interval)} billing) — you&rsquo;ll confirm this
          after creating your Home.
        </p>
      )}
      {registrationClosed ? (
        <section className="registration-closed" aria-labelledby="registration-closed-heading">
          <h2 id="registration-closed-heading">Registration is currently closed</h2>
          <p>
            New MyKhaya accounts are not available right now. If you already have an account, you
            can still sign in.
          </p>
          {signupState?.waitlist_available && (
            <Link className="button full" href="/waitlist">Join the waitlist</Link>
          )}
          <Link className="button full secondary" href="/login">Sign in</Link>
        </section>
      ) : <form onSubmit={submit}>
        <label>
          Your name
          <input name="name" autoComplete="name" required maxLength={100} />
        </label>
        {legalDocuments.length > 0 && (
          <fieldset className="auth-legal-consent">
            <legend>Before you create your account</legend>
            <p className="muted">
              Please review the documents that apply to your account.
            </p>
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
            <p>
              <strong>Informational notices</strong>
            </p>
            <p className="muted">
              <Link href="/legal/privacy">Privacy Notice</Link> ·{" "}
              <Link href="/legal/children">Family &amp; Children&rsquo;s Privacy Notice</Link> ·{" "}
              <Link href="/legal/cookies">Cookie Policy</Link>
            </p>
            <p className="hint">
              By creating an account, you confirm that these notices have been made available to
              you.
            </p>
          </fieldset>
        )}
        <label>
          Email
          <input
            name="email"
            type="email"
            defaultValue={inviteContext?.email ?? shareContext?.recipient_email ?? ""}
            autoComplete="email"
            required
            maxLength={320}
          />
        </label>
        <label>
          Password <small>At least 12 characters</small>
          <input
            name="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            maxLength={128}
          />
        </label>
        <label>
          Confirm password
          <input
            name="confirm"
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            maxLength={128}
          />
        </label>
        <FormStatus error={error} />
        <button
          disabled={busy || Boolean(unavailableReason) || !contractualAcceptanceComplete}
        >
          {busy ? "Creating account…" : "Create account"}
        </button>
      </form>}
    </AuthCard>
  );
}
