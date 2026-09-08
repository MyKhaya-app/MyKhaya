import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DetailPage from "./page";

const { routerPush } = vi.hoisted(() => ({ routerPush: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush, replace: vi.fn() }),
  useParams: () => ({ id: "home-1" }),
  usePathname: () => "/homes/home-1",
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
const put = platformApi.put as unknown as ReturnType<typeof vi.fn>;

const activeHome = {
  id: "home-1",
  name: "The Smiths",
  active: true,
  lifecycle: "active" as const,
  created_at: "2026-01-01T00:00:00Z",
  members: [{ user_id: "u1", display_name: "Jane Smith", email: "jane@example.com", role: "owner" }],
  pending_invitations: [{ id: "inv-1", email: "invitee@example.com", role: "member", expires_at: "2026-12-01T00:00:00Z" }],
  feature_overrides: [{ feature: "calendar", enabled: true }],
  notes: [{ id: "note-1", body: "Called about billing.", created_at: "2026-02-01T00:00:00Z" }],
};
const suspendedHome = { ...activeHome, active: false, lifecycle: "disabled" as const };
const archivedHome = { ...activeHome, active: false, lifecycle: "archived" as const };
const emptyHome = { ...activeHome, members: [], pending_invitations: [], notes: [] };

function findDialog(name: RegExp | string) {
  return screen.findByRole("dialog", { name });
}

beforeEach(() => {
  vi.clearAllMocks();
  routerPush.mockClear();
  get.mockResolvedValue(activeHome);
  post.mockResolvedValue({ message: "ok" });
  put.mockResolvedValue({});
});

describe("Home detail", () => {
  it("renders home metadata and an Active status", async () => {
    render(<DetailPage />);
    expect(await screen.findByText("The Smiths")).toBeInTheDocument();
    expect(screen.getAllByText("Active").length).toBeGreaterThan(0);
    expect(screen.getByText("home-1")).toBeInTheDocument();
  });

  it("shows a Disabled status and a Reactivate action when the home is suspended", async () => {
    get.mockResolvedValue(suspendedHome);
    render(<DetailPage />);
    expect(await screen.findByText("The Smiths")).toBeInTheDocument();
    expect(screen.getAllByText("Disabled").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Reactivate Home" })).toBeInTheDocument();
  });

  it("renders memberships, invitations and notes", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    expect(screen.getByText("Jane Smith")).toBeInTheDocument();
    expect(screen.getByText(/jane@example.com/)).toBeInTheDocument();
    expect(screen.getByText("invitee@example.com")).toBeInTheDocument();
    expect(screen.getByText("Called about billing.")).toBeInTheDocument();
  });

  it("shows empty states when there are no members, invitations or notes", async () => {
    get.mockResolvedValue(emptyHome);
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    expect(screen.getByText("No members yet.")).toBeInTheDocument();
    expect(screen.getByText("No pending invitations.")).toBeInTheDocument();
    expect(screen.getByText("No administrative notes yet.")).toBeInTheDocument();
  });

  it("requires a reason of at least 10 characters before suspending, and sends the exact payload", async () => {
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Suspend Home" }));
    const dialog = await findDialog(/Suspend Home/i);
    const confirmButton = within(dialog).getByRole("button", { name: "Suspend Home" });
    const reasonInput = within(dialog).getByLabelText(/reason for this administrative action/i);
    expect(reasonInput).toHaveAttribute("minLength", "10");
    expect(reasonInput).toHaveAttribute("maxLength", "500");
    expect(reasonInput).toBeRequired();

    await userEvent.type(reasonInput, "Suspending pending a billing dispute");
    await userEvent.click(confirmButton);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/homes/home-1/suspend", {
        reason: "Suspending pending a billing dispute",
        confirmed: true,
      }),
    );
  });

  it("reactivates symmetrically", async () => {
    get.mockResolvedValue(suspendedHome);
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Reactivate Home" }));
    const dialog = await findDialog(/Reactivate Home/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Reactivating per request");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reactivate Home" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/homes/home-1/reactivate", {
        reason: "Reactivating per request",
        confirmed: true,
      }),
    );
  });

  it("requires confirmation and a reason to toggle a feature flag, and sends it to the exact endpoint", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    // calendar is enabled in the fixture, so its action is "Disable".
    const calendarRow = screen.getByText("calendar").closest("article")!;
    await userEvent.click(within(calendarRow).getByRole("button", { name: "Disable" }));
    const dialog = await findDialog(/Disable calendar/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Turning off calendar module");
    await userEvent.click(within(dialog).getByRole("button", { name: "Disable" }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/homes/home-1/feature-flags/calendar", {
        enabled: false,
        reason: "Turning off calendar module",
        confirmed: true,
      }),
    );
  });

  it("adds a note without requiring a reason and reloads", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    await userEvent.type(screen.getByLabelText("New internal note"), "A fresh note");
    await userEvent.click(screen.getByRole("button", { name: "Add administrative note" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/homes/home-1/notes", { body: "A fresh note" }));
    await waitFor(() =>
      expect(get.mock.calls.filter((call) => call[0] === "/homes/home-1")).toHaveLength(2),
    );
  });

  it("shows the reauth modal on a 403 and retries suspend after re-authenticating", async () => {
    post.mockImplementation((path: string) => {
      if (path === "/auth/reauthenticate") return Promise.resolve(undefined);
      if (path === "/homes/home-1/suspend") {
        const attempts = post.mock.calls.filter((call) => call[0] === "/homes/home-1/suspend").length;
        if (attempts === 1) return Promise.reject(new ApiError(403, "Recent administrator authentication required."));
        return Promise.resolve({ message: "Home suspended." });
      }
      return Promise.resolve({ message: "ok" });
    });
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Suspend Home" }));
    const dialog = await findDialog(/Suspend Home/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Suspending for review");
    await userEvent.click(within(dialog).getByRole("button", { name: "Suspend Home" }));

    const reauthDialog = await screen.findByRole("dialog", { name: /Confirm it.?s you/i });
    await userEvent.type(within(reauthDialog).getByLabelText("Password"), "operator-password");
    await userEvent.click(within(reauthDialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.getByText("Home suspended.")).toBeInTheDocument());
    expect(post.mock.calls.filter((call) => call[0] === "/homes/home-1/suspend")).toHaveLength(2);
  });

  it("shows a safe error message when an action fails", async () => {
    post.mockRejectedValueOnce(new Error("Home not found"));
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Suspend Home" }));
    const dialog = await findDialog(/Suspend Home/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Suspending for review");
    await userEvent.click(within(dialog).getByRole("button", { name: "Suspend Home" }));
    expect(await screen.findByText("Home not found")).toBeInTheDocument();
  });
});

describe("Home detail — Archive lifecycle", () => {
  it("offers both Suspend and Archive for an active Home", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    expect(screen.getByRole("button", { name: "Suspend Home" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Archive Home" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Restore Home" })).not.toBeInTheDocument();
  });

  it("offers Reactivate and Archive for a disabled Home", async () => {
    get.mockResolvedValue(suspendedHome);
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    expect(screen.getByRole("button", { name: "Reactivate Home" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Archive Home" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Suspend Home" })).not.toBeInTheDocument();
  });

  it("shows Archived status and only a Restore action for an archived Home", async () => {
    get.mockResolvedValue(archivedHome);
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    expect(screen.getAllByText("Archived").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Restore Home" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Suspend Home" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reactivate Home" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Archive Home" })).not.toBeInTheDocument();
  });

  it("archives a Home with a reason and reloads", async () => {
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Archive Home" }));
    const dialog = await findDialog(/Archive Home/i);
    await userEvent.type(
      within(dialog).getByLabelText(/reason for this administrative action/i),
      "Duplicate test Home",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Archive Home" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/homes/home-1/archive", {
        reason: "Duplicate test Home",
        confirmed: true,
      }),
    );
  });

  it("restores an archived Home with a reason and reloads", async () => {
    get.mockResolvedValue(archivedHome);
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Restore Home" }));
    const dialog = await findDialog(/Restore Home/i);
    await userEvent.type(
      within(dialog).getByLabelText(/reason for this administrative action/i),
      "Restoring by request",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Restore Home" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/homes/home-1/restore", {
        reason: "Restoring by request",
        confirmed: true,
      }),
    );
  });

  it("shows a clear API error when restore is rejected (e.g. no Home Admin)", async () => {
    get.mockResolvedValue(archivedHome);
    post.mockRejectedValueOnce(
      new ApiError(409, "This Home has no Home Admin. Assign one before restoring it."),
    );
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Restore Home" }));
    const dialog = await findDialog(/Restore Home/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Restoring");
    await userEvent.click(within(dialog).getByRole("button", { name: "Restore Home" }));
    expect(
      await screen.findByText("This Home has no Home Admin. Assign one before restoring it."),
    ).toBeInTheDocument();
  });
});

describe("Home detail — Move member", () => {
  beforeEach(() => {
    get.mockImplementation((path: string) => {
      if (path === "/homes/home-1") return Promise.resolve(activeHome);
      if (path.startsWith("/homes?")) {
        return Promise.resolve({
          items: [{ id: "home-2", name: "Carol's Home", active: true, member_count: 1 }],
        });
      }
      return Promise.resolve(activeHome);
    });
  });

  it("opens the Move member dialog from a member row, fixed to this Home as the source", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    const memberRow = screen.getByText("Jane Smith").closest("article")!;
    await userEvent.click(within(memberRow).getByRole("button", { name: "Move" }));

    const dialog = await findDialog(/Move member/i);
    // Source Home is fixed to this Home — no "From Home" picker, since there
    // is only ever one source Home when opened from a Home's own member row.
    expect(within(dialog).queryByLabelText(/from home/i)).not.toBeInTheDocument();
    expect(within(dialog).getByText("The Smiths")).toBeInTheDocument();
  });

  it("moves the member and reloads this Home afterwards", async () => {
    post.mockImplementation((path: string) => {
      if (path === "/users/u1/move-home") return Promise.resolve({ source_disposition: "left_unchanged" });
      return Promise.resolve({ message: "ok" });
    });
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    const memberRow = screen.getByText("Jane Smith").closest("article")!;
    await userEvent.click(within(memberRow).getByRole("button", { name: "Move" }));

    const dialog = await findDialog(/Move member/i);
    await userEvent.type(within(dialog).getByLabelText(/find destination home/i), "Carol's Home");
    await userEvent.click(within(dialog).getByRole("button", { name: "Search" }));
    await userEvent.click(await within(dialog).findByRole("button", { name: /Carol's Home/ }));
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Reconciling Homes");
    await userEvent.click(within(dialog).getByRole("button", { name: "Move member" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/users/u1/move-home", {
        source_group_id: "home-1",
        destination_group_id: "home-2",
        destination_relationship: "partner",
        source_disposition: "leave",
        reason: "Reconciling Homes",
        confirmed: true,
      }),
    );
    expect(await screen.findByText(/moved to Carol's Home/i)).toBeInTheDocument();
    await waitFor(() =>
      expect(get.mock.calls.filter((call) => call[0] === "/homes/home-1")).toHaveLength(2),
    );
  });
});

describe("Home detail — Permanent delete", () => {
  function mockEligibility(blockers: string[]) {
    get.mockImplementation((path: string) => {
      if (path === "/homes/home-1") return Promise.resolve(archivedHome);
      if (path === "/homes/home-1/permanent-delete/eligibility") {
        return Promise.resolve({ eligible: blockers.length === 0, blockers });
      }
      return Promise.resolve(archivedHome);
    });
  }

  it("only offers Permanently delete Home for an archived Home, not active/disabled", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    expect(screen.queryByRole("button", { name: "Permanently delete Home" })).not.toBeInTheDocument();

    get.mockResolvedValue(suspendedHome);
    render(<DetailPage />);
    await screen.findAllByText("The Smiths");
    expect(screen.queryByRole("button", { name: "Permanently delete Home" })).not.toBeInTheDocument();

    mockEligibility([]);
    render(<DetailPage />);
    await screen.findAllByText("The Smiths");
    expect(screen.getByRole("button", { name: "Permanently delete Home" })).toBeInTheDocument();
  });

  it("checks eligibility on open and blocks confirmation while a blocker is present", async () => {
    mockEligibility(["has_active_members"]);
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Permanently delete Home" }));
    const dialog = await findDialog(/Permanently delete Home/i);
    expect(await within(dialog).findByText(/cannot be permanently deleted yet/i)).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/type this home.?s name/i), "The Smiths");
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Accidental test Home");
    await userEvent.click(within(dialog).getByRole("button", { name: "Permanently delete Home" }));
    expect(post).not.toHaveBeenCalledWith("/homes/home-1/permanent-delete", expect.anything());
    expect(routerPush).not.toHaveBeenCalled();
  });

  it("submits the typed name confirmation and reason, then navigates back to Homes", async () => {
    mockEligibility([]);
    post.mockResolvedValue({ message: "Home permanently deleted." });
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Permanently delete Home" }));
    const dialog = await findDialog(/Permanently delete Home/i);
    await within(dialog).findByLabelText(/type this home.?s name/i);
    await userEvent.type(within(dialog).getByLabelText(/type this home.?s name/i), "The Smiths");
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Accidental test Home");
    await userEvent.click(within(dialog).getByRole("button", { name: "Permanently delete Home" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/homes/home-1/permanent-delete", {
        reason: "Accidental test Home",
        confirmation_text: "The Smiths",
        confirmed: true,
      }),
    );
    await waitFor(() => expect(routerPush).toHaveBeenCalledWith("/homes"));
  });
});
