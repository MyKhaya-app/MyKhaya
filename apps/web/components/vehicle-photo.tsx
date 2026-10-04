"use client";

import { useEffect, useState } from "react";
import { Car } from "lucide-react";
import { fetchNativeImage } from "@/components/native-auth";
import { isNativeShell } from "@/components/native-runtime";

export function vehiclePhotoPath(homeId: string, vehicleId: string, version: string): string {
  return `/homes/${encodeURIComponent(homeId)}/vehicles/${encodeURIComponent(vehicleId)}/photo?v=${encodeURIComponent(version)}`;
}

export function VehiclePhoto({ homeId, vehicleId, version, label, className }: { homeId: string; vehicleId: string; version: string | null; label: string; className?: string }) {
  const [nativeUrl, setNativeUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setFailed(false);
    setNativeUrl(null);
    if (!isNativeShell() || !version) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    void fetchNativeImage(vehiclePhotoPath(homeId, vehicleId, version)).then((blob) => {
      if (cancelled) return;
      objectUrl = URL.createObjectURL(blob);
      setNativeUrl(objectUrl);
    }).catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [homeId, vehicleId, version]);
  if (!version || failed || (isNativeShell() && !nativeUrl)) return <Car className={className} size={42} aria-hidden="true" />;
  return <img className={className} src={isNativeShell() ? nativeUrl ?? undefined : `/api/v1${vehiclePhotoPath(homeId, vehicleId, version)}`} alt={label} onError={() => setFailed(true)} />;
}
