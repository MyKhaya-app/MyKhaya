"use client";

import { useEffect, useState } from "react";
import { fetchNativeImage } from "./native-auth";
import { isNativeShell } from "./native-runtime";

/** Authenticated media image: browser uses the cookie-authenticated URL;
 * native shells fetch the same path through the bearer-auth client. */
export function ProtectedImage({ path, alt, className }: { path: string; alt: string; className?: string }) {
  const [src, setSrc] = useState<string | null>(isNativeShell() ? null : path);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!isNativeShell()) { setSrc(path); return; }
    let cancelled = false;
    let objectUrl: string | null = null;
    setSrc(null);
    setFailed(false);
    void fetchNativeImage(path).then((blob) => {
      if (cancelled) return;
      objectUrl = URL.createObjectURL(blob);
      setSrc(objectUrl);
    }).catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [path]);
  if (failed || !src) return null;
  return <img className={className} src={src} alt={alt} onError={() => setFailed(true)} />;
}
