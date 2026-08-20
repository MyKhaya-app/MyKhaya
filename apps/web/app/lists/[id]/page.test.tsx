import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ListDetailPage from "./page";

// Coverage for an individual List — add item, complete/uncomplete
// (optimistic, with rollback on failure), edit, delete, clear completed.
// See docs/architecture/lists.md.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/lists/list-1",
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
      members: vi.fn(),
      list: vi.fn(),
      addListItem: vi.fn(),
      updateListItem: vi.fn(),
      removeListItem: vi.fn(),
      clearCompletedListItems: vi.fn(),
      reorderListItems: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

function detail(overrides: Record<string, unknown> = {}) {
  return {
    id: "list-1",
    name: "Groceries",
    icon: "groceries",
    items: [
      { id: "item-1", position: 0, text: "Milk", quantity: null, note: null, assigned_member_id: null, is_checked: false, completed_at: null, completed_by: null },
      { id: "item-2", position: 1, text: "Bread", quantity: null, note: null, assigned_member_id: null, is_checked: true, completed_at: "2026-08-20T10:00:00Z", completed_by: "u1" },
    ],
    item_count: 2,
    remaining_count: 1,
    created_by: "u1",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

/**
 * `use()` reads a promise synchronously without suspending if the promise
 * already carries React's internal "fulfilled" cache shape — which is how
 * Next.js's own already-resolved `params` promises behave in practice. See
 * the identical helper in
 * app/control-centre/subscriptions/[id]/page.test.tsx.
 */
function resolvedParams(id: string): Promise<{ id: string }> {
  const promise = Promise.resolve({ id }) as Promise<{ id: string }> & {
    status?: string;
    value?: { id: string };
  };
  promise.status = "fulfilled";
  promise.value = { id };
  return promise;
}

function renderPage() {
  return render(<ListDetailPage params={resolvedParams("list-1")} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
    id: "u1",
    display_name: "Megan",
    principal_type: "adult",
  });
  (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (api.list as ReturnType<typeof vi.fn>).mockResolvedValue(detail());
});

describe("List detail — rendering", () => {
  it("shows items with completed ones visually distinguished, not hidden", async () => {
    renderPage();

    expect(await screen.findByText("Milk")).toBeInTheDocument();
    expect(screen.getByText("Bread")).toBeInTheDocument();
    expect(screen.getByText(/1 of 2 remaining/i)).toBeInTheDocument();
  });

  it("shows a calm not-found state for a missing list rather than a raw error", async () => {
    const { ApiError } = await import("@mykhaya/api-client");
    (api.list as ReturnType<typeof vi.fn>).mockRejectedValue(new ApiError(404, "Not found"));

    renderPage();

    expect(await screen.findByText(/that list could not be found/i)).toBeInTheDocument();
    expect(screen.queryByText(/^not found$/i)).not.toBeInTheDocument();
  });
});

describe("List detail — adding items", () => {
  it("adds an item and clears the input for the next one", async () => {
    (api.addListItem as ReturnType<typeof vi.fn>).mockResolvedValue(
      detail({
        items: [
          ...detail().items,
          { id: "item-3", position: 2, text: "Bananas", quantity: null, note: null, assigned_member_id: null, is_checked: false, completed_at: null, completed_by: null },
        ],
        item_count: 3,
        remaining_count: 2,
      }),
    );

    renderPage();
    await screen.findByLabelText(/add an item/i);
    // AppShell's own async bootstrap (api.me) can still be settling once
    // the input first appears, which briefly remounts the tree — wait for
    // that to fully settle before interacting, or the very next keystroke
    // can land on an already-detached input.
    await waitFor(() => expect(api.members).toHaveBeenCalled());
    const input = screen.getByLabelText(/add an item/i);
    fireEvent.input(input, { target: { value: "Bananas" } });
    await waitFor(() => expect(input).toHaveValue("Bananas"));
    fireEvent.click(screen.getByRole("button", { name: /add item/i }));

    await waitFor(() =>
      expect(api.addListItem).toHaveBeenCalledWith("home-1", "list-1", { text: "Bananas" }),
    );
    // Re-query rather than reuse the earlier reference, matching the
    // rollback test above.
    await waitFor(() => expect(screen.getByLabelText(/add an item/i)).toHaveValue(""));
  });
});

describe("List detail — completion", () => {
  it("toggles a checkbox optimistically and rolls back on failure", async () => {
    (api.updateListItem as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("network down"));

    renderPage();
    const checkbox = await screen.findByRole("checkbox", { name: /mark milk complete/i });
    const user = userEvent.setup();
    await user.click(checkbox);

    // Optimistic: briefly checked...
    expect(checkbox).toBeChecked();
    // ...then rolled back once the request fails.
    expect(await screen.findByText(/could not update that item/i)).toBeInTheDocument();
    // Re-query rather than reuse the earlier reference — the row may have
    // re-rendered with a fresh element for the same aria-label.
    expect(await screen.findByRole("checkbox", { name: /mark milk complete/i })).not.toBeChecked();
  });

  it("commits the toggle on success", async () => {
    (api.updateListItem as ReturnType<typeof vi.fn>).mockResolvedValue(
      detail({
        items: [
          { ...detail().items[0], is_checked: true },
          detail().items[1],
        ],
        remaining_count: 0,
      }),
    );

    renderPage();
    const checkbox = await screen.findByRole("checkbox", { name: /mark milk complete/i });
    const user = userEvent.setup();
    await user.click(checkbox);

    expect(api.updateListItem).toHaveBeenCalledWith("home-1", "list-1", "item-1", {
      is_checked: true,
    });
  });
});

describe("List detail — edit and delete", () => {
  it("edits an item's text via the edit sheet", async () => {
    (api.updateListItem as ReturnType<typeof vi.fn>).mockResolvedValue(
      detail({ items: [{ ...detail().items[0], text: "Semi-skimmed milk" }, detail().items[1]] }),
    );

    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Milk" }));

    const textInput = screen.getByLabelText(/^item$/i);
    await user.clear(textInput);
    await user.type(textInput, "Semi-skimmed milk");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(api.updateListItem).toHaveBeenCalledWith(
      "home-1",
      "list-1",
      "item-1",
      expect.objectContaining({ text: "Semi-skimmed milk" }),
    );
  });

  it("removes an item from the edit sheet", async () => {
    (api.removeListItem as ReturnType<typeof vi.fn>).mockResolvedValue(
      detail({ items: [detail().items[1]], item_count: 1, remaining_count: 0 }),
    );

    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Milk" }));
    await user.click(screen.getByRole("button", { name: /remove item/i }));

    expect(api.removeListItem).toHaveBeenCalledWith("home-1", "list-1", "item-1");
  });
});

describe("List detail — clear completed", () => {
  it("clears completed items after confirmation", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    (api.clearCompletedListItems as ReturnType<typeof vi.fn>).mockResolvedValue(
      detail({ items: [detail().items[0]], item_count: 1, remaining_count: 1 }),
    );

    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /list actions/i }));
    await user.click(screen.getByRole("button", { name: /clear completed/i }));

    expect(api.clearCompletedListItems).toHaveBeenCalledWith("home-1", "list-1");
  });
});
