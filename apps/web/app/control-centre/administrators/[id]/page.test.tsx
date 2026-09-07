import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdministratorDetailPage from "./page";

const router = { push: vi.fn(), replace: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useParams: () => ({ id: "target-1" }),
  usePathname: () => "/administrators/target-1",
}));
vi.mock("qrcode", () => ({ default: { toDataURL: vi.fn().mockResolvedValue("data:image/png;base64,x") } }));
vi.mock("@simplewebauthn/browser", () => ({
  startRegistration: vi.fn().mockResolvedValue({ id: "cred-1" }),
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
const patch = platformApi.patch as unknown as ReturnType<typeof vi.fn>;
const del = platformApi.delete as unknown as ReturnType<typeof vi.fn>;

const owner = {
  id: "owner-1",
  email: "owner@example.com",
  display_name: "Owner",
  role: "platform_owner",
  mfa_enrolled: true,
  session_status: "full" as const,
};
const otherAdmin = { ...owner, id: "admin-1", role: "platform_administrator" };

const targetSecurity = {
  id: "target-1",
  email: "target@example.com",
  display_name: "Target Admin",
  role: "platform_administrator",
  is_active: true,
  mfa_enrolled: true,
  totp_enabled: true,
  totp_verified_at: "2026-08-01T00:00:00Z",
  recovery_codes_remaining: 5,
  webauthn_credential_count: 1,
  active_session_count: 2,
  last_seen_at: "2026-09-06T10:00:00Z",
};

function mockLoad(actor: typeof owner, security: typeof targetSecurity = targetSecurity) {
  get.mockImplementation((path: string) => {
    if (path === "/auth/me") return Promise.resolve(actor);
    if (path === "/administrators/target-1/security") return Promise.resolve(security);
    if (path === "/auth/mfa/recovery-codes/status") return Promise.resolve({ remaining: security.recovery_codes_remaining });
    if (path.startsWith("/audit")) return Promise.resolve({ items: [] });
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockLoad(owner);
  post.mockResolvedValue({});
  patch.mockResolvedValue({});
  del.mockResolvedValue(undefined);
});

describe("Administrator detail — overview", () => {
  it("renders account metadata, role and status/MFA badges", async () => {
    render(<AdministratorDetailPage />);
    expect(await screen.findByText("Target Admin")).toBeInTheDocument();
    expect(screen.getAllByText("target@example.com").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Administrator").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Active").length).toBeGreaterThan(0);
    expect(screen.getAllByText("MFA enrolled").length).toBeGreaterThan(0);
  });

  it("shows Change role only for an owner viewing another administrator", async () => {
    render(<AdministratorDetailPage />);
    await screen.findByText("Target Admin");
    expect(screen.getByRole("button", { name: "Change role" })).toBeInTheDocument();
  });

  it("hides Change role for a non-owner viewer", async () => {
    mockLoad(otherAdmin);
    render(<AdministratorDetailPage />);
    await screen.findByText("Target Admin");
    expect(screen.queryByRole("button", { name: "Change role" })).not.toBeInTheDocument();
  });

  it("requires a reason of at least 10 characters and sends the exact role-change payload", async () => {
    render(<AdministratorDetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Change role" }));
    const dialog = await screen.findByRole("dialog", { name: "Change role" });
    await userEvent.selectOptions(within(dialog).getByLabelText("New role"), "security_operator");
    const confirm = within(dialog).getByRole("button", { name: "Change role" });
    await userEvent.click(confirm);
    // Too-short reason should not submit (native minLength validation).
    expect(patch).not.toHaveBeenCalled();
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Promote to security");
    await userEvent.click(confirm);
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith("/administrators/target-1", {
        role: "security_operator",
        reason: "Promote to security",
        confirmed: true,
      }),
    );
    expect(await screen.findByText("Role changed to Security Operator.")).toBeInTheDocument();
  });

  it("requires confirmation and a reason before deactivating, with the exact payload", async () => {
    render(<AdministratorDetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Deactivate administrator" }));
    const dialog = await screen.findByRole("dialog", { name: "Deactivate administrator" });
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Left the company");
    await userEvent.click(within(dialog).getByRole("button", { name: "Deactivate" }));
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith("/administrators/target-1", {
        is_active: false,
        reason: "Left the company",
        confirmed: true,
      }),
    );
  });

  it("hides the deactivate/reactivate action when viewing your own account", async () => {
    // useParams is mocked to always return id "target-1" — making the acting
    // administrator's own id "target-1" simulates viewing your own profile.
    const self = { ...owner, id: "target-1" };
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(self);
      if (path === "/administrators/target-1/security") return Promise.resolve(targetSecurity);
      if (path === "/auth/mfa/recovery-codes/status") return Promise.resolve({ remaining: 5 });
      return Promise.reject(new Error("unexpected"));
    });
    render(<AdministratorDetailPage />);
    await screen.findByText("Target Admin");
    expect(screen.queryByRole("button", { name: /deactivate administrator/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reactivate administrator/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Change role" })).not.toBeInTheDocument();
  });

  it("shows the reauth modal on a 403 and retries deactivation after re-authenticating", async () => {
    patch.mockImplementation((path: string) => {
      const attempts = patch.mock.calls.filter((call) => call[0] === path).length;
      if (attempts === 1) return Promise.reject(new ApiError(403, "Recent administrator authentication required."));
      return Promise.resolve({});
    });
    render(<AdministratorDetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Deactivate administrator" }));
    const dialog = await screen.findByRole("dialog", { name: "Deactivate administrator" });
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Left the company");
    await userEvent.click(within(dialog).getByRole("button", { name: "Deactivate" }));

    const reauthDialog = await screen.findByRole("dialog", { name: /Confirm it.?s you/i });
    await userEvent.type(within(reauthDialog).getByLabelText("Password"), "operator-password");
    await userEvent.click(within(reauthDialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.getByText("Administrator deactivated.")).toBeInTheDocument());
    expect(patch.mock.calls.filter((call) => call[0] === "/administrators/target-1")).toHaveLength(2);
  });

  it("shows a safe error message when a mutation fails", async () => {
    patch.mockRejectedValueOnce(new ApiError(404, "Administrator not found"));
    render(<AdministratorDetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Deactivate administrator" }));
    const dialog = await screen.findByRole("dialog", { name: "Deactivate administrator" });
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Left the company");
    await userEvent.click(within(dialog).getByRole("button", { name: "Deactivate" }));
    expect(await screen.findByText("Administrator not found")).toBeInTheDocument();
  });
});

describe("Administrator detail — security (viewing another administrator)", () => {
  it("requires confirmation and a reason before resetting MFA", async () => {
    render(<AdministratorDetailPage />);
    await screen.findByText("Target Admin");
    await userEvent.click(await screen.findByRole("button", { name: "Security" }));
    await userEvent.click(await screen.findByRole("button", { name: /reset mfa for this administrator/i }));
    const dialog = await screen.findByRole("dialog", { name: "Reset MFA" });
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Lost their device");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reset MFA" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/administrators/target-1/mfa/reset", {
        reason: "Lost their device",
        confirmed: true,
      }),
    );
  });

  it("shows the reduced session summary (no raw session list) for a non-owner viewer", async () => {
    mockLoad(otherAdmin);
    render(<AdministratorDetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Sessions" }));
    expect((await screen.findAllByText(/active session/i)).length).toBeGreaterThan(0);
    expect(screen.getByText(/session ip\/device detail is visible to platform owners only/i)).toBeInTheDocument();
  });
});

describe("Administrator detail — self security & sessions", () => {
  const self = { ...owner, id: "target-1" };
  const selfSecurity = {
    ...targetSecurity,
    webauthn_credentials: [
      { id: "cred-1", label: "Work laptop", created_at: "2026-08-01T00:00:00Z", last_used_at: null },
    ],
    sessions: [
      {
        id: "sess-1",
        created_at: "2026-09-01T09:00:00Z",
        last_seen_at: "2026-09-06T09:00:00Z",
        absolute_expires_at: "2026-10-01T09:00:00Z",
        user_agent: "Chrome on macOS",
        source_ip: "10.0.0.1",
        current: false,
      },
    ],
  };

  function mockSelfLoad() {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(self);
      if (path === "/administrators/target-1/security") return Promise.resolve(selfSecurity);
      if (path === "/auth/sessions") return Promise.resolve(selfSecurity.sessions);
      if (path === "/auth/mfa/recovery-codes/status") return Promise.resolve({ remaining: 5 });
      return Promise.reject(new Error(`unexpected path ${path}`));
    });
  }

  it("requires confirmation before removing a passkey and retries after a 403", async () => {
    mockSelfLoad();
    del.mockImplementation(() => {
      const attempts = del.mock.calls.length;
      if (attempts === 1) return Promise.reject(new ApiError(403, "Recent administrator authentication required."));
      return Promise.resolve(undefined);
    });
    render(<AdministratorDetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Security" }));
    await userEvent.click(await screen.findByRole("button", { name: /remove/i }));
    const dialog = await screen.findByRole("dialog", { name: "Remove passkey" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove" }));

    const reauthDialog = await screen.findByRole("dialog", { name: /Confirm it.?s you/i });
    await userEvent.type(within(reauthDialog).getByLabelText("Password"), "operator-password");
    await userEvent.click(within(reauthDialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.getByText("Passkey removed.")).toBeInTheDocument());
    expect(del).toHaveBeenCalledWith("/auth/mfa/webauthn/credentials/cred-1");
  });

  it("revokes a single session without a confirmation dialog", async () => {
    mockSelfLoad();
    render(<AdministratorDetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Sessions" }));
    await userEvent.click(await screen.findByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/auth/sessions/sess-1"));
    expect(await screen.findByText("Session revoked.")).toBeInTheDocument();
  });

  it("requires confirmation and a reason before signing out every other device", async () => {
    mockSelfLoad();
    render(<AdministratorDetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Sessions" }));
    await userEvent.click(await screen.findByRole("button", { name: /sign out every other device/i }));
    const dialog = await screen.findByRole("dialog", { name: "Sign out every other device" });
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Lost my laptop");
    await userEvent.click(within(dialog).getByRole("button", { name: "Sign out other devices" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/auth/revoke-all", { reason: "Lost my laptop", confirmed: true }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/login"));
  });
});

describe("Administrator detail — activity", () => {
  it("renders the audit table for this administrator", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/auth/me") return Promise.resolve(owner);
      if (path === "/administrators/target-1/security") return Promise.resolve(targetSecurity);
      if (path.startsWith("/audit")) {
        return Promise.resolve({
          items: [
            {
              id: "a1",
              created_at: "2026-09-01T09:00:00Z",
              action: "administrator.updated",
              outcome: "success",
              administrator_id: "owner-1",
              target_id: "target-1",
              reason: "Routine check",
            },
          ],
        });
      }
      return Promise.reject(new Error("unexpected"));
    });
    render(<AdministratorDetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Activity" }));
    expect(await screen.findByText("Routine check")).toBeInTheDocument();
  });

  it("shows a safe error when the administrator fails to load", async () => {
    get.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve(owner) : Promise.reject(new ApiError(404, "That administrator could not be found.")),
    );
    render(<AdministratorDetailPage />);
    expect(await screen.findByText("That administrator could not be found.")).toBeInTheDocument();
  });
});
