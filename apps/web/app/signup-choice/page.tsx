"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type PublicSignupState } from "@mykhaya/api-client";
import { PublicFooter } from "@/components/marketing/public-footer";
import { PublicHeader } from "@/components/marketing/public-header";

export default function SignupChoice() {
  const [state, setState] = useState<PublicSignupState | null>(null);
  useEffect(() => {
    api.publicSignupState().then(setState).catch(() => setState(null));
  }, []);
  return (
    <main className="mk-page">
      <PublicHeader signupState={state} />
      <section className="mk-choice" aria-labelledby="choice-heading">
        <p className="eyebrow">Choose your path</p>
        <h1 id="choice-heading">How would you like to join MyKhaya?</h1>
        <div className="mk-choice-grid">
          <article>
            <h2>Join the Founding Beta</h2>
            <p>Help us test MyKhaya with a limited cohort and receive Complimentary Ultimate access for the lifetime of your Home.</p>
            {state?.beta_joining_available ? (
              <Link className="button" href="/founding-beta">Explore the Beta</Link>
            ) : state?.waitlist_available ? (
              <Link className="button" href="/waitlist">Join the waitlist</Link>
            ) : (
              <p className="notice">Beta joining is currently unavailable.</p>
            )}
          </article>
          <article>
            <h2>Start a regular Home</h2>
            <p>Create a normal account and choose the plan that fits your household. No Beta commitment is needed.</p>
            <Link className="button secondary" href="/register">Create an account</Link>
          </article>
        </div>
      </section>
      <PublicFooter />
    </main>
  );
}
