"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Calendar, Home, MoreHorizontal, Users } from "lucide-react";
import type { PrincipalType } from "@mykhaya/shared-types";
import {
  primaryNavDestinationsFor,
  type PrimaryNavDestination,
} from "./primary-nav-destinations";
import { Logo } from "./logo";

const ICONS: Record<PrimaryNavDestination["id"], typeof Home> = {
  home: Home,
  calendar: Calendar,
  family: Users,
  more: MoreHorizontal,
};

export function DesktopNav({
  principalType,
  familyAccess,
}: {
  principalType?: PrincipalType;
  familyAccess?: boolean;
}) {
  const items = primaryNavDestinationsFor(principalType, familyAccess);
  const path = usePathname();

  return (
    <nav className="desktop-nav" aria-label="Primary navigation">
      <div className="desktop-nav-brand" aria-hidden="true">
        <span className="desktop-nav-brand-mark"><Logo compact /></span>
        <span>MyKhaya</span>
      </div>
      <div className="desktop-nav-links">
        {items.map(({ id, href, label }) => {
          const Icon = ICONS[id];
          return (
            <Link
              key={href}
              href={href}
              className={`desktop-nav-link${path === href || path.startsWith(`${href}/`) ? " active" : ""}`}
              aria-current={path === href || path.startsWith(`${href}/`) ? "page" : undefined}
            >
              <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
              <span>{label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
