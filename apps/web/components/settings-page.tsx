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
  Home,
  HelpCircle,
  ListChecks,
  Puzzle,
  Repeat,
  Shield,
  Smartphone,
  Tag,
  UtensilsCrossed,
  Users,
  type LucideIcon,
} from "lucide-react";
import type { User } from "@mykhaya/shared-types";
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
      { name: "Notifications", detail: "Push, reminders and your daily briefing", href: "/settings/notifications", icon: Bell, tone: "cream", gate: "all" },
    ],
  },
  {
    label: "Household tools",
    items: [
      { name: "Routines & Reminders", detail: "Bins, medication and other things to do or remember", href: "/settings/routines-reminders", icon: Repeat, tone: "sage", gate: "all" },
      { name: "Lists", detail: "Shopping, chores and shared household lists", href: "/lists", icon: ListChecks, tone: "cream", gate: "all" },
      { name: "Meal Plans", detail: "Plan meals together and save family favourites", href: "/meal-plans", icon: UtensilsCrossed, tone: "coral", gate: "all" },
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
    label: "Account & security",
    items: [
      { name: "Security", detail: "Review account and session protection", href: "/settings/security", icon: Shield, tone: "blue", gate: "adult" },
      { name: "Devices", detail: "Manage your trusted devices", href: "/settings/security#devices", icon: Smartphone, tone: "lavender", gate: "adult" },
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
  children,
}: {
  title?: string;
  children?: React.ReactNode;
}) {
  const [user, setUser] = useState<User | null>(null);
  const { activeHome } = useActiveHome();
  useEffect(() => {
    api.me().then(setUser).catch(() => undefined);
  }, []);
  const isAdult = user?.principal_type !== "managed_child";
  const isHomeAdmin = activeHome?.relationship === "home_admin";

  function visible(gate: MoreGate): boolean {
    if (gate === "homeAdmin") return isAdult && isHomeAdmin;
    if (gate === "adult") return isAdult;
    return true;
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
      <main className="standard-page">
        {children ? (
          <>
            <div className="page-heading">
              <div>
                <p className="eyebrow">A calm place for the details</p>
                <h1>{title}</h1>
              </div>
            </div>
            {children}
          </>
        ) : (
          <div className="more-groups">
            {MORE_GROUPS.map((group) => {
              const items = group.items.filter((item) => visible(item.gate));
              if (items.length === 0) return null;
              return (
                <section className="card more-group" key={group.label}>
                  <p className="more-group-label">{group.label}</p>
                  <div className="more-group-rows">
                    {items.map((item) => (
                      <Link className="more-row" href={item.href} key={item.href}>
                        <span className={`more-icon-tile ${item.tone}`} aria-hidden="true">
                          <item.icon size={20} strokeWidth={1.75} />
                        </span>
                        <span className="more-row-text">
                          <h2>{item.name}</h2>
                          <p>{item.detail}</p>
                        </span>
                        <span className="more-row-chevron" aria-hidden="true">
                          ›
                        </span>
                      </Link>
                    ))}
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
