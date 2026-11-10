import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import SupportSettingsPage from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/control-centre/support/settings",
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
const put = platformApi.put as unknown as ReturnType<typeof vi.fn>;

function mockLoad({
  supportEnabled = true,
  serviceStatusState = "configured",
  supportNotificationEmail = "support-team@example.com" as string | null,
  newTicket = {
    configured: false,
    enabled: true,
    roles: [] as string[],
    include_support_inbox: true,
    recipient_count: 0,
    can_manage: false,
  },
}: {
  supportEnabled?: boolean;
  serviceStatusState?: "configured" | "default" | "unset";
  supportNotificationEmail?: string | null;
  newTicket?: {
    configured: boolean;
    enabled: boolean;
    roles: string[];
    include_support_inbox: boolean;
    recipient_count: number;
    can_manage: boolean;
  };
} = {}) {
  get.mockImplementation((path: string) => {
    if (path === "/modules") {
      return Promise.resolve([{ key: "support", enabled: supportEnabled }]);
    }
    if (path === "/settings") {
      return Promise.resolve({
        settings: [{ key: "service_status_url", state: serviceStatusState, value: null }],
      });
    }
    if (path === "/support/settings") {
      return Promise.resolve({
        support_notification_email: supportNotificationEmail,
        new_ticket_notifications: newTicket,
      });
    }
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockLoad();
});

describe("Support settings", () => {
  it("shows Support availability as Enabled, sourced from Platform Modules, with a link to it (not a second toggle)", async () => {
    render(<SupportSettingsPage />);
    await screen.findByText("Enabled");
    const link = screen.getByRole("link", { name: "Platform Modules" });
    expect(link).toHaveAttribute("href", "/modules");
    // No editable control for this value — it's display-only.
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("shows Support availability as Disabled when the module is off", async () => {
    mockLoad({ supportEnabled: false });
    render(<SupportSettingsPage />);
    expect(await screen.findByText("Disabled")).toBeInTheDocument();
  });

  it("shows the configured support notification email destination", async () => {
    render(<SupportSettingsPage />);
    await screen.findAllByText("Configured");
    expect(screen.getByText("support-team@example.com")).toBeInTheDocument();
  });

  it("shows Not configured, and no destination row, when no team notification email is set", async () => {
    mockLoad({ supportNotificationEmail: null });
    render(<SupportSettingsPage />);
    const section = (await screen.findByRole("heading", { name: "Support notification email" })).closest("section")!;
    expect(await within(section).findByText("Not configured")).toBeInTheDocument();
    expect(screen.queryByText("support-team@example.com")).toBeNull();
  });

  it("shows Service Status as Configured with a link to Platform Settings", async () => {
    render(<SupportSettingsPage />);
    await screen.findAllByText("Configured");
    const link = screen.getByRole("link", { name: "Platform Settings" });
    expect(link).toHaveAttribute("href", "/settings");
  });

  it("shows Service Status as Not configured when the URL is unset", async () => {
    mockLoad({ serviceStatusState: "unset" });
    render(<SupportSettingsPage />);
    const section = (await screen.findByRole("heading", { name: "Service Status" })).closest("section")!;
    expect(await within(section).findByText("Not configured")).toBeInTheDocument();
  });

  it("shows Knowledge Base as Coming soon", async () => {
    render(<SupportSettingsPage />);
    await screen.findByText("Enabled");
    expect(screen.getByText("Coming soon")).toBeInTheDocument();
  });

  it("lists what consumer Support provides without exposing internals", async () => {
    render(<SupportSettingsPage />);
    await screen.findByText("Enabled");
    const heading = screen.getByRole("heading", { name: "What consumer Support provides" });
    const section = heading.closest("section");
    expect(section).not.toBeNull();
    const scoped = within(section!);
    expect(scoped.getByText("Report a bug")).toBeInTheDocument();
    expect(scoped.getByText("Contact Support")).toBeInTheDocument();
    expect(scoped.getByText("Diagnostics")).toBeInTheDocument();
    expect(scoped.getByText("My support requests")).toBeInTheDocument();
    expect(scoped.getByText("Email updates")).toBeInTheDocument();
  });

  it("shows a safe error message, not a raw exception, when loading fails", async () => {
    get.mockRejectedValue(new ApiError(500, "Could not load Support settings."));
    render(<SupportSettingsPage />);
    expect(await screen.findByText("Could not load Support settings.")).toBeInTheDocument();
  });
});

describe("Support settings — new ticket email notifications", () => {
  const configured = {
    configured: true,
    enabled: true,
    roles: ["support_operator", "platform_administrator"],
    include_support_inbox: false,
    recipient_count: 3,
    can_manage: true,
  };

  it("explains the original behaviour until the setting is saved, read-only for Support", async () => {
    render(<SupportSettingsPage />);
    expect(await screen.findByText(/emailed only to the support inbox above, as before/)).toBeInTheDocument();
    expect(screen.getByText("Only Platform Owners and Administrators can change these settings.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save notification settings" })).toBeNull();
  });

  it("shows the selected roles and current recipient count", async () => {
    mockLoad({ newTicket: { ...configured, can_manage: false } });
    render(<SupportSettingsPage />);
    expect(await screen.findByText("Administrators, Support operators")).toBeInTheDocument();
    expect(screen.getByText("3 people")).toBeInTheDocument();
    expect(screen.getByText("On")).toBeInTheDocument();
  });

  it("lets an Owner or Administrator save roles with a reason", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    mockLoad({ newTicket: configured });
    put.mockResolvedValue({ ...configured, roles: ["platform_owner", "platform_administrator", "support_operator"], recipient_count: 4 });
    render(<SupportSettingsPage />);
    const owners = await screen.findByRole("checkbox", { name: "Owners" });
    expect(screen.getByRole("checkbox", { name: "Support operators" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Also send to the support inbox \(support-team@example.com\)/ })).not.toBeChecked();
    await userEvent.click(owners);
    await userEvent.type(screen.getByLabelText(/Reason for this change/), "Owners triage weekend tickets");
    await userEvent.click(screen.getByRole("button", { name: "Save notification settings" }));
    expect(put).toHaveBeenCalledWith("/support/settings/new-ticket-notifications", {
      enabled: true,
      roles: ["platform_owner", "platform_administrator", "support_operator"],
      include_support_inbox: false,
      reason: "Owners triage weekend tickets",
      confirmed: true,
    });
    expect(await screen.findByText("New ticket notification settings saved.")).toBeInTheDocument();
    expect(screen.getByText("4 people")).toBeInTheDocument();
  });
});
