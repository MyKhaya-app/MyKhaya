import Link from "next/link";
import { Logo } from "@/components/logo";

export function PublicFooter() {
  const year = new Date().getFullYear();
  return (
    <footer className="mk-footer">
      <div className="mk-footer-brand">
        <Logo />
        <p>Your family, organised — calmly, together.</p>
      </div>
      <nav className="mk-footer-links" aria-label="Footer">
        <Link href="/login">Sign in</Link>
        <Link href="/register">Create an account</Link>
        <Link href="https://status.dev.mykhaya.app/">Status</Link>
        <Link href="/help-support">Support</Link>
      </nav>
      <nav className="mk-footer-links mk-footer-legal-links" aria-label="Legal">
        <Link href="/legal/terms">Terms</Link>
        <Link href="/legal/privacy">Privacy</Link>
        <Link href="/legal/children">Children&rsquo;s Privacy</Link>
        <Link href="/legal/cookies">Cookies</Link>
      </nav>
      <p className="mk-footer-copyright">
        © {year} MyKhaya. All rights reserved.
      </p>
    </footer>
  );
}
