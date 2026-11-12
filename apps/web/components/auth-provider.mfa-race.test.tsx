// @vitest-environment jsdom
/**
 * Regression: a fresh MFA sign-in on /mfa must reach the authenticated
 * shell, however slowly the device runs React's queued effects.
 *
 * On a public route the bootstrap effect resets a not-yet-ready status to
 * "signed_out". setAuthenticatedUser() changes `user`, which re-runs that
 * effect with the `status` captured in its render ("signed_out"). When the
 * device is slow enough that /legal/status answers before that queued
 * effect has run (seen on iPhone WebKit), the stale effect's
 * setStatus("signed_out") lands after setStatus("ready") and wins. The
 * router then moves to /onboarding with status "signed_out" and the
 * bootstrap guard (already bootstrapped) never re-checks the session, so the
 * page is stuck on "Taking you to sign in…".
 *
 * The slow device is simulated deterministically: performance.now() advances
 * 10ms per read, so React's scheduler always yields to the browser between
 * the commit and the queued (passive) effects, exactly as a slow WebKit
 * does. The /legal/status response is released from the commit itself.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { useLayoutEffect } from "react";
import { AuthProvider, useAuth } from "./auth-provider";
vi.unmock("./components/auth-provider");
vi.unmock("./auth-provider");

const legalStatus = vi.fn<() => Promise<unknown>>();
const router = { replace: vi.fn<(url: string) => void>(), push: vi.fn<(url: string) => void>() };
let pathname = "/mfa";
vi.mock("next/navigation", () => ({ usePathname: () => pathname, useRouter: () => router }));
vi.mock("@mykhaya/api-client", () => ({
  api: { me: vi.fn(), renew: vi.fn(), legalStatus: () => legalStatus() },
  ApiError: class ApiError extends Error { status = 401; },
}));
vi.mock("./native-runtime", () => ({
  isNativeShell: () => false,
  nativePlatform: () => "web",
  isPlatformControlCentre: () => false,
}));
vi.mock("./native-auth", () => ({ bootstrapNativeSession: vi.fn(), NativeBiometricUnlockError: class extends Error {} }));
vi.mock("./native-push", () => ({ initializeNativePush: vi.fn(), reconcileNativePush: vi.fn() }));
vi.mock("./auth-diagnostics", () => ({ recordAuthDiagnostic: vi.fn() }));
vi.mock("./native-app-lock", () => ({
  startAppLockTracking: vi.fn(),
  markUnlocked: vi.fn(),
  hasEverBeenBackgrounded: () => false,
  wasBackgroundedLongEnoughToLock: () => false,
}));

const authenticated = { id: "u1", display_name: "Owner", principal_type: "adult" } as never;
let auth: ReturnType<typeof useAuth> | null = null;
let onUserCommitted: (() => void) | null = null;

function Probe() {
  auth = useAuth();
  const userId = auth.user?.id ?? null;
  // Runs inside the commit that first shows the signed-in user: the moment
  // the browser could deliver /legal/status before the queued effects run.
  useLayoutEffect(() => {
    if (userId) onUserCommitted?.();
  }, [userId]);
  return <div data-testid="status">{auth.initialSessionLoading ? "checking" : auth.status}</div>;
}

function setActEnvironment(value: boolean) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = value;
}

beforeEach(() => {
  pathname = "/mfa";
  auth = null;
  onUserCommitted = null;
  legalStatus.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
  setActEnvironment(true);
});

describe("AuthProvider — MFA completion on a slow device", () => {
  it("stays signed in when /legal/status answers before the queued bootstrap effect runs", async () => {
    let releaseLegal!: () => void;
    legalStatus.mockReturnValue(
      new Promise((resolve) => {
        releaseLegal = () => resolve({ action_required: false });
      }),
    );
    const view = render(<AuthProvider><Probe /></AuthProvider>);
    expect(screen.getByTestId("status")).toHaveTextContent("signed_out");

    // Leave React's test batching so the real scheduler runs, as in a browser.
    setActEnvironment(false);
    let clock = performance.now();
    vi.spyOn(performance, "now").mockImplementation(() => (clock += 10));
    onUserCommitted = () => releaseLegal();

    const signIn = auth!.setAuthenticatedUser(authenticated);
    await signIn;
    vi.restoreAllMocks();
    await waitFor(() => expect(screen.getByTestId("status")).not.toHaveTextContent("checking"));

    // /mfa then navigates to /onboarding (or /home).
    setActEnvironment(true);
    pathname = "/onboarding";
    act(() => view.rerender(<AuthProvider><Probe /></AuthProvider>));

    expect(screen.getByTestId("status")).toHaveTextContent("ready");
  });

  it("control: with effects flushed promptly (a fast device) the same sign-in is ready", async () => {
    legalStatus.mockResolvedValue({ action_required: false });
    const view = render(<AuthProvider><Probe /></AuthProvider>);
    await act(async () => {
      await auth!.setAuthenticatedUser(authenticated);
    });
    pathname = "/onboarding";
    act(() => view.rerender(<AuthProvider><Probe /></AuthProvider>));
    expect(screen.getByTestId("status")).toHaveTextContent("ready");
  });
});
