"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Calendar, Home, MoreHorizontal, Users } from "lucide-react";

const ITEMS = [
  { href: "/home", label: "Home", icon: Home },
  { href: "/calendar", label: "Calendar", icon: Calendar },
  { href: "/people", label: "Family", icon: Users },
  { href: "/settings", label: "More", icon: MoreHorizontal },
] as const;

export function BottomNav() {
  const path = usePathname();
  return (
    <nav className="bottom-nav" aria-label="Primary navigation">
      {ITEMS.map(({ href, label, icon: Icon }) => {
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
