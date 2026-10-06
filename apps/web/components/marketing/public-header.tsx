import Link from "next/link";
import { Logo } from "@/components/logo";
import type { PublicSignupState } from "@mykhaya/api-client";
import { signupCtaLabel, signupDestination } from "@/components/public-signup";

/** The public site's header — Logo, in-page section links, and exactly two
 *  actions. The section links are anchors within this same page (see
 *  docs/design/visual-identity.md's "one question per screen" — a marketing
 *  page's one question is "should I sign up"), not a separate site to
 *  navigate around. */
export function PublicHeader({
  signupState = null,
  compactOnMobile = false,
}: {
  signupState?: PublicSignupState | null;
  /** Small screens show only the logo and an outlined Sign in button (for
   *  pages whose own body carries the primary action). Desktop unchanged. */
  compactOnMobile?: boolean;
}) {
  return (
    <header className={`mk-header${compactOnMobile ? " mk-header-compact-mobile" : ""}`}>
      <nav aria-label="Primary">
        <Link href="/" className="mk-header-logo">
          <Logo />
        </Link>
        <div className="mk-header-links">
          <a href="#features">Features</a>
          <a href="#pricing">{signupState?.signup_mode === "beta_only" ? "Beta" : "Pricing"}</a>
        </div>
        <div className="mk-header-actions">
          <Link className="button secondary" href="/login">
            Sign in
          </Link>
          <Link className="button" href={signupDestination(signupState)}>
            {signupCtaLabel(signupState)}
          </Link>
        </div>
      </nav>
    </header>
  );
}
