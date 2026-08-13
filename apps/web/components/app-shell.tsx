"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import type { User } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { AppHeader } from "./app-header";
import { BottomNav } from "./bottom-nav";
import { useActiveHome } from "./use-active-home";
import { useUserUpdatedListener } from "./user-events";

export function AppShell({
  children,
  hero,
}: {
  children: React.ReactNode;
  /** Optional content that visually continues the header's green field
   *  (e.g. the Home screen's greeting). When present, the header itself
   *  renders flush (square bottom) and this slot carries the rounded
   *  bottom edge and shadow instead, so the two read as one block. */
  hero?: React.ReactNode;
}) {
  const path = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const { homes, activeHome, setActiveHomeId, loading } = useActiveHome();

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => router.replace("/login"));
  }, [router]);

  useEffect(() => {
    if (!loading && !homes.length && path !== "/onboarding")
      router.replace("/onboarding");
  }, [homes, loading, path, router]);

  useUserUpdatedListener(setUser);

  return (
    <div className="app-shell">
      <AppHeader
        user={user}
        homes={homes}
        activeHome={activeHome}
        onSwitchHome={setActiveHomeId}
        flush={Boolean(hero)}
      />
      {hero}
      <main className="app-main">{children}</main>
      <BottomNav principalType={user?.principal_type} />
    </div>
  );
}
