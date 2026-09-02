"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { AppShellContent } from "./app-shell";
import { useActiveHome } from "./use-active-home";

const sections = [
  ["General", "/settings/home"],
  ["Members and roles", "/people"],
  ["Child permissions", "/khaya-control-centre/children"],
  ["Security", "/settings/security"],
  ["Feature Management", "/khaya-control-centre/feature-management"],
  ["About", "/settings"],
] as const;

export function KhayaControlShell({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const { activeHome, loading } = useActiveHome();
  const authorised = activeHome?.relationship === "home_admin";

  useEffect(() => {
    if (!loading && !authorised) router.replace("/home");
  }, [authorised, loading, router]);

  if (loading || !authorised) {
    return (
      <AppShellContent>
        <main className="standard-page">
          <p role="status">Checking access…</p>
        </main>
      </AppShellContent>
    );
  }

  return (
    <AppShellContent>
      <main className="standard-page control-page">
        <header className="page-heading">
          <div>
            <p className="eyebrow">Khaya Control Centre</p>
            <h1>{title}</h1>
            <p>{description}</p>
          </div>
        </header>
        <nav
          className="control-tabs"
          aria-label="Khaya Control Centre sections"
        >
          {sections.map(([label, href]) => (
            <Link
              className={
                pathname === href || pathname.startsWith(`${href}/`)
                  ? "active"
                  : ""
              }
              href={href}
              key={href}
            >
              {label}
            </Link>
          ))}
        </nav>
        {children}
      </main>
    </AppShellContent>
  );
}
