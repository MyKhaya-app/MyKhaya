import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { SettingsPage } from "./settings-page";

// Coverage for the new Lists entry on More → Settings — it must sit directly
// below Routines & Reminders and above Meal Plans, and reuse the existing
// Lists route (/lists) rather than a new settings-only screen. See the Home
// "Around the house" Routines & Reminders shortcut coverage in
// app/home/page.test.tsx for the equivalent navigation-only addition on the
// Home screen.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/settings",
}));

vi.mock("./use-active-home", () => ({
  useActiveHome: () => ({
    activeHome: { id: "home-1", name: "Hales Home", relationship: "home_admin" },
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
    },
  };
});

const { api } = await import("@mykhaya/api-client");

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
    id: "u1",
    display_name: "Megan",
    principal_type: "adult",
  });
  global.fetch = vi.fn().mockRejectedValue(new Error("no build info in tests"));
});

describe("Settings — Lists entry", () => {
  it("places Lists directly below Calendars and above Meal Plans, with Calendars below Routines & Reminders", async () => {
    render(<SettingsPage />);

    const headings = await screen.findAllByRole("heading", { level: 2 });
    const names = headings.map((heading) => heading.textContent);
    const routinesIndex = names.indexOf("Routines & Reminders");
    const calendarsIndex = names.indexOf("Calendars");
    const listsIndex = names.indexOf("Lists");
    const mealPlansIndex = names.indexOf("Meal Plans");

    expect(routinesIndex).toBeGreaterThanOrEqual(0);
    expect(calendarsIndex).toBe(routinesIndex + 1);
    expect(listsIndex).toBe(calendarsIndex + 1);
    expect(mealPlansIndex).toBe(listsIndex + 1);
  });

  it("shows a single combined Routines & Reminders entry, not two separate ones", async () => {
    render(<SettingsPage />);

    const heading = await screen.findByRole("heading", { name: "Routines & Reminders" });
    const card = heading.closest("a");
    expect(card).toHaveAttribute("href", "/settings/routines-reminders");
    expect(screen.queryByRole("heading", { name: "Routines" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Reminders" })).not.toBeInTheDocument();
  });

  it("routes the Lists card to the existing Lists experience", async () => {
    render(<SettingsPage />);

    const heading = await screen.findByRole("heading", { name: "Lists" });
    const card = heading.closest("a");
    expect(card).toHaveAttribute("href", "/lists");
    expect(screen.getByText("Shopping, chores and shared household lists")).toBeInTheDocument();
  });

  it("routes the Calendars card to the existing calendar management screen", async () => {
    render(<SettingsPage />);

    const heading = await screen.findByRole("heading", { name: "Calendars" });
    const card = heading.closest("a");
    expect(card).toHaveAttribute("href", "/calendar/calendars");
  });
});

describe("More — flattened destinations, no Control Centre, no version footer", () => {
  it("does not show Khaya Control Centre, even for a Home Admin", async () => {
    render(<SettingsPage />);

    await screen.findByRole("heading", { name: "Profile" });
    expect(screen.queryByRole("heading", { name: "Khaya Control Centre" })).not.toBeInTheDocument();
    expect(screen.queryByText(/members, child permissions and household features/i)).not.toBeInTheDocument();
  });

  it("does not render the inline version/debug footer", async () => {
    render(<SettingsPage />);

    await screen.findByRole("heading", { name: "Profile" });
    expect(screen.queryByText(/MyKhaya \d+\.\d+\.\d+/)).not.toBeInTheDocument();
    expect(screen.queryByText(/SW: not active/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\(development\)/)).not.toBeInTheDocument();
  });

  it("links directly to About MyKhaya and Help & Support", async () => {
    render(<SettingsPage />);

    const about = await screen.findByRole("heading", { name: "About MyKhaya" });
    expect(about.closest("a")).toHaveAttribute("href", "/about");

    const help = await screen.findByRole("heading", { name: "Help & Support" });
    expect(help.closest("a")).toHaveAttribute("href", "/help-support");
  });

  it("does not introduce any duplicate destinations", async () => {
    render(<SettingsPage />);

    const headings = await screen.findAllByRole("heading", { level: 2 });
    const hrefs = headings.map((heading) => heading.closest("a")?.getAttribute("href"));
    const definedHrefs = hrefs.filter((href): href is string => Boolean(href));
    expect(new Set(definedHrefs).size).toBe(definedHrefs.length);
  });
});
