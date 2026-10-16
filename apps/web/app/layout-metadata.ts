import type { Metadata } from "next";

export function metadataForSurface(platformSurface: boolean): Metadata {
  const metadata: Metadata = {
    title: { default: "MyKhaya", template: "%s · MyKhaya" },
    description: "Your family's digital home",
  };
  if (!platformSurface) {
    metadata.manifest = "/manifest.webmanifest";
    metadata.appleWebApp = { title: "MyKhaya", statusBarStyle: "default" };
    metadata.icons = { apple: "/images/mykhaya-apple-icon.png" };
  }
  return metadata;
}
