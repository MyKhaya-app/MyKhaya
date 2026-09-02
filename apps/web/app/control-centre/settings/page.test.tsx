import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PlatformSettingsPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/settings",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    platformApi: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});

const { platformApi } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;
const put = platformApi.put as unknown as ReturnType<typeof vi.fn>;

const actor = {
  id: "op-1",
  email: "op@mykhaya.app",
  display_name: "Operator One",
  role: "platform_owner",
  mfa_enrolled: true,
  session_status: "full" as const,
};

function baseSettings() {
  return {
    settings: [
      {
        key: "platform_display_name",
        label: "Platform name",
        description: "The name shown for MyKhaya in administrator-facing surfaces.",
        section: "General",
        value_type: "text",
        risk: "normal",
        runtime_effect: "informational",
        editable: true,
        consumer_visible: false,
        value: null,
        state: "unset",
      },
      {
        key: "service_status_url",
        label: "Service status page",
        description: "The page consumers are sent to from Help & Support to check MyKhaya's status.",
        section: "Support",
        value_type: "url",
        risk: "normal",
        runtime_effect: "effective",
        editable: true,
        consumer_visible: true,
        value: "https://status.dev.mykhaya.app/",
        state: "default",
      },
      {
        key: "maintenance_mode",
        label: "Maintenance mode",
        description: "Take MyKhaya offline for maintenance.",
        section: "General",
        value_type: "boolean",
        risk: "sensitive",
        runtime_effect: "not_enforced",
        editable: true,
        consumer_visible: false,
        value: false,
        state: "unset",
      },
    ],
    environment: [
      { key: "public_url", value: "https://dev.mykhaya.app", category: "environment_controlled", editable: false },
    ],
  };
}

function mockRoutes(settings = baseSettings()) {
  get.mockImplementation((path: string) => {
    if (path === "/auth/me") return Promise.resolve(actor);
    if (path === "/settings") return Promise.resolve(settings);
    throw new Error(`Unexpected GET ${path}`);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockRoutes();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PCC Settings — friendly labels, not raw keys", () => {
  it("renders friendly labels as the primary heading, with the key only as secondary text", async () => {
    render(<PlatformSettingsPage />);

    const heading = await screen.findByRole("heading", { name: "Platform name" });
    expect(heading).toBeInTheDocument();
    expect(screen.getByText("platform_display_name")).toBeInTheDocument();
  });

  it("groups settings under section headings", async () => {
    render(<PlatformSettingsPage />);

    await screen.findByRole("heading", { name: "Platform name" });
    expect(screen.getByRole("heading", { name: "General" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Support" })).toBeInTheDocument();
  });
});

describe("PCC Settings — value/state rendering, never Unavailable", () => {
  it("shows a default-sourced value with the 'Using deployment default' caption", async () => {
    render(<PlatformSettingsPage />);

    await screen.findByRole("heading", { name: "Service status page" });
    expect(screen.getByDisplayValue("https://status.dev.mykhaya.app/")).toBeInTheDocument();
    expect(screen.getByText("Using deployment default")).toBeInTheDocument();
    expect(screen.queryByText("Unavailable")).not.toBeInTheDocument();
  });

  it("shows an unset value as an empty field with neutral placeholder copy", async () => {
    render(<PlatformSettingsPage />);

    await screen.findByRole("heading", { name: "Platform name" });
    const input = screen.getByPlaceholderText("Not yet set");
    expect(input).toHaveValue("");
    expect(screen.queryByText("Unavailable")).not.toBeInTheDocument();
  });

  it("shows a not_enforced caption without claiming an operational effect", async () => {
    render(<PlatformSettingsPage />);

    await screen.findByRole("heading", { name: "Maintenance mode" });
    expect(screen.getByText("Not yet enforced by the application.")).toBeInTheDocument();
  });
});

describe("PCC Settings — saving a normal setting", () => {
  it("saves exactly one key/value/reason via PUT and shows the configured caption after reload", async () => {
    const user = userEvent.setup();
    put.mockResolvedValue({ key: "platform_display_name", value: "MyKhaya", risk: "normal" });
    render(<PlatformSettingsPage />);

    await screen.findByRole("heading", { name: "Platform name" });
    const row = (await screen.findByRole("heading", { name: "Platform name" })).closest(
      ".setting-row",
    ) as HTMLElement;
    const input = within(row).getByPlaceholderText("Not yet set");
    await user.type(input, "MyKhaya");
    await user.type(within(row).getByLabelText("Reason for this change"), "Setting the platform name.");

    mockRoutes({
      ...baseSettings(),
      settings: baseSettings().settings.map((item) =>
        item.key === "platform_display_name"
          ? { ...item, value: "MyKhaya", state: "configured" }
          : item,
      ),
    });

    await user.click(within(row).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/settings/platform_display_name", {
        value: "MyKhaya",
        reason: "Setting the platform name.",
        confirmed: true,
      }),
    );
    await within(row).findByText("Configured in Platform Control Centre");
  });

  it("surfaces a validation error from a rejected save without clearing the field", async () => {
    const user = userEvent.setup();
    put.mockRejectedValue(new Error("That must be a valid http(s) URL."));
    render(<PlatformSettingsPage />);

    const row = (await screen.findByRole("heading", { name: "Service status page" })).closest(
      ".setting-row",
    ) as HTMLElement;
    // A native <input type="url"> already blocks browser submission for a
    // syntactically-invalid URL like "not-a-url" before this component's own
    // onSubmit ever runs — using a value that *is* syntactically valid HTML5
    // URL syntax (so it reaches our submit handler / the mocked PUT) but
    // that the server's stricter scheme check rejects is what actually
    // exercises the server-validation-error rendering path this test cares
    // about.
    const urlInput = within(row).getByDisplayValue("https://status.dev.mykhaya.app/");
    fireEvent.change(urlInput, { target: { value: "ftp://status.example.com" } });
    await user.type(within(row).getByLabelText("Reason for this change"), "Testing a bad URL.");

    await user.click(within(row).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(put).toHaveBeenCalled());
    await within(row).findByText("That must be a valid http(s) URL.");
    expect(urlInput).toHaveValue("ftp://status.example.com");
  });
});

describe("PCC Settings — sensitive settings require confirmation", () => {
  it("opens CcConfirmDialog instead of saving directly when a sensitive value changes", async () => {
    const user = userEvent.setup();
    render(<PlatformSettingsPage />);

    const row = (await screen.findByRole("heading", { name: "Maintenance mode" })).closest(
      ".setting-row",
    ) as HTMLElement;
    await user.click(within(row).getByRole("checkbox"));
    await user.click(within(row).getByRole("button", { name: "Save" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/does not currently change user access or behaviour/i)).toBeInTheDocument();
    expect(put).not.toHaveBeenCalled();
  });
});
