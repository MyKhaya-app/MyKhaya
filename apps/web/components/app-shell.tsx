"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { Home, HouseholdModule, User } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { Logo } from "./logo";
import { useActiveHome } from "./use-active-home";

const icons: Record<string, string> = {
  dashboard: "⌂",
  calendar: "▣",
  household_members: "♙",
  security: "◈",
};

export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [modules, setModules] = useState<HouseholdModule[]>([]);
  const { homes, activeHome, activeHomeId, setActiveHomeId, loading } =
    useActiveHome();

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => router.replace("/login"));
  }, [router]);

  useEffect(() => {
    if (!loading && !homes.length && path !== "/onboarding")
      router.replace("/onboarding");
  }, [homes, loading, path, router]);

  useEffect(() => {
    if (!activeHomeId) {
      setModules([]);
      return;
    }
    api
      .navigationModules(activeHomeId)
      .then(setModules)
      .catch(() => setModules([]));
  }, [activeHomeId]);

  const navigation = useMemo(
    () => modules.filter((module) => module.route),
    [modules],
  );
  const mobileNavigation = navigation.filter((module) =>
    ["dashboard", "calendar", "household_members", "notifications"].includes(
      module.id,
    ),
  );
  const canAccessControlCentre = activeHome?.relationship === "home_admin";

  async function logout() {
    await api.post("/auth/logout", {});
    router.push("/login");
  }

  return (
    <div className="app-shell">
      <aside>
        <Logo />
        <nav aria-label="Main navigation">
          {navigation.map((module) => (
            <Link
              key={module.id}
              href={module.route!}
              className={
                path === module.route || path.startsWith(`${module.route}/`)
                  ? "active"
                  : ""
              }
            >
              <span aria-hidden="true">{icons[module.id] ?? "•"}</span>
              {module.name}
            </Link>
          ))}
          <Link
            href="/settings"
            className={path.startsWith("/settings") ? "active" : ""}
          >
            <span aria-hidden="true">⚙</span>
            Settings
          </Link>
          {canAccessControlCentre && (
            <Link
              href="/khaya-control-centre"
              className={
                path.startsWith("/khaya-control-centre") ? "active" : ""
              }
            >
              <span aria-hidden="true">◇</span>
              Khaya Control Centre
            </Link>
          )}
        </nav>
        <div className="home-switch">
          <div className="avatars" aria-hidden="true">
            <i>{user?.display_name?.[0] ?? "?"}</i>
          </div>
          <strong>{activeHome?.name ?? "Your Home"}</strong>
          {homes.length > 1 && (
            <label className="home-select">
              Active Home
              <select
                value={activeHomeId ?? ""}
                onChange={(event) => setActiveHomeId(event.target.value)}
              >
                {homes.map((home: Home) => (
                  <option key={home.id} value={home.id}>
                    {home.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button className="link-button" onClick={logout} type="button">
            Sign out
          </button>
        </div>
      </aside>
      <div className="app-main">
        <header>
          <Link className="mobile-logo" aria-label="Go to Home" href="/home">
            <Logo compact />
          </Link>
          <span className="mobile-home-name">
            {activeHome?.name ?? "MyKhaya"}
          </span>
          <span className="hello">{user?.display_name ?? "Welcome"}</span>
        </header>
        {children}
        <nav className="mobile-nav" aria-label="Mobile navigation">
          {mobileNavigation
            .slice(0, canAccessControlCentre ? 3 : 4)
            .map((module) => (
              <Link
                key={module.id}
                href={module.route!}
                className={path === module.route ? "active" : ""}
              >
                <span aria-hidden="true">{icons[module.id] ?? "•"}</span>
                {module.name === "Household members"
                  ? "Household"
                  : module.name}
              </Link>
            ))}
          <Link
            href="/settings"
            className={path.startsWith("/settings") ? "active" : ""}
          >
            <span aria-hidden="true">•••</span>
            More
          </Link>
          {canAccessControlCentre && (
            <Link
              href="/khaya-control-centre"
              className={
                path.startsWith("/khaya-control-centre") ? "active" : ""
              }
            >
              <span aria-hidden="true">Control</span>
              Control
            </Link>
          )}
        </nav>
      </div>
    </div>
  );
}
