import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "@mykhaya/api-client";
import CalendarsPage from "./page";

// Coverage for the Home Calendar sharing/management page's mobile redesign.
// The previous inline `sharingPanel()` broke on narrow screens because
// `.calendar-sharing-panel form` forced a rigid `1fr 180px auto` grid
// regardless of viewport (see app/styles.css) — JSDOM doesn't compute real
// layout, so pixel-overflow itself isn't asserted here; these tests instead
// pin the *structural* fix: the invite form is a plain single-column form
// (the app's base `form` rule, not a custom grid) inside a BottomSheet, the
// "Send invitation" button is a normal form-grid child (which stretches
// full-width by default), errors render next to the field they concern
// rather than in a top-of-form banner, and Close/Delete are no longer
// squeezed next to the calendar name in the list row.

// A stable router object matters here: AppShell's bootstrap effect depends
// on `router` (via useRouter()), so a mock returning a fresh object every
// call would re-run that effect (setAuthState("loading") -> "ready") on
// every unrelated re-render — including every keystroke in the sharing
// form — remounting the BottomSheet mid-interaction. See app/calendar/
// page.test.tsx's mockRouter for the same fix.
const mockRouter = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/calendar/calendars",
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

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      listCalendars: vi.fn(),
      listLabels: vi.fn(),
      sharedCalendars: vi.fn(),
      billingStatus: vi.fn(),
      listSharesForCalendar: vi.fn(),
      createCalendarShare: vi.fn(),
      changeCalendarSharePermission: vi.fn(),
      revokeCalendarShare: vi.fn(),
      createCalendar: vi.fn(),
      deleteCalendar: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

const primaryCalendar = {
  id: "cal-1",
  name: "Hales Home",
  timezone: "Europe/London",
  is_primary: true,
  owner_user_id: null,
  color: "teal",
  commercial_access: "normal" as const,
  created_at: "2026-01-01T00:00:00Z",
};

const secondCalendar = {
  ...primaryCalendar,
  id: "cal-2",
  name: "Football Club",
  is_primary: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "u1", display_name: "Megan" });
  (api.listCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: [primaryCalendar, secondCalendar],
    limit: 2,
    personal_calendar: null,
  });
  (api.listLabels as ReturnType<typeof vi.fn>).mockResolvedValue([
    { id: "l1", name: "Family Events", color: "teal", is_active: true, sort_order: 10, commercial_access: "normal" },
    { id: "l2", name: "Football Club", color: "sage", is_active: true, sort_order: 20, commercial_access: "normal" },
  ]);
  (api.sharedCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
    external_invites_enabled: true,
  });
  (api.listSharesForCalendar as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
});

async function openSharingSheet(name = "Hales Home") {
  render(<CalendarsPage />);
  const heading = await screen.findByRole("heading", { name: new RegExp(name) });
  const row = heading.closest(".calendar-list-card") as HTMLElement;
  fireEvent.click(within(row).getByRole("button", { name: "Manage sharing" }));
  return screen.findByRole("dialog", { name });
}

describe("Calendars page — Manage sharing sheet", () => {
  it("opens a BottomSheet (not an inline-expanding card) with the calendar's name as its title", async () => {
    const dialog = await openSharingSheet();
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText("Invite someone")).toBeInTheDocument();
  });

  it("renders the invite form as a plain single-column form, not the old rigid 3-column layout", async () => {
    const dialog = await openSharingSheet();
    const form = dialog.querySelector(".calendar-share-form") as HTMLFormElement;
    expect(form).not.toBeNull();
    // The bug-causing class no longer wraps the form at all.
    expect(form.closest(".calendar-sharing-panel")).toBeNull();
    expect(within(form).getByLabelText("Email address")).toBeInTheDocument();
    expect(within(form).getByLabelText("Access")).toBeInTheDocument();
    expect(within(form).getByRole("button", { name: "Send invitation" })).toBeInTheDocument();
  });

  it("shows the external-recipient helper copy so an unmatched email is never treated as a fatal error", async () => {
    const dialog = await openSharingSheet();
    expect(
      within(dialog).getByText(/don.t need a MyKhaya account yet/i),
    ).toBeInTheDocument();
  });

  it("reveals a category checklist only after choosing 'Selected categories only'", async () => {
    const dialog = await openSharingSheet();
    expect(within(dialog).queryByText("Family Events")).not.toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("radio", { name: "Selected categories only" }));

    await waitFor(() => expect(within(dialog).getByText("Family Events")).toBeInTheDocument());
    expect(within(dialog).getByText("Football Club")).toBeInTheDocument();
  });

  it("shows a subtle 'Not currently shared' state, not a large empty area, when nothing is shared yet", async () => {
    const dialog = await openSharingSheet();
    expect(within(dialog).getByText("Not currently shared")).toBeInTheDocument();
  });

  it("lists existing shares above the invite form with permission and status", async () => {
    (api.listSharesForCalendar as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "share-1",
          calendar_id: "cal-1",
          calendar_name: "Hales Home",
          calendar_color: "teal",
          source_group_id: "home-1",
          source_group_name: "Hales Home",
          recipient_email: "grandma@example.com",
          recipient_user_id: null,
          permission: "view",
          status: "accepted",
          expired: false,
          requested_by_display_name: "Megan",
          expires_at: "2026-12-01T00:00:00Z",
          accepted_at: "2026-08-01T00:00:00Z",
          declined_at: null,
          revoked_at: null,
          notification_preference: "all",
          include_in_briefing: true,
          category_ids: null,
          created_at: "2026-07-01T00:00:00Z",
        },
      ],
    });

    const dialog = await openSharingSheet();
    const emailNode = await within(dialog).findByText("grandma@example.com");
    expect(emailNode).toBeInTheDocument();
    const shareRow = emailNode.closest(".calendar-share-row") as HTMLElement;
    expect(within(shareRow).getByText(/Can view · Active · Entire calendar/)).toBeInTheDocument();
    expect(within(dialog).queryByText("Not currently shared")).not.toBeInTheDocument();
  });

  it("shows a field-adjacent error, not a top-of-form banner, when sharing fails", async () => {
    (api.createCalendarShare as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(409, "An active share already exists for this email."),
    );
    const user = userEvent.setup();
    const dialog = await openSharingSheet();

    await user.type(within(dialog).getByLabelText("Email address"), "grandma@example.com");
    await user.click(within(dialog).getByRole("button", { name: "Send invitation" }));

    const fieldError = await within(dialog).findByText(
      "An active share already exists for this email.",
    );
    expect(fieldError).toHaveClass("field-error");
    expect(dialog.querySelector(".notice.error")).toBeNull();
  });

  it("translates a generic 'Not found' (feature not enabled) into an actionable message instead of showing it raw", async () => {
    (api.createCalendarShare as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(404, "Not found"),
    );
    const user = userEvent.setup();
    const dialog = await openSharingSheet();

    await user.type(within(dialog).getByLabelText("Email address"), "grandma@example.com");
    await user.click(within(dialog).getByRole("button", { name: "Send invitation" }));

    expect(await within(dialog).findByText(/isn.t turned on for this Home yet/i)).toBeInTheDocument();
    expect(within(dialog).queryByText("Not found")).not.toBeInTheDocument();
  });

  it("submits with a long recipient email without breaking the form", async () => {
    (api.createCalendarShare as ReturnType<typeof vi.fn>).mockResolvedValue({});
    const user = userEvent.setup();
    const dialog = await openSharingSheet();

    const longEmail = "a.very.long.email.address.for.a.grandparent@some-example-family-domain.com";
    await user.type(within(dialog).getByLabelText("Email address"), longEmail);
    await user.click(within(dialog).getByRole("button", { name: "Send invitation" }));

    await waitFor(() =>
      expect(api.createCalendarShare).toHaveBeenCalledWith(
        "home-1",
        expect.objectContaining({ recipient_email: longEmail }),
      ),
    );
  });

  it("only offers Delete calendar for non-primary calendars, and requires confirmation", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    (api.deleteCalendar as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);

    const primaryDialog = await openSharingSheet("Hales Home");
    expect(within(primaryDialog).queryByText("Delete calendar")).not.toBeInTheDocument();
    fireEvent.click(within(primaryDialog).getByRole("button", { name: "Close dialog" }));

    const secondDialog = await openSharingSheet("Football Club");
    fireEvent.click(within(secondDialog).getByRole("button", { name: "Delete calendar" }));

    expect(confirmSpy).toHaveBeenCalled();
    await waitFor(() =>
      expect(api.deleteCalendar).toHaveBeenCalledWith("home-1", "cal-2", { confirmed: true }),
    );
  });

  it("keeps the calendar list row to just a 'Manage sharing' action, with no Delete button competing next to the name", async () => {
    render(<CalendarsPage />);
    const heading = await screen.findByRole("heading", { name: /Hales Home/ });
    const row = heading.closest(".calendar-list-card") as HTMLElement;
    expect(within(row).queryByRole("button", { name: /delete/i })).not.toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Manage sharing" })).toBeInTheDocument();
  });
});
