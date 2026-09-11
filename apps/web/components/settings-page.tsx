"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Baby,
  Bell,
  Calendar,
  CircleUserRound,
  CreditCard,
  ExternalLink,
  Gift,
  Home,
  HelpCircle,
  ListChecks,
  Lock,
  Puzzle,
  Repeat,
  Shield,
  Tag,
  UtensilsCrossed,
  Users,
  type LucideIcon,
} from "lucide-react";
import type { BillingStatus, FeatureMatrix, User } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { AppShellContent } from "./app-shell";
import { HeroFlower } from "./hero-flower";
import { useActiveHome } from "./use-active-home";

// Who may see a given More row. Mirrors the *page's own* access rule in
// every case — this only ever hides a link a visitor genuinely can't (or
// for household-admin items, structurally shouldn't need to) use; it is
// never the source of truth for authorisation, which the destination page
// (and the backend behind it) still enforces independently.
type MoreGate = "all" | "adult" | "homeAdmin";

type TileTone = "sage" | "cream" | "coral" | "blue" | "lavender" | "yellow";

interface MoreItem {
  name: string;
  detail: string;
  href: string;
  icon: LucideIcon;
  tone: TileTone;
  gate: MoreGate;
  // Optional module-awareness — same featureMatrix/billingStatus source of
  // truth the Home dashboard's quick actions already use (see
  // app/home/page.tsx). When set: the row is hidden entirely if the
  // platform/Home module state resolves it unavailable (never a dead link
  // for something genuinely switched off upstream, matching the quick
  // actions' own `{featureOn && (...)}` pattern) — never disabled-but-
  // visible, since nothing in this codebase currently uses that
  // treatment. When the module IS available but this Home's plan doesn't
  // include it, the row stays visible with the same locked treatment
  // (muted + a small Lock icon) quick actions already use, still a normal
  // link to the destination page's own upgrade experience. Used by every
  // optional Household-tools module (Nudges, Lists, Meal Plans, Wishlists);
  // everything else stays on the coarser `gate: "all"`/`"adult"`/`"homeAdmin"`
  // role gates, unaffected.
  featureKey?: string;
  entitlementKey?: keyof BillingStatus;
}

interface MoreGroup {
  label: string;
  items: MoreItem[];
}

const MORE_GROUPS: readonly MoreGroup[] = [
  {
    label: "You",
    items: [
      { name: "Profile", detail: "Your name and account details", href: "/settings/profile", icon: CircleUserRound, tone: "sage", gate: "all" },
      { name: "Security", detail: "Review account and session protection", href: "/settings/security", icon: Shield, tone: "blue", gate: "adult" },
      { name: "Notifications", detail: "Push, reminders and your daily briefing", href: "/settings/notifications", icon: Bell, tone: "cream", gate: "all" },
    ],
  },
  {
    label: "Household tools",
    items: [
      {
        name: "Nudges",
        detail: "Routines, reminders and things to do",
        href: "/settings/routines-reminders",
        icon: Repeat,
        tone: "sage",
        gate: "all",
        featureKey: "nudges",
        entitlementKey: "nudges_enabled",
      },
      {
        name: "Lists",
        detail: "Shopping, chores and shared household lists",
        href: "/lists",
        icon: ListChecks,
        tone: "cream",
        gate: "all",
        featureKey: "shopping",
        // Lists is entitled on both plans (Free's 2-list cap is enforced
        // inside the Lists experience, not here) — set only so the row
        // still hides correctly when the module itself is off; `locked()`
        // never engages since billingStatus.lists_enabled is always true.
        entitlementKey: "lists_enabled",
      },
      {
        name: "Meal Plans",
        detail: "Plan meals together and save family favourites",
        href: "/meal-plans",
        icon: UtensilsCrossed,
        tone: "coral",
        gate: "all",
        featureKey: "meals",
        entitlementKey: "meals_enabled",
      },
      {
        name: "Wishlists",
        detail: "Gift ideas for birthdays and Christmas, shared without spoiling the surprise",
        href: "/wish-lists",
        icon: Gift,
        tone: "blue",
        gate: "all",
        featureKey: "wish_lists",
        entitlementKey: "wishlists_enabled",
      },
    ],
  },
  {
    label: "Home & people",
    items: [
      { name: "Home settings", detail: "Name, details, region and ownership", href: "/settings/home", icon: Home, tone: "sage", gate: "adult" },
      { name: "Members and roles", detail: "Relationships, invitations and access", href: "/settings/members", icon: Users, tone: "cream", gate: "adult" },
      { name: "Child permissions", detail: "Guardians, age bands and privacy", href: "/khaya-control-centre/children", icon: Baby, tone: "coral", gate: "homeAdmin" },
    ],
  },
  {
    label: "Calendar",
    items: [
      { name: "Calendar tags", detail: "Colour and organise your events", href: "/settings/calendar-tags", icon: Tag, tone: "blue", gate: "all" },
      { name: "Home calendars", detail: "Manage shared calendars and permissions", href: "/calendar/calendars", icon: Calendar, tone: "lavender", gate: "all" },
    ],
  },
  {
    label: "Features",
    items: [
      { name: "Module management", detail: "Choose which MyKhaya features are available in this home", href: "/khaya-control-centre/feature-management", icon: Puzzle, tone: "sage", gate: "homeAdmin" },
    ],
  },
  {
    label: "Plan & billing",
    items: [
      { name: "Plan & Billing", detail: "Your Home's plan, and payment status if applicable", href: "/settings/billing", icon: CreditCard, tone: "yellow", gate: "adult" },
    ],
  },
  {
    label: "Support",
    items: [
      { name: "Help & Support", detail: "Knowledge base, support tickets and service status", href: "/help-support", icon: HelpCircle, tone: "yellow", gate: "all" },
      { name: "About MyKhaya", detail: "Version information and useful links", href: "/about", icon: ExternalLink, tone: "sage", gate: "all" },
    ],
  },
];

export function SettingsPage({
  title = "More",
  description,
  hideHeading = false,
  className = "",
  children,
}: {
  title?: string;
  description?: string;
  hideHeading?: boolean;
  className?: string;
  children?: React.ReactNode;
}) {
  const [user, setUser] = useState<User | null>(null);
  const { activeHome, activeHomeId } = useActiveHome();
  const [featureMatrix, setFeatureMatrix] = useState<FeatureMatrix | null>(null);
  const [billingStatus, setBillingStatus] = useState<BillingStatus | null>(null);
  useEffect(() => {
    api.me().then(setUser).catch(() => undefined);
  }, []);
  useEffect(() => {
    setFeatureMatrix(null);
    setBillingStatus(null);
    if (!activeHomeId) return;
    let cancelled = false;
    api
      .featureMatrix(activeHomeId)
      .then((next) => {
        if (!cancelled) setFeatureMatrix(next);
      })
      .catch(() => {
        if (!cancelled) setFeatureMatrix(null);
      });
    api
      .billingStatus(activeHomeId)
      .then((next) => {
        if (!cancelled) setBillingStatus(next);
      })
      .catch(() => {
        if (!cancelled) setBillingStatus(null);
      });
    return () => {
      cancelled = true;
    };
  }, [activeHomeId]);
  const isAdult = user?.principal_type !== "managed_child";
  const isHomeAdmin = activeHome?.relationship === "home_admin";

  function visible(item: MoreItem): boolean {
    if (item.gate === "homeAdmin" && !(isAdult && isHomeAdmin)) return false;
    if (item.gate === "adult" && !isAdult) return false;
    // No featureKey: unaffected, matching every row's current behaviour
    // exactly (Nudges/Lists/Meal Plans and everything else).
    if (!item.featureKey) return true;
    // Platform/Home module state not yet loaded, or genuinely unavailable
    // — hidden, never a dead link, matching the Home dashboard quick
    // actions' own `{featureOn && (...)}` treatment for the same modules.
    return Boolean(
      featureMatrix?.features.some(
        (feature) => feature.feature === item.featureKey && feature.enabled,
      ),
    );
  }

  function locked(item: MoreItem): boolean {
    if (!item.entitlementKey) return false;
    // Unknown/loading is deliberately not Free. A lock is only valid after
    // the current Home's billing response positively says this entitlement
    // is unavailable. This prevents Family users seeing a transient Free
    // presentation while the request hydrates, and prevents an old Home's
    // response from determining the new Home's UI.
    return billingStatus?.[item.entitlementKey] === false;
  }

  return (
    <AppShellContent>
      {!children && (
        <div className="more-hero">
          <div className="more-hero-text">
            <h1>More</h1>
            <p>Everything else for your home</p>
          </div>
          <HeroFlower />
        </div>
      )}
      <main className={`standard-page${className ? ` ${className}` : ""}`}>
        {children ? (
          <>
            {!hideHeading && (
              <div className="page-heading">
                <div>
                  <p className="eyebrow">A calm place for the details</p>
                  <h1>{title}</h1>
                  {description && <p className="muted">{description}</p>}
                </div>
              </div>
            )}
            {children}
          </>
        ) : (
          <div className="more-groups">
            {MORE_GROUPS.map((group) => {
              const items = group.items.filter(visible);
              if (items.length === 0) return null;
              return (
                <section className="card more-group" key={group.label}>
                  <p className="more-group-label">{group.label}</p>
                  <div className="more-group-rows">
                    {items.map((item) => {
                      const itemLocked = locked(item);
                      return (
                        <Link
                          className={`more-row${itemLocked ? " more-row-locked" : ""}`}
                          href={item.href}
                          key={item.href}
                        >
                          <span className={`more-icon-tile ${item.tone}`} aria-hidden="true">
                            <item.icon size={20} strokeWidth={1.75} />
                          </span>
                          <span className="more-row-text">
                            <h2>
                              {item.name}
                              {itemLocked && (
                                <Lock className="more-row-lock" aria-hidden="true" size={12} />
                              )}
                            </h2>
                            <p>{itemLocked ? "Included with MyKhaya Family" : item.detail}</p>
                          </span>
                          <span className="more-row-chevron" aria-hidden="true">
                            ›
                          </span>
                        </Link>
                      );
                    })}
                  </div>
                </section>
              );
            })}
          </div>
        )}
      </main>
    </AppShellContent>
  );
}
