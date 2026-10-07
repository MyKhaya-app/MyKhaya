import type { Metadata } from "next";
import Link from "next/link";
import { MarketingChrome } from "@/components/marketing/site/marketing-chrome";

export const metadata: Metadata = { title: "Support" };

/** Public support landing page. In-app Help & Support (/help-support) needs a
 *  signed-in account, so signed-out visitors from the marketing site land here
 *  instead of being bounced to sign in. */
export default function SupportPage() {
  return (
    <MarketingChrome>
      <main className="mk-page mks-coming-soon">
        <section aria-labelledby="support-heading">
          <p className="eyebrow">Help &amp; Support</p>
          <h1 id="support-heading">Support</h1>
          <p>Coming soon.</p>
          <p>
            Already have an account? <Link href="/login?next=%2Fhelp-support">Sign in</Link> to reach Help &amp;
            Support inside MyKhaya.
          </p>
          <p>
            <Link href="/">Back to the homepage</Link>
          </p>
        </section>
      </main>
    </MarketingChrome>
  );
}
