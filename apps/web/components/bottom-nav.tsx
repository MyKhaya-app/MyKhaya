"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Calendar, Home, MoreHorizontal, Users } from "lucide-react";
import type { PrincipalType } from "@mykhaya/shared-types";
import { primaryNavDestinationsFor, type PrimaryNavDestination } from "./primary-nav-destinations";

const ICONS: Record<PrimaryNavDestination["id"], typeof Home> = {
  home: Home,
  calendar: Calendar,
  family: Users,
  more: MoreHorizontal,
};

export function BottomNav({
  principalType,
}: {
  principalType?: PrincipalType;
}) {
  const path = usePathname();
  const items = primaryNavDestinationsFor(principalType);
  return (
    <nav className="bottom-nav" aria-label="Primary navigation">
      {items.map(({ id, href, label }) => {
        const Icon = ICONS[id];
        const active = path === href || path.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            className={active ? "active" : ""}
            aria-current={active ? "page" : undefined}
          >
            <Icon size={24} strokeWidth={active ? 2.25 : 1.75} aria-hidden="true" />
            <span>{label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
