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
  PackageOpen,
  LifeBuoy,
  ListChecks,
  Mail,
  MessageSquare,
  Scale,
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
import { clearPlatformSession, usePlatformSession } from "./platform-session";

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
    label: "Support",
    items: [
      { label: "Tickets", href: "/support/tickets", icon: LifeBuoy },
      { label: "Settings", href: "/support/settings", icon: Settings },
    ],
  },
  {
    label: "Legal",
    items: [{ label: "Legal & Compliance", href: "/legal", icon: Scale }],
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
      { label: "Home Migration", href: "/home-migration", icon: PackageOpen },
    ],
  },
  {
    label: "Platform",
    items: [
      { label: "Settings", href: "/settings", icon: Settings },
      { label: "Founding Beta", href: "/founding-beta", icon: FlaskConical },
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
  const session = usePlatformSession();
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
  // Redirect only from a *resolved* unauthenticated state; the content gate
  // below already refuses to render anything privileged in the meantime.
  const redirectTo = session.state === "unauthenticated" ? session.destination : null;
  useEffect(() => {
    if (redirectTo) router.replace(redirectTo);
  }, [redirectTo, router]);
  async function signOut() {
    await platformApi.post("/auth/logout", {});
    clearPlatformSession();
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
  // Nothing privileged (sidebar, operator identity, page content) renders until
  // the administrator session is positively resolved as authenticated. A
  // signed-out visitor only ever sees this neutral, content-free surface.
  if (session.state !== "authenticated") {
    return (
      <div className="pcc-root pcc-session-gate" role="status" aria-busy={session.state === "resolving"}>
        {session.state === "unavailable" ? (
          <div className="pcc-session-gate-message">
            <p>The Control Centre could not verify your session.</p>
            <button className="secondary" onClick={session.retry}>Try again</button>
          </div>
        ) : (
          <span className="cc-visually-hidden">Checking your session…</span>
        )}
      </div>
    );
  }
  const { actor } = session;
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
        <nav className="tailadmin-sidebar-scroll" aria-label="Control Centre navigation" tabIndex={0}>
          <section className="tailadmin-nav-section"><ul className="tailadmin-nav-list"><li><NavLink item={overviewItem} active={isNavItemActive(path, overviewItem.href)} /></li>{navGroups.slice(0, 4).map(renderGroup)}</ul></section>
          <section className="tailadmin-nav-section"><ul className="tailadmin-nav-list">{navGroups.slice(4).map(renderGroup)}</ul></section>
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
            <Link href={`/administrators/${actor.id}`} className="operator-identity">
              <span className="operator-avatar" aria-hidden>{actor.display_name.slice(0, 1).toUpperCase()}</span>
              <span><strong>{actor.display_name}</strong><small>{actor.role.replaceAll("_", " ")}</small></span>
              <MoreHorizontal size={18} aria-hidden />
            </Link>
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
