// Plain (server- and client-safe) link data shared by the nav and footer.

export const SECTION_LINKS = [
  { id: "features", label: "Features" },
  { id: "day", label: "A day with us" },
  { id: "how", label: "How it works" },
  { id: "pricing", label: "Pricing" },
  { id: "faq", label: "FAQ" },
] as const;

/** Homepage section links are in-page anchors; on every other public page
 *  they point back to the homepage section. */
export function sectionHref(id: string, onHome: boolean) {
  return onHome ? `#${id}` : `/#${id}`;
}

// Production status page (MYKHAYA_STATUS_URL in .env.production.example).
export const STATUS_URL = "https://status.mykhaya.app/";

// App store listings. Leave empty until the listing is live: an empty URL shows
// the badge as plain (non-link) artwork, and Google Play also shows a
// "Coming soon" pill. Set the URL to turn the badge into a link.
export const APP_STORE_URL = "";
export const GOOGLE_PLAY_URL = "";
