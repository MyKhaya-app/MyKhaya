import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PlatformLogin from "./page";

const replace = vi.fn();
const stableRouter = { replace, push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => stableRouter,
}));
vi.mock("@simplewebauthn/browser", () => ({
  startAuthentication: vi.fn(),
}));
vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    platformApi: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
const { platformApi, ApiError } = await import("@mykhaya/api-client");
const post = platformApi.post as unknown as ReturnType<typeof vi.fn>;

const fullActor = {
  id: "op-1",
  email: "op@mykhaya.app",
  display_name: "Operator One",
  role: "platform_owner",
  mfa_enrolled: true,
  session_status: "full" as const,
};

beforeEach(() => {
  post.mockReset();
  replace.mockReset();
});

describe("PlatformLogin", () => {
  it("renders operator email/password fields and PCC branding", () => {
    render(<PlatformLogin />);
    expect(screen.getByText("MyKhaya")).toBeInTheDocument();
    expect(screen.getByText("Platform Control Centre")).toBeInTheDocument();
    expect(screen.getByLabelText("Operator email")).toBeRequired();
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    expect(screen.getByText(/Household accounts cannot sign in here/)).toBeInTheDocument();
  });

  it("sends exactly the email and password on submit", async () => {
    const user = userEvent.setup();
    post.mockResolvedValue(fullActor);
    render(<PlatformLogin />);
    await user.type(screen.getByLabelText("Operator email"), "admin@mykhaya.app");
    await user.type(screen.getByLabelText("Password"), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "Sign in to Control Centre" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/auth/login", {
        email: "admin@mykhaya.app",
        password: "correct horse battery staple",
      }),
    );
  });

  it("disables the submit button while the request is pending", async () => {
    const user = userEvent.setup();
    let resolveLogin: (value: typeof fullActor) => void = () => {};
    post.mockReturnValue(new Promise((resolve) => (resolveLogin = resolve)));
    render(<PlatformLogin />);
    await user.type(screen.getByLabelText("Operator email"), "admin@mykhaya.app");
    await user.type(screen.getByLabelText("Password"), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "Sign in to Control Centre" }));

    expect(screen.getByRole("button", { name: "Signing in…" })).toBeDisabled();
    resolveLogin(fullActor);
  });

  it("shows a safe error message without leaking the entered password", async () => {
    const user = userEvent.setup();
    post.mockRejectedValue(new ApiError(401, "Invalid email or password."));
    render(<PlatformLogin />);
    await user.type(screen.getByLabelText("Operator email"), "admin@mykhaya.app");
    await user.type(screen.getByLabelText("Password"), "hunter2hunter2hunter2");
    await user.click(screen.getByRole("button", { name: "Sign in to Control Centre" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");
    expect(document.body.textContent ?? "").not.toContain("hunter2hunter2hunter2");
  });

  it("redirects home once a fully authenticated session is returned", async () => {
    const user = userEvent.setup();
    post.mockResolvedValue(fullActor);
    render(<PlatformLogin />);
    await user.type(screen.getByLabelText("Operator email"), "admin@mykhaya.app");
    await user.type(screen.getByLabelText("Password"), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "Sign in to Control Centre" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
  });

  it("redirects to mandatory MFA enrollment when the session requires it", async () => {
    const user = userEvent.setup();
    post.mockResolvedValue({ ...fullActor, session_status: "mfa_setup_required" });
    render(<PlatformLogin />);
    await user.type(screen.getByLabelText("Operator email"), "admin@mykhaya.app");
    await user.type(screen.getByLabelText("Password"), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "Sign in to Control Centre" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/setup-mfa"));
  });

  it("shows the MFA verification step, offering only the account's actual available factors", async () => {
    const user = userEvent.setup();
    post.mockResolvedValue({
      ...fullActor,
      session_status: "pending_mfa",
      available_factors: ["totp", "recovery_code"],
    });
    render(<PlatformLogin />);
    await user.type(screen.getByLabelText("Operator email"), "admin@mykhaya.app");
    await user.type(screen.getByLabelText("Password"), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "Sign in to Control Centre" }));

    expect(await screen.findByText("Verify it’s you")).toBeInTheDocument();
    expect(screen.getByLabelText("6-digit authenticator code")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use a recovery code instead" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Use my passkey instead" })).not.toBeInTheDocument();
  });

  it("submits the TOTP verification code and redirects on success", async () => {
    const user = userEvent.setup();
    post.mockImplementation((path: string) => {
      if (path === "/auth/login") return Promise.resolve({ ...fullActor, session_status: "pending_mfa", available_factors: ["totp"] });
      if (path === "/auth/mfa/totp/login-verify") return Promise.resolve(fullActor);
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    render(<PlatformLogin />);
    await user.type(screen.getByLabelText("Operator email"), "admin@mykhaya.app");
    await user.type(screen.getByLabelText("Password"), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "Sign in to Control Centre" }));
    await screen.findByLabelText("6-digit authenticator code");

    await user.type(screen.getByLabelText("6-digit authenticator code"), "123456");
    await user.click(screen.getByRole("button", { name: "Verify" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/auth/mfa/totp/login-verify", { code: "123456" }),
    );
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
  });
});
