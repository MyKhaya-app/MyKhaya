import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdministratorsPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/administrators",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    platformApi: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
const { platformApi, ApiError } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;
const post = platformApi.post as unknown as ReturnType<typeof vi.fn>;

const owner = {
  id: "op-1",
  email: "owner@example.com",
  display_name: "Owner",
  role: "platform_owner",
  mfa_enrolled: true,
  session_status: "full",
};
const nonOwner = { ...owner, id: "op-2", role: "platform_administrator" };

const administrators = [
  {
    id: "a1",
    email: "admin@example.com",
    display_name: "Ada Admin",
    role: "platform_administrator",
    active: true,
    mfa_enrolled: true,
    last_login_at: "2026-09-01T09:00:00Z",
  },
  {
    id: "a2",
    email: "inactive@example.com",
    display_name: "Ivy Inactive",
    role: "platform_administrator",
    active: false,
    mfa_enrolled: false,
    last_login_at: null,
  },
];

const invitations = [
  {
    id: "inv-1",
    email: "pending@example.com",
    role: "platform_administrator",
    state: "pending",
    invited_by_display_name: "Owner",
    created_at: "2026-09-01T09:00:00Z",
    expires_at: "2026-09-08T09:00:00Z",
  },
];

function mockLoad(actor: typeof owner | typeof nonOwner) {
  get.mockImplementation((path: string) => {
    if (path === "/auth/me") return Promise.resolve(actor);
    if (path === "/administrators") return Promise.resolve(administrators);
    if (path === "/administrators/invitations") return Promise.resolve(invitations);
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockLoad(owner);
  post.mockResolvedValue({});
});

describe("Administrators list", () => {
  it("renders administrators with role and state badges", async () => {
    render(<AdministratorsPage />);
    expect(await screen.findByText("Ada Admin")).toBeInTheDocument();
    expect(screen.getByText("admin@example.com")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Deactivated")).toBeInTheDocument();
    expect(screen.getByText("Enrolled")).toBeInTheDocument();
    expect(screen.getByText("Not enrolled")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ada Admin" })).toHaveAttribute("href", "/administrators/a1");
  });

  it("renders pending invitations for an owner", async () => {
    render(<AdministratorsPage />);
    await screen.findByText("Ada Admin");
    expect(screen.getByText("pending@example.com")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
  });

  it("hides invitations and the add-administrator action for a non-owner", async () => {
    mockLoad(nonOwner);
    render(<AdministratorsPage />);
    await screen.findByText("Ada Admin");
    expect(screen.queryByText("pending@example.com")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add administrator/i })).not.toBeInTheDocument();
  });

  it("opens the invite form and validates required fields", async () => {
    render(<AdministratorsPage />);
    await userEvent.click(await screen.findByRole("button", { name: /add administrator/i }));
    const dialog = await screen.findByRole("dialog", { name: "Add administrator" });
    expect(within(dialog).getByLabelText("Display name")).toBeRequired();
    expect(within(dialog).getByLabelText("Email")).toBeRequired();
    expect(within(dialog).getByLabelText(/reason \(at least 10 characters\)/i)).toBeRequired();
  });

  it("sends the invitation with the exact payload shape and reloads on success", async () => {
    render(<AdministratorsPage />);
    await userEvent.click(await screen.findByRole("button", { name: /add administrator/i }));
    const dialog = await screen.findByRole("dialog", { name: "Add administrator" });
    await userEvent.type(within(dialog).getByLabelText("Display name"), "New Admin");
    await userEvent.type(within(dialog).getByLabelText("Email"), "new-admin@example.com");
    await userEvent.type(within(dialog).getByLabelText(/reason \(at least 10 characters\)/i), "Needs platform access");
    await userEvent.click(within(dialog).getByRole("button", { name: /send invitation/i }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/administrators/invitations", {
        email: "new-admin@example.com",
        display_name: "New Admin",
        role: "platform_administrator",
        reason: "Needs platform access",
        confirmed: true,
      }),
    );
    expect(await screen.findByText("Invitation sent.")).toBeInTheDocument();
  });

  it("requires confirmation before revoking an invitation", async () => {
    render(<AdministratorsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Revoke" }));
    const dialog = await screen.findByRole("dialog", { name: "Revoke invitation" });
    expect(within(dialog).getByText(/pending@example.com/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: /revoke/i }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/administrators/invitations/inv-1/revoke", {}));
    expect(await screen.findByText("Invitation revoked.")).toBeInTheDocument();
  });

  it("resends an invitation without a confirmation dialog", async () => {
    render(<AdministratorsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Resend" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/administrators/invitations/inv-1/resend", {}));
    expect(await screen.findByText(/invitation resent/i)).toBeInTheDocument();
  });

  it("shows the reauth modal on a 403 recent-auth error and retries the invite after re-authenticating", async () => {
    post.mockImplementation((path: string) => {
      if (path === "/auth/reauthenticate") return Promise.resolve(undefined);
      if (path === "/administrators/invitations") {
        const attempts = post.mock.calls.filter((call) => call[0] === "/administrators/invitations").length;
        if (attempts === 1) return Promise.reject(new ApiError(403, "Recent administrator authentication required."));
        return Promise.resolve({});
      }
      return Promise.resolve({});
    });
    render(<AdministratorsPage />);
    await userEvent.click(await screen.findByRole("button", { name: /add administrator/i }));
    const dialog = await screen.findByRole("dialog", { name: "Add administrator" });
    await userEvent.type(within(dialog).getByLabelText("Display name"), "New Admin");
    await userEvent.type(within(dialog).getByLabelText("Email"), "new-admin@example.com");
    await userEvent.type(within(dialog).getByLabelText(/reason \(at least 10 characters\)/i), "Needs platform access");
    await userEvent.click(within(dialog).getByRole("button", { name: /send invitation/i }));

    const reauthDialog = await screen.findByRole("dialog", { name: /Confirm it.?s you/i });
    await userEvent.type(within(reauthDialog).getByLabelText("Password"), "operator-password");
    await userEvent.click(within(reauthDialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.getByText("Invitation sent.")).toBeInTheDocument());
    expect(post).toHaveBeenCalledWith("/auth/reauthenticate", { password: "operator-password" });
  });

  it("shows a safe error message when loading fails", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(owner) : Promise.reject(new ApiError(500, "Service unavailable.")),
    );
    render(<AdministratorsPage />);
    expect(await screen.findByText("Service unavailable.")).toBeInTheDocument();
  });
});
