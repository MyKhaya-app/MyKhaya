"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError, type BetaEligibilityState, type PublicSignupState } from "@mykhaya/api-client";
import { FormStatus } from "@/components/form-status";
import { useAuth } from "@/components/auth-provider";

export function BetaEnrolment() {
  const router = useRouter();
  const params = useSearchParams();
  const invitation = params.get("invitation");
  const { status, user } = useAuth();
  const [state, setState] = useState<PublicSignupState | null>(null);
  const [eligibility, setEligibility] = useState<BetaEligibilityState | null>(null);
  const [homeName, setHomeName] = useState("");
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (status === "signed_out") router.replace("/login?next=/onboarding%3Fbeta%3D1");
  }, [router, status]);

  useEffect(() => {
    if (status !== "ready") return;
    Promise.all([api.publicSignupState(), api.betaEligibility()])
      .then(([signupState, betaEligibility]) => {
        setState(signupState);
        setEligibility(betaEligibility);
        if (betaEligibility.home_name) setHomeName(betaEligibility.home_name);
      })
      .catch((reason: ApiError) => {
        if (reason.status === 401) router.replace("/login?next=/onboarding%3Fbeta%3D1");
        else setError(reason.message);
      });
  }, [status]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!state?.beta_terms_version || !termsAccepted || busy) return;
    setBusy(true);
    setError("");
    try {
      await api.joinBeta({
        home_name: homeName.trim(),
        terms_version: state.beta_terms_version,
        invitation_token: invitation ?? undefined,
      });
      setDone(true);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "We couldn’t enrol this Home.");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return <section className="standard-page"><div className="card feature-card"><p className="eyebrow">Founding Beta</p><h1>Your Home is now in the Founding Beta</h1><p>Your existing data and members remain in place, with complimentary Ultimate access.</p><Link className="button" href="/home">Return home</Link></div></section>;
  }
  if (!user || !eligibility) return <main className="standard-page"><p role="status">Loading your Beta options…</p></main>;
  if (!eligibility.eligible) {
    return <section className="standard-page"><div className="card feature-card"><p className="eyebrow">Founding Beta</p><h1>Your Home already has a paid plan</h1><p>{eligibility.reason ?? "Existing paid Homes cannot be converted through the public Founding Beta."}</p><p>Your current subscription is unchanged. No payment or subscription action has occurred.</p><Link className="button" href="/home">Return home</Link> <Link className="button secondary" href="/founding-beta">Learn about the Beta</Link></div></section>;
  }
  const existingHome = Boolean(eligibility.home_id);
  return <section className="standard-page"><div className="card feature-card"><p className="eyebrow">Founding Beta</p><h1>{existingHome ? `Enrol ${eligibility.home_name} in the Founding Beta` : "Create a Founding Beta Home"}</h1><p>{existingHome ? "The same Home will be retained. All existing data and members will remain, and the Home will become complimentary Ultimate. No second Home will be created." : "Create a Home with complimentary Ultimate access for its lifetime. No payment or card is required."}</p><form onSubmit={submit}>{!existingHome && <label>Home name<input value={homeName} onChange={(event) => setHomeName(event.target.value)} maxLength={100} required /></label>}<label className="check-row"><input type="checkbox" checked={termsAccepted} onChange={(event) => setTermsAccepted(event.target.checked)} required /><span>I accept the Founding Beta Terms (version {state?.beta_terms_version ?? "current"}).</span></label><FormStatus error={error} /><button disabled={busy || !state?.beta_terms_version}>{busy ? "Enrolling…" : existingHome ? "Enrol this Home" : "Create Beta Home"}</button></form></div></section>;
}
