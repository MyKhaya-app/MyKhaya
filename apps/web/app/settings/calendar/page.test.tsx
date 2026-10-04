import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { NotificationPreferences } from "@mykhaya/shared-types";
import CalendarSettingsPage from "./page";

// Coverage for Settings -> Calendar settings. The default reminders are opt-in: a person
// who has never touched them has both switched off, saving the page without touching them
// must not switch them on, and turning one on persists the interval that was chosen.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/settings/calendar",
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
  nativePlatform: () => "web",
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
      listCalendars: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

/** What a person who has never opened Calendar settings has: both default reminders off. */
function shippedPrefs(overrides: Partial<NotificationPreferences> = {}): NotificationPreferences {
  return {
    push_enabled: true,
    in_app_enabled: true,
    email_enabled: false,
    event_reminders_enabled: true,
    default_event_reminder_enabled: false,
    default_event_reminder_minutes: 30,
    all_day_reminder_enabled: false,
    all_day_reminder_time: "09:00",
    default_calendar_id: null,
    week_starts_on: "monday",
    show_declined_events: false,
    event_invitations_enabled: true,
    event_changes_enabled: true,
    household_reminders_enabled: true,
    list_assignments_enabled: true,
    wishlist_sharing_enabled: true,
    daily_briefing_enabled: false,
    briefing_time: "07:30",
    briefing_days: "daily",
    empty_day_briefing_enabled: false,
    daily_nudge_summary_enabled: true,
    daily_nudge_summary_time: "07:30",
    nudges_evening_cleanup_enabled: true,
    nudges_evening_time: "20:30",
    nudges_day_complete_enabled: true,
    lock_screen_preview_level: "title_only",
    quiet_hours_start: null,
    quiet_hours_end: null,
    quiet_hours_critical_only: false,
    ...overrides,
  };
}

const calendars = {
  items: [
    {
      id: "cal-home",
      name: "Home Calendar",
      timezone: "Europe/London",
      is_primary: true,
      color: "#456B76",
      owner_user_id: null,
      commercial_access: "normal",
      created_at: "2026-01-01T00:00:00Z",
    },
  ],
  limit: 1,
  personal_calendar: {
    id: "cal-me",
    name: "Alex's calendar",
    timezone: "Europe/London",
    is_primary: false,
    color: "#7A5C99",
    owner_user_id: "u1",
    commercial_access: "normal",
    created_at: "2026-01-01T00:00:00Z",
  },
};

const REMINDER_CHECKBOX = { name: "Remind me before events I’m attending" };
const ALL_DAY_CHECKBOX = { name: "Remind me about all-day events" };

function savedBody(): NotificationPreferences {
  const update = api.updateNotificationPreferences as ReturnType<typeof vi.fn>;
  expect(update).toHaveBeenCalledTimes(1);
  return update.mock.calls[0]![0] as NotificationPreferences;
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "u1", display_name: "Alex" });
  (api.notificationPreferences as ReturnType<typeof vi.fn>).mockResolvedValue(shippedPrefs());
  (api.updateNotificationPreferences as ReturnType<typeof vi.fn>).mockImplementation(
    async (body: NotificationPreferences) => body,
  );
  (api.listCalendars as ReturnType<typeof vi.fn>).mockResolvedValue(calendars);
});

describe("Calendar settings — reminders", () => {
  it("starts with both default reminders off and the interval choice disabled", async () => {
    render(<CalendarSettingsPage />);
    expect(await screen.findByRole("checkbox", REMINDER_CHECKBOX)).not.toBeChecked();
    expect(screen.getByRole("checkbox", ALL_DAY_CHECKBOX)).not.toBeChecked();
    expect(screen.getByRole("combobox", { name: "Reminder time before events" })).toBeDisabled();
  });

  it("saving without touching the reminders does not switch either one on", async () => {
    const user = userEvent.setup();
    render(<CalendarSettingsPage />);
    await screen.findByRole("checkbox", REMINDER_CHECKBOX);

    await user.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(api.updateNotificationPreferences).toHaveBeenCalled());
    const body = savedBody();
    expect(body.default_event_reminder_enabled).toBe(false);
    expect(body.all_day_reminder_enabled).toBe(false);
    expect(body.event_reminders_enabled).toBe(true); // the per-event reminder switch is not touched
  });

  it("turning the reminder on enables the interval, and the chosen interval is saved", async () => {
    const user = userEvent.setup();
    render(<CalendarSettingsPage />);
    await user.click(await screen.findByRole("checkbox", REMINDER_CHECKBOX));
    const interval = screen.getByRole("combobox", { name: "Reminder time before events" });
    expect(interval).toBeEnabled();
    expect(interval).toHaveValue("30"); // 30 minutes is the starting interval once switched on

    await user.selectOptions(interval, "60");
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(api.updateNotificationPreferences).toHaveBeenCalled());
    const body = savedBody();
    expect(body.default_event_reminder_enabled).toBe(true);
    expect(body.default_event_reminder_minutes).toBe(60);
    expect(body.all_day_reminder_enabled).toBe(false);
    expect(await screen.findByText("Calendar settings saved.")).toBeInTheDocument();
  });

  it("turning the all-day reminder on saves it with the chosen time", async () => {
    const user = userEvent.setup();
    render(<CalendarSettingsPage />);
    await user.click(await screen.findByRole("checkbox", ALL_DAY_CHECKBOX));
    await user.selectOptions(screen.getByRole("combobox", { name: "All-day reminder time" }), "10:00");
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(api.updateNotificationPreferences).toHaveBeenCalled());
    const body = savedBody();
    expect(body.all_day_reminder_enabled).toBe(true);
    expect(body.all_day_reminder_time).toBe("10:00");
    expect(body.default_event_reminder_enabled).toBe(false);
  });

  it("shows the person's saved choices when they come back", async () => {
    (api.notificationPreferences as ReturnType<typeof vi.fn>).mockResolvedValue(
      shippedPrefs({ default_event_reminder_enabled: true, default_event_reminder_minutes: 120 }),
    );
    render(<CalendarSettingsPage />);
    expect(await screen.findByRole("checkbox", REMINDER_CHECKBOX)).toBeChecked();
    expect(screen.getByRole("combobox", { name: "Reminder time before events" })).toHaveValue("120");
  });
});

describe("Calendar settings — defaults and display", () => {
  it("saves the chosen default calendar, week start and declined-events choice", async () => {
    const user = userEvent.setup();
    render(<CalendarSettingsPage />);
    await screen.findByRole("checkbox", REMINDER_CHECKBOX);

    await user.selectOptions(screen.getByRole("combobox", { name: "Default calendar" }), "cal-me");
    await user.selectOptions(screen.getByRole("combobox", { name: "Week starts on" }), "sunday");
    await user.click(screen.getByRole("checkbox", { name: "Show events I’ve declined" }));
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(api.updateNotificationPreferences).toHaveBeenCalled());
    const body = savedBody();
    expect(body.default_calendar_id).toBe("cal-me");
    expect(body.week_starts_on).toBe("sunday");
    expect(body.show_declined_events).toBe(true);
  });

  it("offers the person's own calendar as a default", async () => {
    render(<CalendarSettingsPage />);
    const select = await screen.findByRole("combobox", { name: "Default calendar" });
    const options = Array.from(select.querySelectorAll("option")).map((o) => o.textContent);
    expect(options).toContain("Alex's calendar");
  });

  it("shows a save failure instead of claiming success", async () => {
    (api.updateNotificationPreferences as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("Could not save"),
    );
    const user = userEvent.setup();
    render(<CalendarSettingsPage />);
    await user.click(await screen.findByRole("button", { name: "Save settings" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save");
    expect(screen.queryByText("Calendar settings saved.")).not.toBeInTheDocument();
  });
});
