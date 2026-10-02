"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * In-page tab bar for the Legal & Compliance area (§1 of the Phase 2 brief):
 * the sidebar carries a single "Legal & Compliance" entry, and this renders
 * the area's own Overview | Documents | Acceptance | Privacy Requests |
 * Data & Retention | Subprocessors structure.
 */
const TABS = [
  { label: "Overview", href: "/legal" },
  { label: "Documents", href: "/legal/documents" },
  { label: "Acceptance", href: "/legal/acceptance" },
  { label: "Privacy Requests", href: "/legal/privacy-requests" },
  { label: "Data & Retention", href: "/legal/retention" },
  { label: "Subprocessors", href: "/legal/subprocessors" },
  { label: "Launch Readiness", href: "/legal/launch-readiness" },
] as const;

function isActive(path: string, href: string): boolean {
  if (href === "/legal") return path === "/legal";
  return path === href || path.startsWith(`${href}/`);
}

export function CcLegalSubnav() {
  const path = usePathname().replace(/^\/control-centre/, "") || "/";
  return (
    <nav className="cc-legal-subnav" aria-label="Legal & Compliance sections">
      {TABS.map((tab) => (
        <Link
          key={tab.label}
          href={tab.href}
          className={`cc-legal-subnav-tab ${isActive(path, tab.href) ? "cc-legal-subnav-tab-active" : ""}`}
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
