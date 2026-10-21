import type { Metadata } from "next";
import Link from "next/link";
import { LifeBuoyIcon, LockIcon, MailIcon } from "@/components/marketing/site/icons";
import { MarketingChrome } from "@/components/marketing/site/marketing-chrome";

const SUPPORT_EMAIL = "support@mykhaya.app";

const PAGE_URL = "https://mykhaya.app/support";
const TITLE = "Support";
const DESCRIPTION =
  "Get help with MyKhaya. Use the Support Hub in the app, or email support@mykhaya.app if you can't sign in or access the app.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: PAGE_URL },
  openGraph: {
    type: "website",
    url: PAGE_URL,
    siteName: "MyKhaya",
    locale: "en_GB",
    title: `${TITLE} · MyKhaya`,
    description: DESCRIPTION,
  },
  twitter: { card: "summary", title: `${TITLE} · MyKhaya`, description: DESCRIPTION },
};

/** Public support page (mykhaya.app/support): the support URL given to the App
 *  Store and Google Play. Needs no sign-in (it is on the public-path lists in
 *  AuthProvider and AppShell). The in-app Support Hub (/help-support) stays
 *  behind sign-in: a signed-out visitor following "Open Support Hub" is sent
 *  to /login?next=/help-support by AuthProvider and returned there afterwards.
 *  Built from the homepage's scoped `.mks` styles, so it follows the system
 *  light/dark setting like the homepage. */
export default function SupportPage() {
  return (
    <MarketingChrome theme="system">
      <main className="mks-support">
        <section className="support-intro" aria-labelledby="support-heading">
          <div className="wrap">
            <div className="section-head center">
              <span className="eyebrow">Help &amp; Support</span>
              <h1 id="support-heading">We&rsquo;re here to help.</h1>
              <p className="lede">
                Need help with MyKhaya? Whether you&rsquo;re using the app or having trouble accessing your account,
                we&rsquo;re here to help.
              </p>
            </div>
          </div>
        </section>

        <section className="support-options" aria-label="Ways to get support">
          <div className="wrap">
            <div className="support-grid">
              <article className="support-card" aria-labelledby="support-in-app-heading">
                <span className="ic" style={{ background: "var(--coral-soft)" }}>
                  <LifeBuoyIcon size={24} />
                </span>
                <h2 id="support-in-app-heading">Already using MyKhaya?</h2>
                <p>
                  The best way to get support is through the MyKhaya Support Hub. You can report bugs, contact our
                  support team and share diagnostics to help us investigate any problems.
                </p>
                <Link className="btn btn-primary" href="/help-support">
                  Open Support Hub <span aria-hidden="true">→</span>
                </Link>
              </article>

              <article className="support-card" aria-labelledby="support-email-heading">
                <span className="ic" style={{ background: "var(--mustard-soft)" }}>
                  <MailIcon size={24} />
                </span>
                <h2 id="support-email-heading">Can&rsquo;t access MyKhaya?</h2>
                <p>
                  If you&rsquo;re unable to sign in, experiencing technical difficulties or need assistance without
                  access to the app, you can contact us directly by email.
                </p>
                <p className="support-email">
                  support@<wbr />mykhaya.app
                </p>
                <a className="btn btn-ghost" href={`mailto:${SUPPORT_EMAIL}`}>
                  Email Support
                </a>
              </article>
            </div>

            <p className="note support-privacy">
              <LockIcon size={16} />
              <span>Please don&rsquo;t include passwords, verification codes or sensitive personal information in support emails.</span>
            </p>
          </div>
        </section>
      </main>
    </MarketingChrome>
  );
}
