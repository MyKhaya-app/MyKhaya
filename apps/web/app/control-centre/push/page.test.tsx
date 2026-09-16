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
  active_web_subscriptions: 4,
  active_native_registrations: 9,
  users_with_active_native_push: 5,
  native_registrations_by_environment: { production: 1, sandbox: 2, legacy: 6 },
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

const emptyNativeDevicePage = { items: [], page: 1, page_size: 25, total: 0 };

function mockRoutes(overrides: Record<string, unknown> = {}) {
  get.mockImplementation((path: string) => {
    if (path === "/push") return Promise.resolve(overrides.push ?? pushState);
    if (path === "/auth/me") return Promise.resolve({ email: "op@mykhaya.app" });
    if (path.startsWith("/push/native-devices")) {
      return Promise.resolve(overrides.nativeDevices ?? emptyNativeDevicePage);
    }
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  put.mockReset();
});

describe("PushPage", () => {
  it("renders a masked VAPID key summary and delivery summary", async () => {
    mockRoutes();
    render(<PushPage />);
    expect((await screen.findAllByText("Configured · ending ublicKey")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("4")).length).toBeGreaterThan(0);
    expect(screen.getByText("Configured")).toBeInTheDocument();
  });

  it("never renders the private key value", async () => {
    mockRoutes();
    render(<PushPage />);
    await screen.findAllByText("Configured · ending ublicKey");
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

  it("shows a per-device provider breakdown distinguishing iOS/APNs, Android/FCM and Web Push", async () => {
    const user = userEvent.setup();
    mockRoutes();
    post.mockResolvedValue({
      results: [
        { channel: "web", platform: null, device_label: "Chrome on laptop", result: "accepted" },
        { channel: "native", platform: "ios", device_label: "iPhone", result: "queued" },
        { channel: "native", platform: "android", device_label: "Pixel", result: "queued" },
      ],
    });
    render(<PushPage />);
    await screen.findByLabelText("Recipient's email (must have a registered device)");
    await user.clear(screen.getByLabelText("Recipient's email (must have a registered device)"));
    await user.type(screen.getByLabelText("Recipient's email (must have a registered device)"), "admin@mykhaya.app");
    await user.type(screen.getByLabelText("Reason for test"), "Confirming push wiring");
    await user.click(screen.getByRole("button", { name: "Send test push" }));

    expect(await screen.findByText("3 of 3 device(s) accepted the test push.")).toBeInTheDocument();
    expect(screen.getByText("Web Push")).toBeInTheDocument();
    expect(screen.getByText("iOS · APNs")).toBeInTheDocument();
    expect(screen.getByText("Android · FCM")).toBeInTheDocument();
  });

  it("does not misreport a queued native failure as accepted in the per-device table", async () => {
    const user = userEvent.setup();
    mockRoutes();
    post.mockResolvedValue({
      results: [
        { channel: "native", platform: "android", device_label: "Pixel", result: "FcmPermanentError" },
      ],
    });
    render(<PushPage />);
    await screen.findByLabelText("Recipient's email (must have a registered device)");
    await user.clear(screen.getByLabelText("Recipient's email (must have a registered device)"));
    await user.type(screen.getByLabelText("Recipient's email (must have a registered device)"), "admin@mykhaya.app");
    await user.type(screen.getByLabelText("Reason for test"), "Confirming push wiring");
    await user.click(screen.getByRole("button", { name: "Send test push" }));

    expect(await screen.findByText("0 of 1 device(s) accepted the test push.")).toBeInTheDocument();
    expect(screen.getByText("Android · FCM")).toBeInTheDocument();
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

describe("PushPage — PCC push audit corrections (Phase 2)", () => {
  it("relabels the historical Active devices metric as Active web push subscriptions", async () => {
    mockRoutes();
    render(<PushPage />);
    await screen.findAllByText("Configured · ending ublicKey");

    expect(screen.queryByText("Active devices")).not.toBeInTheDocument();
    expect(screen.queryByText("Active registered devices")).not.toBeInTheDocument();
    expect(screen.getAllByText("Active web push subscriptions").length).toBeGreaterThan(0);
  });

  it("shows all five new native-push summary metrics", async () => {
    mockRoutes();
    render(<PushPage />);
    await screen.findByText("Active native registrations");

    expect(screen.getByText("Users with native push")).toBeInTheDocument();
    expect(screen.getByText("Production APNs")).toBeInTheDocument();
    expect(screen.getByText("Sandbox APNs")).toBeInTheDocument();
    expect(screen.getByText("Legacy registrations")).toBeInTheDocument();
    // Values from the pushState fixture: 9 active, 5 users, 1/2/6 breakdown.
    expect(screen.getByText("9")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument();
  });

  it("renders the native registration table with the minimum required columns", async () => {
    mockRoutes({
      nativeDevices: {
        items: [
          {
            id: "device-1",
            user_id: "user-1",
            display_name: "Jamie Example",
            email: "jamie@example.com",
            platform: "ios",
            device_label: "Jamie's iPhone",
            installation_id: "installation-abc123",
            apns_environment: "sandbox",
            last_seen_at: "2026-09-10T08:00:00Z",
            disabled_at: null,
            disabled_reason: null,
          },
        ],
        page: 1,
        page_size: 25,
        total: 1,
      },
    });
    render(<PushPage />);

    expect(await screen.findByText("Jamie Example")).toBeInTheDocument();
    expect(screen.getByText("jamie@example.com")).toBeInTheDocument();
    expect(screen.getByText("Jamie's iPhone")).toBeInTheDocument();
    expect(screen.getByText("iOS")).toBeInTheDocument();
    expect(screen.getByText("installation-abc123")).toBeInTheDocument();
    expect(screen.getByText("Sandbox")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    // Never the raw device token — the fixture above deliberately has no
    // token field at all, matching what the real endpoint returns.
    expect(document.body.textContent).not.toMatch(/[0-9a-f]{40,}/i);
  });

  it("labels a legacy (NULL apns_environment) row as Legacy, not a raw null", async () => {
    mockRoutes({
      nativeDevices: {
        items: [
          {
            id: "device-legacy",
            user_id: "user-2",
            display_name: "Legacy User",
            email: "legacy@example.com",
            platform: "ios",
            device_label: null,
            installation_id: "installation-legacy",
            apns_environment: null,
            last_seen_at: null,
            disabled_at: null,
            disabled_reason: null,
          },
        ],
        page: 1,
        page_size: 25,
        total: 1,
      },
    });
    render(<PushPage />);

    expect(await screen.findByText("Legacy")).toBeInTheDocument();
    expect(screen.getByText("Never")).toBeInTheDocument();
    expect(screen.getByText("Unlabelled")).toBeInTheDocument();
  });

  it("renders Android rows with an em dash for APNs environment, not a legacy label", async () => {
    mockRoutes({
      nativeDevices: {
        items: [
          {
            id: "device-android",
            user_id: "user-3",
            display_name: "Android User",
            email: "android@example.com",
            platform: "android",
            device_label: "Pixel",
            installation_id: "installation-android",
            apns_environment: null,
            last_seen_at: "2026-09-11T08:00:00Z",
            disabled_at: null,
            disabled_reason: null,
          },
        ],
        page: 1,
        page_size: 25,
        total: 1,
      },
    });
    render(<PushPage />);

    expect(await screen.findByText("Android")).toBeInTheDocument();
    // Both the APNs-environment cell and the (also-null) disabled-reason
    // cell render "—" for this row — assert there are at least one, not
    // exactly one, so this doesn't couple to an unrelated column's own
    // choice of placeholder.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("Legacy")).not.toBeInTheDocument();
  });

  it("distinguishes an active row from a disabled row, showing the disabled reason", async () => {
    mockRoutes({
      nativeDevices: {
        items: [
          {
            id: "device-active",
            user_id: "user-4",
            display_name: "Active User",
            email: "active@example.com",
            platform: "ios",
            device_label: "Active iPhone",
            installation_id: "installation-active",
            apns_environment: "production",
            last_seen_at: "2026-09-12T08:00:00Z",
            disabled_at: null,
            disabled_reason: null,
          },
          {
            id: "device-disabled",
            user_id: "user-5",
            display_name: "Disabled User",
            email: "disabled@example.com",
            platform: "ios",
            device_label: "Old iPhone",
            installation_id: "installation-disabled",
            apns_environment: "sandbox",
            last_seen_at: "2026-08-01T08:00:00Z",
            disabled_at: "2026-08-02T08:00:00Z",
            disabled_reason: "APNs rejected this device registration.",
          },
        ],
        page: 1,
        page_size: 25,
        total: 2,
      },
    });
    render(<PushPage />);

    await screen.findByText("Active iPhone");
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Disabled")).toBeInTheDocument();
    expect(screen.getByText("APNs rejected this device registration.")).toBeInTheDocument();
  });

  it("paginates the native registration table using Previous/Next", async () => {
    const user = userEvent.setup();
    const pageOne = {
      items: [
        {
          id: "device-page-1",
          user_id: "user-6",
          display_name: "Page One User",
          email: "page1@example.com",
          platform: "ios",
          device_label: null,
          installation_id: "installation-1",
          apns_environment: "production",
          last_seen_at: null,
          disabled_at: null,
          disabled_reason: null,
        },
      ],
      page: 1,
      page_size: 25,
      total: 30,
    };
    const pageTwo = { ...pageOne, items: [{ ...pageOne.items[0], id: "device-page-2", display_name: "Page Two User" }], page: 2 };
    get.mockImplementation((path: string) => {
      if (path === "/push") return Promise.resolve(pushState);
      if (path === "/auth/me") return Promise.resolve({ email: "op@mykhaya.app" });
      if (path.includes("page=2")) return Promise.resolve(pageTwo);
      if (path.startsWith("/push/native-devices")) return Promise.resolve(pageOne);
      return Promise.reject(new Error(`unexpected path ${path}`));
    });
    render(<PushPage />);

    await screen.findByText("Page One User");
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Page Two User")).toBeInTheDocument();
  });

  it("shows web vs native context on Recent failures without implying a whole-notification failure", async () => {
    mockRoutes({
      push: {
        ...pushState,
        recent_failures: [
          {
            id: "failure-web",
            notification_type: "event_reminder",
            failed_at: "2026-09-10T08:00:00Z",
            safe_failure_message: "Push service temporarily unavailable.",
            channel: "web",
            platform: null,
            apns_environment: null,
            recipient_user_id: "user-1",
            native_push_device_id: null,
            push_subscription_id: "subscription-1",
          },
          {
            id: "failure-native",
            notification_type: "event_reminder",
            failed_at: "2026-09-10T08:05:00Z",
            safe_failure_message: "Native push service temporarily unavailable.",
            channel: "native",
            platform: "ios",
            apns_environment: "sandbox",
            recipient_user_id: "user-2",
            native_push_device_id: "device-1",
            push_subscription_id: null,
          },
        ],
      },
    });
    render(<PushPage />);

    await screen.findByText("Recent delivery failures");
    expect(screen.getByText("Web Push")).toBeInTheDocument();
    expect(screen.getByText("iOS · APNs (Sandbox)")).toBeInTheDocument();
    expect(
      screen.getByText(
        /Each row is one device's delivery attempt, not a whole notification or a whole user/,
      ),
    ).toBeInTheDocument();
  });
});
