import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MailPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/mail",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
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

const mailState = {
  configured: true,
  transport: "smtp",
  sender_identity: "MyKhaya <no-reply@mykhaya.app>",
  queue_depth: 0,
  last_successful_delivery: "2026-09-01T09:00:00Z",
  recent_failures: [],
  managed_by: "platform_admin",
  smtp_settings: {
    enabled: true,
    host: "smtp.mykhaya.app",
    port: 587,
    connection_security: "starttls",
    auth_enabled: true,
    username: "mailer",
    password_configured: true,
    sender_name: "MyKhaya",
    sender_email: "no-reply@mykhaya.app",
    reply_to: null,
    timeout_seconds: 10,
    updated_at: "2026-09-01T09:00:00Z",
    editable: true,
  },
};

function mockRoutes(overrides: Record<string, unknown> = {}) {
  get.mockImplementation((path: string) => {
    if (path === "/mail") return Promise.resolve(overrides.mail ?? mailState);
    if (path === "/auth/me") return Promise.resolve({ email: "op@mykhaya.app" });
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  put.mockReset();
});

describe("MailPage", () => {
  it("renders the SMTP configuration and transport summary", async () => {
    mockRoutes();
    render(<MailPage />);
    expect(await screen.findByLabelText("Host")).toHaveValue("smtp.mykhaya.app");
    expect(screen.getByLabelText("Port")).toHaveValue(587);
    expect(screen.getByText("Configured")).toBeInTheDocument();
  });

  it("never renders the stored password value, only a placeholder", async () => {
    mockRoutes();
    render(<MailPage />);
    const passwordField = await screen.findByLabelText("Password");
    expect(passwordField).toHaveValue("");
    expect(passwordField).toHaveAttribute("placeholder", "Leave blank to keep the stored password");
    const bodyText = document.body.textContent ?? "";
    expect(bodyText.toLowerCase()).not.toMatch(/hunter2|-----begin/);
  });

  it("sends exactly the SMTP settings payload on save", async () => {
    const user = userEvent.setup();
    mockRoutes();
    put.mockResolvedValue({ message: "Saved." });
    render(<MailPage />);
    await screen.findByLabelText("Host");
    await user.type(screen.getByLabelText("Reason for change"), "Rotating SMTP relay host");
    await user.click(screen.getByRole("button", { name: "Save SMTP settings" }));

    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/mail/smtp-settings", {
        enabled: true,
        host: "smtp.mykhaya.app",
        port: 587,
        connection_security: "starttls",
        auth_enabled: true,
        username: "mailer",
        password: null,
        sender_name: "MyKhaya",
        sender_email: "no-reply@mykhaya.app",
        reply_to: null,
        timeout_seconds: 10,
        reason: "Rotating SMTP relay host",
        confirmed: true,
      }),
    );
  });

  it("sends the exact test-email payload", async () => {
    const user = userEvent.setup();
    mockRoutes();
    post.mockResolvedValue({ message: "Test email accepted." });
    render(<MailPage />);
    await screen.findByLabelText("Recipient");
    await user.clear(screen.getByLabelText("Recipient"));
    await user.type(screen.getByLabelText("Recipient"), "admin@mykhaya.app");
    await user.type(screen.getByLabelText("Reason for test"), "Confirming relay after config change");
    await user.click(screen.getByRole("button", { name: "Send test email" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/mail/test", {
        recipient: "admin@mykhaya.app",
        reason: "Confirming relay after config change",
        confirmed: true,
      }),
    );
  });

  it("clears the stored password only after confirming in the dialog, with recent-auth", async () => {
    const user = userEvent.setup();
    mockRoutes();
    post.mockResolvedValue({ message: "Password cleared." });
    render(<MailPage />);
    await screen.findByText(/A password is currently stored/);
    await user.click(screen.getByRole("button", { name: "Clear stored password" }));

    const dialog = await screen.findByRole("dialog", { name: "Clear stored SMTP password" });
    await user.type(within(dialog).getByLabelText(/Reason for this administrative action/), "Rotating credentials");
    await user.click(within(dialog).getByRole("button", { name: "Clear stored password" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/mail/smtp-settings/clear-password", {
        reason: "Rotating credentials",
        confirmed: true,
      }),
    );
    expect(await screen.findByText("Password cleared.")).toBeInTheDocument();
  });

  it("surfaces a safe error message on a rejected save", async () => {
    const user = userEvent.setup();
    mockRoutes();
    put.mockRejectedValue(new ApiError(422, "The sender email is not a valid address."));
    render(<MailPage />);
    await screen.findByLabelText("Host");
    await user.type(screen.getByLabelText("Reason for change"), "Testing invalid sender");
    await user.click(screen.getByRole("button", { name: "Save SMTP settings" }));

    expect(await screen.findByText("The sender email is not a valid address.")).toBeInTheDocument();
  });

  it("opens the reauth modal on a 403 and retries the same save once verified", async () => {
    mockRoutes();
    put.mockImplementation((path: string) => {
      const priorAttempts = put.mock.calls.filter((call) => call[0] === path).length;
      if (priorAttempts === 1) return Promise.reject(new ApiError(403, "Recent authentication required."));
      return Promise.resolve({ message: "Saved." });
    });
    post.mockImplementation((path: string) =>
      path === "/auth/reauthenticate" ? Promise.resolve(undefined) : Promise.reject(new Error("unexpected")),
    );
    const user = userEvent.setup();
    render(<MailPage />);
    await screen.findByLabelText("Host");
    await user.type(screen.getByLabelText("Reason for change"), "Rotating SMTP relay host");
    await user.click(screen.getByRole("button", { name: "Save SMTP settings" }));

    const reauthDialog = await screen.findByRole("dialog", { name: /Confirm it.s you/i });
    await user.type(within(reauthDialog).getByLabelText("Password"), "hunter2");
    await user.click(within(reauthDialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() =>
      expect(put.mock.calls.filter((call) => call[0] === "/mail/smtp-settings")).toHaveLength(2),
    );
  });

  it("shows a read-only notice when SMTP is managed by the environment", async () => {
    mockRoutes({ mail: { ...mailState, smtp_settings: { ...mailState.smtp_settings, editable: false } } });
    render(<MailPage />);
    expect(await screen.findByText(/Managed by the deployment environment/)).toBeInTheDocument();
    expect(screen.getByLabelText("Host")).toBeDisabled();
  });
});
