import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CleanupPage from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/control-centre/cleanup",
}));
vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    platformApi: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
const { platformApi, ApiError } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;
const post = platformApi.post as unknown as ReturnType<typeof vi.fn>;

const homeRows = [
  {
    id: "home-1",
    name: "Test Home Active",
    lifecycle: "active",
    member_count: 2,
    created_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "home-2",
    name: "Test Home Archived",
    lifecycle: "archived",
    member_count: 0,
    created_at: "2026-01-02T00:00:00Z",
  },
];

const userRows = [
  {
    id: "user-1",
    display_name: "Alice Test",
    email: "alice@example.com",
    lifecycle: "active",
    home_count: 1,
    created_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "user-2",
    display_name: "Bob Test",
    email: "bob@example.com",
    lifecycle: "active",
    home_count: 1,
    created_at: "2026-01-02T00:00:00Z",
  },
];

function mockLists() {
  get.mockImplementation((path: string) => {
    if (path.startsWith("/homes?")) return Promise.resolve({ items: homeRows });
    if (path.startsWith("/users?")) return Promise.resolve({ items: userRows });
    return Promise.reject(new Error("unexpected GET " + path));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockLists();
  post.mockResolvedValue({ succeeded: [], failed: [] });
});

describe("Account & Home cleanup — loading and tabs", () => {
  it("loads the Homes tab by default", async () => {
    render(<CleanupPage />);
    expect(await screen.findByText("Test Home Active")).toBeInTheDocument();
    expect(screen.getByText("Test Home Archived")).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith(expect.stringContaining("/homes?"));
  });

  it("switches to the Users tab and loads users", async () => {
    const user = userEvent.setup();
    render(<CleanupPage />);
    await screen.findByText("Test Home Active");
    await user.click(screen.getByRole("tab", { name: "Users" }));
    expect(await screen.findByText("Alice Test")).toBeInTheDocument();
    expect(screen.getByText("Bob Test")).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith(expect.stringContaining("/users?"));
  });
});

describe("Account & Home cleanup — search and filter", () => {
  it("searches Homes by name on Enter", async () => {
    const user = userEvent.setup();
    render(<CleanupPage />);
    await screen.findByText("Test Home Active");
    await user.type(screen.getByLabelText("Search Homes"), "Test Home{Enter}");
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith(expect.stringContaining("q=Test")),
    );
  });

  it("re-fetches with the selected lifecycle filter", async () => {
    const user = userEvent.setup();
    render(<CleanupPage />);
    await screen.findByText("Test Home Active");
    await user.selectOptions(screen.getByLabelText("Lifecycle filter"), "archived");
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith(expect.stringContaining("lifecycle=archived")),
    );
  });

  it("defaults the lifecycle filter to Active", async () => {
    render(<CleanupPage />);
    await screen.findByText("Test Home Active");
    expect(screen.getByLabelText("Lifecycle filter")).toHaveValue("active");
    expect(get).toHaveBeenCalledWith(expect.stringContaining("lifecycle=active"));
  });
});

describe("Account & Home cleanup — selection and state-aware actions", () => {
  it("selects rows individually and via select-all", async () => {
    const user = userEvent.setup();
    render(<CleanupPage />);
    await screen.findByText("Test Home Active");
    expect(screen.getByText("0 selected")).toBeInTheDocument();

    await user.click(screen.getByLabelText("Select Test Home Active"));
    expect(screen.getByText("1 selected")).toBeInTheDocument();

    await user.click(screen.getByLabelText("Select all Homes in this list"));
    expect(screen.getByText("2 selected")).toBeInTheDocument();

    await user.click(screen.getByLabelText("Select all Homes in this list"));
    expect(screen.getByText("0 selected")).toBeInTheDocument();
  });

  it("disables Disable selected once the selection includes an Archived Home", async () => {
    const user = userEvent.setup();
    render(<CleanupPage />);
    await screen.findByText("Test Home Active");
    await user.click(screen.getByLabelText("Select Test Home Active"));
    expect(screen.getByRole("button", { name: /Disable selected/ })).not.toBeDisabled();

    await user.click(screen.getByLabelText("Select Test Home Archived"));
    expect(screen.getByRole("button", { name: /Disable selected/ })).toBeDisabled();
    // Archive remains available for an already-archived record (idempotent).
    expect(screen.getByRole("button", { name: /Archive selected/ })).not.toBeDisabled();
  });

  it("keeps both bulk buttons disabled with nothing selected", async () => {
    render(<CleanupPage />);
    await screen.findByText("Test Home Active");
    expect(screen.getByRole("button", { name: /Disable selected/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Archive selected/ })).toBeDisabled();
  });
});

describe("Account & Home cleanup — bulk actions", () => {
  async function selectActiveHome() {
    const user = userEvent.setup();
    render(<CleanupPage />);
    await screen.findByText("Test Home Active");
    await user.click(screen.getByLabelText("Select Test Home Active"));
    return user;
  }

  it("shows a Disable confirmation naming the selected Home and requires a reason", async () => {
    const user = await selectActiveHome();
    await user.click(screen.getByRole("button", { name: /Disable selected/ }));
    const dialog = await screen.findByRole("dialog", { name: /Disable 1 Home\?/ });
    expect(within(dialog).getByText(/disappear from normal operational use/)).toBeInTheDocument();
    expect(within(dialog).getByText("Test Home Active")).toBeInTheDocument();
    const confirmButton = within(dialog).getByRole("button", { name: /Disable 1/ });
    expect(confirmButton).toBeDisabled();

    await user.type(
      within(dialog).getByLabelText(/reason for this administrative action/i),
      "Cleaning up test data",
    );
    expect(confirmButton).not.toBeDisabled();
  });

  it("submits the exact bulk-lifecycle payload for Archive", async () => {
    const user = await selectActiveHome();
    await user.click(screen.getByRole("button", { name: /Archive selected/ }));
    const dialog = await screen.findByRole("dialog", { name: /Archive 1 Home\?/ });
    await user.type(
      within(dialog).getByLabelText(/reason for this administrative action/i),
      "Removing duplicate test Home",
    );
    await user.click(within(dialog).getByRole("button", { name: /Archive 1/ }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/homes/bulk-lifecycle", {
        ids: ["home-1"],
        action: "archive",
        reason: "Removing duplicate test Home",
        confirmed: true,
      }),
    );
  });

  it("shows a success summary and reloads the list, clearing the selection", async () => {
    post.mockResolvedValueOnce({ succeeded: ["home-1"], failed: [] });
    const user = await selectActiveHome();
    await user.click(screen.getByRole("button", { name: /Archive selected/ }));
    const dialog = await screen.findByRole("dialog", { name: /Archive 1 Home\?/ });
    await user.type(
      within(dialog).getByLabelText(/reason for this administrative action/i),
      "Removing duplicate test Home",
    );
    await user.click(within(dialog).getByRole("button", { name: /Archive 1/ }));

    expect(await screen.findByText("Archived: 1")).toBeInTheDocument();
    await waitFor(() => expect(get.mock.calls.filter((c) => String(c[0]).startsWith("/homes?"))).toHaveLength(2));
    expect(screen.getByText("0 selected")).toBeInTheDocument();
  });

  it("shows a partial-failure summary with per-item reasons", async () => {
    post.mockResolvedValueOnce({
      succeeded: ["home-1"],
      failed: [{ id: "home-2", code: "archived", message: "This Home is archived. Restore the Home instead." }],
    });
    const user = userEvent.setup();
    render(<CleanupPage />);
    await screen.findByText("Test Home Active");
    await user.click(screen.getByLabelText("Select all Homes in this list"));
    await user.click(screen.getByRole("button", { name: /Archive selected/ }));
    const dialog = await screen.findByRole("dialog", { name: /Archive 2 Homes\?/ });
    await user.type(
      within(dialog).getByLabelText(/reason for this administrative action/i),
      "Cleaning up duplicates",
    );
    await user.click(within(dialog).getByRole("button", { name: /Archive 2/ }));

    expect(await screen.findByText(/Archived: 1/)).toBeInTheDocument();
    expect(screen.getByText(/Could not update 1/)).toBeInTheDocument();
    expect(
      screen.getByText(/Test Home Archived.*This Home is archived\. Restore the Home instead\./),
    ).toBeInTheDocument();
  });

  it("shows a clear API error inside the dialog when the bulk request itself fails", async () => {
    post.mockRejectedValueOnce(new ApiError(422, "Too many targets in one request."));
    const user = await selectActiveHome();
    await user.click(screen.getByRole("button", { name: /Archive selected/ }));
    const dialog = await screen.findByRole("dialog", { name: /Archive 1 Home\?/ });
    await user.type(
      within(dialog).getByLabelText(/reason for this administrative action/i),
      "Cleaning up duplicates",
    );
    await user.click(within(dialog).getByRole("button", { name: /Archive 1/ }));
    expect(await within(dialog).findByText("Too many targets in one request.")).toBeInTheDocument();
  });

  it("submits bulk-lifecycle for Users with the correct entity path", async () => {
    const user = userEvent.setup();
    render(<CleanupPage />);
    await screen.findByText("Test Home Active");
    await user.click(screen.getByRole("tab", { name: "Users" }));
    await screen.findByText("Alice Test");
    await user.click(screen.getByLabelText("Select Alice Test"));
    await user.click(screen.getByRole("button", { name: /Disable selected/ }));
    const dialog = await screen.findByRole("dialog", { name: /Disable 1 user\?/ });
    await user.type(
      within(dialog).getByLabelText(/reason for this administrative action/i),
      "Removing test account",
    );
    await user.click(within(dialog).getByRole("button", { name: /Disable 1/ }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/users/bulk-lifecycle", {
        ids: ["user-1"],
        action: "disable",
        reason: "Removing test account",
        confirmed: true,
      }),
    );
  });
});
