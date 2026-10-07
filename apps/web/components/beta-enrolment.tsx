"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  api,
  ApiError,
  type BetaContinuationState,
  type PublicSignupState,
} from "@mykhaya/api-client";
import { FormStatus } from "@/components/form-status";
import { useAuth } from "@/components/auth-provider";
import { AppLinks, hasAnyAppLink, useNativeShell } from "@/components/app-links/app-links";
import { isNativeShell, nativePlatform } from "@/components/native-runtime";

// The authenticated Founding Beta continuation. Reached after email
// verification and sign-in — automatically for an account created through
// the Beta (the server-side Beta intent, GET /beta/continuation), or from
// /founding-beta for an existing user. It never shows plans, prices or
// payment: the Home gets complimentary Ultimate (founding_beta_lifetime).
//
//   welcome + current Founding Beta Terms -> create/enrol Home -> confirm -> done

type Step = "welcome" | "home" | "confirm" | "done";

function platform(): "web" | "ios" | "android" {
  if (!isNativeShell()) return "web";
  const value = nativePlatform();
  return value === "ios" || value === "android" ? value : "web";
}

export function BetaEnrolment() {
  const router = useRouter();
  const params = useSearchParams();
  const invitation = params.get("invitation");
  const { status } = useAuth();
  const [state, setState] = useState<PublicSignupState | null>(null);
  const [continuation, setContinuation] = useState<BetaContinuationState | null>(null);
  const [step, setStep] = useState<Step>("welcome");
  const [termsChecked, setTermsChecked] = useState(false);
  const [homeName, setHomeName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (status === "signed_out") router.replace("/login?next=/onboarding%3Fbeta%3D1");
  }, [router, status]);

  const load = useCallback(async () => {
    try {
      const [signupState, next] = await Promise.all([api.publicSignupState(), api.betaContinuation()]);
      setState(signupState);
      setContinuation(next);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) router.replace("/login?next=/onboarding%3Fbeta%3D1");
      else setError(reason instanceof ApiError ? reason.message : "We couldn’t load your Founding Beta details.");
    }
  }, [router]);

  useEffect(() => {
    if (status !== "ready") return;
    void load();
  }, [status, load]);

  const terms = continuation?.terms ?? null;
  const existingHome = Boolean(continuation?.home_id);
  // No published Beta Terms document: fall back to the programme's own terms
  // reference (accepted as part of joining, as before).
  const legacyTermsVersion = !terms ? state?.beta_terms_version ?? null : null;
  const termsOutstanding = terms ? !terms.satisfied : Boolean(legacyTermsVersion);

  async function continueFromWelcome(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (termsOutstanding && !termsChecked) {
      setError("Please accept the Founding Beta Terms to continue.");
      return;
    }
    setError("");
    if (terms && !terms.satisfied) {
      setBusy(true);
      try {
        await api.acceptLegalDocument({
          document_key: terms.document_key,
          document_version_id: terms.version_id,
          context: "beta_enrolment",
          platform: platform(),
        });
        setContinuation((current) => (current ? { ...current, terms: { ...terms, satisfied: true } } : current));
      } catch (reason) {
        setError(reason instanceof ApiError ? reason.message : "We couldn’t record your acceptance. Please try again.");
        setBusy(false);
        return;
      }
      setBusy(false);
    }
    setStep(existingHome ? "confirm" : "home");
  }

  function continueFromHome(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!homeName.trim()) {
      setError("Please give your Home a name.");
      return;
    }
    setError("");
    setStep("confirm");
  }

  async function join() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await api.joinBeta({
        home_name: existingHome ? undefined : homeName.trim(),
        terms_version: legacyTermsVersion ?? undefined,
        invitation_token: invitation ?? undefined,
      });
      setStep("done");
    } catch (reason) {
      if (reason instanceof ApiError && reason.code === "beta_terms_required") {
        // The Beta Terms changed while this screen was open: start again from
        // the Terms step with the new version.
        await load();
        setTermsChecked(false);
        setStep("welcome");
      }
      setError(reason instanceof ApiError ? reason.message : "We couldn’t complete your Founding Beta enrolment.");
    } finally {
      setBusy(false);
    }
  }

  if (step === "done") {
    return (
      <BetaCard eyebrow="Founding Beta" title="Your Home is now in the Founding Beta">
        <p>Your Home has complimentary MyKhaya Ultimate access for its lifetime. We’ve sent you a welcome email.</p>
        <GetTheAppStep ios={state?.ios_app_url} android={state?.android_app_url} />
        <Link className="button" href="/home">Enter MyKhaya</Link>
      </BetaCard>
    );
  }

  if (!continuation) {
    return (
      <main className="standard-page beta-continuation">
        {error ? <FormStatus error={error} /> : <p role="status" className="muted">Loading your Founding Beta details…</p>}
      </main>
    );
  }

  if (continuation.enrolled) {
    return (
      <BetaCard eyebrow="Founding Beta" title="Your Home is already in the Founding Beta">
        <p>It has complimentary MyKhaya Ultimate access for its lifetime. There’s nothing more to do.</p>
        <Link className="button" href="/home">Enter MyKhaya</Link>
      </BetaCard>
    );
  }

  if (!continuation.eligible) {
    const paid = Boolean(continuation.home_id);
    return (
      <BetaCard eyebrow="Founding Beta" title={paid ? "Your Home already has a paid plan" : "This account can’t join the Founding Beta"}>
        <p>{continuation.reason ?? "Existing paid Homes cannot be converted through the public Founding Beta."}</p>
        {paid && <p>Your current subscription is unchanged. No payment or subscription action has occurred.</p>}
        <Link className="button" href="/home">Return home</Link>{" "}
        <Link className="button secondary" href="/founding-beta">About the Beta</Link>
      </BetaCard>
    );
  }

  if (step === "home") {
    return (
      <BetaCard eyebrow="Founding Beta" title="Create your Home">
        <p>This Home will receive complimentary MyKhaya Ultimate access as part of the Founding Beta.</p>
        <form onSubmit={continueFromHome}>
          <label>
            Home name
            <input value={homeName} onChange={(event) => setHomeName(event.target.value)} maxLength={100} required autoComplete="organization" />
          </label>
          <FormStatus error={error} />
          <button type="submit">Continue</button>
        </form>
      </BetaCard>
    );
  }

  if (step === "confirm") {
    const name = existingHome ? continuation.home_name ?? "Your Home" : homeName.trim();
    return (
      <BetaCard eyebrow="Founding Beta" title="Confirm your Beta enrolment">
        <p>You’re joining the MyKhaya Founding Beta.</p>
        {existingHome && (
          <p className="muted">Your existing Home stays exactly as it is, with all its members and everything in it.</p>
        )}
        <dl className="beta-summary">
          <div><dt>Home</dt><dd>{name}</dd></div>
          <div><dt>Plan</dt><dd>Ultimate</dd></div>
          <div><dt>Cost</dt><dd>Complimentary</dd></div>
          <div><dt>Payment required</dt><dd>No</dd></div>
        </dl>
        <FormStatus error={error} />
        <button type="button" className="button" onClick={() => void join()} disabled={busy}>
          {busy ? "Joining…" : "Join the Founding Beta"}
        </button>{" "}
        <button type="button" className="tertiary" onClick={() => { setError(""); setStep(existingHome ? "welcome" : "home"); }} disabled={busy}>
          Back
        </button>
      </BetaCard>
    );
  }

  // welcome
  return (
    <BetaCard eyebrow="Founding Beta" title="Welcome to the MyKhaya Founding Beta">
      <p><strong>You’re almost there.</strong></p>
      <p>
        As a Founding Beta household, your Home will receive complimentary access to MyKhaya Ultimate for the
        lifetime of the Home.
      </p>
      <p>No subscription or payment details are required.</p>
      <form onSubmit={continueFromWelcome}>
        {termsOutstanding && (
          <label className="check-row">
            <input type="checkbox" checked={termsChecked} onChange={(event) => setTermsChecked(event.target.checked)} required />
            <span>
              I accept the <Link href="/legal/founding-beta-terms">{terms?.display_name ?? "Founding Beta Terms"}</Link> (version{" "}
              {terms?.version ?? legacyTermsVersion})
            </span>
          </label>
        )}
        {terms?.satisfied && (
          <p className="muted">You’ve already accepted the current Founding Beta Terms (version {terms.version}).</p>
        )}
        <FormStatus error={error} />
        <button type="submit" disabled={busy || (termsOutstanding && !termsChecked)}>
          {busy ? "Saving…" : "Continue"}
        </button>
      </form>
    </BetaCard>
  );
}

function BetaCard({ eyebrow, title, children }: { eyebrow: string; title: string; children: React.ReactNode }) {
  return (
    <section className="standard-page beta-continuation">
      <div className="card feature-card">
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        {children}
      </div>
    </section>
  );
}

/** "Next: get MyKhaya on your phone", from the PCC iPhone/Android app links
 *  (same link-type rules as the homepage and Founding Beta page). Hidden when
 *  neither link is set, and when this card is shown inside the native app. */
function GetTheAppStep({ ios, android }: { ios: string | null | undefined; android: string | null | undefined }) {
  const native = useNativeShell();
  if (native || !hasAnyAppLink(ios, android)) return null;
  return (
    <section className="beta-get-app" aria-labelledby="beta-get-app-heading">
      <h2 id="beta-get-app-heading">Next: get MyKhaya on your phone</h2>
      <p>Install the app and sign in with this account to take your Home with you.</p>
      <AppLinks ios={ios} android={android} surface="beta" label="Get the app" />
    </section>
  );
}
