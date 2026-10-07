"use client";

import { signupPromiseApplies } from "@/components/public-signup";
import { SignupLink } from "./signup-link";
import { useSignupStateContext } from "./signup-state-context";

/** The hero's signup-mode-dependent parts: the primary action and the
 *  "Free to start · No card required · Set up in minutes" ticks. */
export function HeroActions() {
  const signupState = useSignupStateContext();
  const promise = signupPromiseApplies(signupState);
  return (
    <>
      <div className="hero-actions">
        <SignupLink className="btn btn-primary" state={signupState} suffix=" →" />
        <a className="btn btn-ghost" href="#features">
          Take the tour
        </a>
      </div>
      {/* Only promised when true for the current signup mode. Held (but
          invisible, so nothing shifts) until the mode is known; removed when
          sign-ups are closed. */}
      {promise !== false && (
        <ul
          className="ticks"
          style={promise === null ? { visibility: "hidden" } : undefined}
          aria-hidden={promise === null || undefined}
        >
          <li>Free to start</li>
          <li>No card required</li>
          <li>Set up in minutes</li>
        </ul>
      )}
    </>
  );
}
