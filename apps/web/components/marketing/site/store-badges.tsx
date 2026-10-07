"use client";

import { useEffect, useState } from "react";
import { isNativeShell } from "@/components/native-runtime";
import { APP_STORE_URL, GOOGLE_PLAY_URL } from "./site-links";

const IMG = "/images/marketing";

function Badge({
  href,
  src,
  width,
  alt,
  pending,
}: {
  href: string;
  src: string;
  width: number;
  alt: string;
  pending: boolean;
}) {
  const artwork = <img src={src} alt={alt} width={width} height={40} decoding="async" />;
  if (href) {
    return (
      <a className="mks-store-badge" href={href} target="_blank" rel="noopener noreferrer">
        {artwork}
      </a>
    );
  }
  return (
    <span className="mks-store-badge">
      {artwork}
      {pending && (
        <span className="mks-store-pill" aria-hidden="true">
          Coming soon
        </span>
      )}
    </span>
  );
}

/** Official App Store / Google Play badges under the hero. Each becomes a link
 *  once its listing URL is set (site-links.ts); until then Google Play carries
 *  a "Coming soon" pill. Not shown inside the native iOS/Android app (checked
 *  after mount, so server and first client render match). */
export function StoreBadges() {
  const [native, setNative] = useState(false);
  useEffect(() => {
    setNative(isNativeShell());
  }, []);
  if (native) return null;
  return (
    <div className="mks-store-badges" role="group" aria-label="Get the app">
      <Badge href={APP_STORE_URL} src={`${IMG}/app-store-badge.png`} width={120} alt="Download on the App Store" pending={false} />
      <Badge
        href={GOOGLE_PLAY_URL}
        src={`${IMG}/google-play-badge.png`}
        width={135}
        alt={GOOGLE_PLAY_URL ? "Get it on Google Play" : "Get it on Google Play, coming soon"}
        pending={!GOOGLE_PLAY_URL}
      />
    </div>
  );
}
