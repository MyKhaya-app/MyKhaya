import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WishListsPage from "./page";

// Coverage for the Wishlists landing page — Free-plan/module gates mirror
// Lists' (see app/lists/page.test.tsx), plus the Your Home vs Shared with me
// split that's specific to Wishlists. See docs/product/wishlists.md.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/wish-lists",
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
      featureMatrix: vi.fn(),
      wishlists: vi.fn(),
      sharedWithMe: vi.fn(),
      createWishlist: vi.fn(),
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
  (api.wishlists as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.sharedWithMe as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
    features: [{ feature: "wish_lists", enabled: true }],
  });
});

describe("Wishlists — Free plan locked state", () => {
  it("shows the Family upsell and no wishlist content for a Free Home", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({ wishlists_enabled: false });

    render(<WishListsPage />);

    expect(await screen.findByText(/view family plan/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /new wishlist/i })).not.toBeInTheDocument();
  });
});

describe("Wishlists — feature-gate consistency", () => {
  it("shows a calm message instead of the interactive overview when the module isn't released", async () => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({ wishlists_enabled: true });
    (api.featureMatrix as ReturnType<typeof vi.fn>).mockResolvedValue({
      features: [{ feature: "wish_lists", enabled: false }],
    });

    render(<WishListsPage />);

    expect(await screen.findByText(/isn't available for this home yet/i)).toBeInTheDocument();
  });
});

describe("Wishlists — Family plan overview", () => {
  beforeEach(() => {
    (api.billingStatus as ReturnType<typeof vi.fn>).mockResolvedValue({ wishlists_enabled: true });
  });

  it("shows the empty state with a call to action when there are no wishlists", async () => {
    render(<WishListsPage />);

    expect(await screen.findByText(/no wishlists yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create your first wishlist/i })).toBeInTheDocument();
  });

  it("groups Your Home wishlists by owner and only shows Shared with me when non-empty", async () => {
    (api.wishlists as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "wl-1",
          home_id: "home-1",
          title: "My birthday",
          occasion: "birthday",
          occasion_date: null,
          description: null,
          owner_user_id: "u1",
          owner_display_name: "Megan",
          item_count: 3,
          is_owner: true,
          created_at: "2026-08-01T00:00:00Z",
          updated_at: "2026-08-01T00:00:00Z",
        },
        {
          id: "wl-2",
          home_id: "home-1",
          title: "Dad's Christmas list",
          occasion: "christmas",
          occasion_date: null,
          description: null,
          owner_user_id: "u2",
          owner_display_name: "Dave",
          item_count: 1,
          is_owner: false,
          created_at: "2026-08-01T00:00:00Z",
          updated_at: "2026-08-01T00:00:00Z",
        },
      ],
    });

    render(<WishListsPage />);

    const mine = await screen.findByRole("link", { name: /my birthday/i });
    expect(mine).toHaveAttribute("href", "/wish-lists/wl-1");
    expect(screen.getByText("Dave")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /dad's christmas list/i })).toBeInTheDocument();
    expect(screen.queryByText(/shared with me/i)).not.toBeInTheDocument();
  });

  it("renders a Shared with me section when there are shares from outside the Home", async () => {
    (api.sharedWithMe as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "wl-9",
          home_id: "other-home",
          title: "Cousin's wishlist",
          occasion: "general",
          occasion_date: null,
          description: null,
          owner_user_id: "u9",
          owner_display_name: "Priya",
          item_count: 2,
          is_owner: false,
          created_at: "2026-08-01T00:00:00Z",
          updated_at: "2026-08-01T00:00:00Z",
        },
      ],
    });

    render(<WishListsPage />);

    expect(await screen.findByText(/shared with me/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /cousin's wishlist/i })).toHaveAttribute(
      "href",
      "/wish-lists/wl-9",
    );
  });

  it("creates a new wishlist from the New wishlist sheet", async () => {
    (api.createWishlist as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "wl-9",
      home_id: "home-1",
      title: "Christmas list",
      occasion: "general",
      occasion_date: null,
      description: null,
      owner_user_id: "u1",
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
      items: [],
    });

    render(<WishListsPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /new wishlist/i }));
    await user.type(screen.getByLabelText(/title/i), "Christmas list");
    await user.click(screen.getByRole("button", { name: /^create wishlist$/i }));

    expect(api.createWishlist).toHaveBeenCalledWith("home-1", {
      title: "Christmas list",
      occasion: "general",
      occasion_date: null,
      description: null,
    });
  });
});
