import "@mykhaya/design-tokens/css";
import "./styles.css";
import type { Metadata, Viewport } from "next";
import { ServiceWorkerRegister } from "../components/service-worker-register";
import { NativeBackButton } from "../components/native-back-button";
import { AuthProvider } from "../components/auth-provider";
import { PersistentAppShell } from "../components/app-shell";
import { isPlatformControlCentreHost } from "../components/application-host";
import { headers } from "next/headers";
export const dynamic = "force-dynamic";
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

export async function generateMetadata(): Promise<Metadata> {
  const host = (await headers()).get("host") ?? "";
  return metadataForSurface(isPlatformControlCentreHost(host));
}
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#7D8F7A",
  // Lets the page extend under the iOS status bar/Dynamic Island and home
  // indicator instead of Safari/WKWebView letterboxing around them, so
  // env(safe-area-inset-*) actually resolves to the real inset instead of
  // 0 — required for both the native Capacitor shell and an iOS PWA added
  // to the home screen. See app/styles.css's :root --safe-top/--safe-bottom/
  // --safe-left/--safe-right — the one shared safe-area strategy every
  // top-level page container (public marketing header, auth pages,
  // AppShell's own header/bottom-nav, sheets) reads from, unconditionally
  // and without any JS-toggled class — env() alone already resolves to 0 on
  // a browser/PWA tab with no notch, so nothing here needs native-shell
  // detection just to apply safe-area padding.
  viewportFit: "cover",
};
export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const host = (await headers()).get("host") ?? "";
  const platformSurface = isPlatformControlCentreHost(host);
  const application = platformSurface ? children : (
    <AuthProvider>
      <PersistentAppShell>{children}</PersistentAppShell>
    </AuthProvider>
  );
  return (
    <html lang="en">
      <body>
        {application}
        {!platformSurface && <ServiceWorkerRegister />}
        <NativeBackButton />
      </body>
    </html>
  );
}
