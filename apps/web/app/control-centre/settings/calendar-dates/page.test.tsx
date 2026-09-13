import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import CalendarDatesPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/settings/calendar-dates",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    platformApi: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
  };
});

const { platformApi } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;
const post = platformApi.post as unknown as ReturnType<typeof vi.fn>;
const put = platformApi.put as unknown as ReturnType<typeof vi.fn>;

const sources = [
  {
    id: "za",
    country_name: "South Africa",
    flag_emoji: "🇿🇦",
    region_name: "National holidays",
    provider: "South African Government",
    enabled: true,
    sync_status: "healthy" as const,
    last_successful_sync: "2026-09-12T20:22:00Z",
    last_sync_error: null,
    cached_holiday_count: 40,
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  get.mockImplementation((path: string) => {
    if (path === "/auth/me") {
      return Promise.resolve({
        id: "operator",
        email: "operator@example.com",
        display_name: "Operator",
        role: "platform_owner",
        mfa_enrolled: true,
        session_status: "full",
      });
    }
    if (path === "/calendar/holiday-calendars") return Promise.resolve(sources);
    throw new Error(`Unexpected GET ${path}`);
  });
  put.mockResolvedValue({});
  post.mockResolvedValue({});
});

describe("Calendar & Dates", () => {
  it("uses the shared table and preserves availability and sync actions", async () => {
    render(<CalendarDatesPage />);

    const table = await screen.findByRole("table", {
      name: "Supported holiday calendars",
    });
    const row = within(table).getAllByRole("row")[1];
    expect(within(row).getByText(/South Africa$/)).toBeInTheDocument();
    expect(within(table).getByText("Healthy")).toBeInTheDocument();

    fireEvent.click(within(table).getByRole("checkbox"));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith(
        "/calendar/holiday-calendars/za",
        expect.objectContaining({ enabled: false, confirmed: true }),
      ),
    );

    fireEvent.click(within(table).getByRole("button", { name: "Sync now" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/calendar/holiday-calendars/za/sync",
        expect.objectContaining({ confirmed: true }),
      ),
    );
  });
});
