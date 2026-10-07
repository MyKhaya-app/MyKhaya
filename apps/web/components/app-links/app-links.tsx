"use client";

import "./app-links.css";
import { useEffect, useState } from "react";
import { Smartphone } from "lucide-react";
import { isNativeShell } from "@/components/native-runtime";
import { androidLinkKind, iosLinkKind } from "./app-link-kind";

// The one place the site turns the PCC "iPhone app link" / "Android app link"
// settings into buttons. Shown on the homepage hero, the Founding Beta page
// and the in-app Founding Beta confirmation card; styles in ./app-links.css.

const IMG = "/images/marketing";

/**
 * - "beta": the Founding Beta page. TestFlight and Play-testing/other links
 *   get custom buttons; store listings get the official badges; an empty
 *   iPhone link is hidden and an empty Android link is a muted placeholder.
 * - "homepage": only real store listings are linked. Otherwise the official
 *   badges stay as plain artwork, and Google Play carries a "Coming soon" pill.
 */
export type AppLinksSurface = "beta" | "homepage";

export function useNativeShell(): boolean {
  // Read after mount so the server render and first client render match.
  const [native, setNative] = useState(false);
  useEffect(() => {
    setNative(isNativeShell());
  }, []);
  return native;
}

function StoreBadge({
  store,
  href,
  pending = false,
}: {
  store: "app-store" | "google-play";
  href?: string;
  pending?: boolean;
}) {
  const appStore = store === "app-store";
  const alt = appStore
    ? "Download on the App Store"
    : pending
      ? "Get it on Google Play, coming soon"
      : "Get it on Google Play";
  const artwork = (
    <img
      src={`${IMG}/${appStore ? "app-store-badge" : "google-play-badge"}.png`}
      alt={alt}
      width={appStore ? 120 : 135}
      height={40}
      decoding="async"
    />
  );
  if (href) {
    return (
      <a className="mk-applink-badge" href={href} target="_blank" rel="noopener noreferrer">
        {artwork}
      </a>
    );
  }
  return (
    <span className="mk-applink-badge">
      {artwork}
      {pending && (
        <span className="mk-applink-pill" aria-hidden="true">
          Coming soon
        </span>
      )}
    </span>
  );
}

function CustomButton({ href, label, sub }: { href: string; label: string; sub?: string }) {
  return (
    <a className="mk-applink-btn" href={href} target="_blank" rel="noopener noreferrer">
      <Smartphone size={20} strokeWidth={1.9} aria-hidden="true" />
      <span className="mk-applink-btn-text">
        <span className="mk-applink-btn-label">{label}</span>
        {sub && <span className="mk-applink-btn-sub">{sub}</span>}
      </span>
    </a>
  );
}

/** The iPhone half. Returns null when nothing should be shown. */
export function IosAppLink({ url, surface }: { url: string | null | undefined; surface: AppLinksSurface }) {
  const kind = iosLinkKind(url);
  if (kind === "app-store") return <StoreBadge store="app-store" href={url!.trim()} />;
  if (surface === "homepage") return <StoreBadge store="app-store" />;
  if (kind === "testflight") {
    return (
      <span className="mk-applink-stack">
        <CustomButton href={url!.trim()} label="Install on iPhone" sub="via TestFlight" />
        <span className="mk-applink-note">You&apos;ll need Apple&apos;s free TestFlight app.</span>
      </span>
    );
  }
  return null;
}

/** The Android half. Returns null when nothing should be shown. */
export function AndroidAppLink({ url, surface }: { url: string | null | undefined; surface: AppLinksSurface }) {
  const kind = androidLinkKind(url);
  if (kind === "play-listing") return <StoreBadge store="google-play" href={url!.trim()} />;
  if (surface === "homepage") return <StoreBadge store="google-play" pending />;
  if (kind === "play-testing" || kind === "other") {
    return <CustomButton href={url!.trim()} label="Get the Android beta" />;
  }
  return (
    <span className="mk-applink-placeholder" aria-disabled="true">
      <Smartphone size={18} strokeWidth={1.8} aria-hidden="true" />
      Android coming soon
    </span>
  );
}

/** Whether a surface would show anything for these links. The Founding Beta
 *  block is hidden when both links are empty; the homepage always shows its
 *  badges. */
export function hasAnyAppLink(ios: string | null | undefined, android: string | null | undefined) {
  return iosLinkKind(ios) !== "none" || androidLinkKind(android) !== "none";
}

/** Both halves side by side (wrapping on small phones). Hidden inside the
 *  native iOS/Android app. */
export function AppLinks({
  ios,
  android,
  surface,
  label = "Get the app",
}: {
  ios: string | null | undefined;
  android: string | null | undefined;
  surface: AppLinksSurface;
  label?: string;
}) {
  const native = useNativeShell();
  if (native) return null;
  return (
    <div className={`mk-applinks mk-applinks-${surface}`} role="group" aria-label={label}>
      <IosAppLink url={ios} surface={surface} />
      <AndroidAppLink url={android} surface={surface} />
    </div>
  );
}
