"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError, type PublicSignupState } from "@mykhaya/api-client";
import { PublicFooter } from "@/components/marketing/public-footer";
import { PublicHeader } from "@/components/marketing/public-header";

export function PublicFoundingBeta() {
  const router = useRouter();
  const params = useSearchParams();
  const invitation = params.get("invitation");
  const [state, setState] = useState<PublicSignupState | null>(null);
  const [invitationValid, setInvitationValid] = useState<boolean | null>(invitation ? null : false);
  const [invitationExpiresAt, setInvitationExpiresAt] = useState<string | null>(null);
  const [checkingSession, setCheckingSession] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.publicSignupState().then(setState).catch((reason: ApiError) => setError(reason.message));
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

  async function joinBeta() {
    setCheckingSession(true);
    setError("");
    try {
      await api.me();
      router.push(`/onboarding?beta=1${invitation ? `&invitation=${encodeURIComponent(invitation)}` : ""}`);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) {
        router.push(`/register?beta=1${invitation ? `&beta_invitation=${encodeURIComponent(invitation)}` : ""}`);
      } else {
        setError("We couldn’t check your sign-in. Please try again.");
      }
    } finally {
      setCheckingSession(false);
    }
  }

  const canJoin = Boolean(state?.beta_joining_available || invitationValid === true);
  const waitlist = state?.waitlist_available === true && !canJoin;

  return (
    <div className="mk-page mk-page-centred">
      <PublicHeader signupState={state} />
      <main className="mk-beta-main">
      <section className="mk-beta-hero" aria-labelledby="beta-heading">
        <p className="eyebrow">Founding Beta</p>
        <h1 id="beta-heading">Help shape a calmer home.</h1>
        <p>We’re inviting a limited number of households to help us test and improve MyKhaya.</p>
        <ul className="mk-plan-list mk-beta-public-list">
          <li>Complimentary Ultimate access for the lifetime of your Home</li>
          <li>All Ultimate features, with no payment or card required</li>
          <li>An opportunity to help shape MyKhaya</li>
        </ul>
        {invitation && invitationValid === false && <p className="notice error" role="alert">This Beta invitation is invalid, expired, cancelled or already used.</p>}
        {invitation && invitationValid === true && invitationExpiresAt && (
          <p className="notice success" role="status">This place is reserved for you until {new Date(invitationExpiresAt).toLocaleString("en-GB")}.</p>
        )}
        {error && <p className="notice error" role="alert">{error}</p>}
        {canJoin ? (
          <button className="button large" type="button" onClick={() => void joinBeta()} disabled={checkingSession}>
            {checkingSession ? "Checking your sign-in…" : "Join the Beta"}
          </button>
        ) : waitlist ? (
          <>
            <p className="notice">The next places are being offered from the waitlist first.</p>
            <Link className="button large" href="/waitlist">Join the waitlist</Link>
          </>
        ) : (
          <p className="notice" role="status">Founding Beta joining is currently unavailable. Please check back later.</p>
        )}
        {state?.joinable_count !== null && state?.joinable_count !== undefined && canJoin && (
          <p className="mk-beta-places" role="status">{state.joinable_count} places currently available</p>
        )}
        <p className="auth-footer"><Link href="/login">Already a member? Sign in</Link></p>
      </section>
      </main>
      <PublicFooter />
    </div>
  );
}
