"use client";
import { CalendarTagsManager } from "@/components/calendar-tags-manager";
import { SettingsPage } from "@/components/settings-page";
import { useActiveHome } from "@/components/use-active-home";

// The canonical "Calendar tags" destination reached from More — see
// components/calendar-tags-manager.tsx for the actual implementation
// (moved out of Home settings, which is now home details only).
export default function CalendarTagsPage() {
  const { activeHome, activeHomeId } = useActiveHome();
  const canManageCalendars = activeHome?.capabilities.includes("calendar.edit_all") ?? false;
  return (
    <SettingsPage title="Calendar tags">
      {activeHomeId && canManageCalendars ? (
        <CalendarTagsManager homeId={activeHomeId} />
      ) : (
        <p className="quiet-state">
          You don&rsquo;t currently have permission to manage this Home&rsquo;s Calendar Tags.
        </p>
      )}
    </SettingsPage>
  );
}
