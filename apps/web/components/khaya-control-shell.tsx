"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { AppShellContent } from "./app-shell";
import { useActiveHome } from "./use-active-home";

// The shared Home-admin-only gate + page header for the household
// management screens reached from More (Child permissions, Module
// management). Deliberately no longer carries its own cross-page nav strip
// — that duplicated More itself; navigating between these screens now goes
// back through More, the one place all of them are listed. See
// components/settings-page.tsx.
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
            <p className="eyebrow">Home administration</p>
            <h1>{title}</h1>
            <p>{description}</p>
          </div>
        </header>
        {children}
      </main>
    </AppShellContent>
  );
}
