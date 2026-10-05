"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, ApiError, type PublicSignupState } from "@mykhaya/api-client";
import { AuthCard } from "@/components/auth-card";
import { FormStatus } from "@/components/form-status";

export default function FoundingBeta() {
  const params = useSearchParams();
  const invitation = params.get("invitation");
  const [state, setState] = useState<PublicSignupState | null>(null);
  const [eligibility, setEligibility] = useState<{
    eligible: boolean;
    home_id: string | null;
    home_name: string | null;
    reason: string | null;
  } | null>(null);
  const [joined, setJoined] = useState(false);
  const [joinBusy, setJoinBusy] = useState(false);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [invitationValid, setInvitationValid] = useState<boolean | null>(invitation ? null : false);
  const [invitationExpiresAt, setInvitationExpiresAt] = useState<string | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.publicSignupState().then(setState).catch((reason: ApiError) => setError(reason.message));
    api.betaEligibility().then(setEligibility).catch(() => setEligibility(null));
  }, []);
  useEffect(() => {
    if (!invitation) return;
    api.publicBetaInvitation(invitation)
      .then((result) => {
        setInvitationValid(result.valid);
        setInvitationExpiresAt(result.expires_at);
      })
      .catch(() => setInvitationValid(false));
  }, [invitation]);
  const canJoin = Boolean(state?.beta_joining_available || invitationValid === true);
  const waitlist = state?.waitlist_available === true && !canJoin;
  async function enrolExistingHome() {
    if (!state?.beta_terms_version || !termsAccepted) return;
    setJoinBusy(true);
    setError("");
    try {
      await api.joinBeta({
        home_name: eligibility?.home_name ?? "MyKhaya Home",
        terms_version: state.beta_terms_version,
        invitation_token: invitation ?? undefined,
      });
      setJoined(true);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "We couldn’t enrol this Home.");
    } finally {
      setJoinBusy(false);
    }
  }
  return (
    <AuthCard title="Founding Beta" intro="A limited cohort helping shape a calmer digital home.">
      <p>
        Founding Beta members receive Complimentary Ultimate access for the lifetime of their Home.
        There is no cost to join, and places are limited while we test and improve MyKhaya.
      </p>
      {invitation && invitationValid === false && <p className="notice error" role="alert">This Beta invitation is invalid, expired, cancelled or already used.</p>}
      {invitation && invitationValid === true && invitationExpiresAt && (
        <p className="notice success" role="status">
          This place is reserved for you until {new Date(invitationExpiresAt).toLocaleString("en-GB")}.
        </p>
      )}
      {error && <FormStatus error={error} />}
      {joined && <p className="notice success" role="status">Your Home is now enrolled with complimentary Ultimate access.</p>}
      {eligibility?.reason && <p className="notice" role="status">{eligibility.reason}</p>}
      {eligibility?.eligible && eligibility.home_name && !joined && (
        <section className="beta-existing-home" aria-labelledby="existing-home-heading">
          <h2 id="existing-home-heading">Enrol {eligibility.home_name} in the Founding Beta</h2>
          <p>Your existing Home, data and members stay in place. Its access becomes complimentary Ultimate under the Beta benefit.</p>
          <label className="check-row">
            <input type="checkbox" checked={termsAccepted} onChange={(event) => setTermsAccepted(event.target.checked)} />
            <span>I accept the Founding Beta Terms (version {state?.beta_terms_version ?? "current"}).</span>
          </label>
          <button type="button" className="button full" disabled={joinBusy || !termsAccepted} onClick={() => void enrolExistingHome()}>
            {joinBusy ? "Enrolling…" : "Enrol this Home"}
          </button>
        </section>
      )}
      {canJoin ? (
        <Link className="button full" href={`/register?beta=1${invitation ? `&beta_invitation=${encodeURIComponent(invitation)}` : ""}`}>
          Continue to Beta registration
        </Link>
      ) : waitlist ? (
        <>
          <p className="notice">The next places are being offered from the waitlist first.</p>
          <Link className="button full" href="/waitlist">Join the waitlist</Link>
        </>
      ) : (
        <p className="notice" role="status">Founding Beta joining is currently unavailable. Please check back later.</p>
      )}
      <p className="auth-footer"><Link href="/login">Already a member? Sign in</Link></p>
    </AuthCard>
  );
}
