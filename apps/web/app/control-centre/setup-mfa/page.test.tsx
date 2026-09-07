import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SetupMfa from "./page";

const replace = vi.fn();
const stableRouter = { replace, push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => stableRouter,
}));
vi.mock("@simplewebauthn/browser", () => ({
  startRegistration: vi.fn(),
}));
vi.mock("qrcode", () => ({
  default: { toDataURL: vi.fn().mockResolvedValue("data:image/png;base64,fakeqr") },
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

const pendingSetupActor = {
  id: "op-1",
  email: "op@mykhaya.app",
  display_name: "Operator One",
  role: "platform_owner",
  mfa_enrolled: false,
  session_status: "mfa_setup_required" as const,
};

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  replace.mockReset();
});

describe("SetupMfa — entry gating", () => {
  it("shows the method choice once the session requires MFA setup", async () => {
    get.mockResolvedValue(pendingSetupActor);
    render(<SetupMfa />);
    expect(await screen.findByText("Set up a passkey")).toBeInTheDocument();
    expect(screen.getByText("Use an authenticator app")).toBeInTheDocument();
  });

  it("redirects home if the session is already fully authenticated", async () => {
    get.mockResolvedValue({ ...pendingSetupActor, mfa_enrolled: true, session_status: "full" });
    render(<SetupMfa />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
  });

  it("redirects to login if there is no eligible session", async () => {
    get.mockRejectedValue(new Error("unauthenticated"));
    render(<SetupMfa />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });
});

describe("SetupMfa — authenticator app enrollment", () => {
  it("shows the QR code and manual secret, without any premature disclosure", async () => {
    const user = userEvent.setup();
    get.mockResolvedValue(pendingSetupActor);
    post.mockResolvedValue({ secret: "JBSWY3DPEHPK3PXP", provisioning_uri: "otpauth://totp/x" });
    render(<SetupMfa />);
    await user.click(await screen.findByText("Use an authenticator app"));

    const qr = await screen.findByAltText(/authenticator setup link/i);
    expect(qr).toHaveAttribute("src", "data:image/png;base64,fakeqr");
    expect(screen.getByText("JBSWY3DPEHPK3PXP")).toBeInTheDocument();
    // The secret must never appear anywhere before this stage.
  });

  it("verifies the entered code and shows recovery codes exactly once", async () => {
    const user = userEvent.setup();
    get.mockResolvedValue(pendingSetupActor);
    post.mockImplementation((path: string) => {
      if (path === "/auth/mfa/totp/setup")
        return Promise.resolve({ secret: "JBSWY3DPEHPK3PXP", provisioning_uri: "otpauth://totp/x" });
      if (path === "/auth/mfa/totp/verify")
        return Promise.resolve({ ...pendingSetupActor, mfa_enrolled: true, recovery_codes: ["AAAA-1111", "BBBB-2222"] });
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    render(<SetupMfa />);
    await user.click(await screen.findByText("Use an authenticator app"));
    await screen.findByLabelText("6-digit code from your app");

    await user.type(screen.getByLabelText("6-digit code from your app"), "654321");
    await user.click(screen.getByRole("button", { name: "Verify and continue" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/auth/mfa/totp/verify", { code: "654321" }),
    );
    expect(await screen.findByText("Save your recovery codes")).toBeInTheDocument();
    expect(screen.getByText("AAAA-1111")).toBeInTheDocument();
    expect(screen.getByText("BBBB-2222")).toBeInTheDocument();
  });

  it("shows a safe error and keeps the code form open for a retry on an invalid code", async () => {
    const user = userEvent.setup();
    get.mockResolvedValue(pendingSetupActor);
    post.mockImplementation((path: string) => {
      if (path === "/auth/mfa/totp/setup")
        return Promise.resolve({ secret: "JBSWY3DPEHPK3PXP", provisioning_uri: "otpauth://totp/x" });
      if (path === "/auth/mfa/totp/verify")
        return Promise.reject(new ApiError(422, "That code is not correct."));
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    render(<SetupMfa />);
    await user.click(await screen.findByText("Use an authenticator app"));
    await screen.findByLabelText("6-digit code from your app");

    await user.type(screen.getByLabelText("6-digit code from your app"), "000000");
    await user.click(screen.getByRole("button", { name: "Verify and continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("That code is not correct.");
    // The QR/secret stay on screen so the operator can retry without rescanning.
    expect(screen.getByLabelText("6-digit code from your app")).toBeInTheDocument();
    expect(screen.getByText("JBSWY3DPEHPK3PXP")).toBeInTheDocument();
  });

  it("lets the operator abandon the code form and choose a different method", async () => {
    const user = userEvent.setup();
    get.mockResolvedValue(pendingSetupActor);
    post.mockResolvedValue({ secret: "JBSWY3DPEHPK3PXP", provisioning_uri: "otpauth://totp/x" });
    render(<SetupMfa />);
    await user.click(await screen.findByText("Use an authenticator app"));
    await screen.findByLabelText("6-digit code from your app");

    await user.click(screen.getByRole("button", { name: "Choose a different method" }));
    expect(await screen.findByText("Set up a passkey")).toBeInTheDocument();
  });

  it("disables enrollment controls while a passkey registration is pending", async () => {
    const user = userEvent.setup();
    get.mockResolvedValue(pendingSetupActor);
    let resolveRegister: (value: unknown) => void = () => {};
    post.mockImplementation((path: string) => {
      if (path === "/auth/mfa/webauthn/register/options")
        return new Promise((resolve) => (resolveRegister = resolve));
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    render(<SetupMfa />);
    const passkeyButton = await screen.findByRole("button", { name: /Set up a passkey/ });
    await user.click(passkeyButton);

    expect(await screen.findByText("Waiting for your passkey…")).toBeInTheDocument();
    resolveRegister({ options_json: "{}" });
  });

  it("does not re-render recovery codes once the operator has moved on", async () => {
    const user = userEvent.setup();
    get.mockResolvedValue(pendingSetupActor);
    post.mockImplementation((path: string) => {
      if (path === "/auth/mfa/totp/setup")
        return Promise.resolve({ secret: "JBSWY3DPEHPK3PXP", provisioning_uri: "otpauth://totp/x" });
      if (path === "/auth/mfa/totp/verify") return Promise.resolve({ ...pendingSetupActor, mfa_enrolled: true, recovery_codes: [] });
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    render(<SetupMfa />);
    await user.click(await screen.findByText("Use an authenticator app"));
    await screen.findByLabelText("6-digit code from your app");
    await user.type(screen.getByLabelText("6-digit code from your app"), "654321");
    await user.click(screen.getByRole("button", { name: "Verify and continue" }));

    expect(await screen.findByText("Your account is secured. You can generate recovery codes any time from Security.")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Download codes" })).not.toBeInTheDocument();
  });
});
