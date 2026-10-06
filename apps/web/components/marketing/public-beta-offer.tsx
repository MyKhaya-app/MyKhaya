import Link from "next/link";
import type { PublicSignupState } from "@mykhaya/api-client";

export function PublicBetaOffer({ signupState }: { signupState: PublicSignupState }) {
  return (
    <section id="pricing" className="mk-section mk-pricing mk-beta-offer" aria-labelledby="beta-offer-heading">
      <div className="mk-pricing-heading">
        <p className="eyebrow">Founding Beta</p>
        <h2 id="beta-offer-heading">Join MyKhaya at no cost during our Founding Beta</h2>
        <p>We’re inviting a limited number of households to help us test and improve MyKhaya.</p>
      </div>
      <div className="mk-beta-offer-card">
        <h3>Founding Beta Homes receive</h3>
        <ul className="mk-plan-list">
          <li>Complimentary Ultimate access for the lifetime of their Home</li>
          <li>All Ultimate features</li>
          <li>No payment or card required</li>
          <li>An opportunity to help shape MyKhaya</li>
        </ul>
        {signupState.joinable_count !== null && signupState.beta_joining_available ? (
          <p className="mk-beta-places" role="status">
            {signupState.joinable_count} places currently available
          </p>
        ) : null}
        {signupState.beta_joining_available ? (
          <Link className="button large" href="/founding-beta">Join the Beta</Link>
        ) : signupState.waitlist_available ? (
          <Link className="button large" href="/waitlist">Join the waitlist</Link>
        ) : (
          <p className="notice" role="status">Founding Beta joining is currently unavailable.</p>
        )}
      </div>
    </section>
  );
}
