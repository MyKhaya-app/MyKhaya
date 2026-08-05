"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { platformApi } from "@mykhaya/api-client";

const navigation = [
  ["Overview", "/"], ["Users", "/users"], ["Homes", "/homes"],
  ["Health", "/health"], ["Jobs", "/jobs"], ["Email", "/mail"], ["Push", "/push"],
  ["Settings", "/settings"], ["Modules & Features", "/modules"],
  ["Security", "/security"], ["Audit", "/audit"],
  ["Administrators", "/administrators"], ["Public Status", "/incidents"],
] as const;

type Actor = { display_name: string; email: string; role: string };

export function PlatformShell({ children }: { children: React.ReactNode }) {
  const path = usePathname().replace(/^\/control-centre/, "") || "/";
  const router = useRouter();
  const [actor, setActor] = useState<Actor | null>(null);
  useEffect(() => {
    platformApi.get<Actor>("/auth/me").then(setActor).catch(() => router.replace("/login"));
  }, [router]);
  async function signOut() {
    await platformApi.post("/auth/logout", {});
    router.replace("/login");
  }
  return (
    <div className="platform-shell">
      <aside>
        <div className="platform-brand">
          <span aria-hidden="true">MK</span>
          <div><strong>MyKhaya</strong><small>Platform Control Centre</small></div>
        </div>
        <p className="privileged-indicator">Privileged system</p>
        <nav aria-label="Control Centre navigation">
          {navigation.map(([label, href]) => (
            <Link key={href} className={path === href ? "active" : ""} href={href}>{label}</Link>
          ))}
        </nav>
        <div className="operator-card">
          <strong>{actor?.display_name ?? "Loading operator…"}</strong>
          <small>{actor?.role?.replaceAll("_", " ")}</small>
          <button onClick={signOut}>Sign out of Control Centre</button>
        </div>
      </aside>
      <div className="platform-main">
        <header><strong>MyKhaya Platform Control Centre</strong></header>
        {children}
      </div>
    </div>
  );
}
