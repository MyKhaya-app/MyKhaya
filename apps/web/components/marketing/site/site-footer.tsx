import Link from "next/link";
import { SiteBrand } from "./site-brand";
import { sectionHref } from "./site-nav";

export const STATUS_URL = "https://status.dev.mykhaya.app/";

export function SiteFooter({ onHome }: { onHome: boolean }) {
  const year = new Date().getFullYear();
  return (
    <footer className="site-footer">
      <div className="wrap">
        <div className="foot">
          <div>
            <SiteBrand />
            <p className="tagline">Your family, organised: calmly, together.</p>
          </div>
          <div>
            <h4>Product</h4>
            <ul>
              <li><a href={sectionHref("features", onHome)}>Features</a></li>
              <li><a href={sectionHref("how", onHome)}>How it works</a></li>
              <li><a href={sectionHref("pricing", onHome)}>Pricing</a></li>
              <li><a href={sectionHref("faq", onHome)}>FAQ</a></li>
            </ul>
          </div>
          <div>
            <h4>Account</h4>
            <ul>
              <li><Link href="/login">Sign in</Link></li>
              <li><Link href="/register">Create an account</Link></li>
            </ul>
          </div>
          <div>
            <h4>Help</h4>
            <ul>
              <li><Link href="/support">Support</Link></li>
              <li><a href={STATUS_URL}>Service status</a></li>
            </ul>
          </div>
        </div>
        <div className="legal">
          <span>© {year} MyKhaya. All rights reserved.</span>
          <nav aria-label="Legal">
            <Link href="/legal/terms">Terms</Link>
            <Link href="/legal/privacy">Privacy</Link>
            <Link href="/legal/children">Children&apos;s Privacy</Link>
            <Link href="/legal/cookies">Cookies</Link>
          </nav>
        </div>
      </div>
    </footer>
  );
}
