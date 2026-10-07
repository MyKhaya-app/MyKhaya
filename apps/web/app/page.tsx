import type { Metadata } from "next";
import Welcome from "@/components/marketing/site/welcome";
import { MarketingHome } from "@/components/marketing/site/marketing-home";

const SITE_URL = "https://mykhaya.app/";
const TITLE = "MyKhaya: your family's digital home";
const DESCRIPTION =
  "MyKhaya is your family's digital home: shared calendars, meal plans, nudges and lists in one calm place. Free to start.";
// Absolute so link previews (Open Graph / Twitter) resolve it from any host.
const SHARE_IMAGE = {
  url: "https://mykhaya.app/images/marketing/mykhaya-share.png",
  width: 1200,
  height: 630,
  alt: "MyKhaya: Bring your family together. Three phones showing the Meal Plans, Home and Calendar screens.",
};

export const metadata: Metadata = {
  title: { absolute: TITLE },
  description: DESCRIPTION,
  alternates: { canonical: SITE_URL },
  openGraph: {
    type: "website",
    url: SITE_URL,
    siteName: "MyKhaya",
    locale: "en_GB",
    title: TITLE,
    description: DESCRIPTION,
    images: [SHARE_IMAGE],
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
    images: [{ url: SHARE_IMAGE.url, alt: SHARE_IMAGE.alt }],
  },
};

/** mykhaya.app — the public marketing homepage (and the native shell's
 *  startup route; see Welcome). */
export default function HomePage() {
  return (
    <Welcome>
      <MarketingHome />
    </Welcome>
  );
}
