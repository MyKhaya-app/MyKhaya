"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { User } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { AppShellContent } from "./app-shell";
const links = [
  ["Profile", "Your name and account details", "/settings/profile"],
  ["Notifications", "Push, reminders and your daily briefing", "/settings/notifications"],
  ["Routines & Reminders", "Bins, medication and other things to do or remember", "/settings/routines-reminders"],
  ["Calendars", "Manage your Home's calendars and sharing", "/calendar/calendars"],
  ["Lists", "Shopping, chores and shared household lists", "/lists"],
  ["Meal Plans", "Plan meals together and save family favourites", "/meal-plans"],
  ["Security", "Password, biometric sign-in and signed-in devices", "/settings/security"],
  ["Home settings", "Name and membership controls", "/settings/home"],
  ["Plan & Billing", "Your Home's plan, and payment status if applicable", "/settings/billing"],
  ["About MyKhaya", "Version information and useful links", "/about"],
  ["Help & Support", "Knowledge base, support tickets and service status", "/help-support"],
] as const;
// Not part of a managed Child's restricted surface — a Child has no password, no
// household administration rights, and no invite/membership controls. Any adult
// member (not just a Home Admin) can still open Plan & Billing — the page itself
// shows read-only status to anyone without billing_manage, per
// docs/security/platform-administration-security.md#household-billing-response.
const ADULT_ONLY_LINKS = new Set(["Security", "Home settings", "Plan & Billing"]);
export function SettingsPage({
  title = "More",
  children,
}: {
  title?: string;
  children?: React.ReactNode;
}) {
  const [user, setUser] = useState<User | null>(null);
  useEffect(() => {
    api.me().then(setUser).catch(() => undefined);
  }, []);
  const isAdult = user?.principal_type !== "managed_child";
  return (
    <AppShellContent>
      <main className="standard-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow">A calm place for the details</p>
            <h1>{title}</h1>
          </div>
        </div>
        {children ?? (
          <div className="settings-list">
            {links
              .filter(([name]) => isAdult || !ADULT_ONLY_LINKS.has(name))
              .map(([name, detail, url]) => (
              <Link className="card" href={url} key={url}>
                <div>
                  <h2>{name}</h2>
                  <p>{detail}</p>
                </div>
                <span>›</span>
              </Link>
            ))}
          </div>
        )}
      </main>
    </AppShellContent>
  );
}
