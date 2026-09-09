import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { NotificationPreferences } from "@mykhaya/shared-types";
import NotificationSettings from "./page";

// Coverage for the Daily Nudge Summary preference: its own section (rendered
// above Daily briefing, per the desired settings order), its own default
// on/off + delivery-time state independent from Daily Briefing's, and that
// the two never cross-contaminate each other's saved values.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/settings/notifications",
}));

vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({
    activeHome: { id: "home-1", name: "Hales Home" },
    activeHomeId: "home-1",
    homes: [{ id: "home-1", name: "Hales Home" }],
    setActiveHomeId: vi.fn(),
    loading: false,
  }),
}));

vi.mock("@/components/native-runtime", () => ({
  isNativeShell: () => false,
}));

vi.mock("@/components/install-prompt", () => ({
  isStandalone: () => false,
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      notificationPreferences: vi.fn(),
      updateNotificationPreferences: vi.fn(),
      listPushSubscriptions: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

function basePrefs(overrides: Partial<NotificationPreferences> = {}): NotificationPreferences {
  return {
    push_enabled: true,
    in_app_enabled: true,
    email_enabled: false,
    event_reminders_enabled: true,
    event_invitations_enabled: true,
    event_changes_enabled: true,
    household_reminders_enabled: true,
    list_assignments_enabled: true,
    wishlist_sharing_enabled: true,
    daily_briefing_enabled: true,
    briefing_time: "07:00",
    briefing_days: "daily",
    empty_day_briefing_enabled: true,
    daily_nudge_summary_enabled: true,
    daily_nudge_summary_time: "07:30",
    nudges_evening_cleanup_enabled: true,
    nudges_evening_time: "20:30",
    nudges_day_complete_enabled: true,
    lock_screen_preview_level: "title_only",
    quiet_hours_start: null,
    quiet_hours_end: null,
    quiet_hours_critical_only: true,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "u1", display_name: "Owner" });
  (api.notificationPreferences as ReturnType<typeof vi.fn>).mockResolvedValue(basePrefs());
  (api.updateNotificationPreferences as ReturnType<typeof vi.fn>).mockImplementation(
    async (body: NotificationPreferences) => body,
  );
  (api.listPushSubscriptions as ReturnType<typeof vi.fn>).mockResolvedValue([]);
});

describe("Notification settings — Nudges section", () => {
  it("renders the Nudges heading before the Daily briefing heading", async () => {
    render(<NotificationSettings />);
    const headings = await screen.findAllByRole("heading", { level: 2 });
    const labels = headings.map((heading) => heading.textContent);
    expect(labels.indexOf("Nudges")).toBeGreaterThanOrEqual(0);
    expect(labels.indexOf("Daily briefing")).toBeGreaterThanOrEqual(0);
    expect(labels.indexOf("Nudges")).toBeLessThan(labels.indexOf("Daily briefing"));
  });

  // Both sections' delivery-time <select> share the accessible name
  // "Delivery time" (same label wording by design, matching Daily
  // Briefing's existing pattern) — the Nudges one renders first in DOM
  // order (it now sits above Daily briefing), so index 0 is always it.
  function nudgeSummaryTimeSelect(): HTMLElement {
    const [nudgeSelect] = screen.getAllByRole("combobox", { name: /delivery time/i });
    if (!nudgeSelect) throw new Error("Nudge summary delivery-time select not found");
    return nudgeSelect;
  }
  function briefingTimeSelect(): HTMLElement {
    const [, briefingSelect] = screen.getAllByRole("combobox", { name: /delivery time/i });
    if (!briefingSelect) throw new Error("Daily briefing delivery-time select not found");
    return briefingSelect;
  }

  it("defaults the toggle on and the time to 07:30 for a fresh preference row", async () => {
    render(<NotificationSettings />);
    const toggle = await screen.findByRole("checkbox", { name: "Send me a daily Nudge summary" });
    expect(toggle).toBeChecked();
    await screen.findAllByRole("combobox", { name: /delivery time/i });
    expect(nudgeSummaryTimeSelect()).toHaveValue("07:30");
  });

  it("lets the delivery time be changed independently and saves it", async () => {
    render(<NotificationSettings />);
    await screen.findByRole("checkbox", { name: "Send me a daily Nudge summary" });
    await userEvent.selectOptions(nudgeSummaryTimeSelect(), "18:00");
    await userEvent.click(screen.getByRole("button", { name: /save preferences/i }));

    await waitFor(() =>
      expect(api.updateNotificationPreferences).toHaveBeenCalledWith(
        expect.objectContaining({ daily_nudge_summary_time: "18:00", daily_nudge_summary_enabled: true }),
      ),
    );
  });

  it("keeps Daily briefing's delivery time untouched when only the Nudge summary time changes", async () => {
    render(<NotificationSettings />);
    await screen.findByRole("checkbox", { name: "Send me a daily Nudge summary" });
    expect(briefingTimeSelect()).toHaveValue("custom");
    await userEvent.selectOptions(nudgeSummaryTimeSelect(), "18:00");
    await userEvent.click(screen.getByRole("button", { name: /save preferences/i }));

    await waitFor(() =>
      expect(api.updateNotificationPreferences).toHaveBeenCalledWith(
        expect.objectContaining({ briefing_time: "07:00" }),
      ),
    );
    // Untouched — still whatever it resolved to before saving.
    expect(briefingTimeSelect()).toHaveValue("custom");
  });

  it("switching the Nudge summary toggle off does not change Daily briefing's settings", async () => {
    render(<NotificationSettings />);
    const nudgeToggle = await screen.findByRole("checkbox", {
      name: "Send me a daily Nudge summary",
    });
    await userEvent.click(nudgeToggle);
    expect(nudgeToggle).not.toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: /save preferences/i }));

    await waitFor(() =>
      expect(api.updateNotificationPreferences).toHaveBeenCalledWith(
        expect.objectContaining({
          daily_nudge_summary_enabled: false,
          daily_briefing_enabled: true,
          briefing_time: "07:00",
          briefing_days: "daily",
        }),
      ),
    );
  });

  it("disables the delivery-time selector while off, and retains the previous time when saved", async () => {
    render(<NotificationSettings />);
    const nudgeToggle = await screen.findByRole("checkbox", {
      name: "Send me a daily Nudge summary",
    });
    await screen.findAllByRole("combobox", { name: /delivery time/i });
    const timeSelect = nudgeSummaryTimeSelect();
    expect(timeSelect).not.toBeDisabled();

    await userEvent.click(nudgeToggle);
    expect(timeSelect).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: /save preferences/i }));
    await waitFor(() =>
      expect(api.updateNotificationPreferences).toHaveBeenCalledWith(
        expect.objectContaining({ daily_nudge_summary_time: "07:30" }),
      ),
    );
  });

  it("persists the saved value after a reload (re-fetch)", async () => {
    const { unmount } = render(<NotificationSettings />);
    await screen.findByRole("checkbox", { name: "Send me a daily Nudge summary" });
    unmount();

    (api.notificationPreferences as ReturnType<typeof vi.fn>).mockResolvedValue(
      basePrefs({ daily_nudge_summary_enabled: false, daily_nudge_summary_time: "09:00" }),
    );

    // A fresh mount simulates a page reload re-fetching preferences from the
    // server — the previously-saved value should come back, not a default.
    render(<NotificationSettings />);
    const toggle = await screen.findByRole("checkbox", {
      name: "Send me a daily Nudge summary",
    });
    expect(toggle).not.toBeChecked();
  });
});

describe("Notification settings — Daily briefing unaffected", () => {
  it("still shows its own independent toggle and time", async () => {
    render(<NotificationSettings />);
    await screen.findByRole("heading", { name: "Daily briefing" });
    expect(
      screen.getByRole("checkbox", { name: "Send me a morning summary" }),
    ).toBeChecked();
  });
});
