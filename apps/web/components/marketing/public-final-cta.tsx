import Link from "next/link";
import type { PublicSignupState } from "@mykhaya/api-client";
import { signupCtaLabel, signupDestination } from "@/components/public-signup";

export function PublicFinalCta({ signupState = null }: { signupState?: PublicSignupState | null }) {
  return (
    <section className="mk-final-cta" aria-labelledby="final-cta-heading">
      <h2 id="final-cta-heading">Ready to bring your family together?</h2>
      <p>Free to start. No card required.</p>
      <Link className="button large mk-final-cta-button" href={signupDestination(signupState)}>
        {signupCtaLabel(signupState)}
      </Link>
    </section>
  );
}
