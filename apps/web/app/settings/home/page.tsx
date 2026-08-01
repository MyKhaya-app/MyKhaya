"use client";
import { useEffect, useState } from "react";
import type { Home } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { SettingsPage } from "@/components/settings-page";
import { useActiveHome } from "@/components/use-active-home";
export default function HomeSettings() {
  const [home, setHome] = useState<Home | null>(null);
  const { activeHomeId } = useActiveHome();
  useEffect(() => {
    if (!activeHomeId) return;
    api.homes().then((homes) => setHome(homes.find((row) => row.id === activeHomeId) ?? null));
  }, [activeHomeId]);
  return (
    <SettingsPage title="Home settings">
      <section className="card details">
        <h2>{home?.name ?? "Your Home"}</h2>
        <p>
          {home?.member_count ?? 0} people · Your role:{" "}
          {home?.role.replace("_", " ") ?? "—"}
        </p>
        <p className="hint">
          Home ownership transfers and deletion will be added after the recovery
          workflow is independently reviewed.
        </p>
      </section>
    </SettingsPage>
  );
}
