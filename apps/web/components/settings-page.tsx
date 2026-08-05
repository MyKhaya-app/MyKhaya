"use client";

import Link from "next/link";
import { AppShell } from "./app-shell";
import { AppVersion } from "./app-version";
import { useActiveHome } from "./use-active-home";
const links = [
  ["Profile", "Your name and account details", "/settings/profile"],
  ["Security", "Password and signed-in devices", "/settings/security"],
  ["Home settings", "Name and membership controls", "/settings/home"],
] as const;
export function SettingsPage({
  title = "Settings",
  children,
}: {
  title?: string;
  children?: React.ReactNode;
}) {
  const { activeHome } = useActiveHome();
  const isHomeAdmin = activeHome?.relationship === "home_admin";
  return (
    <AppShell>
      <main className="standard-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow">A calm place for the details</p>
            <h1>{title}</h1>
          </div>
        </div>
        {children ?? (
          <div className="settings-list">
            {links.map(([name, detail, url]) => (
              <Link className="card" href={url} key={url}>
                <div>
                  <h2>{name}</h2>
                  <p>{detail}</p>
                </div>
                <span>›</span>
              </Link>
            ))}
            {isHomeAdmin && (
              <Link className="card" href="/khaya-control-centre">
                <div>
                  <h2>Khaya Control Centre</h2>
                  <p>Members, child permissions and household features</p>
                </div>
                <span>›</span>
              </Link>
            )}
          </div>
        )}
        <AppVersion />
      </main>
    </AppShell>
  );
}
