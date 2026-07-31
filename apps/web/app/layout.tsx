import "@mykhaya/design-tokens/css";
import "./styles.css";
import type { Metadata } from "next";
export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: { default: "MyKhaya", template: "%s · MyKhaya" },
  description: "Your family's digital home",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
