import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AcceptInvitationPage from "./page";

const replace = vi.fn();
const stableRouter = { replace, push: vi.fn() };
let searchParams = new URLSearchParams({ token: "tok-123" });
vi.mock("next/navigation", () => ({
  useRouter: () => stableRouter,
  useSearchParams: () => searchParams,
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

const preview = {
  email: "new-admin@mykhaya.app",
  display_name: "New Admin",
  role: "support",
  invited_by_display_name: "Jamie Owner",
  expires_at: "2026-09-08T00:00:00Z",
};

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  replace.mockReset();
  searchParams = new URLSearchParams({ token: "tok-123" });
});

describe("AcceptInvitationPage — valid invitation", () => {
  it("shows the invitation metadata: who invited, role and identity", async () => {
    get.mockResolvedValue(preview);
    render(<AcceptInvitationPage />);
    expect(await screen.findByText("New Admin")).toBeInTheDocument();
    expect(screen.getByText("new-admin@mykhaya.app")).toBeInTheDocument();
    expect(screen.getByText("Support")).toBeInTheDocument();
    expect(screen.getByText(/Jamie Owner invited you as/)).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/administrators/invitations/preview?token=tok-123");
  });

  it("requires matching passwords before submitting", async () => {
    const user = userEvent.setup();
    get.mockResolvedValue(preview);
    render(<AcceptInvitationPage />);
    await screen.findByText("New Admin");

    await user.type(screen.getByLabelText("Password"), "a-strong-password-value");
    await user.type(screen.getByLabelText("Confirm password"), "a-different-password-value");
    await user.click(screen.getByRole("button", { name: "Set password and continue" }));

    expect(await screen.findByText("Those passwords do not match.")).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it("sends exactly the token and password on acceptance", async () => {
    const user = userEvent.setup();
    get.mockResolvedValue(preview);
    post.mockResolvedValue({
      id: "op-2",
      email: preview.email,
      display_name: preview.display_name,
      role: preview.role,
      mfa_enrolled: false,
      session_status: "mfa_setup_required",
    });
    render(<AcceptInvitationPage />);
    await screen.findByText("New Admin");

    await user.type(screen.getByLabelText("Password"), "a-strong-password-value");
    await user.type(screen.getByLabelText("Confirm password"), "a-strong-password-value");
    await user.click(screen.getByRole("button", { name: "Set password and continue" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/administrators/invitations/accept", {
        token: "tok-123",
        password: "a-strong-password-value",
      }),
    );
  });

  it("redirects to mandatory MFA enrollment after acceptance", async () => {
    const user = userEvent.setup();
    get.mockResolvedValue(preview);
    post.mockResolvedValue({
      id: "op-2",
      email: preview.email,
      display_name: preview.display_name,
      role: preview.role,
      mfa_enrolled: false,
      session_status: "mfa_setup_required",
    });
    render(<AcceptInvitationPage />);
    await screen.findByText("New Admin");
    await user.type(screen.getByLabelText("Password"), "a-strong-password-value");
    await user.type(screen.getByLabelText("Confirm password"), "a-strong-password-value");
    await user.click(screen.getByRole("button", { name: "Set password and continue" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/setup-mfa"));
  });

  it("shows a safe error and does not navigate when acceptance fails", async () => {
    const user = userEvent.setup();
    get.mockResolvedValue(preview);
    post.mockRejectedValue(new ApiError(409, "This invitation has already been accepted."));
    render(<AcceptInvitationPage />);
    await screen.findByText("New Admin");
    await user.type(screen.getByLabelText("Password"), "a-strong-password-value");
    await user.type(screen.getByLabelText("Confirm password"), "a-strong-password-value");
    await user.click(screen.getByRole("button", { name: "Set password and continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("This invitation has already been accepted.");
    expect(replace).not.toHaveBeenCalled();
  });
});

describe("AcceptInvitationPage — invalid/expired/missing invitation", () => {
  it("shows a safe error for an expired or invalid token, without a password form", async () => {
    get.mockRejectedValue(new ApiError(410, "This invitation has expired."));
    render(<AcceptInvitationPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("This invitation has expired.");
    expect(screen.getByText("Invitation unavailable")).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });

  it("shows a safe error when the link has no token, without calling the API", async () => {
    searchParams = new URLSearchParams();
    render(<AcceptInvitationPage />);
    expect(await screen.findByText("This invitation link is missing its token.")).toBeInTheDocument();
    expect(get).not.toHaveBeenCalled();
  });

  it("shows a loading state while the invitation is being checked", async () => {
    get.mockReturnValue(new Promise(() => {}));
    render(<AcceptInvitationPage />);
    expect(await screen.findByText("Checking your invitation…")).toBeInTheDocument();
  });
});
