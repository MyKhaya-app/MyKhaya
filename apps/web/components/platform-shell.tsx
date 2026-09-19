"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ComponentType } from "react";
import {
  Archive,
  BarChart3,
  Bell,
  CalendarDays,
  ChevronDown,
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
  Menu,
  MoreHorizontal,
  Search,
  X,
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
      { label: "Cleanup", href: "/cleanup", icon: Archive },
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
      { label: "Usage", href: "/usage", icon: BarChart3 },
      { label: "Diagnostics", href: "/diagnostics", icon: Stethoscope },
      { label: "Status & Incidents", href: "/incidents", icon: Siren },
    ],
  },
  {
    label: "Platform",
    items: [
      { label: "Settings", href: "/settings", icon: Settings },
      { label: "Calendar & Dates", href: "/settings/calendar-dates", icon: CalendarDays },
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

function NavLink({ item, active, nested = false }: { item: NavItem; active: boolean; nested?: boolean }) {
  const Icon = item.icon;
  return (
    <Link href={item.href} className={`menu-item ${active ? "menu-item-active" : "menu-item-inactive"} ${nested ? "menu-dropdown-item" : ""}`}>
      <Icon size={nested ? 14 : 20} strokeWidth={nested ? 2 : 1.8} aria-hidden />
      <span>{item.label}</span>
    </Link>
  );
}

export function PlatformShell({ children }: { children: React.ReactNode }) {
  const path = usePathname().replace(/^\/control-centre/, "") || "/";
  const router = useRouter();
  const [actor, setActor] = useState<PlatformActor | null>(null);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(navGroups.map((group) => [group.label, true])),
  );
  const [navStateHydrated, setNavStateHydrated] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem("mykhaya.pcc.nav-groups");
      if (stored) {
        const parsed = JSON.parse(stored) as Record<string, unknown>;
        setExpandedGroups((current) =>
          Object.fromEntries(
            navGroups.map((group) => [group.label, parsed[group.label] !== false && current[group.label] !== false]),
          ),
        );
      }
    } catch {
      // A blocked or malformed local preference should never affect navigation.
    } finally {
      setNavStateHydrated(true);
    }
  }, []);

  useEffect(() => {
    const activeGroup = navGroups.find((group) => group.items.some((item) => isNavItemActive(path, item.href)));
    if (activeGroup) {
      setExpandedGroups((current) => ({ ...current, [activeGroup.label]: true }));
    }
  }, [path]);

  useEffect(() => {
    setMobileOpen(false);
  }, [path]);

  useEffect(() => {
    if (navStateHydrated) {
      try {
        window.localStorage.setItem("mykhaya.pcc.nav-groups", JSON.stringify(expandedGroups));
      } catch {
        // Persistence is optional; navigation remains usable if storage is blocked.
      }
    }
  }, [expandedGroups, navStateHydrated]);
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
  function renderGroup(group: NavGroup) {
    const groupId = `pcc-nav-group-${group.label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
    const expanded = expandedGroups[group.label] !== false;
    const active = group.items.some((item) => isNavItemActive(path, item.href));
    return (
      <li key={group.label} className="tailadmin-nav-group">
        <button type="button" className={`menu-item menu-item-group ${active || expanded ? "menu-item-active" : "menu-item-inactive"}`} aria-expanded={expanded} aria-controls={groupId} onClick={() => setExpandedGroups((current) => ({ ...current, [group.label]: !expanded }))}>
          <span className="menu-item-text">{group.label}</span>
          <ChevronDown size={20} strokeWidth={1.8} aria-hidden className={expanded ? "expanded" : ""} />
        </button>
        <div id={groupId} className="menu-dropdown-wrap" hidden={!expanded}>
          <ul className="menu-dropdown-list">{group.items.map((item) => <li key={item.href}><NavLink item={item} nested active={isNavItemActive(path, item.href)} /></li>)}</ul>
        </div>
      </li>
    );
  }
  return (
    <div className={`pcc-root platform-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""} ${mobileOpen ? "mobile-sidebar-open" : ""}`}>
      <aside className="tailadmin-sidebar" onMouseEnter={() => sidebarCollapsed && setSidebarCollapsed(false)}>
        <div className="platform-brand tailadmin-brand">
          <Link href="/" aria-label="MyKhaya Overview">
            <span className="platform-brand-mark" aria-hidden="true">MK</span>
            <span className="platform-brand-copy"><strong>MyKhaya</strong><small>Platform Control Centre</small></span>
          </Link>
        </div>
        <p className="privileged-indicator">Privileged system</p>
        <nav className="tailadmin-sidebar-scroll" aria-label="Control Centre navigation">
          <section className="tailadmin-nav-section"><h2>Menu</h2><ul className="tailadmin-nav-list"><li><NavLink item={overviewItem} active={isNavItemActive(path, overviewItem.href)} /></li>{navGroups.slice(0, 4).map(renderGroup)}</ul></section>
          <section className="tailadmin-nav-section"><h2>Others</h2><ul className="tailadmin-nav-list">{navGroups.slice(4).map(renderGroup)}</ul></section>
        </nav>
      </aside>
      {mobileOpen && <button className="tailadmin-sidebar-backdrop" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}
      <div className="platform-main">
        <header className="platform-topbar">
          <div className="tailadmin-header-left">
            <button className="tailadmin-sidebar-toggle" type="button" aria-label="Toggle sidebar" onClick={() => window.innerWidth < 1024 ? setMobileOpen((value) => !value) : setSidebarCollapsed((value) => !value)}>
              {mobileOpen ? <X size={20} aria-hidden /> : <Menu size={20} aria-hidden />}
            </button>
            <div className="tailadmin-search"><Search size={18} aria-hidden /><input aria-label="Search Control Centre" placeholder="Search or type command..." /><kbd>⌘ K</kbd></div>
          </div>
          <div className="platform-topbar-account">
            {actor ? (
              <Link href={`/administrators/${actor.id}`} className="operator-identity">
                <span className="operator-avatar" aria-hidden>{actor.display_name.slice(0, 1).toUpperCase()}</span>
                <span><strong>{actor.display_name}</strong><small>{actor.role.replaceAll("_", " ")}</small></span>
                <MoreHorizontal size={18} aria-hidden />
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
