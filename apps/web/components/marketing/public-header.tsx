import Link from "next/link";
import { Logo } from "@/components/logo";

/** The public site's header — Logo plus exactly two actions, on purpose.
 *  No nav link list: the whole public site is one page (see
 *  docs/design/visual-identity.md's "one question per screen" — a
 *  marketing page's one question is "should I sign up"), so there is
 *  nothing else to navigate to. */
export function PublicHeader() {
  return (
    <header className="mk-header">
      <nav aria-label="Primary">
        <Link href="/" className="mk-header-logo">
          <Logo />
        </Link>
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
