"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// Bare paths — do not add a control-centre prefix here. On the real admin
// domain (admin[.dev].mykhaya.app), middleware.ts rewrites every incoming
// request onto the internal Control Centre route and the browser/
// usePathname() never see that prefix — matching PlatformShell's own
// top-level nav array. A prefixed href here would get double-rewritten and
// 404 on the deployed admin site (though not under `next dev` on a bare
// localhost, where no such rewrite happens) — see middleware.ts.
const TABS = [
  ["Overview", "/notifications"],
  ["Templates", "/notifications/templates"],
  ["Channels", "/notifications/channels"],
  ["Daily Briefing", "/notifications/briefing"],
  ["Test Centre", "/notifications/test-centre"],
  ["Delivery Logs", "/notifications/delivery-logs"],
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
