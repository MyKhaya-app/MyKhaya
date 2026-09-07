"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ComponentType } from "react";
import {
  Bell,
  Clock,
  CreditCard,
  FlaskConical,
  HeartPulse,
  LayoutDashboard,
  ListChecks,
  Mail,
  MessageSquare,
  ScrollText,
  Send,
  Settings,
  Shield,
  Siren,
  Stethoscope,
  ToggleLeft,
  UserCog,
  Users,
  House,
  Wallet,
  LogOut,
} from "lucide-react";
import { platformApi } from "@mykhaya/api-client";
import { resolveLoginDestination } from "./platform-mfa-logic";
import type { PlatformActor } from "./platform-types";

type NavIcon = ComponentType<{ size?: number; strokeWidth?: number; "aria-hidden"?: boolean }>;
type NavItem = { label: string; href: string; icon: NavIcon };
type NavGroup = { label: string; items: NavItem[] };

// The Overview link is rendered on its own, outside any group heading — a
// single top-level destination doesn't need a labelled group above it.
const overviewItem: NavItem = { label: "Overview", href: "/", icon: LayoutDashboard };

// Visual grouping only — approved by the task owner as a display grouping
// for the sidebar. Every href/label/destination below is unchanged from the
// original flat `navigation` list; nothing was added, removed, or renamed.
const navGroups: NavGroup[] = [
  {
    label: "People",
    items: [
      { label: "Users", href: "/users", icon: Users },
      { label: "Homes", href: "/homes", icon: House },
      { label: "Administrators", href: "/administrators", icon: UserCog },
      { label: "Demo & Test Homes", href: "/demo-test-homes", icon: FlaskConical },
    ],
  },
  {
    label: "Billing",
    items: [
      { label: "Subscriptions", href: "/subscriptions", icon: CreditCard },
      { label: "Payments", href: "/payments", icon: Wallet },
    ],
  },
  {
    label: "Communications",
    items: [
      { label: "Email", href: "/mail", icon: Mail },
      { label: "Push", href: "/push", icon: Bell },
      { label: "Notifications", href: "/notifications", icon: Send },
      { label: "Communications", href: "/communications", icon: MessageSquare },
    ],
  },
  {
    label: "Operations",
    items: [
      { label: "Health", href: "/health", icon: HeartPulse },
      { label: "Jobs", href: "/jobs", icon: ListChecks },
      { label: "Timeline", href: "/timeline", icon: Clock },
      { label: "Diagnostics", href: "/diagnostics", icon: Stethoscope },
      { label: "Status & Incidents", href: "/incidents", icon: Siren },
    ],
  },
  {
    label: "Platform",
    items: [
      { label: "Settings", href: "/settings", icon: Settings },
      { label: "Modules & Features", href: "/modules", icon: ToggleLeft },
      { label: "Security", href: "/security", icon: Shield },
      { label: "Audit", href: "/audit", icon: ScrollText },
    ],
  },
];

/**
 * Whether a nav item should render as active for the current path. The
 * Overview/root item (`href === "/"`) only matches the exact root — without
 * this special case it would match every route, since every path starts
 * with "/". Every other item matches its own path or any descendant route
 * below it (e.g. `/notifications/briefing` or `/subscriptions/abc123`
 * highlight `/notifications`/`/subscriptions`), using a trailing-slash
 * boundary so `/users` doesn't also match a hypothetical `/users2`.
 */
function isNavItemActive(path: string, href: string): boolean {
  if (href === "/") return path === "/";
  return path === href || path.startsWith(`${href}/`);
}

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link href={item.href} className={active ? "active" : ""}>
      <Icon size={16} strokeWidth={2} aria-hidden />
      <span>{item.label}</span>
    </Link>
  );
}

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
          <NavLink item={overviewItem} active={isNavItemActive(path, overviewItem.href)} />
          {navGroups.map((group) => (
            <div key={group.label} className="platform-nav-group">
              <p className="platform-nav-group-label">{group.label}</p>
              {group.items.map((item) => (
                <NavLink key={item.href} item={item} active={isNavItemActive(path, item.href)} />
              ))}
            </div>
          ))}
        </nav>
      </aside>
      <div className="platform-main">
        <header className="platform-topbar">
          <div className="platform-topbar-identity">
            <strong>MyKhaya Platform Control Centre</strong>
          </div>
          <div className="platform-topbar-account">
            {actor ? (
              <Link href={`/administrators/${actor.id}`} className="operator-identity">
                <strong>{actor.display_name}</strong>
                <small>{actor.role.replaceAll("_", " ")}</small>
              </Link>
            ) : (
              <strong>Loading operator…</strong>
            )}
            <button className="secondary" onClick={signOut}>
              <LogOut size={16} strokeWidth={2} aria-hidden />
              Sign out
            </button>
          </div>
        </header>
        {children}
      </div>
    </div>
  );
}
