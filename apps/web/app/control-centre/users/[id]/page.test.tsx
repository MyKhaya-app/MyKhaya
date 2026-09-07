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
  created_at: "2026-01-01T00:00:00Z",
  last_login_at: "2026-02-01T00:00:00Z",
  homes: [{ id: "home-1", name: "The Smiths", role: "owner" }],
  sessions: [{ id: "s1", user_agent: "Chrome on macOS", last_seen_at: "2026-03-01T00:00:00Z", expires_at: "2026-04-01T00:00:00Z" }],
  notes: [{ id: "note-1", body: "Called about billing.", created_at: "2026-02-15T00:00:00Z" }],
};
const unverifiedUser = { ...verifiedUser, verified: false };
const suspendedUser = { ...verifiedUser, active: false };
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

  it("shows Suspended status when the user is suspended", async () => {
    get.mockResolvedValue(suspendedUser);
    render(<DetailPage />);
    await screen.findByText("Jane Smith");
    expect(screen.getAllByText("Suspended").length).toBeGreaterThan(0);
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
