// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QuickSignIn } from "./quick-sign-in";

// Regression coverage for "Quick Sign-In freezes/crashes the native app":
// a Capacitor plugin whose iOS implementation isn't actually linked into
// the compiled binary (see apps/ios-shell/package.json) can leave a bridge
// call permanently unresolved rather than rejecting — these tests prove
// this component never gets stuck waiting on such a call, using fake
// timers to simulate "never resolves" without an actually-slow test.

const getBiometricCapability = vi.fn<() => Promise<unknown>>();
const authenticateWithBiometrics = vi.fn<(reason: string) => Promise<unknown>>();
// Defaults match iOS shape — most of this file's own concern is the
// hang/timeout safety net and the enable/disable flow, not per-platform
// copy (see native-biometric.test.ts's biometricLabel/deviceNoun describe
// blocks for that in isolation) — but the "Android" describe block below
// overrides these per-test to prove the component itself renders Android's
// neutral copy correctly end-to-end, not just that the helpers return it.
const biometricLabelMock = vi.fn((kind: string) => (kind === "none" ? "Face ID" : kind));
const deviceNounMock = vi.fn(() => "this iPhone");
vi.mock("./native-biometric", () => ({
  getBiometricCapability: () => getBiometricCapability(),
  authenticateWithBiometrics: (reason: string) => authenticateWithBiometrics(reason),
  isBiometricCancellation: (result: { ok: boolean }) => !result.ok,
  biometricLabel: (kind: string) => biometricLabelMock(kind),
  deviceNoun: () => deviceNounMock(),
}));

const isBiometricSignInEnabled = vi.fn<() => Promise<boolean>>();
const setBiometricSignInEnabled = vi.fn<(enabled: boolean) => Promise<void>>();
vi.mock("./native-biometric-preference", () => ({
  isBiometricSignInEnabled: () => isBiometricSignInEnabled(),
  setBiometricSignInEnabled: (enabled: boolean) => setBiometricSignInEnabled(enabled),
}));

beforeEach(() => {
  vi.clearAllMocks();
  getBiometricCapability.mockResolvedValue({
    kind: "faceId",
    label: "Face ID",
    available: true,
    lockedOut: false,
    notEnrolled: false,
    reason: "",
  });
  isBiometricSignInEnabled.mockResolvedValue(false);
  setBiometricSignInEnabled.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("QuickSignIn — plugin whose native implementation is not linked (never resolves)", () => {
  it("settles into a safe unavailable state instead of hanging forever when checkBiometry never resolves", async () => {
    vi.useFakeTimers();
    getBiometricCapability.mockReturnValue(new Promise(() => {})); // never resolves
    isBiometricSignInEnabled.mockReturnValue(new Promise(() => {}));

    render(<QuickSignIn />);

    await vi.advanceTimersByTimeAsync(5000);

    expect(
      screen.getByText(/quick sign-in isn.t available on this iphone/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /enable/i })).not.toBeInTheDocument();
  });

  it("still renders normally, with no timeout delay, when the plugin responds promptly", async () => {
    render(<QuickSignIn />);

    expect(await screen.findByRole("button", { name: /enable face id/i })).toBeInTheDocument();
  });

  it("a hanging authenticate() call during Enable resolves to a safe failure instead of leaving the button stuck busy", async () => {
    vi.useFakeTimers();
    authenticateWithBiometrics.mockReturnValue(new Promise(() => {})); // never resolves
    render(<QuickSignIn />);
    // Flush the mount effect's already-resolved mock promises. Testing
    // Library's own findBy*/waitFor poll with real timers, which don't mix
    // with fake ones — vi.waitFor is timer-aware and works correctly here.
    await vi.waitFor(() => screen.getByRole("button", { name: /enable face id/i }));

    // fireEvent (not userEvent) — userEvent's own internal waiting doesn't
    // mix reliably with fake timers, and this test only needs the click's
    // synchronous dispatch, not userEvent's realistic pointer sequencing.
    fireEvent.click(screen.getByRole("button", { name: /enable face id/i }));
    await vi.advanceTimersByTimeAsync(5000);

    await vi.waitFor(() =>
      expect(screen.getByRole("button", { name: /enable face id/i })).not.toBeDisabled(),
    );
    expect(setBiometricSignInEnabled).not.toHaveBeenCalledWith(true);
  });
});

describe("QuickSignIn — normal enable/disable flow (unaffected by the timeout guard)", () => {
  it("enabling records the preference on a successful biometric confirmation", async () => {
    authenticateWithBiometrics.mockResolvedValue({ ok: true });
    const user = userEvent.setup();
    render(<QuickSignIn />);

    await user.click(await screen.findByRole("button", { name: /enable face id/i }));

    expect(setBiometricSignInEnabled).toHaveBeenCalledWith(true);
    await screen.findByText(/face id is ready/i);
  });

  it("disabling clears the preference", async () => {
    isBiometricSignInEnabled.mockResolvedValue(true);
    const user = userEvent.setup();
    render(<QuickSignIn />);

    await user.click(await screen.findByRole("button", { name: /disable/i }));

    expect(setBiometricSignInEnabled).toHaveBeenCalledWith(false);
    await screen.findByText(/turned off on this iphone/i);
  });
});

describe("QuickSignIn — Android's neutral copy end-to-end", () => {
  beforeEach(() => {
    biometricLabelMock.mockImplementation((kind: string) =>
      kind === "none" ? "biometric sign-in" : "biometric sign-in",
    );
    deviceNounMock.mockImplementation(() => "this device");
    getBiometricCapability.mockResolvedValue({
      kind: "other",
      label: "biometric sign-in",
      available: true,
      lockedOut: false,
      notEnrolled: false,
      reason: "",
    });
  });

  afterEach(() => {
    biometricLabelMock.mockImplementation((kind: string) => (kind === "none" ? "Face ID" : kind));
    deviceNounMock.mockImplementation(() => "this iPhone");
  });

  it("offers neutral 'biometric sign-in' copy, never 'Face ID'/'Touch ID', when available", async () => {
    render(<QuickSignIn />);

    const button = await screen.findByRole("button", { name: /enable biometric sign-in/i });
    expect(button).toBeInTheDocument();
    expect(screen.getByText(/securely access mykhaya on this device/i)).toBeInTheDocument();
    expect(screen.queryByText(/face id|touch id/i)).not.toBeInTheDocument();
  });

  it("enabling on Android records the preference and shows neutral confirmation copy", async () => {
    authenticateWithBiometrics.mockResolvedValue({ ok: true });
    const user = userEvent.setup();
    render(<QuickSignIn />);

    await user.click(await screen.findByRole("button", { name: /enable biometric sign-in/i }));

    expect(setBiometricSignInEnabled).toHaveBeenCalledWith(true);
    expect(authenticateWithBiometrics).toHaveBeenCalledWith("Enable biometric sign-in for MyKhaya");
    await screen.findByText(/biometric sign-in is ready/i);
  });

  it("not-enrolled copy on Android names the device generically, never 'iPhone'", async () => {
    getBiometricCapability.mockResolvedValue({
      kind: "other",
      label: "biometric sign-in",
      available: false,
      lockedOut: false,
      notEnrolled: true,
      reason: "The user does not have any biometrics enrolled.",
    });

    render(<QuickSignIn />);

    expect(await screen.findByText(/isn.t set up on this device yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/iphone/i)).not.toBeInTheDocument();
  });

  it("cancelling the Android biometric prompt during Enable never shows an error or enables the preference", async () => {
    authenticateWithBiometrics.mockResolvedValue({ ok: false, code: "userCancel", message: "cancelled" });
    const user = userEvent.setup();
    render(<QuickSignIn />);

    await user.click(await screen.findByRole("button", { name: /enable biometric sign-in/i }));

    expect(setBiometricSignInEnabled).not.toHaveBeenCalledWith(true);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
