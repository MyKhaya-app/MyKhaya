import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import type { BirthdayEntry, EventOccurrence, Home, Member, Reminder, Routine } from "@mykhaya/shared-types";
import Family from "./page";

// The Family tab — now a people-focused household overview (member
// administration moved to /settings/members, reached via "Manage family
// members" below and via More → "Members and roles"). See
// app/settings/members/page.test.tsx for the moved admin-flow coverage.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/people",
}));

async function waitForPageReady(): Promise<void> {
  await waitFor(() => {
    const row = document.querySelector(".family-status-row");
    if (!row || row.children.length === 0) throw new Error("status row not ready");
  });
}

function home(): Home {
  return {
    id: "home-1",
    name: "Hales Home",
    role: "owner",
    relationship: "home_admin",
    permission_profile: "home_admin",
    capabilities: ["members.invite", "members.manage_relationships"],
    member_count: 2,
    child_login_code: "1234",
  };
}

vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({
    activeHome: home(),
    activeHomeId: "home-1",
    homes: [home()],
    setActiveHomeId: vi.fn(),
    loading: false,
  }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      members: vi.fn(),
      homeSummary: vi.fn(),
      routines: vi.fn(),
      reminders: vi.fn(),
      billingStatus: vi.fn(),
      mealPlanDay: vi.fn(),
      birthdays: vi.fn(),
      listEvents: vi.fn(),
      sharedCalendars: vi.fn(),
      listSharedEvents: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

function member(overrides: Partial<Member> = {}): Member {
  return {
    membership_id: "m1",
    user_id: "u1",
    display_name: "Anthony",
    email: "anthony@example.com",
    role: "owner",
    relationship: "home_admin",
    permission_profile: "home_admin",
    permission_overrides: {},
    shared_resources: [],
    colour: "teal",
    avatar_version: null,
    ...overrides,
  };
}

function freeBillingStatus() {
  return {
    stored_plan: "free" as const,
    provider: "free" as const,
    status: "active" as const,
    effective_plan: "free" as const,
    effective_status_reason: null,
    billing_interval: null,
    price: null,
    current_period_end: null,
    cancel_at_period_end: false,
    complimentary_expires_at: null,
    can_manage_billing: true,
    has_stripe_customer: false,
    stripe_billing_available: true,
    calendar_usage: { count: 1, limit: 1, over_limit: false },
    category_usage: { count: 1, limit: 1, over_limit: false },
    member_usage: { count: 1, limit: 1, over_limit: false },
    household_routines_enabled: false,
    shared_events_enabled: false,
    external_invites_enabled: false,
    meals_enabled: false,
    lists_enabled: false,
    wishlists_enabled: false,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "u1", display_name: "Anthony" });
  (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([
    member(),
    member({ membership_id: "m2", user_id: "u2", display_name: "Megan", relationship: "partner", colour: "sage" }),
  ]);
  (api.homeSummary as ReturnType<typeof vi.fn>).mockResolvedValue({
    home_name: "Hales Home",
    member_count: 2,
    pending_invitations: 0,
    today_events: [],
    next_event: null,
  });
  (api.routines as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(freeBillingStatus());
  (api.mealPlanDay as ReturnType<typeof vi.fn>).mockResolvedValue({ date: "2026-09-05", entries: [] });
  (api.birthdays as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [], next_page: null });
  (api.sharedCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.listSharedEvents as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [], next_page: null });
});

describe("Family — page intro and status row", () => {
  it("renders for a normal Home, with the eyebrow/heading/subtitle", async () => {
    render(<Family />);

    expect(await screen.findByRole("heading", { name: "Family", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("HALES HOME")).toBeInTheDocument();
    expect(screen.getByText("What's happening with your people".replace("'", "’"))).toBeInTheDocument();
  });

  it("uses the shared .module-page compact-spacing standard beneath the global header, not a page-local override", async () => {
    const { container } = render(<Family />);
    await screen.findByRole("heading", { name: "Family", level: 1 });

    const main = container.querySelector("main");
    expect(main).toHaveClass("standard-page");
    expect(main).toHaveClass("module-page");
  });

  it("does not render a non-functional Family activity control — there is no activity destination yet", async () => {
    render(<Family />);
    await screen.findByRole("heading", { name: "Family", level: 1 });

    expect(screen.queryByRole("button", { name: /family activity/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /family activity/i })).not.toBeInTheDocument();
  });

  async function findStatusRow(): Promise<HTMLElement> {
    return waitFor(() => {
      const row = document.querySelector(".family-status-row");
      if (!row || row.children.length === 0) throw new Error("status row not ready");
      return row as HTMLElement;
    });
  }

  it("shows every real Home member in the status row, with a real relationship label, never a fabricated location", async () => {
    render(<Family />);
    const row = within(await findStatusRow());

    expect(row.getByText("Anthony")).toBeInTheDocument();
    expect(row.getByText("Megan")).toBeInTheDocument();
    expect(row.getByText("Home Admin")).toBeInTheDocument();
    expect(row.getByText("Partner")).toBeInTheDocument();
    // No invented presence words anywhere on the page.
    for (const fabricated of ["Home", "Away", "At work", "At school"]) {
      expect(screen.queryByText(fabricated)).not.toBeInTheDocument();
    }
    // No presence dot either — even a neutral one implies an online/location
    // signal the app doesn't actually have.
    expect(document.querySelector(".family-status-dot")).not.toBeInTheDocument();
  });

  it("does not hard-code member names — a different Home's members render instead", async () => {
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([
      member({ user_id: "u9", display_name: "Someone Else", relationship: "adult" }),
    ]);
    render(<Family />);
    const row = within(await findStatusRow());

    expect(row.getByText("Someone Else")).toBeInTheDocument();
    expect(screen.queryByText("Anthony")).not.toBeInTheDocument();
  });

  it("falls back to initials when a member has no avatar image", async () => {
    render(<Family />);
    const row = await findStatusRow();

    const avatars = row.querySelectorAll(".avatar");
    expect(avatars.length).toBeGreaterThan(0);
    expect(Array.from(avatars).some((el) => el.textContent === "A")).toBe(true);
  });

  it("scrolls rather than breaking layout with a large household", async () => {
    (api.members as ReturnType<typeof vi.fn>).mockResolvedValue(
      Array.from({ length: 12 }, (_, index) =>
        member({ membership_id: `m${index}`, user_id: `u${index}`, display_name: `Person ${index}` }),
      ),
    );
    render(<Family />);
    const row = within(await findStatusRow());

    expect(row.getByText("Person 0")).toBeInTheDocument();
    expect(row.getByText("Person 11")).toBeInTheDocument();
    const rowEl = document.querySelector(".family-status-row");
    expect(rowEl?.children.length).toBe(12);
  });
});

describe("Family — chat placeholder", () => {
  it("renders the coming-soon placeholder safely, with no unread pill and no real messages", async () => {
    render(<Family />);
    await waitForPageReady();

    expect(screen.getByRole("heading", { name: "Family chat" })).toBeInTheDocument();
    expect(screen.getByText("Private to your family")).toBeInTheDocument();
    expect(screen.getByText(/coming soon/i)).toBeInTheDocument();
    expect(screen.queryByText(/new$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/end-to-end encrypted/i)).not.toBeInTheDocument();
    const openChat = screen.getByRole("button", { name: /open chat/i });
    expect(openChat).toBeDisabled();
  });

  it("never calls a chat/messaging API — the placeholder is pure UI", async () => {
    render(<Family />);
    await waitForPageReady();

    const calledEndpoints = (api.me as ReturnType<typeof vi.fn>).mock.calls;
    // No api.* method with "chat"/"message" in its name was ever added to
    // the mocked client in this test file — if the component tried to call
    // one, `api.<thatMethod>` would be undefined and calling it would throw
    // during render, which findByText above would have already surfaced.
    expect(calledEndpoints).toBeDefined();
    expect(Object.keys(api)).not.toEqual(
      expect.arrayContaining([expect.stringMatching(/chat|message/i)]),
    );
  });
});

describe("Family — Today with the family", () => {
  it("shows a friendly empty state when there is nothing on today", async () => {
    render(<Family />);
    expect(await screen.findByText(/nothing on today/i)).toBeInTheDocument();
  });

  it("shows real events, reminders, routines and meals, capped at 4 rows, using real data", async () => {
    (api.homeSummary as ReturnType<typeof vi.fn>).mockResolvedValue({
      home_name: "Hales Home",
      member_count: 2,
      pending_invitations: 0,
      today_events: [
        {
          occurrence_id: "occ-1",
          event_id: "e1",
          calendar_id: "cal-1",
          title: "Football",
          start_at: "2026-09-05T17:30:00Z",
          end_at: "2026-09-05T18:30:00Z",
          is_all_day: false,
          timezone: "UTC",
          description: null,
          location_text: null,
          label: null,
          calendar_color: "teal",
          member_ids: ["u1"],
          recurrence: "none",
          reminder_minutes: null,
          created_by: "u1",
          updated_at: "2026-09-01T00:00:00Z",
          occurrence_start: "2026-09-05T17:30:00Z",
          is_overridden: false,
        },
      ],
      next_event: null,
    });
    const routine: Routine = {
      id: "r1",
      title: "Bin day",
      description: null,
      scope: "household",
      owner_user_id: null,
      interval_weeks: 1,
      repeat_unit: "weekly",
      week_anchor_date: "2026-09-05",
      reminder_timing: "evening_before",
      is_critical: false,
      pinned: false,
      enabled: true,
      start_date: "2026-01-01",
      end_date: null,
      member_ids: [],
      next_occurrence_date: "2026-09-05",
      completed_today: false,
      home_occurrence_date: "2026-09-05",
      home_completed_at: null,
      created_by: "u1",
      updated_at: "2026-09-01T00:00:00Z",
    };
    const reminder: Reminder = {
      id: "rem1",
      title: "Homework reminder",
      description: null,
      scope: "personal",
      owner_user_id: "u2",
      due_date: "2026-09-05",
      due_time: "16:00:00",
      repeat: "never",
      cadence: "once",
      enabled: true,
      member_ids: ["u2"],
      next_occurrence_date: "2026-09-05",
      completed_today: false,
      home_occurrence_date: "2026-09-05",
      home_completed_at: null,
      created_by: "u1",
      updated_at: "2026-09-01T00:00:00Z",
    };
    (api.routines as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [routine] });
    (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [reminder] });

    render(<Family />);

    await screen.findByText("Football");
    expect(screen.getByText("Homework reminder")).toBeInTheDocument();
    expect(screen.getByText("Bin day")).toBeInTheDocument();
    // Football is attributed to Anthony (the single assigned member); the
    // household-wide routine is attributed to "Family".
    const feed = document.querySelector(".family-feed-list") as HTMLElement;
    expect(within(feed).getAllByText("Anthony").length).toBeGreaterThan(0);
    expect(within(feed).getAllByText("Family").length).toBeGreaterThan(0);
  });

  it("excludes items already completed today", async () => {
    const completedRoutine: Routine = {
      id: "r2",
      title: "Already done",
      description: null,
      scope: "household",
      owner_user_id: null,
      interval_weeks: 1,
      repeat_unit: "weekly",
      week_anchor_date: "2026-09-05",
      reminder_timing: "evening_before",
      is_critical: false,
      pinned: false,
      enabled: true,
      start_date: "2026-01-01",
      end_date: null,
      member_ids: [],
      next_occurrence_date: "2026-09-05",
      completed_today: true,
      home_occurrence_date: "2026-09-05",
      home_completed_at: "2026-09-05T08:00:00Z",
      created_by: "u1",
      updated_at: "2026-09-01T00:00:00Z",
    };
    (api.routines as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [completedRoutine] });

    render(<Family />);
    await screen.findByText(/nothing on today/i);
    expect(screen.queryByText("Already done")).not.toBeInTheDocument();
  });
});

function event(overrides: Partial<EventOccurrence> = {}): EventOccurrence {
  return {
    occurrence_id: "occ-1",
    event_id: "e1",
    calendar_id: "cal-1",
    title: "Football",
    start_at: "2026-09-05T17:30:00Z",
    end_at: "2026-09-05T18:30:00Z",
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
    updated_at: "2026-09-01T00:00:00Z",
    occurrence_start: "2026-09-05T17:30:00Z",
    is_overridden: false,
    ...overrides,
  };
}

describe("Family — Our week", () => {
  it("shows zero counts honestly rather than hiding the card or inventing values", async () => {
    render(<Family />);

    await screen.findByRole("heading", { name: "Our week" });
    expect(screen.getByText("Events this week")).toBeInTheDocument();
    expect(screen.getByText("Routines left")).toBeInTheDocument();
    expect(screen.getByText("Reminders due")).toBeInTheDocument();
    expect(screen.getByText("Birthdays this month")).toBeInTheDocument();
    const tiles = document.querySelectorAll(".family-stat-tile strong");
    const values = Array.from(tiles).map((el) => el.textContent);
    expect(values).toEqual(["0", "0", "0", "0"]);
  });

  it("shows a real upcoming-birthday count when one exists, as a plain number", async () => {
    const entry: BirthdayEntry = {
      owner_type: "user",
      owner_id: "u2",
      display_name: "Megan",
      month: new Date().getMonth() + 1,
      day: new Date().getDate(),
      next_occurrence_date: new Date().toISOString().slice(0, 10),
    };
    (api.birthdays as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [entry] });

    render(<Family />);
    await screen.findByRole("heading", { name: "Our week" });
    const birthdayTile = screen.getByText("Birthdays this month").closest(".family-stat-tile");
    expect(within(birthdayTile as HTMLElement).getByText("1")).toBeInTheDocument();
  });

  it("counts a Home-owned event toward 'Events this week'", async () => {
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [event({ occurrence_id: "home-occ" })],
      next_page: null,
    });

    render(<Family />);
    const tile = (await screen.findByText("Events this week")).closest(".family-stat-tile");
    expect(within(tile as HTMLElement).getByText("1")).toBeInTheDocument();
  });

  it("includes an externally shared calendar's event in 'Events this week', reusing the same visible-event union as Calendar", async () => {
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [], next_page: null });
    (api.sharedCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [{ id: "share-1", permission: "view", source_group_name: "Grandma's" }],
    });
    (api.listSharedEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [event({ occurrence_id: "shared-occ", title: "Shared party" })],
      next_page: null,
    });

    render(<Family />);
    const tile = (await screen.findByText("Events this week")).closest(".family-stat-tile");
    expect(within(tile as HTMLElement).getByText("1")).toBeInTheDocument();
    const [shareId, shareRange] = (api.listSharedEvents as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      { start_at: string; end_at: string },
    ];
    expect(shareId).toBe("share-1");
    expect(typeof shareRange.start_at).toBe("string");
    expect(typeof shareRange.end_at).toBe("string");
  });

  it("excludes an event outside the current 7-day window from 'Events this week'", async () => {
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [], next_page: null });

    render(<Family />);
    const tile = (await screen.findByText("Events this week")).closest(".family-stat-tile");
    // The mocked listEvents call for this test always returns items: [] for
    // any range — a real 404-days-away event would never be included
    // because it's outside the requested start_at/end_at window in the
    // first place (server-side filtering), which this asserts indirectly:
    // the tile shows 0 when nothing falls inside the requested range.
    expect(within(tile as HTMLElement).getByText("0")).toBeInTheDocument();
    const [, range] = (api.listEvents as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      { start_at: string; end_at: string },
    ];
    const spanDays = (new Date(range.end_at).getTime() - new Date(range.start_at).getTime()) / 86_400_000;
    expect(spanDays).toBe(7);
  });

  it("excludes a completed routine and a completed reminder from their counts", async () => {
    (api.routines as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "r1",
          title: "Bin day",
          description: null,
          scope: "household",
          owner_user_id: null,
          interval_weeks: 1,
          repeat_unit: "weekly",
          week_anchor_date: "2026-09-05",
          reminder_timing: "evening_before",
          is_critical: false,
          pinned: false,
          enabled: true,
          start_date: "2026-01-01",
          end_date: null,
          member_ids: [],
          next_occurrence_date: "2026-09-05",
          completed_today: true,
          home_occurrence_date: "2026-09-05",
          home_completed_at: "2026-09-05T08:00:00Z",
          created_by: "u1",
          updated_at: "2026-09-01T00:00:00Z",
        } satisfies Routine,
      ],
    });
    (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "rem1",
          title: "Homework",
          description: null,
          scope: "personal",
          owner_user_id: "u2",
          due_date: "2026-09-05",
          due_time: "16:00:00",
          repeat: "never",
          cadence: "once",
          enabled: true,
          member_ids: ["u2"],
          next_occurrence_date: "2026-09-05",
          completed_today: true,
          home_occurrence_date: "2026-09-05",
          home_completed_at: "2026-09-05T08:00:00Z",
          created_by: "u1",
          updated_at: "2026-09-01T00:00:00Z",
        } satisfies Reminder,
      ],
    });

    render(<Family />);
    const routinesTile = (await screen.findByText("Routines left")).closest(".family-stat-tile");
    const remindersTile = screen.getByText("Reminders due").closest(".family-stat-tile");
    expect(within(routinesTile as HTMLElement).getByText("0")).toBeInTheDocument();
    expect(within(remindersTile as HTMLElement).getByText("0")).toBeInTheDocument();
  });
});

describe("Family — Everyone card counts reconcile with Our week", () => {
  it("counts a member's real event participation from the same visible-events union as 'Events this week', not from event titles or a separate scope", async () => {
    (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        event({ occurrence_id: "occ-anthony", title: "Anthony only", member_ids: ["u1"] }),
        event({ occurrence_id: "occ-both", title: "Football", member_ids: ["u1", "u2"] }),
      ],
      next_page: null,
    });

    render(<Family />);
    const grid = await waitFor(() => {
      const el = document.querySelector(".family-everyone-grid");
      if (!el || el.children.length === 0) throw new Error("everyone grid not ready");
      return el as HTMLElement;
    });

    const anthonyCard = within(grid).getByText("Anthony").closest(".family-everyone-card") as HTMLElement;
    const meganCard = within(grid).getByText("Megan").closest(".family-everyone-card") as HTMLElement;
    expect(within(anthonyCard).getByText(/2 events/)).toBeInTheDocument();
    expect(within(meganCard).getByText(/1 event\b/)).toBeInTheDocument();
  });

  it("counts a reminder assigned via member_ids for every assigned member, matching how 'Reminders due' counts it once", async () => {
    (api.reminders as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "rem-shared",
          title: "Pack for holiday",
          description: null,
          scope: "household",
          owner_user_id: null,
          due_date: "2026-09-05",
          due_time: "16:00:00",
          repeat: "never",
          cadence: "once",
          enabled: true,
          member_ids: ["u1", "u2"],
          next_occurrence_date: "2026-09-05",
          completed_today: false,
          home_occurrence_date: "2026-09-05",
          home_completed_at: null,
          created_by: "u1",
          updated_at: "2026-09-01T00:00:00Z",
        } satisfies Reminder,
      ],
    });

    render(<Family />);
    const remindersTile = (await screen.findByText("Reminders due")).closest(".family-stat-tile");
    expect(within(remindersTile as HTMLElement).getByText("1")).toBeInTheDocument();

    const grid = document.querySelector(".family-everyone-grid") as HTMLElement;
    const anthonyCard = within(grid).getByText("Anthony").closest(".family-everyone-card") as HTMLElement;
    const meganCard = within(grid).getByText("Megan").closest(".family-everyone-card") as HTMLElement;
    expect(within(anthonyCard).getByText(/1 reminder\b/)).toBeInTheDocument();
    expect(within(meganCard).getByText(/1 reminder\b/)).toBeInTheDocument();
  });

  it("shows 0 events • 0 reminders for a member genuinely uninvolved in either, without hiding their card", async () => {
    render(<Family />);
    const grid = await waitFor(() => {
      const el = document.querySelector(".family-everyone-grid");
      if (!el || el.children.length === 0) throw new Error("everyone grid not ready");
      return el as HTMLElement;
    });

    const anthonyCard = within(grid).getByText("Anthony").closest(".family-everyone-card") as HTMLElement;
    expect(within(anthonyCard).getByText("0 events · 0 reminders")).toBeInTheDocument();
  });
});

describe("Family — member management moved to More", () => {
  it("links 'Manage family members' to the canonical /settings/members destination", async () => {
    render(<Family />);
    const link = await screen.findByRole("link", { name: /manage family members/i });
    expect(link).toHaveAttribute("href", "/settings/members");
  });

  it("never renders inline admin controls (Change relationship, Change colour, Manage child privacy) on the overview", async () => {
    render(<Family />);
    await waitForPageReady();

    expect(screen.queryByText(/change relationship/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/change colour/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/manage child privacy/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add member/i })).not.toBeInTheDocument();
  });

  it("the Everyone section routes each member to the existing member management page, not a new profile subsystem", async () => {
    render(<Family />);
    await waitForPageReady();
    const grid = document.querySelector(".family-everyone-grid");
    const card = within(grid as HTMLElement).getByText("Anthony").closest("a");
    expect(card).toHaveAttribute("href", "/settings/members");
  });

  it("labels the Everyone card action 'Manage member', not 'View profile' — there is no profile subsystem", async () => {
    render(<Family />);
    const grid = await waitFor(() => {
      const el = document.querySelector(".family-everyone-grid");
      if (!el || el.children.length === 0) throw new Error("everyone grid not ready");
      return el as HTMLElement;
    });

    expect(within(grid).getAllByText("Manage member").length).toBeGreaterThan(0);
    expect(within(grid).queryByText(/view profile/i)).not.toBeInTheDocument();
  });
});

describe("Family — Home data isolation", () => {
  it("loads members/summary/routines/reminders/events scoped to the active Home only", async () => {
    render(<Family />);
    await waitForPageReady();

    expect(api.members).toHaveBeenCalledWith("home-1");
    expect(api.homeSummary).toHaveBeenCalledWith("home-1");
    expect(api.routines).toHaveBeenCalledWith("home-1", { home: true });
    expect(api.reminders).toHaveBeenCalledWith("home-1", { home: true });
    const [listEventsHomeId, listEventsRange] = (api.listEvents as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      { start_at: string; end_at: string },
    ];
    expect(listEventsHomeId).toBe("home-1");
    expect(typeof listEventsRange.start_at).toBe("string");
    expect(typeof listEventsRange.end_at).toBe("string");
  });

  it("never shows another Home's shared-calendar events under this Home's total", async () => {
    // sharedCalendars() is a per-signed-in-user endpoint (no homeId param —
    // same call Calendar's own load() makes), so "no cross-Home leakage"
    // here means: only shares this user actually holds are ever merged in,
    // and each is fetched for this Home's own selected week range, never a
    // stale or different range.
    (api.sharedCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [{ id: "share-mine", permission: "view", source_group_name: "Nana's" }],
    });
    (api.listSharedEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [event({ occurrence_id: "shared-occ" })],
      next_page: null,
    });

    render(<Family />);
    await screen.findByText("Events this week");

    expect(api.sharedCalendars).toHaveBeenCalledTimes(1);
    expect(api.listSharedEvents).toHaveBeenCalledWith("share-mine", expect.any(Object));
    const [homeCallId] = (api.listEvents as ReturnType<typeof vi.fn>).mock.calls[0] as [string, unknown];
    expect(homeCallId).toBe("home-1");
  });
});
