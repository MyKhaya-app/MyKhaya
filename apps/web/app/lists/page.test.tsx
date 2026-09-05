import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ListsPage from "./page";

// Coverage for the Lists overview — see docs/architecture/lists.md. Mirrors
// the Meal Plans locked-state/feature-gate pattern established in
// app/meal-plans/page.test.tsx.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/lists",
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
      billingStatus: vi.fn(),
      members: vi.fn(),
      featureMatrix: vi.fn(),
      lists: vi.fn(),
      createList: vi.fn(),
      renameList: vi.fn(),
      deleteList: vi.fn(),
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
  (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (api.lists as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
    features: [{ feature: "shopping", enabled: true }],
  });
});

describe("Lists — Free plan locked state", () => {
  it("shows the Family upsell and no list content for a Free Home", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({ lists_enabled: false });

    render(<ListsPage />);

    expect(await screen.findByText(/view family plan/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /new list/i })).not.toBeInTheDocument();
  });
});

describe("Lists — feature-gate consistency", () => {
  it("shows a calm message instead of the interactive overview when the module isn't released", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({ lists_enabled: true });
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
      features: [{ feature: "shopping", enabled: false }],
    });

    render(<ListsPage />);

    expect(await screen.findByText(/isn't available for this home yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/^not found$/i)).not.toBeInTheDocument();
  });
});

describe("Lists — Family plan overview", () => {
  beforeEach(() => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({ lists_enabled: true });
  });

  it("shows the empty state with a call to action when there are no lists", async () => {
    render(<ListsPage />);

    expect(await screen.findByText(/no lists yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create your first list/i })).toBeInTheDocument();
  });

  it("renders the hero artwork with the correct asset path and alt text, and uses the shared compact module-page spacing", async () => {
    const { container } = render(<ListsPage />);
    await screen.findByRole("heading", { name: "Lists", level: 1 });

    const art = screen.getByAltText("Small lists, big things together");
    expect(art.tagName).toBe("IMG");
    expect(art).toHaveAttribute("src", expect.stringContaining("/images/lists-hero.png"));

    const main = container.querySelector("main");
    expect(main).toHaveClass("standard-page");
    expect(main).toHaveClass("module-page");
  });

  it("keeps the existing My Lists view functional and shows a calm, non-fabricated placeholder for Templates", async () => {
    (api.lists as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "list-1",
          name: "Groceries",
          icon: "groceries",
          item_count: 8,
          remaining_count: 3,
          created_by: "u1",
          created_at: "2026-08-01T00:00:00Z",
          updated_at: "2026-08-01T00:00:00Z",
        },
      ],
    });
    render(<ListsPage />);
    const user = userEvent.setup();

    expect(await screen.findByRole("link", { name: /groceries/i })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Templates" }));

    expect(screen.getByText(/templates.*coming soon/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /groceries/i })).not.toBeInTheDocument();
    // No fabricated template data — Templates never calls a lists-fetching
    // endpoint of its own, since no such backend concept exists yet.
    expect(api.lists).toHaveBeenCalledTimes(1);
  });

  it("gives each recognised list category a real image icon, and falls back to the generic icon for an unrecognised/custom one", async () => {
    (api.lists as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "list-1",
          name: "Groceries",
          icon: "groceries",
          item_count: 1,
          remaining_count: 1,
          created_by: "u1",
          created_at: "2026-08-01T00:00:00Z",
          updated_at: "2026-08-01T00:00:00Z",
        },
        {
          id: "list-2",
          name: "Something bespoke",
          icon: null,
          item_count: 1,
          remaining_count: 1,
          created_by: "u1",
          created_at: "2026-08-01T00:00:00Z",
          updated_at: "2026-08-01T00:00:00Z",
        },
      ],
    });

    render(<ListsPage />);
    const groceriesCard = (await screen.findByRole("link", { name: /groceries/i })).closest(".lists-card");
    const customCard = screen.getByRole("link", { name: /something bespoke/i }).closest(".lists-card");

    expect(groceriesCard?.querySelector(".lists-card-icon")).toHaveAttribute(
      "src",
      expect.stringContaining("/images/lists-groceries.png"),
    );
    expect(customCard?.querySelector(".lists-card-icon")).toHaveAttribute(
      "src",
      expect.stringContaining("/images/lists-other.png"),
    );
  });

  it("renders list cards with remaining/total counts", async () => {
    (api.lists as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "list-1",
          name: "Groceries",
          icon: "groceries",
          item_count: 8,
          remaining_count: 3,
          created_by: "u1",
          created_at: "2026-08-01T00:00:00Z",
          updated_at: "2026-08-01T00:00:00Z",
        },
        {
          id: "list-2",
          name: "School supplies",
          icon: null,
          item_count: 6,
          remaining_count: 0,
          created_by: "u1",
          created_at: "2026-08-01T00:00:00Z",
          updated_at: "2026-08-01T00:00:00Z",
        },
      ],
    });

    render(<ListsPage />);

    const groceries = await screen.findByRole("link", { name: /groceries/i });
    expect(groceries).toHaveAttribute("href", "/lists/list-1");
    expect(screen.getByText(/3 remaining · 8 items/i)).toBeInTheDocument();
    expect(screen.getByText(/complete · 6 items/i)).toBeInTheDocument();
  });

  it("creates a new list from the New list sheet", async () => {
    (api.createList as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "list-9",
      name: "Packing",
      icon: null,
      items: [],
      item_count: 0,
      remaining_count: 0,
      created_by: "u1",
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
    });

    render(<ListsPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /new list/i }));
    await user.type(screen.getByLabelText(/list name/i), "Packing");
    await user.click(screen.getByRole("button", { name: /create list/i }));

    expect(api.createList).toHaveBeenCalledWith("home-1", { name: "Packing", icon: null });
  });

  it("filters lists by search", async () => {
    (api.lists as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
    render(<ListsPage />);
    await screen.findByRole("button", { name: /new list/i });
    fireEvent.change(screen.getByLabelText(/search lists/i), { target: { value: "pack" } });

    await waitFor(
      () => {
        expect(api.lists).toHaveBeenCalledWith("home-1", { q: "pack" });
      },
      { timeout: 3000 },
    );
  });
});
