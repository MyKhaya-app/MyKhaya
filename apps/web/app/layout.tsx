import "@mykhaya/design-tokens/css";
import "./styles.css";
import type { Metadata, Viewport } from "next";
import { ServiceWorkerRegister } from "../components/service-worker-register";
import { InstallPrompt } from "../components/install-prompt";
import { AuthProvider } from "../components/auth-provider";
export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: { default: "MyKhaya", template: "%s · MyKhaya" },
  description: "Your family's digital home",
  appleWebApp: { title: "MyKhaya", statusBarStyle: "default" },
};
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
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
        <ServiceWorkerRegister />
        <InstallPrompt />
      </body>
    </html>
  );
}
