import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PushPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/push",
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

const pushState = {
  configured: true,
  managed_by: "platform_admin",
  public_key: "BExamplePublicKey",
  active_subscriptions: 4,
  recent_failures: [],
  push_settings: {
    enabled: true,
    subject: "mailto:ops@mykhaya.app",
    vapid_public_key: "BExamplePublicKey",
    private_key_configured: true,
    updated_at: "2026-09-01T09:00:00Z",
    editable: true,
  },
};

function mockRoutes(overrides: Record<string, unknown> = {}) {
  get.mockImplementation((path: string) => {
    if (path === "/push") return Promise.resolve(overrides.push ?? pushState);
    if (path === "/auth/me") return Promise.resolve({ email: "op@mykhaya.app" });
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  put.mockReset();
});

describe("PushPage", () => {
  it("renders the VAPID public key and delivery summary", async () => {
    mockRoutes();
    render(<PushPage />);
    expect(await screen.findByText("BExamplePublicKey")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("Configured")).toBeInTheDocument();
  });

  it("never renders the private key value", async () => {
    mockRoutes();
    render(<PushPage />);
    await screen.findByText("BExamplePublicKey");
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).not.toMatch(/-----BEGIN/);
    expect(bodyText.toLowerCase()).not.toMatch(/private[_-]?key.{0,3}:.*[a-z0-9]{20,}/);
  });

  it("offers Rotate keys once a key pair exists, not Generate", async () => {
    mockRoutes();
    render(<PushPage />);
    expect(await screen.findByRole("button", { name: "Rotate keys" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generate VAPID keys" })).not.toBeInTheDocument();
  });

  it("offers Generate VAPID keys when no key pair exists yet", async () => {
    mockRoutes({ push: { ...pushState, public_key: null, push_settings: { ...pushState.push_settings, vapid_public_key: null } } });
    render(<PushPage />);
    expect(await screen.findByRole("button", { name: "Generate VAPID keys" })).toBeInTheDocument();
  });

  it("rotates keys only after confirming the destructive dialog", async () => {
    const user = userEvent.setup();
    mockRoutes();
    post.mockResolvedValue({ message: "Keys rotated.", public_key: "BNewKey" });
    render(<PushPage />);
    await user.click(await screen.findByRole("button", { name: "Rotate keys" }));

    const dialog = await screen.findByRole("dialog", { name: "Rotate VAPID key pair" });
    await user.type(within(dialog).getByLabelText(/Reason for this administrative action/), "Suspected key compromise");
    await user.click(within(dialog).getByRole("button", { name: "Rotate keys" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/push/vapid-settings/generate-keys", {
        rotate: true,
        reason: "Suspected key compromise",
        confirmed: true,
      }),
    );
  });

  it("sends exactly the push settings payload on save", async () => {
    const user = userEvent.setup();
    mockRoutes();
    put.mockResolvedValue({ message: "Saved." });
    render(<PushPage />);
    await screen.findByLabelText("Contact address (mailto: or https://)");
    await user.type(screen.getByLabelText("Reason for change"), "Updating contact address");
    await user.click(screen.getByRole("button", { name: "Save push settings" }));

    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/push/vapid-settings", {
        enabled: true,
        subject: "mailto:ops@mykhaya.app",
        reason: "Updating contact address",
        confirmed: true,
      }),
    );
  });

  it("sends the exact test-push payload", async () => {
    const user = userEvent.setup();
    mockRoutes();
    post.mockResolvedValue({ results: [{ device_label: "iPhone", result: "accepted" }] });
    render(<PushPage />);
    await screen.findByLabelText("Recipient's email (must have a registered device)");
    await user.clear(screen.getByLabelText("Recipient's email (must have a registered device)"));
    await user.type(screen.getByLabelText("Recipient's email (must have a registered device)"), "admin@mykhaya.app");
    await user.type(screen.getByLabelText("Reason for test"), "Confirming push wiring");
    await user.click(screen.getByRole("button", { name: "Send test push" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/push/test", {
        recipient: "admin@mykhaya.app",
        reason: "Confirming push wiring",
        confirmed: true,
      }),
    );
    expect(await screen.findByText("1 of 1 device(s) accepted the test push.")).toBeInTheDocument();
  });

  it("surfaces a safe error message on a rejected save", async () => {
    const user = userEvent.setup();
    mockRoutes();
    put.mockRejectedValue(new ApiError(422, "The contact address must be a mailto: or https: URL."));
    render(<PushPage />);
    await screen.findByLabelText("Contact address (mailto: or https://)");
    await user.type(screen.getByLabelText("Reason for change"), "Testing invalid contact");
    await user.click(screen.getByRole("button", { name: "Save push settings" }));

    expect(await screen.findByText("The contact address must be a mailto: or https: URL.")).toBeInTheDocument();
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
    render(<PushPage />);
    await screen.findByLabelText("Contact address (mailto: or https://)");
    await user.type(screen.getByLabelText("Reason for change"), "Updating contact address");
    await user.click(screen.getByRole("button", { name: "Save push settings" }));

    const reauthDialog = await screen.findByRole("dialog", { name: /Confirm it.s you/i });
    await user.type(within(reauthDialog).getByLabelText("Password"), "hunter2");
    await user.click(within(reauthDialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() =>
      expect(put.mock.calls.filter((call) => call[0] === "/push/vapid-settings")).toHaveLength(2),
    );
  });
});
