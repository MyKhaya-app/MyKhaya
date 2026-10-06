"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Calendar, Home, MoreHorizontal, Users } from "lucide-react";
import type { PrincipalType } from "@mykhaya/shared-types";
import { primaryNavDestinationsFor, type FamilyAccessState, type PrimaryNavDestination } from "./primary-nav-destinations";

const ICONS: Record<PrimaryNavDestination["id"], typeof Home> = {
  home: Home,
  calendar: Calendar,
  family: Users,
  more: MoreHorizontal,
};

export function BottomNav({
  principalType,
  familyAccess,
}: {
  principalType?: PrincipalType;
  familyAccess?: FamilyAccessState;
}) {
  const path = usePathname();
  const items = primaryNavDestinationsFor(principalType, familyAccess);
  return (
    <nav className="bottom-nav" aria-label="Primary navigation">
      {items.map(({ id, href, label, pending }) => {
        const Icon = ICONS[id];
        const active = path === href || path.startsWith(`${href}/`) || (id === "more" && (path === "/budget" || path.startsWith("/budget/")));
        return (
          <Link
            key={href}
            href={href}
            className={`${active ? "active" : ""}${pending ? " nav-pending" : ""}`.trim()}
            aria-current={active ? "page" : undefined}
            aria-hidden={pending || undefined}
            tabIndex={pending ? -1 : undefined}
          >
            <Icon size={24} strokeWidth={active ? 2.25 : 1.75} aria-hidden="true" />
            <span>{label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
