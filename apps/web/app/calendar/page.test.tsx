import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import CalendarPage from "./page";
import { SETTLE_DURATION_MS } from "./use-month-swipe";

// Integration coverage for Month view navigation on the real, fully mounted
// calendar page — proves the existing Previous/Next buttons and the new
// swipe gesture both drive the same focusDate/heading, and that neither
// regressed the other. (Gesture-classification edge cases — short/vertical
// movement, reduced motion, mouse — are covered in isolation against
// MonthSwipeView directly in month-swipe-view.test.tsx.)

// A stable router object matters here specifically: CalendarPage's
// feature-check effect depends on `router` (via useRouter()), so a mock
// that returns a fresh object identity on every call would re-trigger that
// effect (and its "Checking Calendar access…" loading branch) on every
// unrelated re-render — including the focusDate updates this file's tests
// are asserting on — silently swapping in a brand-new heading DOM node.
const mockRouter = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/calendar",
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
      featureMatrix: vi.fn(),
      listEvents: vi.fn(),
      listLabels: vi.fn(),
      members: vi.fn(),
      listCalendars: vi.fn(),
      billingStatus: vi.fn(),
      birthdays: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "u1", display_name: "Megan" });
  (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
    features: [{ feature: "calendar", enabled: true }],
  });
  (api.listEvents as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.listLabels as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (api.listCalendars as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: [{ id: "cal-1", is_primary: true, timezone: "UTC" }],
    personal_calendar: null,
  });
  (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
    shared_events_enabled: false,
  });
  (api.birthdays as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
});

describe("Calendar — Month view navigation", () => {
  it("the Previous/Next buttons still move the month and keep the heading in sync", async () => {
    render(<CalendarPage />);

    const heading = await screen.findByRole("heading", { level: 1 });
    const initialLabel = heading.textContent;
    expect(initialLabel).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Next period" }));
    await waitFor(() => expect(heading.textContent).not.toBe(initialLabel));
    const afterNext = heading.textContent;

    fireEvent.click(screen.getByRole("button", { name: "Previous period" }));
    await waitFor(() => expect(heading.textContent).toBe(initialLabel));
    expect(heading.textContent).not.toBe(afterNext);
  });

  it("a left swipe on the month grid navigates forward and updates the heading, same as Next", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<CalendarPage />);

    const heading = await screen.findByRole("heading", { level: 1 });
    const initialLabel = heading.textContent;

    const swipeArea = document.querySelector(".calendar-month-swipe");
    expect(swipeArea).not.toBeNull();

    const pointerId = 1;
    const down = new Event("pointerdown", { bubbles: true, cancelable: true });
    Object.assign(down, { pointerId, pointerType: "touch", clientX: 200, clientY: 200 });
    fireEvent(swipeArea!, down);

    const move = new Event("pointermove", { bubbles: true, cancelable: true });
    Object.assign(move, { pointerId, pointerType: "touch", clientX: 80, clientY: 200 });
    fireEvent(swipeArea!, move);

    const up = new Event("pointerup", { bubbles: true, cancelable: true });
    Object.assign(up, { pointerId, pointerType: "touch", clientX: 80, clientY: 200 });
    fireEvent(swipeArea!, up);

    act(() => {
      vi.advanceTimersByTime(SETTLE_DURATION_MS);
    });
    vi.useRealTimers();

    await waitFor(() => expect(heading.textContent).not.toBe(initialLabel));
  });
});
