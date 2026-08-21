import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { SettingsPage } from "./settings-page";

// Coverage for the new Lists entry on More → Settings — it must sit directly
// below Routines and above Meal Plans, and reuse the existing Lists route
// (/lists) rather than a new settings-only screen. See the Home "Around the
// house" Routines-shortcut coverage in app/home/page.test.tsx for the
// equivalent navigation-only addition on the Home screen.

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
  it("places Lists directly below Routines and above Meal Plans", async () => {
    render(<SettingsPage />);

    const headings = await screen.findAllByRole("heading", { level: 2 });
    const names = headings.map((heading) => heading.textContent);
    const routinesIndex = names.indexOf("Routines");
    const listsIndex = names.indexOf("Lists");
    const mealPlansIndex = names.indexOf("Meal Plans");

    expect(routinesIndex).toBeGreaterThanOrEqual(0);
    expect(listsIndex).toBe(routinesIndex + 1);
    expect(mealPlansIndex).toBe(listsIndex + 1);
  });

  it("routes the Lists card to the existing Lists experience", async () => {
    render(<SettingsPage />);

    const heading = await screen.findByRole("heading", { name: "Lists" });
    const card = heading.closest("a");
    expect(card).toHaveAttribute("href", "/lists");
    expect(screen.getByText("Shopping, chores and shared household lists")).toBeInTheDocument();
  });
});
