"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { FeatureKey, Home, HomeFeature, User } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { Logo } from "./logo";

type NavItem = {
  icon: string;
  label: string;
  url: string;
  featureKey?: FeatureKey;
};

const nav: readonly NavItem[] = [
  { icon: "⌂", label: "Home", url: "/home" },
  { icon: "▣", label: "Calendar", url: "/calendar", featureKey: "calendar" },
  { icon: "☑", label: "Tasks", url: "/tasks", featureKey: "tasks" },
  { icon: "🛒", label: "Shopping", url: "/shopping", featureKey: "shopping" },
  { icon: "♨", label: "Meals", url: "/meals", featureKey: "meals" },
  { icon: "◇", label: "Plans", url: "/plans", featureKey: "plans" },
  {
    icon: "♧",
    label: "Wish Lists",
    url: "/wish-lists",
    featureKey: "wish_lists",
  },
  { icon: "♙", label: "People", url: "/people" },
  {
    icon: "♢",
    label: "Notifications",
    url: "/notifications",
    featureKey: "notifications",
  },
  { icon: "⚙", label: "Settings", url: "/settings" },
];

const routeFeatureMap: Record<string, FeatureKey> = {
  "/calendar": "calendar",
  "/tasks": "tasks",
  "/shopping": "shopping",
  "/meals": "meals",
  "/plans": "plans",
  "/wish-lists": "wish_lists",
  "/notifications": "notifications",
};

function routeFeature(path: string): FeatureKey | null {
  for (const [prefix, key] of Object.entries(routeFeatureMap)) {
    if (path === prefix || path.startsWith(`${prefix}/`)) return key;
  }
  return null;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname(),
    router = useRouter();
  const [user, setUser] = useState<User | null>(null),
    [homes, setHomes] = useState<Home[]>([]),
    [features, setFeatures] = useState<HomeFeature[]>([]),
    [featuresLoaded, setFeaturesLoaded] = useState(false);

  useEffect(() => {
    Promise.all([api.me(), api.homes()])
      .then(async ([u, h]) => {
        setUser(u);
        setHomes(h);
        const firstHome = h[0];
        if (!firstHome) {
          if (path !== "/onboarding") router.replace("/onboarding");
          return;
        }
        const envelope = await api.homeFeatures(firstHome.id);
        setFeatures(envelope.features);
        setFeaturesLoaded(true);
      })
      .catch(() => router.replace("/login"));
  }, [path, router]);

  const enabledFeatures = new Set(
    features.filter((item) => item.enabled).map((item) => item.key),
  );
  const visibleNav = nav.filter(
    (item) => !item.featureKey || enabledFeatures.has(item.featureKey),
  );

  useEffect(() => {
    if (!featuresLoaded) return;
    const requiredFeature = routeFeature(path);
    if (requiredFeature && !enabledFeatures.has(requiredFeature)) {
      router.replace("/home");
    }
  }, [enabledFeatures, featuresLoaded, path, router]);

  async function logout() {
    await api.post("/auth/logout", {});
    router.push("/login");
  }
  return (
    <div className="app-shell">
      <aside>
        <Logo />
        <nav aria-label="Main navigation">
          {visibleNav.map((item) => (
            <Link
              key={item.url}
              href={item.url}
              className={
                path === item.url || path.startsWith(`${item.url}/`) ? "active" : ""
              }
            >
              <span aria-hidden="true">{item.icon}</span>
              {item.label}
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
          {visibleNav.slice(0, 4).map((item) => (
            <Link
              key={item.url}
              href={item.url}
              className={path === item.url ? "active" : ""}
            >
              <span>{item.icon}</span>
              {item.label}
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
