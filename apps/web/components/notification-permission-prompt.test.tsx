// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { NotificationPermissionPrompt } from "./notification-permission-prompt";

let nativeShell = true;
const hook = vi.hoisted(() => ({
  status: "not_requested" as "not_requested" | "granted" | "denied" | "restricted" | "unsupported",
  loading: false,
  requestPermission: vi.fn(),
  openSettings: vi.fn(),
  refresh: vi.fn(),
}));
let dismissed = false;

vi.mock("./native-runtime", () => ({ isNativeShell: () => nativeShell }));
vi.mock("./use-notification-permission", () => ({ useNotificationPermission: () => hook }));
vi.mock("./notification-permission-state", () => ({
  wasRecentlyDismissed: () => dismissed,
  recordDismissal: vi.fn(() => {
    dismissed = true;
  }),
}));

beforeEach(() => {
  nativeShell = true;
  dismissed = false;
  hook.status = "not_requested";
  hook.loading = false;
  hook.requestPermission.mockReset().mockResolvedValue("granted");
  hook.openSettings.mockReset().mockResolvedValue(undefined);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("NotificationPermissionPrompt — recommend (first native launch, not requested)", () => {
  it("shows the MyKhaya explainer as a shared BottomSheet, not a bespoke element", async () => {
    render(<NotificationPermissionPrompt />);
    const dialog = await screen.findByRole("dialog");

    expect(dialog).toHaveClass("bottom-sheet");
    expect(screen.getByText("Stay in the loop")).toBeInTheDocument();
    expect(screen.getByText(/MyKhaya works best when notifications are enabled/)).toBeInTheDocument();
  });

  it("'Enable notifications' calls the adapter's requestPermission and closes", async () => {
    render(<NotificationPermissionPrompt />);
    await screen.findByRole("dialog");

    screen.getByRole("button", { name: "Enable notifications" }).click();

    await waitFor(() => expect(hook.requestPermission).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("'Not now' closes without calling requestPermission and persists dismissal", async () => {
    render(<NotificationPermissionPrompt />);
    await screen.findByRole("dialog");

    screen.getByRole("button", { name: "Not now" }).click();

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(hook.requestPermission).not.toHaveBeenCalled();
    expect(dismissed).toBe(true);
  });

  it("does not reappear within the dismissal cooldown window (re-mount)", async () => {
    const { unmount } = render(<NotificationPermissionPrompt />);
    await screen.findByRole("dialog");
    screen.getByRole("button", { name: "Not now" }).click();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    unmount();

    render(<NotificationPermissionPrompt />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("NotificationPermissionPrompt — denied (previously denied at OS level)", () => {
  it("shows the 'Open phone settings' variant, never calling requestPermission", async () => {
    hook.status = "denied";
    render(<NotificationPermissionPrompt />);
    const dialog = await screen.findByRole("dialog");

    expect(screen.getByText("Notifications are turned off")).toBeInTheDocument();
    const openSettingsButton = screen.getByRole("button", { name: "Open phone settings" });
    openSettingsButton.click();

    await waitFor(() => expect(hook.openSettings).toHaveBeenCalledTimes(1));
    expect(hook.requestPermission).not.toHaveBeenCalled();
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
  });

  it("'Maybe later' dismisses without opening settings", async () => {
    hook.status = "denied";
    render(<NotificationPermissionPrompt />);
    await screen.findByRole("dialog");

    screen.getByRole("button", { name: "Maybe later" }).click();

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(hook.openSettings).not.toHaveBeenCalled();
    expect(dismissed).toBe(true);
  });
});

describe("NotificationPermissionPrompt — quiet states", () => {
  it("renders nothing once permission is granted", () => {
    hook.status = "granted";
    render(<NotificationPermissionPrompt />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders nothing while restricted (no actionable common state defined for it yet)", () => {
    hook.status = "restricted";
    render(<NotificationPermissionPrompt />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders nothing outside the native shell (browser/PWA unaffected)", () => {
    nativeShell = false;
    hook.status = "not_requested";
    render(<NotificationPermissionPrompt />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders nothing while still loading the initial status", () => {
    hook.loading = true;
    render(<NotificationPermissionPrompt />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders nothing if already dismissed within the cooldown window", () => {
    dismissed = true;
    render(<NotificationPermissionPrompt />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
