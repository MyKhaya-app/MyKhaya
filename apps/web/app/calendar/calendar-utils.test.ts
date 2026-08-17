import { describe, expect, it } from "vitest";
import type { EventOccurrence, Member } from "@mykhaya/shared-types";
import {
  agendaRange,
  emptyStateMessage,
  eventsForDay,
  filterVisibleEvents,
  groupEventsByDay,
  monthCells,
  monthRange,
  resolveMemberFilter,
} from "./calendar-utils";

function event(overrides: Partial<EventOccurrence>): EventOccurrence {
  return {
    occurrence_id: crypto.randomUUID(),
    event_id: crypto.randomUUID(),
    calendar_id: crypto.randomUUID(),
    title: "Event",
    start_at: "2026-07-31T10:00:00+00:00",
    end_at: "2026-07-31T11:00:00+00:00",
    is_all_day: false,
    timezone: "Europe/London",
    description: null,
    location_text: null,
    label: null,
    member_ids: [],
    recurrence: "none",
    reminder_minutes: null,
    created_by: crypto.randomUUID(),
    updated_at: "2026-07-01T00:00:00+00:00",
    ...overrides,
  };
}

function member(overrides: Partial<Member>): Member {
  return {
    membership_id: crypto.randomUUID(),
    user_id: crypto.randomUUID(),
    display_name: "Member",
    email: null,
    role: "member",
    relationship: "adult",
    permission_profile: "standard",
    permission_overrides: {},
    shared_resources: [],
    colour: null,
    avatar_version: null,
    ...overrides,
  } as Member;
}

describe("Calendar presentation", () => {
  it("builds a stable six-week Monday-first month", () => {
    const cells = monthCells(new Date("2026-08-15T00:00:00Z"));
    expect(cells).toHaveLength(42);
    expect(cells[0]?.getUTCDay()).toBe(1);
    expect(
      cells.some((day) => day.toISOString().startsWith("2026-08-01")),
    ).toBe(true);
  });

  it("orders all-day events before timed events", () => {
    const rows = eventsForDay(
      [
        event({ title: "Later", start_at: "2026-07-31T15:00:00+00:00" }),
        event({
          title: "All day",
          is_all_day: true,
          start_at: "2026-07-31T00:00:00+00:00",
          end_at: "2026-08-01T00:00:00+00:00",
        }),
        event({ title: "Earlier", start_at: "2026-07-31T09:00:00+00:00" }),
      ],
      "2026-07-31",
    );
    expect(rows.map((row) => row.title)).toEqual([
      "All day",
      "Earlier",
      "Later",
    ]);
  });

  it("includes multi-day events on every covered date", () => {
    const multi = event({
      start_at: "2026-07-30T12:00:00+00:00",
      end_at: "2026-08-01T12:00:00+00:00",
    });
    expect(eventsForDay([multi], "2026-07-31")).toEqual([multi]);
  });
});

describe("Schedule (agenda) view date range", () => {
  // Regression test for: Month view showed a member's event but switching to
  // Schedule for the same browsed period showed nothing. Root cause was that
  // agendaRange started at `base`'s own day and only looked forward, so any
  // event still within the browsed month but before `base` (e.g. "today")
  // silently fell out of the Schedule fetch window even though Month view
  // (which always spans the full 1st-to-last day of the month) still showed it.
  it("covers every date Month view shows for the same browsed period", () => {
    // "Today"/focusDate is late in the month; the event under test sits
    // earlier in the same month - Month view shows it (full month range),
    // Schedule must show it too when switching views without moving focusDate.
    const focusDate = new Date("2026-08-17T09:00:00Z");
    const monthWindow = monthRange(focusDate);
    const scheduleWindow = agendaRange(focusDate);

    expect(scheduleWindow.start.getTime()).toBeLessThanOrEqual(
      monthWindow.start.getTime(),
    );
    expect(scheduleWindow.end.getTime()).toBeGreaterThanOrEqual(
      monthWindow.end.getTime(),
    );

    const eyeAppointment = event({
      title: "Eye Appointment",
      start_at: "2026-08-15T09:00:00+00:00",
      end_at: "2026-08-15T09:30:00+00:00",
      member_ids: ["megan"],
    });

    const inMonth =
      new Date(eyeAppointment.start_at) >= monthWindow.start &&
      new Date(eyeAppointment.start_at) < monthWindow.end;
    const inSchedule =
      new Date(eyeAppointment.start_at) >= scheduleWindow.start &&
      new Date(eyeAppointment.start_at) < scheduleWindow.end;

    expect(inMonth).toBe(true);
    expect(inSchedule).toBe(true);

    const byDay = groupEventsByDay([eyeAppointment]);
    expect(byDay.get("2026-08-15")?.map((row) => row.title)).toEqual([
      "Eye Appointment",
    ]);
  });

  it("anchors to the start of the browsed month regardless of the day within it", () => {
    const earlyInMonth = agendaRange(new Date("2026-08-02T00:00:00Z"));
    const lateInMonth = agendaRange(new Date("2026-08-30T00:00:00Z"));
    expect(earlyInMonth.start.toISOString()).toBe(
      lateInMonth.start.toISOString(),
    );
    expect(earlyInMonth.start.toISOString().slice(0, 10)).toBe("2026-08-01");
  });

  it("still looks 45 days ahead of the start of the browsed month", () => {
    const { start, end } = agendaRange(new Date("2026-08-17T00:00:00Z"));
    const days = Math.round((end.getTime() - start.getTime()) / 86_400_000);
    expect(days).toBe(45);
  });

  it("does not require the selected member to be the event creator to appear on its date", () => {
    const megansEvent = event({
      title: "Eye Appointment",
      start_at: "2026-08-15T09:00:00+00:00",
      end_at: "2026-08-15T09:30:00+00:00",
      created_by: "member-a-id",
      member_ids: ["member-b-id"],
    });
    const rows = eventsForDay([megansEvent], "2026-08-15");
    expect(rows).toEqual([megansEvent]);
    expect(rows[0]?.member_ids).toContain("member-b-id");
  });

  it("excludes an event that does not fall on the requested day", () => {
    const notAssignedToday = event({
      start_at: "2026-08-20T09:00:00+00:00",
      end_at: "2026-08-20T09:30:00+00:00",
      member_ids: ["member-b-id"],
    });
    expect(eventsForDay([notAssignedToday], "2026-08-15")).toEqual([]);
  });
});

describe("Category (label) filter", () => {
  // The category selector (moved into the search/filter flyout) filters by
  // CalendarEventLabel (a household-defined category, e.g. "Family calendar",
  // "Work", or a personal label a household names after someone, such as
  // "Megan") - it is NOT a member/participant filter, even when its name
  // happens to match a person's name. Both Month and Schedule must apply
  // whichever category is selected identically, from the same filtered set.
  const eyeAppointment = event({
    title: "Eye Appointment",
    start_at: "2026-08-15T09:00:00+00:00",
    end_at: "2026-08-15T09:30:00+00:00",
    label: {
      id: "label-megan",
      name: "Megan",
      color: "teal",
      commercial_access: "normal",
      is_active: true,
      sort_order: 0,
    },
    member_ids: ["megan-user-id"],
  });
  const otherHouseholdEvent = event({
    title: "Bin collection",
    start_at: "2026-08-15T07:00:00+00:00",
    end_at: "2026-08-15T07:15:00+00:00",
    label: {
      id: "label-family",
      name: "Family calendar",
      color: "amber",
      commercial_access: "normal",
      is_active: true,
      sort_order: 0,
    },
    member_ids: [],
  });
  const allEvents = [eyeAppointment, otherHouseholdEvent];

  it("Month's per-day list and Schedule's grouped list agree for the same category selection", () => {
    const visible = filterVisibleEvents(allEvents, "", "label-megan", "");
    expect(visible).toEqual([eyeAppointment]);

    // Month view derives its per-day list via eventsForDay(visibleEvents, day);
    // Schedule derives byDay via groupEventsByDay(visibleEvents). Both must be
    // built from the same filtered set and agree on which events appear.
    const monthDayList = eventsForDay(visible, "2026-08-15");
    const scheduleByDay = groupEventsByDay(visible);

    expect(monthDayList.map((row) => row.title)).toEqual(["Eye Appointment"]);
    expect(scheduleByDay.get("2026-08-15")?.map((row) => row.title)).toEqual([
      "Eye Appointment",
    ]);
  });

  it("excludes events under a different category from both Month and Schedule", () => {
    const visible = filterVisibleEvents(allEvents, "", "label-megan", "");
    expect(visible.some((row) => row.title === "Bin collection")).toBe(false);
  });

  it("shows every event when no category is selected (the default/all state)", () => {
    const visible = filterVisibleEvents(allEvents, "", "", "");
    expect(visible).toHaveLength(2);
  });

  it("combines category selection with an active search query", () => {
    const visible = filterVisibleEvents(allEvents, "", "label-megan", "eye");
    expect(visible.map((row) => row.title)).toEqual(["Eye Appointment"]);
    expect(filterVisibleEvents(allEvents, "", "label-megan", "bin")).toEqual(
      [],
    );
  });
});

describe("Household member filter", () => {
  // The primary selector beside Month/Week/Day/Schedule filters by the
  // canonical event-membership relationship (EventOccurrence.member_ids,
  // backed by CalendarEventMember) - "who is this event assigned to", never
  // by who created it, and never by a label/category of the same name.
  const anthony = member({ user_id: "anthony-id", display_name: "Anthony" });
  const megan = member({ user_id: "megan-id", display_name: "Megan" });
  const alyssa = member({ user_id: "alyssa-id", display_name: "Alyssa" });
  const roster = [anthony, megan, alyssa];

  const eyeAppointment = event({
    title: "Eye Appointment",
    start_at: "2026-08-15T09:00:00+00:00",
    end_at: "2026-08-15T09:30:00+00:00",
    created_by: anthony.user_id,
    member_ids: [megan.user_id],
    label: {
      id: "label-appointment",
      name: "Appointment",
      color: "teal",
      commercial_access: "normal",
      is_active: true,
      sort_order: 0,
    },
  });
  const familyDinner = event({
    title: "Family Dinner",
    start_at: "2026-08-16T18:00:00+00:00",
    end_at: "2026-08-16T19:00:00+00:00",
    created_by: anthony.user_id,
    member_ids: [anthony.user_id, megan.user_id, alyssa.user_id],
    label: {
      id: "label-family",
      name: "Family",
      color: "amber",
      commercial_access: "normal",
      is_active: true,
      sort_order: 0,
    },
  });
  const anthonysWorkMeeting = event({
    title: "Work meeting",
    start_at: "2026-08-17T09:00:00+00:00",
    end_at: "2026-08-17T10:00:00+00:00",
    created_by: anthony.user_id,
    member_ids: [anthony.user_id],
    label: {
      id: "label-work",
      name: "Work",
      color: "slate",
      commercial_access: "normal",
      is_active: true,
      sort_order: 0,
    },
  });
  const allEvents = [eyeAppointment, familyDinner, anthonysWorkMeeting];

  it("1. Everyone shows events for multiple members", () => {
    const visible = filterVisibleEvents(allEvents, "", "", "");
    expect(visible.map((row) => row.title)).toEqual([
      "Eye Appointment",
      "Family Dinner",
      "Work meeting",
    ]);
  });

  it("2. selecting Megan includes an event assigned to her", () => {
    const visible = filterVisibleEvents(allEvents, megan.user_id, "", "");
    expect(visible.map((row) => row.title)).toContain("Eye Appointment");
  });

  it("3. creator identity is irrelevant — Anthony created it, only Megan is assigned", () => {
    // eyeAppointment.created_by === anthony.user_id, but member_ids is
    // [megan.user_id] only. The filter must key off member_ids, not created_by.
    const visible = filterVisibleEvents(allEvents, megan.user_id, "", "");
    expect(visible).toContainEqual(eyeAppointment);
    expect(eyeAppointment.created_by).toBe(anthony.user_id);
  });

  it("4. selecting a member the event isn't assigned to excludes it", () => {
    // The Eye Appointment is assigned only to Megan (not Anthony), even
    // though Anthony created it — Anthony's own filtered view must not
    // include it.
    const visible = filterVisibleEvents(allEvents, anthony.user_id, "", "");
    expect(visible.map((row) => row.title)).not.toContain("Eye Appointment");
  });

  it("5. an event with multiple participants appears for each of them and for Everyone", () => {
    for (const selected of ["", anthony.user_id, megan.user_id, alyssa.user_id]) {
      const visible = filterVisibleEvents(allEvents, selected, "", "");
      expect(visible.map((row) => row.title)).toContain("Family Dinner");
    }
  });

  it("6. member + category compose: Megan + Appointment includes it, Megan + Work excludes it", () => {
    const meganAppointments = filterVisibleEvents(
      allEvents,
      megan.user_id,
      "label-appointment",
      "",
    );
    expect(meganAppointments.map((row) => row.title)).toEqual([
      "Eye Appointment",
    ]);

    const meganWork = filterVisibleEvents(
      allEvents,
      megan.user_id,
      "label-work",
      "",
    );
    expect(meganWork).toEqual([]);
  });

  it("7. member + category + search compose together", () => {
    const visible = filterVisibleEvents(
      allEvents,
      megan.user_id,
      "label-appointment",
      "eye",
    );
    expect(visible.map((row) => row.title)).toEqual(["Eye Appointment"]);
    expect(
      filterVisibleEvents(allEvents, megan.user_id, "label-appointment", "dinner"),
    ).toEqual([]);
  });

  it("8. Month and Schedule consume the same filtered set for a given member/date", () => {
    const visible = filterVisibleEvents(allEvents, megan.user_id, "", "");
    const monthDayList = eventsForDay(visible, "2026-08-15");
    const scheduleByDay = groupEventsByDay(visible);
    expect(monthDayList.map((row) => row.title)).toEqual(["Eye Appointment"]);
    expect(scheduleByDay.get("2026-08-15")?.map((row) => row.title)).toEqual([
      "Eye Appointment",
    ]);
  });

  it("12. a recurring occurrence assigned to Megan is matched the same as a one-off event", () => {
    // Occurrence expansion happens server-side (calendar_occurrences.py); by
    // the time an occurrence reaches the frontend it is a plain
    // EventOccurrence with member_ids already attached, so the member filter
    // does not need — and must not have — any recurrence-specific branch.
    const recurringOccurrence = event({
      title: "Weekly swimming",
      start_at: "2026-08-18T16:00:00+00:00",
      end_at: "2026-08-18T17:00:00+00:00",
      recurrence: "weekly",
      member_ids: [megan.user_id],
    });
    const visible = filterVisibleEvents(
      [...allEvents, recurringOccurrence],
      megan.user_id,
      "",
      "",
    );
    expect(visible.map((row) => row.title)).toContain("Weekly swimming");
  });

  describe("10. resolveMemberFilter — invalid/stale persisted member falls back to Everyone", () => {
    it("keeps a persisted id that is still a real member of this Home", () => {
      expect(resolveMemberFilter(roster, megan.user_id)).toBe(megan.user_id);
    });

    it("falls back to Everyone when the persisted member left/was deleted", () => {
      expect(resolveMemberFilter(roster, "someone-who-left-id")).toBe("");
    });

    it("passes through an unfiltered (Everyone) selection unchanged", () => {
      expect(resolveMemberFilter(roster, "")).toBe("");
    });
  });

  describe("11. resolveMemberFilter — Home switching never reuses another Home's member id", () => {
    it("a member id valid in Home A is not valid against Home B's roster", () => {
      const homeBRoster = [
        member({ user_id: "home-b-member-1", display_name: "Someone Else" }),
      ];
      // megan.user_id belongs to Home A's roster, not Home B's.
      expect(resolveMemberFilter(homeBRoster, megan.user_id)).toBe("");
    });

    it("resolves correctly once the roster actually belongs to the same Home", () => {
      expect(resolveMemberFilter(roster, megan.user_id)).toBe(megan.user_id);
    });
  });
});

describe("emptyStateMessage", () => {
  it("gives a plain message with no filters applied", () => {
    expect(emptyStateMessage(null, null)).toBe("No upcoming events.");
  });

  it("names the selected member", () => {
    expect(emptyStateMessage("Megan", null)).toBe(
      "No upcoming events for Megan.",
    );
  });

  it("names the selected category", () => {
    expect(emptyStateMessage(null, "Appointment")).toBe(
      "No upcoming events in Appointment.",
    );
  });

  it("combines member and category", () => {
    expect(emptyStateMessage("Megan", "Appointment")).toBe(
      "No upcoming events for Megan in Appointment.",
    );
  });
});
