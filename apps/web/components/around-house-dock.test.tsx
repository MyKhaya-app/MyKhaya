// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { AroundHouseDock } from "./around-house-dock";

type TestActiveHome = {
  activeHomeId: string | null;
  activeHome: { id: string; name: string; capabilities: string[] } | null;
};
const activeHomeMock = vi.fn<() => TestActiveHome>();

vi.mock("./use-active-home", () => ({
  useActiveHome: () => activeHomeMock(),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      billingStatus: vi.fn(),
      featureMatrix: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

function billing(overrides: Record<string, unknown> = {}) {
  return {
    member_usage: { count: 1, limit: 4, over_limit: false },
    meals_enabled: true,
    lists_enabled: true,
    wishlists_enabled: true,
    nudges_enabled: true,
    ...overrides,
  };
}

function features(overrides: { feature: string; enabled: boolean }[] = []) {
  const base = [
    { feature: "calendar", enabled: true },
    { feature: "meals", enabled: true },
    { feature: "shopping", enabled: true },
    { feature: "wish_lists", enabled: true },
    { feature: "nudges", enabled: true },
  ];
  return { features: [...base.filter((item) => !overrides.some((override) => override.feature === item.feature)), ...overrides] };
}

beforeEach(() => {
  vi.clearAllMocks();
  activeHomeMock.mockReturnValue({
    activeHomeId: "home-1",
    activeHome: { id: "home-1", name: "Hales Home", capabilities: ["members.invite"] },
  });
  (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(billing());
  (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue(features());
});

describe("AroundHouseDock", () => {
  it("renders permitted shortcuts once the current Home access state is ready", async () => {
    render(<AroundHouseDock />);

    expect(await screen.findByRole("heading", { name: "Around the house" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add event" })).toHaveAttribute("href", "/calendar");
    expect(screen.getByRole("link", { name: "Invite family" })).toHaveAttribute(
      "href",
      "/settings/members",
    );
    expect(screen.getByRole("link", { name: "Meal plans" })).toHaveAttribute("href", "/meal-plans");
  });

  it("does not render while the current Home access state is unknown", () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => undefined));
    render(<AroundHouseDock />);
    expect(screen.queryByRole("heading", { name: "Around the house" })).not.toBeInTheDocument();
  });

  it("keeps existing locked shortcut treatment and hides unreleased modules", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue(billing({ meals_enabled: false }));
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue(
      features([
        { feature: "shopping", enabled: false },
        { feature: "nudges", enabled: false },
      ]),
    );

    render(<AroundHouseDock />);

    const meals = await screen.findByRole("link", { name: "Meal plans" });
    expect(meals).toHaveClass("quick-action-locked");
    expect(screen.queryByRole("link", { name: "Lists" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Nudges" })).not.toBeInTheDocument();
  });

  it("fails closed when there is no active Home", () => {
    activeHomeMock.mockReturnValue({ activeHomeId: null, activeHome: null });
    render(<AroundHouseDock />);
    expect(screen.queryByRole("heading", { name: "Around the house" })).not.toBeInTheDocument();
    expect(api.billingStatus).not.toHaveBeenCalled();
  });
});
