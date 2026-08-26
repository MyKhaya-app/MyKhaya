"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  ["Overview", "/control-centre/notifications"],
  ["Templates", "/control-centre/notifications/templates"],
  ["Channels", "/control-centre/notifications/channels"],
  ["Daily Briefing", "/control-centre/notifications/briefing"],
  ["Test Centre", "/control-centre/notifications/test-centre"],
  ["Delivery Logs", "/control-centre/notifications/delivery-logs"],
] as const;

/** Second-level navigation within the PCC Notifications module — Overview /
 *  Templates / Channels / Daily Briefing / Test Centre / Delivery Logs.
 *  Distinct from PlatformShell's own top-level sidebar nav (see
 *  .platform-subnav in styles.css). */
export function NotificationsSubNav() {
  const path = usePathname();
  return (
    <nav className="platform-subnav" aria-label="Notifications section navigation">
      {TABS.map(([label, href]) => (
        <Link key={href} href={href} className={path === href ? "active" : ""}>
          {label}
        </Link>
      ))}
    </nav>
  );
}
