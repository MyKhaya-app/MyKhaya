// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { NativeBiometricOffer } from "./native-biometric-offer";

let nativeShell = true;
let offerAfterLogin = true;
const capability = vi.hoisted(() => ({
  kind: "faceId" as const,
  label: "Face ID",
  available: true,
  lockedOut: false,
  notEnrolled: false,
  reason: "",
}));
const getBiometricCapability = vi.fn<() => Promise<typeof capability>>();
const getBiometricPreference = vi.fn<() => Promise<"enabled" | "declined" | "undecided">>();
const authenticateWithBiometrics = vi.fn<(reason: string) => Promise<{ ok: boolean }>>();
const setBiometricSignInEnabled = vi.fn<(enabled: boolean) => Promise<void>>();
const declineBiometricSignIn = vi.fn<() => Promise<void>>();

vi.mock("./native-runtime", () => ({ isNativeShell: () => nativeShell }));
vi.mock("./native-auth", () => ({ consumeBiometricOfferAfterLogin: () => offerAfterLogin }));
vi.mock("./native-biometric", () => ({
  getBiometricCapability: () => getBiometricCapability(),
  authenticateWithBiometrics: (reason: string) => authenticateWithBiometrics(reason),
  isBiometricCancellation: () => false,
}));
vi.mock("./native-biometric-preference", () => ({
  getBiometricPreference: () => getBiometricPreference(),
  setBiometricSignInEnabled: (enabled: boolean) => setBiometricSignInEnabled(enabled),
  declineBiometricSignIn: () => declineBiometricSignIn(),
}));

beforeEach(() => {
  nativeShell = true;
  offerAfterLogin = true;
  getBiometricCapability.mockResolvedValue(capability);
  getBiometricPreference.mockResolvedValue("undecided");
  authenticateWithBiometrics.mockResolvedValue({ ok: true });
  setBiometricSignInEnabled.mockResolvedValue(undefined);
  declineBiometricSignIn.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("NativeBiometricOffer — onSettled sequencing signal", () => {
  it("fires onSettled immediately outside the native shell, without showing the offer", async () => {
    nativeShell = false;
    const onSettled = vi.fn();
    render(<NativeBiometricOffer onSettled={onSettled} />);

    await waitFor(() => expect(onSettled).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("fires onSettled immediately when there was no post-login offer to consume", async () => {
    offerAfterLogin = false;
    const onSettled = vi.fn();
    render(<NativeBiometricOffer onSettled={onSettled} />);

    await waitFor(() => expect(onSettled).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("fires onSettled once capability/preference resolve to 'nothing to show'", async () => {
    getBiometricPreference.mockResolvedValue("enabled");
    const onSettled = vi.fn();
    render(<NativeBiometricOffer onSettled={onSettled} />);

    await waitFor(() => expect(onSettled).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("does not fire onSettled while the offer is visible and awaiting a decision", async () => {
    const onSettled = vi.fn();
    render(<NativeBiometricOffer onSettled={onSettled} />);

    await screen.findByRole("dialog");
    expect(onSettled).not.toHaveBeenCalled();
  });

  it("fires onSettled after the user enables biometrics", async () => {
    const onSettled = vi.fn();
    render(<NativeBiometricOffer onSettled={onSettled} />);
    const dialog = await screen.findByRole("dialog");

    await act(async () => {
      screen.getByRole("button", { name: /enable face id/i }).click();
    });

    await waitFor(() => expect(onSettled).toHaveBeenCalledTimes(1));
    expect(dialog).not.toBeInTheDocument();
  });

  it("fires onSettled after the user declines with Not now", async () => {
    const onSettled = vi.fn();
    render(<NativeBiometricOffer onSettled={onSettled} />);
    await screen.findByRole("dialog");

    await act(async () => {
      screen.getByRole("button", { name: /not now/i }).click();
    });

    await waitFor(() => expect(onSettled).toHaveBeenCalledTimes(1));
    expect(declineBiometricSignIn).toHaveBeenCalledTimes(1);
  });

  it("works with no onSettled prop at all (existing/default usage unaffected)", async () => {
    expect(() => render(<NativeBiometricOffer />)).not.toThrow();
    await screen.findByRole("dialog");
  });
});
