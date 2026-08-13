"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { platformApi } from "@mykhaya/api-client";
import { resolveLoginDestination } from "./platform-mfa-logic";
import type { PlatformActor } from "./platform-types";

const navigation = [
  ["Overview", "/"], ["Users", "/users"], ["Homes", "/homes"],
  ["Health", "/health"], ["Jobs", "/jobs"], ["Email", "/mail"], ["Push", "/push"],
  ["Templates", "/notification-templates"], ["Communications", "/communications"],
  ["Timeline", "/timeline"], ["Diagnostics", "/diagnostics"],
  ["Settings", "/settings"], ["Modules & Features", "/modules"],
  ["Administrators", "/administrators"], ["Security", "/security"], ["Audit", "/audit"],
  ["Public Status", "/incidents"],
] as const;

export function PlatformShell({ children }: { children: React.ReactNode }) {
  const path = usePathname().replace(/^\/control-centre/, "") || "/";
  const router = useRouter();
  const [actor, setActor] = useState<PlatformActor | null>(null);
  useEffect(() => {
    platformApi
      .get<PlatformActor>("/auth/me")
      .then((value) => {
        // A session still mid-MFA-flow must never render ordinary Control
        // Centre content — the backend already refuses these routes for such
        // a session, but bouncing to the flow it actually needs (enrollment,
        // or the login page's inline verify step) is better than a raw 403.
        const destination = resolveLoginDestination(value.session_status);
        if (destination === "setup-mfa") {
          router.replace("/setup-mfa");
          return;
        }
        if (destination === "verify") {
          router.replace("/login");
          return;
        }
        setActor(value);
      })
      .catch(() => router.replace("/login"));
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
          {actor ? (
            <Link href={`/administrators/${actor.id}`} className="operator-identity">
              <strong>{actor.display_name}</strong>
              <small>{actor.role.replaceAll("_", " ")}</small>
            </Link>
          ) : (
            <strong>Loading operator…</strong>
          )}
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
