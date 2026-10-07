"use client";

import Link from "next/link";
import { signupPromiseApplies } from "@/components/public-signup";
import { SignupLink, signupIsSignIn } from "./signup-link";
import { useSignupStateContext } from "./signup-state-context";

/** Final sign-up banner; its wording follows the signup mode. */
export function HomeCta() {
  const signupState = useSignupStateContext();
  const promise = signupPromiseApplies(signupState);
  return (
    <section className="cta">
      <div className="wrap">
        <div className="cta-box">
          <div className="blocks" aria-hidden="true">
            <i style={{ background: "var(--coral)" }} />
            <i style={{ background: "var(--on-forest)" }} />
            <i style={{ background: "var(--sage)" }} />
            <i style={{ background: "var(--mustard)" }} />
          </div>
          <div>
            <h2>Ready to bring your family together?</h2>
            {promise === false ? (
              <p>New sign-ups are currently closed.</p>
            ) : (
              <p style={promise === null ? { visibility: "hidden" } : undefined}>Free to start. No card required. Set up in minutes.</p>
            )}
          </div>
          <div className="cta-actions">
            <SignupLink className="btn btn-primary" state={signupState} suffix=" →" />
            {!signupIsSignIn(signupState) && (
              <Link className="btn btn-light" href="/login">
                Sign in
              </Link>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
