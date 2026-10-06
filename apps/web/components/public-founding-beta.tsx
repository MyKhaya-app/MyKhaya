"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, CreditCard, Gift, Users, type LucideIcon } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError, type PublicSignupState } from "@mykhaya/api-client";
import { PublicFooter } from "@/components/marketing/public-footer";
import { PublicHeader } from "@/components/marketing/public-header";

const BENEFITS: { title: string; detail: string; icon: LucideIcon; tone: "sage" | "blue" | "sand" }[] = [
  { title: "Complimentary Ultimate for life", detail: "Full access to all features.", icon: Gift, tone: "sage" },
  { title: "No payment card required", detail: "Join without any payment details.", icon: CreditCard, tone: "blue" },
  { title: "Limited places while we test", detail: "A small number of households.", icon: Users, tone: "sand" },
];

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
    <div className="mk-page mk-beta-page">
      <PublicHeader signupState={state} compactOnMobile />
      <main className="mk-beta-main">
        <section className="mk-beta" aria-labelledby="beta-heading">
          <div className="mk-beta-intro">
            <p className="eyebrow mk-beta-eyebrow">Founding Beta</p>
            <h1 id="beta-heading">Help shape a calmer home.</h1>
            <p className="mk-beta-lede">Join a small group of households testing and improving MyKhaya.</p>
          </div>

          <section className="mk-beta-benefits" aria-labelledby="beta-benefits-heading">
            <h2 id="beta-benefits-heading">What you get</h2>
            <ul>
              {BENEFITS.map(({ title, detail, icon: Icon, tone }) => (
                <li key={title}>
                  <span className={`mk-beta-benefit-icon ${tone}`} aria-hidden="true">
                    <Icon size={24} strokeWidth={1.75} />
                  </span>
                  <span className="mk-beta-benefit-text">
                    <strong>{title}</strong>
                    <span>{detail}</span>
                  </span>
                </li>
              ))}
            </ul>
          </section>

          <div className="mk-beta-actions">
            {invitation && invitationValid === false && <p className="notice error" role="alert">This Beta invitation is invalid, expired, cancelled or already used.</p>}
            {invitation && invitationValid === true && invitationExpiresAt && (
              <p className="notice success" role="status">This place is reserved for you until {new Date(invitationExpiresAt).toLocaleString("en-GB")}.</p>
            )}
            {error && <p className="notice error" role="alert">{error}</p>}
            {canJoin ? (
              <button className="button mk-beta-cta" type="button" onClick={() => void joinBeta()} disabled={checkingSession}>
                {checkingSession ? "Checking your sign-in…" : <>Join the Beta <ArrowRight size={22} strokeWidth={2} aria-hidden="true" /></>}
              </button>
            ) : waitlist ? (
              <>
                <p className="notice">The next places are being offered from the waitlist first.</p>
                <Link className="button mk-beta-cta" href="/waitlist">Join the waitlist <ArrowRight size={22} strokeWidth={2} aria-hidden="true" /></Link>
              </>
            ) : (
              <p className="notice" role="status">Founding Beta joining is currently unavailable. Please check back later.</p>
            )}
            <p className="mk-beta-member">Already a member? <Link href="/login">Sign in</Link></p>
            <p className="mk-beta-terms">By joining, you agree to our <Link href="/legal/founding-beta-terms">Beta Terms</Link>.</p>
          </div>
        </section>
      </main>
      <PublicFooter compactOnMobile />
    </div>
  );
}
