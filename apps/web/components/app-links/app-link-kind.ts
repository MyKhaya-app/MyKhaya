// What kind of app link PCC holds, which decides how it is shown. Pure so it
// can be unit-tested and shared by every surface (homepage, Founding Beta).
// The API already validates both links (see founding_beta_schemas.py); this
// re-checks defensively and treats anything unexpected as "none".

export type IosLinkKind = "testflight" | "app-store" | "none";
export type AndroidLinkKind = "play-testing" | "play-listing" | "other" | "none";

function httpsUrl(value: string | null | undefined): URL | null {
  if (!value) return null;
  try {
    const url = new URL(value.trim());
    return url.protocol === "https:" && url.hostname && !url.username && !url.password ? url : null;
  } catch {
    return null;
  }
}

export function iosLinkKind(value: string | null | undefined): IosLinkKind {
  const url = httpsUrl(value);
  const host = url?.hostname.toLowerCase();
  if (host === "testflight.apple.com") return "testflight";
  if (host === "apps.apple.com") return "app-store";
  return "none";
}

export function androidLinkKind(value: string | null | undefined): AndroidLinkKind {
  const url = httpsUrl(value);
  if (!url) return "none";
  if (url.hostname.toLowerCase() === "play.google.com") {
    // Play testing opt-in pages live under /apps/testing/<package>.
    return url.pathname.startsWith("/apps/testing/") ? "play-testing" : "play-listing";
  }
  return "other";
}
