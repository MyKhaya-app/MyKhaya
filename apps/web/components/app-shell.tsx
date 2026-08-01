"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { FeatureKey, Home, User } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { Logo } from "./logo";
import { useActiveHome } from "./use-active-home";
const nav: readonly [string, string, string, FeatureKey | null][] = [
  ["⌂", "Home", "/home", null],
  ["▣", "Calendar", "/calendar", "calendar"],
  ["☑", "Tasks", "/tasks", "tasks"],
  ["🛒", "Shopping", "/shopping", "shopping"],
  ["♨", "Meals", "/meals", "meals"],
  ["◇", "Plans", "/plans", "plans"],
  ["♧", "Wish Lists", "/wish-lists", "wish_lists"],
  ["♙", "People", "/people", null],
  ["♢", "Notifications", "/notifications", "notifications"],
  ["⚙", "Settings", "/settings", null],
] as const;
export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname(),
    router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [features, setFeatures] = useState<Partial<Record<FeatureKey, boolean>>>({});
  const { homes, activeHome, activeHomeId, setActiveHomeId, loading } =
    useActiveHome();
  useEffect(() => {
    api
      .me()
      .then((u) => {
        setUser(u);
      })
      .catch(() => router.replace("/login"));
  }, [router]);
  useEffect(() => {
    if (!loading && !homes.length && path !== "/onboarding") {
      router.replace("/onboarding");
    }
  }, [homes, loading, path, router]);
  useEffect(() => {
    if (!activeHomeId) {
      setFeatures({});
      return;
    }
    api
      .featureMatrix(activeHomeId)
      .then((matrix) =>
        setFeatures(
          Object.fromEntries(matrix.features.map((item) => [item.feature, item.enabled])),
        ),
      )
      .catch(() => setFeatures({}));
  }, [activeHomeId]);
  const visibleNav = nav.filter(([, , , feature]) => !feature || features[feature] === true);
  async function logout() {
    await api.post("/auth/logout", {});
    router.push("/login");
  }
  return (
    <div className="app-shell">
      <aside>
        <Logo />
        <nav aria-label="Main navigation">
          {visibleNav.map(([icon, label, url]) => (
            <Link
              key={url}
              href={url}
              className={
                path === url || path.startsWith(`${url}/`) ? "active" : ""
              }
            >
              <span aria-hidden="true">{icon}</span>
              {label}
            </Link>
          ))}
        </nav>
        <div className="home-switch">
          <div className="avatars" aria-hidden="true">
            <i>{user?.display_name?.[0] ?? "?"}</i>
            <i>+</i>
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
          <button className="link-button" onClick={logout}>
            Sign out
          </button>
        </div>
      </aside>
      <div className="app-main">
        <header>
          <button className="mobile-logo" aria-label="Open menu">
            <Logo compact />
          </button>
          <div className="search" aria-label="Search is coming soon">
            Search your Home… <span>⌕</span>
          </div>
          <span className="hello">{user?.display_name ?? "Welcome"}</span>
        </header>
        {children}
        <nav className="mobile-nav" aria-label="Mobile navigation">
          {visibleNav.slice(0, 4).map(([icon, label, url]) => (
            <Link key={url} href={url} className={path === url ? "active" : ""}>
              <span>{icon}</span>
              {label}
            </Link>
          ))}
          <Link href="/settings">
            <span>•••</span>More
          </Link>
        </nav>
      </div>
    </div>
  );
}
