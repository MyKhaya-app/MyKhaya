"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Calendar, Home, MoreHorizontal, Users } from "lucide-react";
import type { PrincipalType } from "@mykhaya/shared-types";

const ITEMS = [
  { href: "/home", label: "Home", icon: Home, adultOnly: false },
  { href: "/calendar", label: "Calendar", icon: Calendar, adultOnly: false },
  // "Family" is primarily invitation and membership management — not part of a
  // Child's restricted surface.
  { href: "/people", label: "Family", icon: Users, adultOnly: true },
  { href: "/settings", label: "More", icon: MoreHorizontal, adultOnly: false },
] as const;

export function BottomNav({
  principalType,
}: {
  principalType?: PrincipalType;
}) {
  const path = usePathname();
  const items = ITEMS.filter(
    (item) => !item.adultOnly || principalType !== "managed_child",
  );
  return (
    <nav className="bottom-nav" aria-label="Primary navigation">
      {items.map(({ href, label, icon: Icon }) => {
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
