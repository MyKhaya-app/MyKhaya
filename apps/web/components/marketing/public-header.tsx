import Link from "next/link";
import { Logo } from "@/components/logo";

/** The public site's header — Logo, in-page section links, and exactly two
 *  actions. The section links are anchors within this same page (see
 *  docs/design/visual-identity.md's "one question per screen" — a marketing
 *  page's one question is "should I sign up"), not a separate site to
 *  navigate around. */
export function PublicHeader() {
  return (
    <header className="mk-header">
      <nav aria-label="Primary">
        <Link href="/" className="mk-header-logo">
          <Logo />
        </Link>
        <div className="mk-header-links">
          <a href="#features">Features</a>
          <a href="#pricing">Pricing</a>
          <a href="#how-it-works">How it works</a>
        </div>
        <div className="mk-header-actions">
          <Link className="button secondary" href="/login">
            Sign in
          </Link>
          <Link className="button" href="/register">
            Get started free
          </Link>
        </div>
      </nav>
    </header>
  );
}
