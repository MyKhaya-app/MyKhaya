import "@mykhaya/design-tokens/css";
import "./styles.css";
import type { Metadata, Viewport } from "next";
import { ServiceWorkerRegister } from "../components/service-worker-register";
import { InstallPrompt } from "../components/install-prompt";
export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: { default: "MyKhaya", template: "%s · MyKhaya" },
  description: "Your family's digital home",
  appleWebApp: { title: "MyKhaya", statusBarStyle: "default" },
};
export const viewport: Viewport = {
  themeColor: "#7D8F7A",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        {children}
        <ServiceWorkerRegister />
        <InstallPrompt />
      </body>
    </html>
  );
}
