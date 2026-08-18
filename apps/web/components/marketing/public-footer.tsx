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
        <Link href="/service-status">Status</Link>
      </nav>
      <p className="mk-footer-copyright">
        © {year} MyKhaya. All rights reserved.
      </p>
    </footer>
  );
}
