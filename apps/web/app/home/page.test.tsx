import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import HomePage from "./page";

// Coverage for the Home screen's "Around the house" Meal Plans shortcut —
// see docs/architecture/meal-plans.md. The shortcut always links to
// /meal-plans (the destination page owns the Family/Free FamilyUpsell gate)
// but is only rendered at all when the module is actually released for this
// Home (mirrors the existing calendarEnabled precedent), and shows a locked
// treatment rather than disappearing when the Home is on the Free plan.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/home",
}));

function defaultActiveHome() {
  return {
    activeHome: { id: "home-1", name: "Hales Home", capabilities: ["members.invite"] },
    activeHomeId: "home-1",
    homes: [{ id: "home-1", name: "Hales Home" }],
    setActiveHomeId: vi.fn(),
    loading: false,
  };
}

const activeHomeMock = vi.fn(defaultActiveHome);

vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => activeHomeMock(),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      birthdays: vi.fn(),
      billingStatus: vi.fn(),
      featureMatrix: vi.fn(),
      members: vi.fn(),
      homeSummary: vi.fn(),
      listEvents: vi.fn(),
      listUpcomingEvents: vi.fn(),
      sharedCalendars: vi.fn(),
      listUpcomingSharedEvents: vi.fn(),
      routines: vi.fn(),
      completeRoutine: vi.fn(),
      reminders: vi.fn(),
      completeReminder: vi.fn(),
      mealPlanDay: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

function billing(overrides: Record<string, unknown> = {}) {
  return {
    member_usage: { count: 1, limit: 1, over_limit: false },
    meals_enabled: false,
    lists_enabled: false,
    wishlists_enabled: false,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  // clearAllMocks() resets call history but not a mock's implementation —
  // explicitly restore the default here so a test-local
  // activeHomeMock.mockReturnValue(...) (mockClear doesn't undo those
  // either) never leaks into a later test.
  activeHomeMock.mockImplementation(defaultActiveHome);
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "u1", display_name: "Megan" });
  (api.birthdays as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (api.routines as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.completeRoutine as ReturnType<typeof vi.fn>).mockResolvedValue({});
  (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.completeReminder as ReturnType<typeof vi.fn>).mockResolvedValue({});
  (api.mealPlanDay as ReturnType<typeof vi.fn>).mockResolvedValue({ date: "2026-08-20", entries: [] });
  (api.homeSummary as ReturnType<typeof vi.fn>).mockResolvedValue({
    today_events: [],
    next_event: null,
  });
  (api.listUpcomingEvents as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [], next_page: null });
  (api.sharedCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.listUpcomingSharedEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: [],
    next_page: null,
  });
  (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
    features: [
      { feature: "calendar", enabled: false },
      { feature: "meals", enabled: true },
      { feature: "shopping", enabled: true },
    ],
  });
});

describe("Home — Meal plans shortcut", () => {
  it("links to Meal Plans with no lock treatment on a Family Home", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(billing({ meals_enabled: true }));

    render(<HomePage />);

    const link = await screen.findByRole("link", { name: /meal plans/i });
    expect(link).toHaveAttribute("href", "/meal-plans");
    expect(link.className).not.toMatch(/quick-action-locked/);
  });

  it("shows the locked treatment but still links through on a Free Home", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(billing({ meals_enabled: false }));

    render(<HomePage />);

    const link = await screen.findByRole("link", { name: /meal plans/i });
    expect(link).toHaveAttribute("href", "/meal-plans");
    expect(link.className).toMatch(/quick-action-locked/);
  });

  it("hides the shortcut entirely when the module isn't released for this Home", async () => {
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
      features: [
        { feature: "calendar", enabled: false },
        { feature: "meals", enabled: false },
      ],
    });
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(billing({ meals_enabled: true }));

    render(<HomePage />);

    await screen.findByText(/around the house/i);
    expect(screen.queryByRole("link", { name: /meal plans/i })).not.toBeInTheDocument();
  });
});

describe("Home — Lists shortcut", () => {
  it("links to Lists with no lock treatment on a Family Home", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(billing({ lists_enabled: true }));

    render(<HomePage />);

    const link = await screen.findByRole("link", { name: /^lists$/i });
    expect(link).toHaveAttribute("href", "/lists");
    expect(link.className).not.toMatch(/quick-action-locked/);
  });

  it("shows the locked treatment but still links through on a Free Home", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(billing({ lists_enabled: false }));

    render(<HomePage />);

    const link = await screen.findByRole("link", { name: /^lists$/i });
    expect(link).toHaveAttribute("href", "/lists");
    expect(link.className).toMatch(/quick-action-locked/);
  });

  it("hides the shortcut entirely when the module isn't released for this Home", async () => {
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
      features: [
        { feature: "calendar", enabled: false },
        { feature: "meals", enabled: false },
        { feature: "shopping", enabled: false },
      ],
    });
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(billing({ lists_enabled: true }));

    render(<HomePage />);

    await screen.findByText(/around the house/i);
    expect(screen.queryByRole("link", { name: /^lists$/i })).not.toBeInTheDocument();
  });
});

describe("Home — Wishlists shortcut", () => {
  beforeEach(() => {
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
      features: [
        { feature: "calendar", enabled: false },
        { feature: "meals", enabled: true },
        { feature: "shopping", enabled: true },
        { feature: "wish_lists", enabled: true },
      ],
    });
  });

  it("links to Wishlists with no lock treatment on a Family Home", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      billing({ wishlists_enabled: true }),
    );

    render(<HomePage />);

    const link = await screen.findByRole("link", { name: /^wishlists$/i });
    expect(link).toHaveAttribute("href", "/wish-lists");
    expect(link.className).not.toMatch(/quick-action-locked/);
  });

  it("shows the locked treatment but still links through on a Free Home", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      billing({ wishlists_enabled: false }),
    );

    render(<HomePage />);

    const link = await screen.findByRole("link", { name: /^wishlists$/i });
    expect(link).toHaveAttribute("href", "/wish-lists");
    expect(link.className).toMatch(/quick-action-locked/);
  });

  it("hides the shortcut entirely when the module isn't released for this Home", async () => {
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
      features: [
        { feature: "calendar", enabled: false },
        { feature: "meals", enabled: false },
        { feature: "shopping", enabled: false },
        { feature: "wish_lists", enabled: false },
      ],
    });
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      billing({ wishlists_enabled: true }),
    );

    render(<HomePage />);

    await screen.findByText(/around the house/i);
    expect(screen.queryByRole("link", { name: /^wishlists$/i })).not.toBeInTheDocument();
  });
});

describe("Home — Routines shortcut", () => {
  it("always links to the combined Routines & Reminders settings screen, with no feature flag or lock", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(billing());
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
      features: [
        { feature: "calendar", enabled: false },
        { feature: "meals", enabled: false },
        { feature: "shopping", enabled: false },
      ],
    });

    render(<HomePage />);

    const link = await screen.findByRole("link", { name: /routines & reminders/i });
    expect(link).toHaveAttribute("href", "/settings/routines-reminders");
    expect(link.className).not.toMatch(/quick-action-locked/);
  });

  it("groups Add event/Invite family into a 2-tile row and Routines/Meal plans/Lists into a 3-tile row, with no empty placeholder tile", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      billing({
        meals_enabled: true,
        lists_enabled: true,
        member_usage: { count: 1, limit: 4, over_limit: false },
      }),
    );
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
      features: [
        { feature: "calendar", enabled: true },
        { feature: "meals", enabled: true },
        { feature: "shopping", enabled: true },
      ],
    });

    const { container } = render(<HomePage />);

    await screen.findByRole("link", { name: /add event/i });

    const topRow = container.querySelector(".quick-actions-row-2");
    const bottomRow = container.querySelector(".quick-actions-row-3");
    expect(topRow).not.toBeNull();
    expect(bottomRow).not.toBeNull();
    expect(topRow?.children).toHaveLength(2);
    expect(bottomRow?.children).toHaveLength(3);
    expect(container.querySelectorAll(".quick-actions-row").length).toBe(2);
    // No leftover empty grid cell/placeholder from the old flat 2-column grid.
    expect(container.querySelector(".quick-action-placeholder")).toBeNull();
  });

  it("shrinks the feature row to match however many shortcuts are actually entitled/released", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(billing());
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
      features: [
        { feature: "calendar", enabled: false },
        { feature: "meals", enabled: false },
        { feature: "shopping", enabled: false },
      ],
    });

    const { container } = render(<HomePage />);

    await screen.findByRole("link", { name: /routines & reminders/i });
    const bottomRow = container.querySelector(".quick-actions-row-1");
    expect(bottomRow).not.toBeNull();
    expect(bottomRow?.children).toHaveLength(1);
    expect(screen.queryByRole("link", { name: /meal plans/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^lists$/i })).not.toBeInTheDocument();
  });
});

// Relative to whenever the suite actually runs, not a fixed calendar date —
// a hardcoded absolute date here would eventually become "the past" and
// silently start failing every test below that doesn't override start_at/
// end_at, now that Coming up genuinely filters on real elapsed time (see
// app/calendar/calendar-utils.ts's isEventStillUpcoming). Exported for the
// "Home — Coming up" tests below, which build their own scenarios around it.
function minutesFromNow(minutes: number): string {
  return new Date(Date.now() + minutes * 60_000).toISOString();
}

function occurrence(overrides: Record<string, unknown>) {
  return {
    occurrence_id: "occ-1",
    event_id: "event-1",
    calendar_id: "cal-1",
    title: "Event",
    start_at: minutesFromNow(60),
    end_at: minutesFromNow(120),
    is_all_day: false,
    timezone: "UTC",
    description: null,
    location_text: null,
    label: null,
    calendar_color: "teal",
    member_ids: [],
    recurrence: "none",
    reminder_minutes: null,
    created_by: "u1",
    updated_at: "2026-08-01T00:00:00+00:00",
    ...overrides,
  };
}

function enableCalendarOnly() {
  (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
    features: [
      { feature: "calendar", enabled: true },
      { feature: "meals", enabled: false },
      { feature: "shopping", enabled: false },
    ],
  });
  (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(billing());
}

// The native-shell hero-density and top-overscroll-background fixes
// (app/styles.css's `html.native-shell .home-hero`/`.home-family-strip`/
// `.app-content-scroll-region:has(.home-hero)` rules) are CSS-only —
// nothing here renders differently between native and browser. What
// actually keeps those selectors correct is this exact DOM contract:
// `.home-hero` and `.home-family-strip` must keep existing, with the
// avatar strip nested inside the hero. This guards that contract against
// a future refactor silently renaming/removing the hooks that CSS depends
// on, in either environment.
describe("Home — hero markup contract", () => {
  it("renders the hero and family strip with the classNames styles.css depends on", async () => {
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        membership_id: "m1",
        user_id: "u2",
        display_name: "Erin",
        email: null,
        role: "adult_member",
        relationship: "partner",
        permission_profile: "standard_partner",
        permission_overrides: {},
        shared_resources: [],
        colour: "sky",
        avatar_version: null,
      },
    ]);

    render(<HomePage />);
    await screen.findByText("Routines & Reminders");

    const hero = document.querySelector(".home-hero");
    expect(hero).not.toBeNull();
    expect(hero?.querySelector("h1")).not.toBeNull();
    const strip = hero?.querySelector(".home-family-strip");
    expect(strip).not.toBeNull();
    expect(strip?.querySelector(".avatar")).not.toBeNull();
  });
});

describe("Home — Coming up", () => {
  it("shows the empty-state copy when there are genuinely no future events", async () => {
    enableCalendarOnly();

    render(<HomePage />);

    await screen.findByText("Coming up");
    expect(await screen.findByText("Nothing else planned yet.")).toBeInTheDocument();
  });

  // Coming up must show the next 3 chronological events from right now —
  // including whatever's left of today — not skip straight to tomorrow.
  // See app/calendar/calendar-utils.ts's isEventStillUpcoming, the shared
  // eligibility rule this whole describe block exercises end to end
  // (minutesFromNow is the module-level helper defined above, next to
  // occurrence()).

  it("includes an event later today, even though Today's own card also shows it", async () => {
    enableCalendarOnly();
    const laterToday = minutesFromNow(60);
    (api.homeSummary as ReturnType<typeof vi.fn>).mockResolvedValue({
      // Today's own summary lists the whole day, past and future alike —
      // Coming up must not treat that as a reason to hide the same event.
      today_events: [occurrence({ occurrence_id: "occ-later", title: "Breakfast @ Jacks", start_at: laterToday, end_at: laterToday })],
      next_event: null,
    });
    (api.listUpcomingEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        occurrence({ occurrence_id: "occ-later", title: "Breakfast @ Jacks", start_at: laterToday, end_at: laterToday }),
      ],
      next_page: null,
    });

    render(<HomePage />);

    // Appears twice, deliberately: once in Today's own list (the whole day,
    // past and future) and once in Coming up (the next 3 events from now) —
    // the two cards answer different questions and are expected to overlap
    // on a day that still has events left, not dedupe each other away.
    await screen.findAllByText("Breakfast @ Jacks");
    expect(screen.getAllByText("Breakfast @ Jacks")).toHaveLength(2);
  });

  it("excludes an event earlier today that has already finished", async () => {
    enableCalendarOnly();
    const finishedEarlier = minutesFromNow(-120);
    (api.listUpcomingEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        occurrence({
          occurrence_id: "occ-past",
          title: "Fergie Juniors",
          start_at: finishedEarlier,
          end_at: minutesFromNow(-60),
        }),
      ],
      next_page: null,
    });

    render(<HomePage />);

    await screen.findByText("Nothing else planned yet.");
    expect(screen.queryByText("Fergie Juniors")).not.toBeInTheDocument();
  });

  it("returns two events later today before tomorrow's event, in chronological order", async () => {
    enableCalendarOnly();
    (api.listUpcomingEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        // Deliberately out of order in the API response — the page must
        // still sort by actual start time.
        occurrence({
          occurrence_id: "occ-tomorrow",
          title: "Tomorrow's event",
          start_at: minutesFromNow(60 * 30),
          end_at: minutesFromNow(60 * 30 + 30),
        }),
        occurrence({
          occurrence_id: "occ-erin",
          title: "Erin Drumming",
          start_at: minutesFromNow(150),
          end_at: minutesFromNow(180),
        }),
        occurrence({
          occurrence_id: "occ-breakfast",
          title: "Breakfast @ Jacks",
          start_at: minutesFromNow(60),
          end_at: minutesFromNow(90),
        }),
      ],
      next_page: null,
    });

    render(<HomePage />);

    await screen.findByText("Breakfast @ Jacks");
    const titles = screen
      .getAllByText(/Breakfast @ Jacks|Erin Drumming|Tomorrow's event/)
      .map((node) => node.textContent);
    expect(titles).toEqual(["Breakfast @ Jacks", "Erin Drumming", "Tomorrow's event"]);
  });

  it("falls back to tomorrow/next future events when nothing is left today", async () => {
    enableCalendarOnly();
    (api.listUpcomingEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        occurrence({
          occurrence_id: "occ-past",
          title: "Finished earlier",
          start_at: minutesFromNow(-120),
          end_at: minutesFromNow(-60),
        }),
        occurrence({
          occurrence_id: "occ-future",
          title: "Next week's event",
          start_at: minutesFromNow(60 * 24 * 8),
          end_at: minutesFromNow(60 * 24 * 8 + 30),
        }),
      ],
      next_page: null,
    });

    render(<HomePage />);

    expect(await screen.findByText("Next week's event")).toBeInTheDocument();
    expect(screen.queryByText("Finished earlier")).not.toBeInTheDocument();
  });

  it("includes an all-day event covering today", async () => {
    enableCalendarOnly();
    const todayKey = new Date().toISOString().slice(0, 10);
    const tomorrowKey = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
    (api.listUpcomingEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        occurrence({
          occurrence_id: "occ-allday",
          title: "Sports Day",
          is_all_day: true,
          start_at: `${todayKey}T00:00:00+00:00`,
          end_at: `${tomorrowKey}T00:00:00+00:00`,
        }),
      ],
      next_page: null,
    });

    render(<HomePage />);

    expect(await screen.findByText("Sports Day")).toBeInTheDocument();
  });

  it("includes an event currently in progress", async () => {
    enableCalendarOnly();
    (api.listUpcomingEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        occurrence({
          occurrence_id: "occ-inprogress",
          title: "Swimming lesson",
          start_at: minutesFromNow(-15),
          end_at: minutesFromNow(15),
        }),
      ],
      next_page: null,
    });

    render(<HomePage />);

    expect(await screen.findByText("Swimming lesson")).toBeInTheDocument();
  });

  it("includes a recurring occurrence later today", async () => {
    enableCalendarOnly();
    (api.listUpcomingEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        occurrence({
          occurrence_id: "event-recurring:2026-08-29T18:00:00+00:00",
          title: "Weekly Piano",
          recurrence: "weekly",
          start_at: minutesFromNow(90),
          end_at: minutesFromNow(120),
        }),
      ],
      next_page: null,
    });

    render(<HomePage />);

    expect(await screen.findByText("Weekly Piano")).toBeInTheDocument();
  });

  it("returns exactly 3 results when more than 3 future occurrences exist", async () => {
    enableCalendarOnly();
    (api.listUpcomingEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [1, 2, 3, 4, 5].map((n) =>
        occurrence({
          occurrence_id: `occ-${n}`,
          title: `Event ${n}`,
          start_at: minutesFromNow(n * 30),
          end_at: minutesFromNow(n * 30 + 15),
        }),
      ),
      next_page: null,
    });

    render(<HomePage />);

    await screen.findByText("Event 1");
    expect(screen.getByText("Event 2")).toBeInTheDocument();
    expect(screen.getByText("Event 3")).toBeInTheDocument();
    expect(screen.queryByText("Event 4")).not.toBeInTheDocument();
    expect(screen.queryByText("Event 5")).not.toBeInTheDocument();
  });

  it("merges in an event from a calendar shared into this Home", async () => {
    enableCalendarOnly();
    const tomorrow = new Date(Date.now() + 86_400_000).toISOString();
    (api.sharedCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "share-1",
          calendar_id: "shared-cal",
          calendar_name: "Grandma's calendar",
          source_group_id: "other-home",
          source_group_name: "Grandma's House",
          recipient_email: "me@example.com",
          recipient_user_id: "u1",
          permission: "view",
          status: "accepted",
        },
      ],
    });
    (api.listUpcomingSharedEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [occurrence({ occurrence_id: "occ-shared", title: "Sunday lunch", start_at: tomorrow })],
      next_page: null,
    });

    render(<HomePage />);

    expect(await screen.findByText("Sunday lunch")).toBeInTheDocument();
    // vitest's `expect.any(Number)` types as `any`, which trips
    // @typescript-eslint/no-unsafe-assignment — assert the actual fetch
    // limit (UPCOMING_FETCH_LIMIT in page.tsx) instead, which is both
    // properly typed and a more precise assertion.
    expect(api.listUpcomingSharedEvents).toHaveBeenCalledWith(
      "share-1",
      expect.objectContaining({ limit: 8 }),
    );
  });
});

describe("Home — household routines", () => {
  it("shows an outstanding routine and completes its current occurrence", async () => {
    const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
      features: [
        { feature: "calendar", enabled: false },
        { feature: "meals", enabled: false },
        { feature: "notifications", enabled: true },
      ],
    });
    (api.routines as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "routine-1",
          title: "Put green bin out",
          description: null,
          scope: "household",
          owner_user_id: null,
          interval_weeks: 1,
          repeat_unit: "weekly",
          week_anchor_date: tomorrow,
          reminder_timing: "evening_before",
          is_critical: false,
          pinned: false,
          enabled: true,
          start_date: tomorrow,
          end_date: null,
          member_ids: ["u1"],
          next_occurrence_date: tomorrow,
          completed_today: false,
          home_occurrence_date: tomorrow,
          home_completed_at: null,
          home_completed_by_user_id: null,
          home_completed_by_display_name: null,
          created_by: "u1",
          updated_at: new Date().toISOString(),
        },
      ],
    });

    render(<HomePage />);

    expect(await screen.findByText("Put green bin out")).toBeInTheDocument();
    expect(screen.getByText(/Tomorrow · Household/)).toBeInTheDocument();
    screen.getByRole("button", { name: /complete put green bin out/i }).click();
    expect(await screen.findByText(/Done by Megan/)).toBeInTheDocument();
    expect(api.completeRoutine).toHaveBeenCalledWith("home-1", "routine-1", tomorrow);
  });

  it("keeps completed items visible, orders them after outstanding items, and expands inline", async () => {
    const today = new Date().toISOString().slice(0, 10);
    const completedAt = new Date().toISOString();
    const routine = (id: string, title: string, completed: boolean, scope: "household" | "personal" = "household") => ({
      id,
      title,
      description: null,
      scope,
      owner_user_id: scope === "personal" ? "u1" : null,
      interval_weeks: 1,
      repeat_unit: "daily" as const,
      week_anchor_date: today,
      reminder_timing: "same_day" as const,
      is_critical: false,
      pinned: true,
      enabled: true,
      start_date: today,
      end_date: null,
      member_ids: [],
      next_occurrence_date: today,
      completed_today: completed,
      home_occurrence_date: today,
      home_completed_at: completed ? completedAt : null,
      home_completed_by_user_id: completed ? "u1" : null,
      home_completed_by_display_name: completed && scope === "household" ? "Megan" : null,
      created_by: "u1",
      updated_at: completedAt,
    });
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
      features: [
        { feature: "calendar", enabled: false },
        { feature: "notifications", enabled: true },
      ],
    });
    (api.routines as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        routine("r1", "Outstanding one", false),
        routine("r2", "Outstanding two", false),
        routine("r3", "Feed the dog", true),
        routine("r4", "Take Tablet", true, "personal"),
      ],
    });

    render(<HomePage />);

    expect(await screen.findByText("Outstanding one")).toBeInTheDocument();
    expect(screen.getByText("Outstanding two")).toBeInTheDocument();
    expect(screen.getByText("Feed the dog")).toBeInTheDocument();
    expect(screen.queryByText("Take Tablet")).not.toBeInTheDocument();
    expect(screen.getByText(/Done by Megan/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show more" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("link", { name: "See all" })).toHaveAttribute(
      "href",
      "/settings/routines-reminders",
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Show more" }));
    expect(screen.getByText("Take Tablet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
    await user.click(screen.getByRole("button", { name: "Show less" }));
    expect(screen.queryByText("Take Tablet")).not.toBeInTheDocument();
  });
});

describe("Home — reminders on the combined To-do list", () => {
  function reminder(overrides: Record<string, unknown> = {}) {
    const today = new Date().toISOString().slice(0, 10);
    return {
      id: "reminder-1",
      title: "Call the dentist",
      description: null,
      scope: "personal" as const,
      owner_user_id: "u1",
      due_date: today,
      due_time: "09:00:00",
      repeat: "never" as const,
      cadence: "once" as const,
      enabled: true,
      member_ids: [],
      next_occurrence_date: today,
      completed_today: false,
      home_occurrence_date: today,
      home_completed_at: null,
      home_completed_by_user_id: null,
      home_completed_by_display_name: null,
      created_by: "u1",
      updated_at: new Date().toISOString(),
      ...overrides,
    };
  }
  const tomorrow = () => new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);

  it("shows Routines and Reminders together, each subtly labelled", async () => {
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
      features: [
        { feature: "calendar", enabled: false },
        { feature: "notifications", enabled: true },
      ],
    });
    (api.routines as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "routine-1",
          title: "Put bins out",
          description: null,
          scope: "household",
          owner_user_id: null,
          interval_weeks: 1,
          repeat_unit: "weekly",
          week_anchor_date: tomorrow(),
          reminder_timing: "evening_before",
          is_critical: false,
          pinned: false,
          enabled: true,
          start_date: tomorrow(),
          end_date: null,
          member_ids: [],
          next_occurrence_date: tomorrow(),
          completed_today: false,
          home_occurrence_date: tomorrow(),
          home_completed_at: null,
          home_completed_by_user_id: null,
          home_completed_by_display_name: null,
          created_by: "u1",
          updated_at: new Date().toISOString(),
        },
      ],
    });
    (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [reminder()],
    });

    render(<HomePage />);

    expect(await screen.findByText("Put bins out")).toBeInTheDocument();
    expect(screen.getByText("Call the dentist")).toBeInTheDocument();
    const rows = document.querySelectorAll(".home-routine-row");
    expect(rows).toHaveLength(2);
    expect(document.querySelectorAll(".home-todo-kind")).toHaveLength(2);
    expect(screen.getByText("Routine")).toBeInTheDocument();
    expect(screen.getByText("Reminder")).toBeInTheDocument();
  });

  it("completes a reminder from Home without affecting an unrelated routine", async () => {
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
      features: [
        { feature: "calendar", enabled: false },
        { feature: "notifications", enabled: true },
      ],
    });
    (api.routines as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "routine-1",
          title: "Feed the dog",
          description: null,
          scope: "household",
          owner_user_id: null,
          interval_weeks: 1,
          repeat_unit: "daily",
          week_anchor_date: new Date().toISOString().slice(0, 10),
          reminder_timing: "same_day",
          is_critical: false,
          pinned: false,
          enabled: true,
          start_date: new Date().toISOString().slice(0, 10),
          end_date: null,
          member_ids: [],
          next_occurrence_date: new Date().toISOString().slice(0, 10),
          completed_today: false,
          home_occurrence_date: new Date().toISOString().slice(0, 10),
          home_completed_at: null,
          home_completed_by_user_id: null,
          home_completed_by_display_name: null,
          created_by: "u1",
          updated_at: new Date().toISOString(),
        },
      ],
    });
    (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [reminder()],
    });

    render(<HomePage />);

    await screen.findByText("Call the dentist");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /complete call the dentist/i }));

    expect(api.completeReminder).toHaveBeenCalledWith(
      "home-1",
      "reminder-1",
      reminder().home_occurrence_date,
    );
    expect(api.completeRoutine).not.toHaveBeenCalled();
    await screen.findByText(/Done/);
    // The unrelated routine stays exactly as it was — not marked done too.
    expect(screen.getByRole("button", { name: /complete feed the dog/i })).not.toBeDisabled();
  });

  it("restores the reminder and shows an error if completion fails", async () => {
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
      features: [
        { feature: "calendar", enabled: false },
        { feature: "notifications", enabled: true },
      ],
    });
    (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [reminder()] });
    (api.completeReminder as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("Could not complete that reminder."),
    );

    render(<HomePage />);

    await screen.findByText("Call the dentist");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /complete call the dentist/i }));

    expect(await screen.findByText("Could not complete that reminder.")).toBeInTheDocument();
    // Rolled back to not-completed — the check button is enabled again.
    expect(screen.getByRole("button", { name: /complete call the dentist/i })).not.toBeDisabled();
  });
});

// A Child's Home dashboard must reuse these exact same components — no
// role branching anywhere on this page — with only the underlying
// capability/permission data differing. These tests simulate a Child by
// controlling capabilities/API responses the same way a real Child
// membership would produce them, never by asserting on a role field.
describe("Home — Invite family is capability-gated, not role-gated", () => {
  it("hides Invite family when the member has no members.invite capability, even with seats available", async () => {
    activeHomeMock.mockReturnValue({
      activeHome: { id: "home-1", name: "Hales Home", capabilities: [] },
      activeHomeId: "home-1",
      homes: [{ id: "home-1", name: "Hales Home" }],
      setActiveHomeId: vi.fn(),
      loading: false,
    });
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      billing({ member_usage: { count: 1, limit: 4, over_limit: false } }),
    );

    render(<HomePage />);

    await screen.findByText("Routines & Reminders");
    expect(screen.queryByRole("link", { name: /invite family/i })).not.toBeInTheDocument();
  });

  it("shows Invite family when both seats are available and members.invite is held", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      billing({ member_usage: { count: 1, limit: 4, over_limit: false } }),
    );

    render(<HomePage />);

    expect(await screen.findByRole("link", { name: /invite family/i })).toHaveAttribute(
      "href",
      "/settings/members",
    );
  });

  it("still hides Invite family when the capability is held but the Home is at capacity", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      billing({ member_usage: { count: 4, limit: 4, over_limit: false } }),
    );

    render(<HomePage />);

    await screen.findByText("Routines & Reminders");
    expect(screen.queryByRole("link", { name: /invite family/i })).not.toBeInTheDocument();
  });
});

describe("Home — a denied member roster degrades gracefully (Child parity)", () => {
  it("still loads Coming up, Meals and Routines, with no global permission error, when /members 403s", async () => {
    enableCalendarOnly();
    (api.members as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("You do not have permission to perform that action."),
    );
    (api.homeSummary as ReturnType<typeof vi.fn>).mockResolvedValue({
      today_events: [],
      next_event: null,
    });
    const tomorrow = new Date(Date.now() + 86_400_000).toISOString();
    (api.listUpcomingEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [occurrence({ occurrence_id: "occ-tomorrow", title: "Sports day", start_at: tomorrow })],
      next_page: null,
    });

    render(<HomePage />);

    expect(await screen.findByText("Sports day")).toBeInTheDocument();
    expect(screen.getByText("Coming up")).toBeInTheDocument();
    expect(document.querySelector(".notice.error")).not.toBeInTheDocument();
  });

  it("does not populate the members list used for event avatars when denied, but does not error either", async () => {
    (api.members as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("forbidden"));

    render(<HomePage />);

    await screen.findByText("Routines & Reminders");
    expect(document.querySelector(".notice.error")).not.toBeInTheDocument();
  });
});

describe("Home — denied calendar visibility fails closed, not with a global error", () => {
  it("shows the Coming up empty state rather than a permission banner when calendar_view is denied", async () => {
    enableCalendarOnly();
    (api.homeSummary as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("You do not have permission to perform that action."),
    );
    (api.listUpcomingEvents as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("You do not have permission to perform that action."),
    );

    render(<HomePage />);

    expect(await screen.findByText("Coming up")).toBeInTheDocument();
    expect(screen.getByText("Nothing else planned yet.")).toBeInTheDocument();
    expect(document.querySelector(".notice.error")).not.toBeInTheDocument();
  });
});

describe("Home — genuine unexpected errors still surface", () => {
  it("still shows the error banner when the feature matrix itself fails unexpectedly", async () => {
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("Network error"));

    render(<HomePage />);

    expect(await screen.findByText("Network error")).toBeInTheDocument();
  });
});

describe("Home — Meals card shows for a Child once meals_view is granted", () => {
  it("renders today's meals from the same MealPlansTodayCard adults use", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(billing({ meals_enabled: true }));
    (api.mealPlanDay as ReturnType<typeof vi.fn>).mockResolvedValue({
      date: "2026-08-26",
      entries: [
        {
          id: "entry-1",
          meal_slot: "dinner",
          meal_id: "meal-1",
          meal_name: "Spaghetti",
          quick_meal_name: null,
          time: "18:00:00",
          member_ids: ["u1"],
        },
      ],
    });

    render(<HomePage />);

    expect(await screen.findByText("Meals")).toBeInTheDocument();
    expect(screen.getByText(/Spaghetti/)).toBeInTheDocument();
  });

  it("does not require any meal-plan management capability merely to view today's meals", async () => {
    // No members.invite, no other capability granted — mirrors a
    // child_restricted membership with no ChildProfile toggles enabled.
    activeHomeMock.mockReturnValue({
      activeHome: { id: "home-1", name: "Hales Home", capabilities: ["meals.view"] },
      activeHomeId: "home-1",
      homes: [{ id: "home-1", name: "Hales Home" }],
      setActiveHomeId: vi.fn(),
      loading: false,
    });
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(billing({ meals_enabled: true }));
    (api.mealPlanDay as ReturnType<typeof vi.fn>).mockResolvedValue({
      date: "2026-08-26",
      entries: [
        {
          id: "entry-1",
          meal_slot: "breakfast",
          meal_id: "meal-1",
          meal_name: "Porridge",
          quick_meal_name: null,
          time: null,
          member_ids: [],
        },
      ],
    });

    render(<HomePage />);

    expect(await screen.findByText(/Porridge/)).toBeInTheDocument();
  });
});
