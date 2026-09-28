"use client";

import { useEffect, useState } from "react";
import { fetchNativeImage } from "./native-auth";
import { isNativeShell } from "./native-runtime";

export function apiRelativeMediaPath(path: string): string {
  if (path.startsWith("/api/v1/")) return path.slice("/api/v1".length);
  return path;
}

export function browserMediaPath(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  const relativePath = apiRelativeMediaPath(path);
  return `/api/v1${relativePath.startsWith("/") ? relativePath : `/${relativePath}`}`;
}

/** Authenticated media image: browser uses the cookie-authenticated URL;
 * native shells fetch the same path through the bearer-auth client. */
export function ProtectedImage({ path, alt, className }: { path: string; alt: string; className?: string }) {
  const [src, setSrc] = useState<string | null>(isNativeShell() ? null : browserMediaPath(path));
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!isNativeShell()) { setSrc(browserMediaPath(path)); return; }
    let cancelled = false;
    let objectUrl: string | null = null;
    setSrc(null);
    setFailed(false);
    void fetchNativeImage(apiRelativeMediaPath(path)).then((blob) => {
      if (cancelled) return;
      objectUrl = URL.createObjectURL(blob);
      setSrc(objectUrl);
    }).catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [path]);
  if (failed || !src) return null;
  return <img className={className} src={src} alt={alt} onError={() => setFailed(true)} />;
}
