import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DetailPage from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useParams: () => ({ id: "user-1" }),
  usePathname: () => "/users/user-1",
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

const verifiedUser = {
  id: "user-1",
  email: "jane@example.com",
  display_name: "Jane Smith",
  verified: true,
  active: true,
  lifecycle: "active" as const,
  created_at: "2026-01-01T00:00:00Z",
  last_login_at: "2026-02-01T00:00:00Z",
  homes: [{ id: "home-1", name: "The Smiths", role: "owner" }],
  sessions: [{ id: "s1", user_agent: "Chrome on macOS", last_seen_at: "2026-03-01T00:00:00Z", expires_at: "2026-04-01T00:00:00Z" }],
  notes: [{ id: "note-1", body: "Called about billing.", created_at: "2026-02-15T00:00:00Z" }],
};
const unverifiedUser = { ...verifiedUser, verified: false };
const suspendedUser = { ...verifiedUser, active: false, lifecycle: "disabled" as const };
const archivedUser = { ...verifiedUser, active: false, lifecycle: "archived" as const };
const anonymisedUser = {
  ...verifiedUser,
  active: false,
  lifecycle: "anonymised" as const,
  display_name: "Deleted user",
  email: "deleted-user-1@removed.mykhaya.invalid",
  anonymised_at: "2026-03-05T00:00:00Z",
};
const emptyUser = { ...verifiedUser, homes: [], sessions: [], notes: [] };

function findDialog(name: RegExp | string) {
  return screen.findByRole("dialog", { name });
}

beforeEach(() => {
  vi.clearAllMocks();
  get.mockResolvedValue(verifiedUser);
  post.mockResolvedValue({ message: "ok" });
});

describe("User detail", () => {
  it("renders account metadata and an Active status", async () => {
    render(<DetailPage />);
    expect(await screen.findByText("Jane Smith")).toBeInTheDocument();
    expect(screen.getByText("jane@example.com")).toBeInTheDocument();
    expect(screen.getAllByText("Active").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Verified").length).toBeGreaterThan(0);
  });

  it("shows Disabled status when the user is suspended", async () => {
    get.mockResolvedValue(suspendedUser);
    render(<DetailPage />);
    await screen.findByText("Jane Smith");
    expect(screen.getAllByText("Disabled").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Reactivate user" })).toBeInTheDocument();
  });

  it("only shows Resend verification when the user is unverified", async () => {
    render(<DetailPage />);
    await screen.findByText("Jane Smith");
    expect(screen.queryByRole("button", { name: "Resend verification email" })).not.toBeInTheDocument();

    get.mockResolvedValue(unverifiedUser);
    render(<DetailPage />);
    expect(await screen.findByRole("button", { name: "Resend verification email" })).toBeInTheDocument();
  });

  it("renders homes, sessions and notes, and empty states when there are none", async () => {
    render(<DetailPage />);
    await screen.findByText("Jane Smith");
    expect(screen.getByText("The Smiths")).toBeInTheDocument();
    expect(screen.getByText("Chrome on macOS")).toBeInTheDocument();
    expect(screen.getByText("Called about billing.")).toBeInTheDocument();

    get.mockResolvedValue(emptyUser);
    render(<DetailPage />);
    await screen.findAllByText("Jane Smith");
    expect(screen.getByText("Not a member of any Home.")).toBeInTheDocument();
    expect(screen.getByText("No active sessions.")).toBeInTheDocument();
    expect(screen.getByText("No administrative notes yet.")).toBeInTheDocument();
  });

  it("requires a reason before suspending, and sends the exact payload", async () => {
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Suspend user" }));
    const dialog = await findDialog(/Suspend user/i);
    const confirmButton = within(dialog).getByRole("button", { name: "Suspend user" });
    const reasonInput = within(dialog).getByLabelText(/reason for this administrative action/i);
    expect(reasonInput).toHaveAttribute("minLength", "10");
    expect(reasonInput).toHaveAttribute("maxLength", "500");
    expect(reasonInput).toBeRequired();

    await userEvent.type(reasonInput, "Suspicious billing activity");
    await userEvent.click(confirmButton);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/users/user-1/suspend", { reason: "Suspicious billing activity", confirmed: true }),
    );
  });

  it("reactivates symmetrically", async () => {
    get.mockResolvedValue(suspendedUser);
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Reactivate user" }));
    const dialog = await findDialog(/Reactivate user/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Reactivating per request");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reactivate user" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/users/user-1/reactivate", { reason: "Reactivating per request", confirmed: true }),
    );
  });

  it("revokes all sessions with its own confirmation and reason", async () => {
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Revoke all sessions" }));
    const dialog = await findDialog(/Revoke all sessions/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Suspected compromise");
    await userEvent.click(within(dialog).getByRole("button", { name: "Revoke all sessions" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/users/user-1/revoke-sessions", { reason: "Suspected compromise", confirmed: true }),
    );
  });

  it("resends verification with its own confirmation and reason", async () => {
    get.mockResolvedValue(unverifiedUser);
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Resend verification email" }));
    const dialog = await findDialog(/Resend verification email/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "User requested resend");
    await userEvent.click(within(dialog).getByRole("button", { name: "Resend verification" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/users/user-1/resend-verification", { reason: "User requested resend", confirmed: true }),
    );
  });

  it("sends a password-reset email with its own confirmation and reason", async () => {
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Send password-reset email" }));
    const dialog = await findDialog(/Send password-reset email/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "User forgot password");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send reset email" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/users/user-1/send-password-reset", { reason: "User forgot password", confirmed: true }),
    );
  });

  it("adds a note without requiring a reason and reloads", async () => {
    render(<DetailPage />);
    await screen.findByText("Jane Smith");
    await userEvent.type(screen.getByLabelText("New internal note"), "A fresh note");
    await userEvent.click(screen.getByRole("button", { name: "Add administrative note" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/users/user-1/notes", { body: "A fresh note" }));
    await waitFor(() =>
      expect(get.mock.calls.filter((call) => call[0] === "/users/user-1")).toHaveLength(2),
    );
  });

  it("shows the reauth modal on a 403 and retries revoke-sessions after re-authenticating", async () => {
    post.mockImplementation((path: string) => {
      if (path === "/auth/reauthenticate") return Promise.resolve(undefined);
      if (path === "/users/user-1/revoke-sessions") {
        const attempts = post.mock.calls.filter((call) => call[0] === "/users/user-1/revoke-sessions").length;
        if (attempts === 1) return Promise.reject(new ApiError(403, "Recent administrator authentication required."));
        return Promise.resolve({ message: "All user sessions were revoked." });
      }
      return Promise.resolve({ message: "ok" });
    });
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Revoke all sessions" }));
    const dialog = await findDialog(/Revoke all sessions/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Suspected compromise");
    await userEvent.click(within(dialog).getByRole("button", { name: "Revoke all sessions" }));

    const reauthDialog = await screen.findByRole("dialog", { name: /Confirm it.?s you/i });
    await userEvent.type(within(reauthDialog).getByLabelText("Password"), "operator-password");
    await userEvent.click(within(reauthDialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.getByText("All user sessions were revoked.")).toBeInTheDocument());
    expect(post.mock.calls.filter((call) => call[0] === "/users/user-1/revoke-sessions")).toHaveLength(2);
  });

  it("shows a safe error message when an action fails", async () => {
    post.mockRejectedValueOnce(new Error("User not found"));
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Suspend user" }));
    const dialog = await findDialog(/Suspend user/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Suspending for review");
    await userEvent.click(within(dialog).getByRole("button", { name: "Suspend user" }));
    expect(await screen.findByText("User not found")).toBeInTheDocument();
  });
});

describe("User detail — Archive lifecycle", () => {
  it("offers both Suspend and Archive for an active user", async () => {
    render(<DetailPage />);
    await screen.findByText("Jane Smith");
    expect(screen.getByRole("button", { name: "Suspend user" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Archive user" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Restore user" })).not.toBeInTheDocument();
  });

  it("offers Reactivate and Archive for a disabled user", async () => {
    get.mockResolvedValue(suspendedUser);
    render(<DetailPage />);
    await screen.findByText("Jane Smith");
    expect(screen.getByRole("button", { name: "Reactivate user" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Archive user" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Suspend user" })).not.toBeInTheDocument();
  });

  it("shows Archived status and only a Restore action for an archived user — no Suspend/Reactivate/Archive", async () => {
    get.mockResolvedValue(archivedUser);
    render(<DetailPage />);
    await screen.findByText("Jane Smith");
    expect(screen.getAllByText("Archived").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Restore user" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Suspend user" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reactivate user" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Archive user" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Move member" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Revoke all sessions" })).not.toBeInTheDocument();
  });

  it("archives a user with a reason and reloads", async () => {
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Archive user" }));
    const dialog = await findDialog(/Archive user/i);
    await userEvent.type(
      within(dialog).getByLabelText(/reason for this administrative action/i),
      "Duplicate test account",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Archive user" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/users/user-1/archive", {
        reason: "Duplicate test account",
        confirmed: true,
      }),
    );
  });

  it("restores an archived user with a reason and reloads", async () => {
    get.mockResolvedValue(archivedUser);
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Restore user" }));
    const dialog = await findDialog(/Restore user/i);
    await userEvent.type(
      within(dialog).getByLabelText(/reason for this administrative action/i),
      "Restoring by request",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Restore user" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/users/user-1/restore", {
        reason: "Restoring by request",
        confirmed: true,
      }),
    );
  });

  it("shows the reauth modal on a 403 and retries archive after re-authenticating", async () => {
    post.mockImplementation((path: string) => {
      if (path === "/auth/reauthenticate") return Promise.resolve(undefined);
      if (path === "/users/user-1/archive") {
        const attempts = post.mock.calls.filter((call) => call[0] === "/users/user-1/archive").length;
        if (attempts === 1) return Promise.reject(new ApiError(403, "Recent administrator authentication required."));
        return Promise.resolve({ message: "User archived and sessions revoked." });
      }
      return Promise.resolve({ message: "ok" });
    });
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Archive user" }));
    const dialog = await findDialog(/Archive user/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Duplicate account");
    await userEvent.click(within(dialog).getByRole("button", { name: "Archive user" }));

    const reauthDialog = await screen.findByRole("dialog", { name: /Confirm it.?s you/i });
    await userEvent.type(within(reauthDialog).getByLabelText("Password"), "operator-password");
    await userEvent.click(within(reauthDialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.getByText("User archived and sessions revoked.")).toBeInTheDocument());
  });
});

describe("User detail — Move member", () => {
  function mockHomeSearch(items: { id: string; name: string; active: boolean; member_count: number }[]) {
    get.mockImplementation((path: string) => {
      if (path === "/users/user-1") return Promise.resolve(verifiedUser);
      if (path.startsWith("/homes?")) return Promise.resolve({ items });
      return Promise.resolve(verifiedUser);
    });
  }

  async function openAndFindDestination(
    home = { id: "home-2", name: "Carol's Home", active: true, member_count: 1 },
  ) {
    mockHomeSearch([home]);
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Move member" }));
    const dialog = await findDialog(/Move member/i);
    await userEvent.type(within(dialog).getByLabelText(/find destination home/i), home.name);
    await userEvent.click(within(dialog).getByRole("button", { name: "Search" }));
    await userEvent.click(await within(dialog).findByRole("button", { name: new RegExp(home.name) }));
    return dialog;
  }

  it("is not shown when the user has no active Home memberships", async () => {
    get.mockResolvedValue(emptyUser);
    render(<DetailPage />);
    await screen.findByText("Jane Smith");
    expect(screen.queryByRole("button", { name: "Move member" })).not.toBeInTheDocument();
  });

  it("renders the desktop two-column structure: source summary, destination results, and inline disposition options", async () => {
    const dialog = await openAndFindDestination();

    const sourcePanel = within(dialog).getByText("Source Home").closest("div")!;
    expect(within(sourcePanel).getByText("The Smiths")).toBeInTheDocument();
    expect(within(sourcePanel).getByText("owner")).toBeInTheDocument();

    expect(
      within(dialog).getByRole("button", { name: /Carol's Home/ }),
    ).toHaveTextContent("1 member");

    const dispositionGroup = within(dialog).getByRole("group", { name: /source home, once this member leaves/i });
    expect(within(dispositionGroup).getByLabelText("Leave unchanged")).toBeInTheDocument();
    expect(within(dispositionGroup).getByLabelText("Archive if empty")).toBeInTheDocument();
  });

  it("searches for and selects a destination Home, then submits the expected payload", async () => {
    const dialog = await openAndFindDestination();
    await userEvent.selectOptions(within(dialog).getByLabelText(/new relationship/i), "adult");
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Merging duplicate Homes");
    await userEvent.click(within(dialog).getByRole("button", { name: "Move member" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/users/user-1/move-home", {
        source_group_id: "home-1",
        destination_group_id: "home-2",
        destination_relationship: "adult",
        source_disposition: "leave",
        reason: "Merging duplicate Homes",
        confirmed: true,
      }),
    );
  });

  it("shows an impact summary naming the account-preservation guarantees before confirming", async () => {
    const dialog = await openAndFindDestination();
    expect(within(dialog).getByText(/Before you confirm/i, { selector: "h3" })).toBeInTheDocument();
    expect(
      within(dialog).getByText(/same user ID, and login credentials/i, { selector: "li" }),
    ).toBeInTheDocument();
    expect(within(dialog).getByText(/Passkeys, trusted devices/i, { selector: "li" })).toBeInTheDocument();
    expect(
      within(dialog).getByText(/this moves membership only, never Home data/i, { selector: "li" }),
    ).toBeInTheDocument();
  });

  it("disables Move member until a destination is chosen and a reason is entered", async () => {
    mockHomeSearch([{ id: "home-2", name: "Carol's Home", active: true, member_count: 1 }]);
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Move member" }));
    const dialog = await findDialog(/Move member/i);
    const confirmButton = within(dialog).getByRole("button", { name: "Move member" });
    expect(confirmButton).toBeDisabled();
  });

  it("shows a clear API error (e.g. the last-admin block) without crashing the dialog", async () => {
    post.mockRejectedValueOnce(
      new ApiError(409, "Assign another Home Admin in the source Home before moving this member."),
    );
    const dialog = await openAndFindDestination();
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Reconciling Homes");
    await userEvent.click(within(dialog).getByRole("button", { name: "Move member" }));
    expect(
      await within(dialog).findByText("Assign another Home Admin in the source Home before moving this member."),
    ).toBeInTheDocument();
  });

  it("shows a success message and reloads the user after a successful move", async () => {
    post.mockImplementation((path: string) => {
      if (path === "/users/user-1/move-home") return Promise.resolve({ source_disposition: "left_unchanged" });
      return Promise.resolve({ message: "ok" });
    });
    const dialog = await openAndFindDestination();
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Reconciling Homes");
    await userEvent.click(within(dialog).getByRole("button", { name: "Move member" }));

    expect(await screen.findByText(/moved to Carol's Home/i)).toBeInTheDocument();
    await waitFor(() =>
      expect(get.mock.calls.filter((call) => call[0] === "/users/user-1")).toHaveLength(2),
    );
  });
});

describe("User detail — Anonymise", () => {
  function mockEligibility(blockers: string[]) {
    get.mockImplementation((path: string) => {
      if (path === "/users/user-1") return Promise.resolve(archivedUser);
      if (path === "/users/user-1/anonymise/eligibility") return Promise.resolve({ eligible: blockers.length === 0, blockers });
      return Promise.resolve(archivedUser);
    });
  }

  it("only offers Anonymise user for an archived user, not active/disabled", async () => {
    render(<DetailPage />);
    await screen.findByText("Jane Smith");
    expect(screen.queryByRole("button", { name: "Anonymise user" })).not.toBeInTheDocument();

    get.mockResolvedValue(suspendedUser);
    render(<DetailPage />);
    await screen.findAllByText("Jane Smith");
    expect(screen.queryByRole("button", { name: "Anonymise user" })).not.toBeInTheDocument();

    mockEligibility([]);
    render(<DetailPage />);
    await screen.findAllByText("Jane Smith");
    expect(screen.getByRole("button", { name: "Anonymise user" })).toBeInTheDocument();
  });

  it("checks eligibility on open and blocks confirmation while a blocker is present", async () => {
    mockEligibility(["last_home_admin"]);
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Anonymise user" }));
    const dialog = await findDialog(/Anonymise user/i);
    expect(await within(dialog).findByText(/cannot be anonymised yet/i)).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/type this user.?s current email/i), "jane@example.com");
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Cleaning up test data");
    await userEvent.click(within(dialog).getByRole("button", { name: "Anonymise user" }));
    expect(post).not.toHaveBeenCalledWith("/users/user-1/anonymise", expect.anything());
  });

  it("submits the typed email confirmation and reason once eligible", async () => {
    mockEligibility([]);
    post.mockResolvedValue({ message: "User anonymised." });
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Anonymise user" }));
    const dialog = await findDialog(/Anonymise user/i);
    await within(dialog).findByLabelText(/type this user.?s current email/i);
    await userEvent.type(within(dialog).getByLabelText(/type this user.?s current email/i), "jane@example.com");
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Cleaning up test data");
    await userEvent.click(within(dialog).getByRole("button", { name: "Anonymise user" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/users/user-1/anonymise", {
        reason: "Cleaning up test data",
        confirmation_text: "jane@example.com",
        confirmed: true,
      }),
    );
  });

  it("shows an Anonymised status with no Restore action once anonymised", async () => {
    get.mockResolvedValue(anonymisedUser);
    render(<DetailPage />);
    await screen.findByText("Deleted user");
    expect(screen.getAllByText("Anonymised").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Restore user" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Anonymise user" })).not.toBeInTheDocument();
    expect(screen.queryByText("jane@example.com")).not.toBeInTheDocument();
  });
});
