import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WishlistDetailPage from "./page";

// Coverage for an individual Wishlist. The single most important case here
// is "Wishlists — owner never sees reservation state": it renders the exact
// owner-shape response (no reservation_status/reserved_by_display_name
// fields at all — see wishlist_schemas.py's WishlistItemOwnerResponse) and
// asserts nothing reservation-related appears anywhere in the DOM. This is
// the frontend mirror of the backend's own privacy guarantee.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/wish-lists/wl-1",
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
      wishlistTopLevel: vi.fn(),
      reserveWishlistItem: vi.fn(),
      markWishlistItemBought: vi.fn(),
      releaseWishlistItem: vi.fn(),
      shares: vi.fn(),
      revokeShare: vi.fn(),
      createShare: vi.fn(),
      lookupShareRecipient: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

function resolvedParams(id: string): Promise<{ id: string }> {
  const promise = Promise.resolve({ id }) as Promise<{ id: string }> & {
    status?: string;
    value?: { id: string };
  };
  promise.status = "fulfilled";
  promise.value = { id };
  return promise;
}

function renderPage(id = "wl-1") {
  return render(<WishlistDetailPage params={resolvedParams(id)} />);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Wishlists — owner never sees reservation state", () => {
  it("renders no reservation status, reserved-by, or reserve/release controls for the owner's own wishlist", async () => {
    (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "u1",
      display_name: "Megan",
      principal_type: "adult",
    });
    // The exact owner-shape response — structurally, there is nowhere for a
    // reservation_status/reserved_by_display_name value to even live here.
    (api.wishlistTopLevel as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "wl-1",
      home_id: "home-1",
      title: "My birthday",
      occasion: "birthday",
      occasion_date: null,
      description: null,
      owner_user_id: "u1",
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
      items: [
        {
          id: "item-1",
          name: "Board game",
          url: null,
          price: "29.99",
          currency: "GBP",
          note: null,
          image_url: null,
          quantity: 1,
          sort_order: 0,
          created_at: "2026-08-01T00:00:00Z",
          updated_at: "2026-08-01T00:00:00Z",
        },
      ],
    });

    renderPage();

    expect(await screen.findByText("Board game")).toBeInTheDocument();
    // No reservation vocabulary anywhere on the page.
    expect(screen.queryByText(/available/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/reserved/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/bought/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^reserve$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /mark as bought/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^release$/i })).not.toBeInTheDocument();
    // Owner controls are present instead.
    expect(await screen.findByRole("button", { name: /add item/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /share wishlist/i })).toBeInTheDocument();
  });
});

describe("Wishlists — viewer reservation controls", () => {
  beforeEach(() => {
    (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "u2",
      display_name: "Dave",
      principal_type: "adult",
    });
  });

  function viewerDetail(itemOverrides: Record<string, unknown> = {}) {
    return {
      id: "wl-1",
      home_id: "home-1",
      title: "Megan's birthday",
      occasion: "birthday",
      occasion_date: null,
      description: null,
      owner_user_id: "u1",
      owner_display_name: "Megan",
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
      items: [
        {
          id: "item-1",
          name: "Board game",
          url: null,
          price: null,
          currency: null,
          note: null,
          image_url: null,
          quantity: 1,
          sort_order: 0,
          created_at: "2026-08-01T00:00:00Z",
          updated_at: "2026-08-01T00:00:00Z",
          reservation_status: "available",
          reserved_by_display_name: null,
          ...itemOverrides,
        },
      ],
    };
  }

  it("shows Reserve and Mark as bought for an available item, and reserves it", async () => {
    (api.wishlistTopLevel as ReturnType<typeof vi.fn>).mockResolvedValue(viewerDetail());
    (api.reserveWishlistItem as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "item-1",
      name: "Board game",
      url: null,
      price: null,
      currency: null,
      note: null,
      image_url: null,
      quantity: 1,
      sort_order: 0,
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
      reservation_status: "reserved",
      reserved_by_display_name: "Dave",
    });

    renderPage();
    const user = userEvent.setup();

    expect(await screen.findByText(/available/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^reserve$/i }));

    expect(api.reserveWishlistItem).toHaveBeenCalledWith("wl-1", "item-1");
    expect(await screen.findByText(/reserved by dave/i)).toBeInTheDocument();
  });

  it("shows Release (not Reserve) once an item is reserved", async () => {
    (api.wishlistTopLevel as ReturnType<typeof vi.fn>).mockResolvedValue(
      viewerDetail({ reservation_status: "reserved", reserved_by_display_name: "Dave" }),
    );

    renderPage();

    expect(await screen.findByRole("button", { name: /^release$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^reserve$/i })).not.toBeInTheDocument();
  });
});

describe("Wishlists — sharing", () => {
  beforeEach(() => {
    (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "u1",
      display_name: "Megan",
      principal_type: "adult",
    });
    (api.wishlistTopLevel as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "wl-1",
      home_id: "home-1",
      title: "My birthday",
      occasion: "birthday",
      occasion_date: null,
      description: null,
      owner_user_id: "u1",
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
      items: [],
    });
  });

  it("detects an existing MyKhaya account by email and offers to share directly", async () => {
    (api.lookupShareRecipient as ReturnType<typeof vi.fn>).mockResolvedValue({
      existing_user_id: "u9",
      existing_user_display_name: "Priya",
    });
    (api.createShare as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "share-1",
      recipient_name: "Priya",
      share_type: "mykhaya_user",
      created_at: "2026-08-01T00:00:00Z",
    });

    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /share wishlist/i }));
    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText(/^name$/i), "Priya");
    await user.type(within(dialog).getByLabelText(/email/i), "priya@example.com");
    await user.click(within(dialog).getByRole("button", { name: /^share wishlist$/i }));

    expect(await screen.findByText(/already uses mykhaya/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /share with their account/i }));

    expect(api.createShare).toHaveBeenCalledWith("home-1", "wl-1", {
      recipient_name: "Priya",
      recipient_email: "priya@example.com",
      share_type: "mykhaya_user",
      confirmed_user_id: "u9",
    });
  });

  it("reveals a one-time link and PIN for a guest share", async () => {
    (api.createShare as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "share-2",
      recipient_name: "Grandma",
      share_type: "guest",
      created_at: "2026-08-01T00:00:00Z",
      link_token: "tok_abc123",
      pin: "482913",
    });

    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /share wishlist/i }));
    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText(/^name$/i), "Grandma");
    await user.click(within(dialog).getByRole("button", { name: /^share wishlist$/i }));

    expect(await screen.findByText(/shown once/i)).toBeInTheDocument();
    expect(screen.getByDisplayValue("482913")).toBeInTheDocument();
    expect(screen.getByDisplayValue(/tok_abc123/)).toBeInTheDocument();
  });

  it("revokes an existing share from Manage sharing", async () => {
    (api.shares as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: "share-1",
          recipient_name: "Priya",
          recipient_email: "priya@example.com",
          share_type: "mykhaya_user",
          created_at: "2026-08-01T00:00:00Z",
          last_accessed_at: null,
          revoked: false,
        },
      ],
    });
    (api.revokeShare as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);

    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /wishlist actions/i }));
    await user.click(screen.getByRole("button", { name: /manage sharing/i }));
    await screen.findByText("Priya");
    await user.click(screen.getByRole("button", { name: /revoke access/i }));

    expect(api.revokeShare).toHaveBeenCalledWith("home-1", "wl-1", "share-1");
  });
});
