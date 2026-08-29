import { describe, expect, it } from "vitest";
import type { EventOccurrence, EventPayload, Member } from "@mykhaya/shared-types";
import {
  agendaRange,
  applyAllDayToggle,
  canDeleteEvent,
  canDeleteSharedEvent,
  canEditEvent,
  canEditSharedEvent,
  computeInitialWhen,
  DEFAULT_EVENT_DURATION_MINUTES,
  DEFAULT_EVENT_END_TIME,
  DEFAULT_EVENT_START_TIME,
  emptyStateMessage,
  eventDateBounds,
  eventsForDay,
  filterByVisibleCalendars,
  filterVisibleEvents,
  groupEventsByDay,
  isCalendarVisible,
  isEventStillUpcoming,
  monthCells,
  monthRange,
  parseLocalInputValue,
  resolveMemberFilter,
  shiftEndWithStart,
  toEventUpdatePayload,
  toSharedEventPayload,
  toSharedEventUpdatePayload,
  utcToZonedInputValue,
  zonedDateKey,
  zonedTimeToUtc,
  zonedToday,
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
    calendar_color: "teal",
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
  describe("isEventStillUpcoming — Home 'Coming up' eligibility", () => {
    // 08:48 UTC on 2026-08-29 — matches the reported bug's exact scenario.
    const now = new Date("2026-08-29T08:48:00Z");

    it("excludes an event earlier today that has already finished", () => {
      expect(
        isEventStillUpcoming(
          event({ start_at: "2026-08-29T07:00:00Z", end_at: "2026-08-29T07:45:00Z" }),
          now,
        ),
      ).toBe(false);
    });

    it("includes an event later today", () => {
      expect(
        isEventStillUpcoming(
          event({ start_at: "2026-08-29T10:00:00Z", end_at: "2026-08-29T10:30:00Z" }),
          now,
        ),
      ).toBe(true);
      expect(
        isEventStillUpcoming(
          event({ start_at: "2026-08-29T11:20:00Z", end_at: "2026-08-29T12:00:00Z" }),
          now,
        ),
      ).toBe(true);
    });

    it("includes an event currently in progress (started before now, ends after it)", () => {
      expect(
        isEventStillUpcoming(
          event({ start_at: "2026-08-29T08:00:00Z", end_at: "2026-08-29T09:00:00Z" }),
          now,
        ),
      ).toBe(true);
    });

    it("includes an all-day event covering today", () => {
      expect(
        isEventStillUpcoming(
          event({
            is_all_day: true,
            start_at: "2026-08-29T00:00:00+00:00",
            end_at: "2026-08-30T00:00:00+00:00",
          }),
          now,
        ),
      ).toBe(true);
    });

    it("excludes an all-day event that covered a previous day only", () => {
      expect(
        isEventStillUpcoming(
          event({
            is_all_day: true,
            start_at: "2026-08-28T00:00:00+00:00",
            end_at: "2026-08-29T00:00:00+00:00",
          }),
          now,
        ),
      ).toBe(false);
    });

    it("includes a multi-day event currently in progress", () => {
      expect(
        isEventStillUpcoming(
          event({ start_at: "2026-08-28T10:00:00Z", end_at: "2026-08-31T10:00:00Z" }),
          now,
        ),
      ).toBe(true);
    });

    it("has no upper bound — an event many months away still qualifies", () => {
      expect(
        isEventStillUpcoming(
          event({ start_at: "2027-02-21T10:00:00Z", end_at: "2027-02-21T11:00:00Z" }),
          now,
        ),
      ).toBe(true);
    });

    it("handles the midnight boundary correctly regardless of local calendar date", () => {
      // 23:50 on New Year's Eve UTC — an event ending 20 minutes later
      // crosses into the next UTC calendar date but is still in progress now.
      const lateNow = new Date("2026-12-31T23:50:00Z");
      expect(
        isEventStillUpcoming(
          event({ start_at: "2026-12-31T23:30:00Z", end_at: "2027-01-01T00:10:00Z" }),
          lateNow,
        ),
      ).toBe(true);
      // An event that finished 5 minutes before midnight is excluded, even
      // though "now" and the event share no calendar date confusion here —
      // this is exactly the date-vs-instant distinction the old
      // date-key-based rule got wrong.
      expect(
        isEventStillUpcoming(
          event({ start_at: "2026-12-31T22:30:00Z", end_at: "2026-12-31T23:45:00Z" }),
          lateNow,
        ),
      ).toBe(false);
    });
  });
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
      "Europe/London",
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
    expect(eventsForDay([multi], "2026-07-31", "Europe/London")).toEqual([multi]);
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

    const byDay = groupEventsByDay([eyeAppointment], "Europe/London");
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
    const rows = eventsForDay([megansEvent], "2026-08-15", "Europe/London");
    expect(rows).toEqual([megansEvent]);
    expect(rows[0]?.member_ids).toContain("member-b-id");
  });

  it("excludes an event that does not fall on the requested day", () => {
    const notAssignedToday = event({
      start_at: "2026-08-20T09:00:00+00:00",
      end_at: "2026-08-20T09:30:00+00:00",
      member_ids: ["member-b-id"],
    });
    expect(eventsForDay([notAssignedToday], "2026-08-15", "Europe/London")).toEqual([]);
  });
});

describe("Category (label) filter", () => {
  // The category selector (moved into the search/filter flyout) filters by
  // CalendarEventLabel (a household-defined category, e.g. "Chores",
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
      id: "label-chores",
      name: "Chores",
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
    // Schedule derives byDay via groupEventsByDay(visibleEvents, "Europe/London"). Both must be
    // built from the same filtered set and agree on which events appear.
    const monthDayList = eventsForDay(visible, "2026-08-15", "Europe/London");
    const scheduleByDay = groupEventsByDay(visible, "Europe/London");

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
    const monthDayList = eventsForDay(visible, "2026-08-15", "Europe/London");
    const scheduleByDay = groupEventsByDay(visible, "Europe/London");
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

describe("Timezone-correct instant <-> wall-clock conversion", () => {
  // Regression coverage for the root cause of the 1-hour bug: the app must
  // interpret/display event times in the relevant Home/event timezone, never
  // the server's or browser's own timezone. `zonedTimeToUtc` and
  // `utcToZonedInputValue` are the only two functions in the app that do
  // this conversion — every other display/picker function goes through them.

  it("basic round trip: 14 Aug 2026 09:30 Europe/London (BST, UTC+1) stores as 08:30Z", () => {
    const instant = zonedTimeToUtc(2026, 8, 14, 9, 30, "Europe/London");
    expect(instant.toISOString()).toBe("2026-08-14T08:30:00.000Z");
  });

  it("displays that same instant back as 09:30, never 08:30", () => {
    const instant = new Date("2026-08-14T08:30:00.000Z");
    expect(utcToZonedInputValue(instant, "Europe/London")).toBe(
      "2026-08-14T09:30",
    );
  });

  it("is correct regardless of which server/process timezone is assumed", () => {
    // These functions never call `new Date(string)` (browser/process-local
    // parsing) or read any ambient/process timezone — every conversion goes
    // through Intl.DateTimeFormat with an explicit `timeZone`, so the same
    // instant produces the same local wall-clock digits no matter what
    // timezone the Node process (or CI runner) happens to be started in.
    // Exercise a spread of unrelated timezones against the same instant to
    // prove the result depends only on the explicit `timeZone` argument.
    const instant = new Date("2026-08-14T08:30:00.000Z");
    expect(utcToZonedInputValue(instant, "Europe/London")).toBe(
      "2026-08-14T09:30",
    );
    expect(utcToZonedInputValue(instant, "UTC")).toBe("2026-08-14T08:30");
    expect(utcToZonedInputValue(instant, "America/New_York")).toBe(
      "2026-08-14T04:30",
    );
    expect(utcToZonedInputValue(instant, "Pacific/Auckland")).toBe(
      "2026-08-14T20:30",
    );
  });

  it("round-trips through parseLocalInputValue the same way the picker does", () => {
    const value = utcToZonedInputValue(
      new Date("2026-08-14T08:30:00.000Z"),
      "Europe/London",
    );
    const parts = parseLocalInputValue(value);
    const restored = zonedTimeToUtc(
      parts.year,
      parts.month,
      parts.day,
      parts.hour,
      parts.minute,
      "Europe/London",
    );
    expect(restored.toISOString()).toBe("2026-08-14T08:30:00.000Z");
  });

  it("winter (GMT, UTC+0): 14 Feb 2026 09:30 Europe/London stores as 09:30Z", () => {
    const instant = zonedTimeToUtc(2026, 2, 14, 9, 30, "Europe/London");
    expect(instant.toISOString()).toBe("2026-02-14T09:30:00.000Z");
  });
});

describe("DST correctness (Europe/London)", () => {
  // UK 2026 transitions: clocks go forward 01:00 -> 02:00 on Sun 29 Mar
  // 2026 (GMT -> BST), and back 02:00 -> 01:00 on Sun 25 Oct 2026 (BST ->
  // GMT). Real IANA data via the platform's Intl implementation, not
  // hand-rolled offset math.

  it("just before the spring-forward transition is still GMT (UTC+0)", () => {
    const instant = zonedTimeToUtc(2026, 3, 29, 0, 30, "Europe/London");
    expect(instant.toISOString()).toBe("2026-03-29T00:30:00.000Z");
  });

  it("just after the spring-forward transition is BST (UTC+1)", () => {
    const instant = zonedTimeToUtc(2026, 3, 29, 3, 0, "Europe/London");
    expect(instant.toISOString()).toBe("2026-03-29T02:00:00.000Z");
    expect(utcToZonedInputValue(instant, "Europe/London")).toBe(
      "2026-03-29T03:00",
    );
  });

  it("the nonexistent 01:30 spring-forward local time resolves deterministically, not corrupted", () => {
    // 01:00-02:00 local doesn't exist on 29 Mar 2026 (clocks skip straight
    // from 01:00 to 02:00) — the platform's Intl data resolves this
    // consistently rather than throwing or producing NaN.
    const instant = zonedTimeToUtc(2026, 3, 29, 1, 30, "Europe/London");
    expect(Number.isNaN(instant.getTime())).toBe(false);
  });

  it("just before the autumn-back transition is still BST (UTC+1)", () => {
    const instant = zonedTimeToUtc(2026, 10, 25, 0, 30, "Europe/London");
    expect(instant.toISOString()).toBe("2026-10-24T23:30:00.000Z");
  });

  it("just after the autumn-back transition is GMT (UTC+0)", () => {
    const instant = zonedTimeToUtc(2026, 10, 25, 3, 0, "Europe/London");
    expect(instant.toISOString()).toBe("2026-10-25T03:00:00.000Z");
    expect(utcToZonedInputValue(instant, "Europe/London")).toBe(
      "2026-10-25T03:00",
    );
  });

  it("the ambiguous repeated 01:30 autumn-back local time resolves deterministically, not corrupted", () => {
    const instant = zonedTimeToUtc(2026, 10, 25, 1, 30, "Europe/London");
    expect(Number.isNaN(instant.getTime())).toBe(false);
  });

  it("a 09:30-local recurring event's wall-clock time reads back as 09:30 on both sides of a DST transition", () => {
    // Same intended local time, two different UTC instants either side of
    // the spring transition — the *server-side* occurrence expansion
    // (calendar_occurrences.py, tested separately in
    // test_weekly_recurrence_survives_dst_transition) is what keeps the
    // stored UTC instant correct per-occurrence; this proves the
    // *frontend display* layer reads whatever correct instant it's given
    // back out as the same local wall-clock time, regardless of DST.
    const beforeTransition = zonedTimeToUtc(2026, 3, 22, 9, 30, "Europe/London");
    const afterTransition = zonedTimeToUtc(2026, 4, 5, 9, 30, "Europe/London");
    expect(utcToZonedInputValue(beforeTransition, "Europe/London").endsWith("09:30")).toBe(true);
    expect(utcToZonedInputValue(afterTransition, "Europe/London").endsWith("09:30")).toBe(true);
    // The underlying UTC instants genuinely differ by exactly one hour less
    // than 14 raw days, because of the offset change — proving this isn't
    // passing by coincidence (e.g. both accidentally landing on the same
    // offset).
    const rawDiffMs = afterTransition.getTime() - beforeTransition.getTime();
    const fourteenDaysMs = 14 * 24 * 60 * 60 * 1000;
    expect(rawDiffMs).toBe(fourteenDaysMs - 60 * 60 * 1000);
  });
});

describe("Start/End picker duration behaviour", () => {
  it("defaults a new event to a 1-hour duration", () => {
    expect(DEFAULT_EVENT_DURATION_MINUTES).toBe(60);
  });

  it("preserves the default 1-hour duration when Start moves", () => {
    const previousStart = new Date("2026-08-14T07:30:00.000Z"); // 08:30 BST
    const previousEnd = new Date("2026-08-14T08:30:00.000Z"); // 09:30 BST
    const nextStart = new Date("2026-08-14T09:00:00.000Z"); // 10:00 BST
    const nextEnd = shiftEndWithStart(previousStart, previousEnd, nextStart);
    expect(nextEnd.toISOString()).toBe("2026-08-14T10:00:00.000Z"); // 11:00 BST
  });

  it("preserves a custom (non-default) duration when Start moves", () => {
    const previousStart = new Date("2026-08-14T07:30:00.000Z"); // 08:30 BST
    const previousEnd = new Date("2026-08-14T08:00:00.000Z"); // 09:00 BST (30 min)
    const nextStart = new Date("2026-08-14T09:00:00.000Z"); // 10:00 BST
    const nextEnd = shiftEndWithStart(previousStart, previousEnd, nextStart);
    expect(nextEnd.toISOString()).toBe("2026-08-14T09:30:00.000Z"); // 10:30 BST
  });

  it("never produces an End at or before the new Start, even from a corrupt zero/negative previous duration", () => {
    const previousStart = new Date("2026-08-14T08:00:00.000Z");
    const previousEnd = new Date("2026-08-14T08:00:00.000Z"); // zero duration
    const nextStart = new Date("2026-08-14T09:00:00.000Z");
    const nextEnd = shiftEndWithStart(previousStart, previousEnd, nextStart);
    expect(nextEnd.getTime()).toBeGreaterThan(nextStart.getTime());
    expect(nextEnd.getTime() - nextStart.getTime()).toBe(
      DEFAULT_EVENT_DURATION_MINUTES * 60_000,
    );
  });
});

describe("All-day events are pure calendar dates, immune to timezone conversion", () => {
  function allDayEvent(overrides: Partial<EventOccurrence> = {}): EventOccurrence {
    return {
      occurrence_id: crypto.randomUUID(),
      event_id: crypto.randomUUID(),
      calendar_id: crypto.randomUUID(),
      title: "Sports Day",
      is_all_day: true,
      start_at: "2026-08-14T00:00:00+00:00",
      end_at: "2026-08-15T00:00:00+00:00", // exclusive end, per backend contract
      timezone: "Europe/London",
      description: null,
      location_text: null,
      label: null,
      calendar_color: "teal",
      member_ids: [],
      recurrence: "none",
      reminder_minutes: null,
      created_by: crypto.randomUUID(),
      updated_at: "2026-07-01T00:00:00+00:00",
      ...overrides,
    };
  }

  it("stays on 14 Aug regardless of which timezone the calendar is viewed in", () => {
    for (const timeZone of ["UTC", "Europe/London", "America/New_York", "Pacific/Auckland"]) {
      const { startKey, endKey } = eventDateBounds(allDayEvent(), timeZone);
      expect(startKey).toBe("2026-08-14");
      expect(endKey).toBe("2026-08-14");
    }
  });

  it("a multi-day all-day event covers every date in between, in any timezone", () => {
    const multiDay = allDayEvent({ end_at: "2026-08-17T00:00:00+00:00" }); // 14-16 Aug inclusive
    for (const timeZone of ["UTC", "America/New_York"]) {
      const { startKey, endKey } = eventDateBounds(multiDay, timeZone);
      expect(startKey).toBe("2026-08-14");
      expect(endKey).toBe("2026-08-16");
    }
  });
});

describe("Overnight / multi-day timed events", () => {
  it("an overnight event (23:00 -> 01:00 next day) is a valid range spanning two calendar dates", () => {
    const start = zonedTimeToUtc(2026, 8, 14, 23, 0, "Europe/London");
    const end = zonedTimeToUtc(2026, 8, 15, 1, 0, "Europe/London");
    expect(end.getTime()).toBeGreaterThan(start.getTime());
    const overnight: EventOccurrence = {
      occurrence_id: crypto.randomUUID(),
      event_id: crypto.randomUUID(),
      calendar_id: crypto.randomUUID(),
      title: "Overnight flight",
      is_all_day: false,
      start_at: start.toISOString(),
      end_at: end.toISOString(),
      timezone: "Europe/London",
      description: null,
      location_text: null,
      label: null,
      calendar_color: "teal",
      member_ids: [],
      recurrence: "none",
      reminder_minutes: null,
      created_by: crypto.randomUUID(),
      updated_at: "2026-07-01T00:00:00+00:00",
    };
    const { startKey, endKey } = eventDateBounds(overnight, "Europe/London");
    expect(startKey).toBe("2026-08-14");
    expect(endKey).toBe("2026-08-15");
  });
});

describe("zonedToday / zonedDateKey — timezone-correct 'today', never the server's", () => {
  it("zonedDateKey reads the calendar date an instant falls on in a given timezone", () => {
    // 23:30 on 14 Aug UTC is already 15 Aug in a positive-offset timezone
    // ahead of UTC at that moment, and still 14 Aug for one behind it.
    const instant = new Date("2026-08-14T23:30:00.000Z");
    expect(zonedDateKey(instant, "UTC")).toBe("2026-08-14");
    expect(zonedDateKey(instant, "Pacific/Auckland")).toBe("2026-08-15");
    expect(zonedDateKey(instant, "America/New_York")).toBe("2026-08-14");
  });

  it("zonedToday returns a UTC-midnight-anchored placeholder for the given timezone's current date", () => {
    const today = zonedToday("Europe/London");
    expect(today.getUTCHours()).toBe(0);
    expect(today.getUTCMinutes()).toBe(0);
    expect(zonedDateKey(new Date(), "Europe/London")).toBe(
      today.toISOString().slice(0, 10),
    );
  });
});

describe("All day -> timed conversion never derives a clock value from the all-day boundary", () => {
  // Regression coverage for: an all-day event's UTC-midnight boundary,
  // reinterpreted through a real IANA timezone, produces a technically-
  // explicable but meaningless clock value (00:00Z -> "01:00" during BST).
  // Timed events represent instants with timezone semantics; all-day events
  // represent calendar-date ranges. Converting from all-day to timed must
  // establish/restore a meaningful wall-clock time, never reinterpret the
  // all-day boundary as one.
  function persistedAllDayEvent(
    overrides: Partial<EventOccurrence> = {},
  ): EventOccurrence {
    return {
      occurrence_id: crypto.randomUUID(),
      event_id: crypto.randomUUID(),
      calendar_id: crypto.randomUUID(),
      title: "Sports Day",
      is_all_day: true,
      start_at: "2026-08-20T00:00:00+00:00",
      end_at: "2026-08-21T00:00:00+00:00", // exclusive end
      timezone: "Europe/London",
      description: null,
      location_text: null,
      label: null,
      calendar_color: "teal",
      member_ids: [],
      recurrence: "none",
      reminder_minutes: null,
      created_by: crypto.randomUUID(),
      updated_at: "2026-07-01T00:00:00+00:00",
      ...overrides,
    };
  }

  it("persisted all-day -> timed during BST: date preserved, Start is never 01:00 or otherwise boundary-derived", () => {
    const initial = persistedAllDayEvent(); // 20 Aug 2026, BST (UTC+1)
    const when = computeInitialWhen(initial, new Date(), "Europe/London");
    expect(when.hasTimedValues).toBe(false);
    expect(when.startDate).toBe("2026-08-20");
    expect(when.endDate).toBe("2026-08-20");

    const timed = applyAllDayToggle(when, false);
    expect(timed.allDay).toBe(false);
    expect(timed.hasTimedValues).toBe(true);
    // The date must remain 20 August — only the clock portion changes.
    expect(timed.startDate).toBe("2026-08-20");
    expect(timed.endDate).toBe("2026-08-20");
    // Never the localized-UTC-midnight artifact.
    expect(timed.startTime).not.toBe("01:00");
    expect(timed.startTime).toBe(DEFAULT_EVENT_START_TIME);
    expect(timed.endTime).toBe(DEFAULT_EVENT_END_TIME);
    // Established default duration/rule: End > Start on the same date.
    const startInstant = zonedTimeToUtc(2026, 8, 20, 9, 0, "Europe/London");
    const endInstant = zonedTimeToUtc(2026, 8, 20, 10, 0, "Europe/London");
    expect(endInstant.getTime()).toBeGreaterThan(startInstant.getTime());
    expect(
      (endInstant.getTime() - startInstant.getTime()) / 60_000,
    ).toBe(DEFAULT_EVENT_DURATION_MINUTES);
  });

  it("persisted all-day -> timed during GMT: same behaviour, offset-independent", () => {
    const initial = persistedAllDayEvent({
      title: "Winter Fair",
      start_at: "2026-02-14T00:00:00+00:00", // GMT, UTC+0
      end_at: "2026-02-15T00:00:00+00:00",
    });
    const when = computeInitialWhen(initial, new Date(), "Europe/London");
    expect(when.hasTimedValues).toBe(false);
    expect(when.startDate).toBe("2026-02-14");

    const timed = applyAllDayToggle(when, false);
    expect(timed.startDate).toBe("2026-02-14");
    expect(timed.endDate).toBe("2026-02-14");
    expect(timed.startTime).toBe(DEFAULT_EVENT_START_TIME);
    expect(timed.endTime).toBe(DEFAULT_EVENT_END_TIME);
    // GMT is UTC+0, so even the naive (buggy) localized-midnight value would
    // coincidentally be "00:00" here — assert the *correct* mechanism was
    // used (the deterministic default), not a coincidentally-matching one.
    expect(timed.startTime).toBe("09:00");
  });

  it("timed -> all-day -> timed in the same edit session restores the original values exactly", () => {
    const timedEvent: EventOccurrence = {
      occurrence_id: crypto.randomUUID(),
      event_id: crypto.randomUUID(),
      calendar_id: crypto.randomUUID(),
      title: "Dentist",
      is_all_day: false,
      start_at: zonedTimeToUtc(2026, 8, 20, 14, 30, "Europe/London").toISOString(),
      end_at: zonedTimeToUtc(2026, 8, 20, 15, 15, "Europe/London").toISOString(),
      timezone: "Europe/London",
      description: null,
      location_text: null,
      label: null,
      calendar_color: "teal",
      member_ids: [],
      recurrence: "none",
      reminder_minutes: null,
      created_by: crypto.randomUUID(),
      updated_at: "2026-07-01T00:00:00+00:00",
    };
    const initialWhen = computeInitialWhen(timedEvent, new Date(), "Europe/London");
    expect(initialWhen.hasTimedValues).toBe(true);
    expect(initialWhen.startTime).toBe("14:30");
    expect(initialWhen.endTime).toBe("15:15");

    const allDayOn = applyAllDayToggle(initialWhen, true);
    expect(allDayOn.allDay).toBe(true);
    // Hidden, not discarded.
    expect(allDayOn.startTime).toBe("14:30");
    expect(allDayOn.endTime).toBe("15:15");

    const allDayOffAgain = applyAllDayToggle(allDayOn, false);
    expect(allDayOffAgain.allDay).toBe(false);
    expect(allDayOffAgain.startTime).toBe("14:30");
    expect(allDayOffAgain.endTime).toBe("15:15");
  });

  it("a user-edited timed value survives a second All-day round trip without being re-synthesized", () => {
    // Persisted all-day -> user turns All day off (gets the 09:00-10:00
    // default) -> user edits to a custom time -> toggles All day on and off
    // again: the custom edit must not be discarded and replaced with the
    // default a second time.
    const initial = persistedAllDayEvent();
    const afterFirstToggleOff = applyAllDayToggle(
      computeInitialWhen(initial, new Date(), "Europe/London"),
      false,
    );
    const userEdited: typeof afterFirstToggleOff = {
      ...afterFirstToggleOff,
      startTime: "16:00",
      endTime: "17:00",
    };
    const toggledOnAgain = applyAllDayToggle(userEdited, true);
    const toggledOffAgain = applyAllDayToggle(toggledOnAgain, false);
    expect(toggledOffAgain.startTime).toBe("16:00");
    expect(toggledOffAgain.endTime).toBe("17:00");
  });

  it("does not shift to the previous or next day in BST or GMT", () => {
    for (const [tz, startAt, endAt, expectedDate] of [
      ["Europe/London", "2026-08-20T00:00:00+00:00", "2026-08-21T00:00:00+00:00", "2026-08-20"],
      ["Europe/London", "2026-02-14T00:00:00+00:00", "2026-02-15T00:00:00+00:00", "2026-02-14"],
    ] as const) {
      const when = computeInitialWhen(
        persistedAllDayEvent({ start_at: startAt, end_at: endAt }),
        new Date(),
        tz,
      );
      const timed = applyAllDayToggle(when, false);
      expect(timed.startDate).toBe(expectedDate);
      expect(timed.endDate).toBe(expectedDate);
    }
  });

  it("a multi-day all-day event (20-22 Aug) preserves its date range and produces End > Start when converted to timed", () => {
    const initial = persistedAllDayEvent({
      title: "Camping Trip",
      start_at: "2026-08-20T00:00:00+00:00",
      end_at: "2026-08-23T00:00:00+00:00", // exclusive end -> 20, 21, 22 Aug inclusive
    });
    const when = computeInitialWhen(initial, new Date(), "Europe/London");
    expect(when.multiDay).toBe(true);
    expect(when.startDate).toBe("2026-08-20");
    expect(when.endDate).toBe("2026-08-22");

    const timed = applyAllDayToggle(when, false);
    expect(timed.multiDay).toBe(true);
    // The date range must not collapse to a single day.
    expect(timed.startDate).toBe("2026-08-20");
    expect(timed.endDate).toBe("2026-08-22");

    const startInstant = zonedTimeToUtc(2026, 8, 20, 9, 0, "Europe/London");
    const endInstant = zonedTimeToUtc(2026, 8, 22, 10, 0, "Europe/London");
    expect(endInstant.getTime()).toBeGreaterThan(startInstant.getTime());
  });
});

describe("Event View/Edit permissions (mirrors update_event/delete_event)", () => {
  // The frontend Edit/Delete affordances must only ever be shown when the
  // backend would actually allow the action — these mirror
  // apps/api/mykhaya/routers/calendar.py's update_event (edit_own vs
  // edit_all) and delete_event (delete, no ownership tier) rules exactly.
  // This is a UI convenience only; the backend re-checks on every request
  // regardless of what the frontend decided to render.
  function ownEvent(overrides: Partial<EventOccurrence> = {}): EventOccurrence {
    return {
      occurrence_id: crypto.randomUUID(),
      event_id: crypto.randomUUID(),
      calendar_id: crypto.randomUUID(),
      title: "Event",
      is_all_day: false,
      start_at: "2026-08-20T08:00:00+00:00",
      end_at: "2026-08-20T09:00:00+00:00",
      timezone: "Europe/London",
      description: null,
      location_text: null,
      label: null,
      calendar_color: "teal",
      member_ids: [],
      recurrence: "none",
      reminder_minutes: null,
      created_by: "me-user-id",
      updated_at: "2026-07-01T00:00:00+00:00",
      ...overrides,
    };
  }

  describe("canEditEvent", () => {
    it("edit_all grants edit access to any event, including someone else's", () => {
      const someoneElsesEvent = ownEvent({ created_by: "other-user-id" });
      expect(
        canEditEvent(["calendar.edit_all"], someoneElsesEvent, "me-user-id"),
      ).toBe(true);
    });

    it("edit_own alone grants edit access only to the current user's own event", () => {
      const own = ownEvent({ created_by: "me-user-id" });
      const someoneElses = ownEvent({ created_by: "other-user-id" });
      expect(canEditEvent(["calendar.edit_own"], own, "me-user-id")).toBe(true);
      expect(canEditEvent(["calendar.edit_own"], someoneElses, "me-user-id")).toBe(
        false,
      );
    });

    it("no relevant capability denies edit access even for the user's own event", () => {
      const own = ownEvent({ created_by: "me-user-id" });
      expect(canEditEvent([], own, "me-user-id")).toBe(false);
      expect(canEditEvent(["calendar.view"], own, "me-user-id")).toBe(false);
    });

    it("an unknown current user (not yet loaded) never gets edit_own access", () => {
      const own = ownEvent({ created_by: "me-user-id" });
      expect(canEditEvent(["calendar.edit_own"], own, null)).toBe(false);
    });
  });

  describe("canDeleteEvent", () => {
    it("grants delete access with the delete capability, regardless of event ownership", () => {
      expect(canDeleteEvent(["calendar.delete"])).toBe(true);
    });

    it("denies delete access without the delete capability, even with edit_all", () => {
      expect(canDeleteEvent(["calendar.edit_all", "calendar.edit_own"])).toBe(false);
      expect(canDeleteEvent([])).toBe(false);
    });
  });
});

// Regression: editing any event 422'd ("extra_forbidden") because
// EventForm's submit() always includes `calendar_id` in the payload it
// builds (needed for create, via EventCreate), but EventUpdate has no such
// field — an event's calendar assignment is fixed at creation. update() in
// page.tsx now builds its PATCH body through toEventUpdatePayload instead
// of spreading the raw create-shaped payload.
describe("toEventUpdatePayload", () => {
  function eventPayload(overrides: Partial<EventPayload> = {}): EventPayload {
    return {
      title: "Weekly sync",
      start_at: "2026-08-20T09:00:00+00:00",
      end_at: "2026-08-20T10:00:00+00:00",
      timezone: "Europe/London",
      is_all_day: false,
      description: null,
      location_text: null,
      label_id: null,
      calendar_id: null,
      member_ids: [],
      reminder_minutes: null,
      recurrence: "none",
      recurrence_interval: 1,
      recurrence_until: null,
      recurrence_count: null,
      ...overrides,
    };
  }

  it("never includes calendar_id, regardless of what the create-shaped payload carries", () => {
    const withCalendarId = eventPayload({ calendar_id: "some-calendar-id" });
    const result = toEventUpdatePayload(withCalendarId, "2026-08-01T00:00:00+00:00");
    expect(result).not.toHaveProperty("calendar_id");
  });

  it("carries every other field through unchanged, plus expected_updated_at", () => {
    const payload = eventPayload({
      title: "Renamed",
      label_id: "label-1",
      member_ids: ["user-1", "user-2"],
    });
    const result = toEventUpdatePayload(payload, "2026-08-01T00:00:00+00:00");
    expect(result).toEqual({
      title: "Renamed",
      start_at: payload.start_at,
      end_at: payload.end_at,
      timezone: payload.timezone,
      is_all_day: false,
      description: null,
      location_text: null,
      label_id: "label-1",
      member_ids: ["user-1", "user-2"],
      reminder_minutes: null,
      recurrence: "none",
      recurrence_interval: 1,
      recurrence_until: null,
      recurrence_count: null,
      expected_updated_at: "2026-08-01T00:00:00+00:00",
    });
  });

  it("carries a recurrence end date through event updates", () => {
    const payload = eventPayload({
      recurrence: "weekly",
      recurrence_end_date: "2026-09-18",
    });
    expect(toEventUpdatePayload(payload, "2026-08-01T00:00:00+00:00").recurrence_end_date).toBe(
      "2026-09-18",
    );
  });
});

// External Calendar Sharing — an occurrence merged in from a shared calendar
// (see CalendarPage.load in app/calendar/page.tsx) carries its own
// share_id/share_permission/shared_by_home_name instead of relying on the
// viewer's Home capabilities, since an external recipient may have none at
// all (they're not a Home member). Mirrors
// apps/api/mykhaya/routers/calendar_sharing.py's `_require_my_share(...,
// need_manage=True)` exactly.
describe("Shared-calendar permission and visibility helpers", () => {
  function sharedEvent(overrides: Partial<EventOccurrence> = {}): EventOccurrence {
    return {
      occurrence_id: crypto.randomUUID(),
      event_id: crypto.randomUUID(),
      calendar_id: "shared-calendar-1",
      title: "School play",
      is_all_day: false,
      start_at: "2026-08-20T08:00:00+00:00",
      end_at: "2026-08-20T09:00:00+00:00",
      timezone: "Europe/London",
      description: null,
      location_text: null,
      label: null,
      calendar_color: "teal",
      member_ids: [],
      recurrence: "none",
      reminder_minutes: null,
      created_by: "someone-else",
      updated_at: "2026-07-01T00:00:00+00:00",
      share_id: "share-1",
      share_permission: "view",
      shared_by_home_name: "Smith Home",
      ...overrides,
    };
  }

  describe("canEditSharedEvent / canDeleteSharedEvent", () => {
    it("a view-only share grants neither edit nor delete", () => {
      const viewOnly = sharedEvent({ share_permission: "view" });
      expect(canEditSharedEvent(viewOnly)).toBe(false);
      expect(canDeleteSharedEvent(viewOnly)).toBe(false);
    });

    it("a manage share grants both edit and delete", () => {
      const manage = sharedEvent({ share_permission: "manage" });
      expect(canEditSharedEvent(manage)).toBe(true);
      expect(canDeleteSharedEvent(manage)).toBe(true);
    });
  });

  describe("isCalendarVisible / filterByVisibleCalendars", () => {
    it("a shared event is visible unless its share_id is hidden — its calendar_id is irrelevant", () => {
      const visible = sharedEvent({ share_id: "share-1", calendar_id: "cal-x" });
      expect(isCalendarVisible(visible, new Set(["share-1"]))).toBe(false);
      expect(isCalendarVisible(visible, new Set(["cal-x"]))).toBe(true);
      expect(isCalendarVisible(visible, new Set())).toBe(true);
    });

    it("a Home's own event (no share_id) is keyed by calendar_id", () => {
      const own = sharedEvent({ share_id: undefined, calendar_id: "home-cal-1" });
      expect(isCalendarVisible(own, new Set(["home-cal-1"]))).toBe(false);
      expect(isCalendarVisible(own, new Set(["some-other-id"]))).toBe(true);
    });

    it("filterByVisibleCalendars drops only the hidden ones, from a mixed list", () => {
      const events = [
        sharedEvent({ share_id: "share-1" }),
        sharedEvent({ share_id: "share-2" }),
        sharedEvent({ share_id: undefined, calendar_id: "home-cal-1" }),
      ];
      const result = filterByVisibleCalendars(events, new Set(["share-1"]));
      expect(result.map((event) => event.share_id ?? event.calendar_id)).toEqual([
        "share-2",
        "home-cal-1",
      ]);
    });

    it("an empty hidden set returns every event unchanged", () => {
      const events = [sharedEvent(), sharedEvent({ share_id: undefined })];
      expect(filterByVisibleCalendars(events, new Set())).toBe(events);
    });
  });

  describe("toSharedEventPayload / toSharedEventUpdatePayload", () => {
    it("drops member_ids, label_id and calendar_id — a shared event can't carry either", () => {
      const payload: EventPayload = {
        title: "Sports day",
        start_at: "2026-08-20T08:00:00+00:00",
        end_at: "2026-08-20T09:00:00+00:00",
        timezone: "Europe/London",
        is_all_day: false,
        description: "Bring boots",
        location_text: "Field",
        label_id: "some-label-id",
        calendar_id: "some-calendar-id",
        member_ids: ["user-1", "user-2"],
        reminder_minutes: 30,
        recurrence: "none",
        recurrence_interval: 1,
        recurrence_until: null,
        recurrence_end_date: null,
        recurrence_count: null,
      };
      const result = toSharedEventPayload(payload);
      expect(result).not.toHaveProperty("member_ids");
      expect(result).not.toHaveProperty("label_id");
      expect(result).not.toHaveProperty("calendar_id");
      expect(result).toEqual({
        title: "Sports day",
        start_at: payload.start_at,
        end_at: payload.end_at,
        timezone: "Europe/London",
        is_all_day: false,
        description: "Bring boots",
        location_text: "Field",
        reminder_minutes: 30,
        recurrence: "none",
        recurrence_interval: 1,
        recurrence_until: null,
        recurrence_end_date: null,
        recurrence_count: null,
      });

      const updatable = toSharedEventUpdatePayload(payload, "2026-08-01T00:00:00+00:00");
      expect(updatable.expected_updated_at).toBe("2026-08-01T00:00:00+00:00");
      expect(updatable).not.toHaveProperty("member_ids");
    });
  });
});
