"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { Home, User } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { Logo } from "./logo";
const nav = [
  ["⌂", "Home", "/home"],
  ["▣", "Calendar", "/calendar"],
  ["☑", "Tasks", "/tasks"],
  ["🛒", "Shopping", "/shopping"],
  ["♨", "Meals", "/meals"],
  ["◇", "Plans", "/plans"],
  ["♧", "Wish Lists", "/wish-lists"],
  ["♙", "People", "/people"],
  ["♢", "Notifications", "/notifications"],
  ["⚙", "Settings", "/settings"],
] as const;
export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname(),
    router = useRouter();
  const [user, setUser] = useState<User | null>(null),
    [homes, setHomes] = useState<Home[]>([]);
  useEffect(() => {
    Promise.all([api.me(), api.homes()])
      .then(([u, h]) => {
        setUser(u);
        setHomes(h);
        if (!h.length && path !== "/onboarding") router.replace("/onboarding");
      })
      .catch(() => router.replace("/login"));
  }, [path, router]);
  async function logout() {
    await api.post("/auth/logout", {});
    router.push("/login");
  }
  return (
    <div className="app-shell">
      <aside>
        <Logo />
        <nav aria-label="Main navigation">
          {nav.map(([icon, label, url]) => (
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
          <strong>{homes[0]?.name ?? "Your Home"}</strong>
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
          {nav.slice(0, 4).map(([icon, label, url]) => (
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
