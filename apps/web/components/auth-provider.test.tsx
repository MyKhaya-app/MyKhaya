// @vitest-environment jsdom
import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { AuthProvider, useAuth } from "./auth-provider";
vi.unmock("./components/auth-provider");
vi.unmock("./auth-provider");

const me = vi.fn<(...args: unknown[]) => Promise<unknown>>();
const renew = vi.fn<(...args: unknown[]) => Promise<unknown>>();
const router = { replace: vi.fn<(url: string) => void>() };
let pathname = "/home";
vi.mock("next/navigation", () => ({ usePathname: () => pathname, useRouter: () => router }));
vi.mock("@mykhaya/api-client", () => ({ api: { me: (...args: unknown[]) => me(...args), renew: (...args: unknown[]) => renew(...args) }, ApiError: class ApiError extends Error { status = 401; } }));
const { nativeShellState, platformSurface, bootstrapNativeSession } = vi.hoisted(() => ({
  nativeShellState: { value: false },
  platformSurface: { value: false },
  bootstrapNativeSession: vi.fn<() => Promise<unknown>>(),
}));
vi.mock("./native-runtime", () => ({
  isNativeShell: () => nativeShellState.value,
  nativePlatform: () => nativeShellState.value ? "ios" : "web",
  isPlatformControlCentre: () => platformSurface.value,
}));
vi.mock("./native-auth", () => ({ bootstrapNativeSession, NativeBiometricUnlockError: class NativeBiometricUnlockError extends Error { name = "NativeBiometricUnlockError"; } }));
vi.mock("./native-push", () => ({
  initializeNativePush: vi.fn().mockResolvedValue(undefined),
  reconcileNativePush: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("./auth-diagnostics", () => ({ recordAuthDiagnostic: vi.fn() }));

// Phase 4 lifecycle wiring: a controllable @capacitor/app so tests can fire
// appStateChange directly, and a controllable native-app-lock so each test
// can choose what the elapsed-background-time decision should be without
// manipulating real timers/module singleton state across files.
const { appLock, handlerBox, addListener, removeListener } = vi.hoisted(() => ({
  appLock: { hasEverBeenBackgrounded: false, wasBackgroundedLongEnoughToLock: false },
  handlerBox: { current: null as ((info: { isActive: boolean }) => void) | null },
  addListener: vi.fn<(event: string, cb: (info: { isActive: boolean }) => void) => void>(),
  removeListener: vi.fn(),
}));
vi.mock("@capacitor/app", () => ({
  App: {
    addListener: (event: string, cb: (info: { isActive: boolean }) => void) => {
      addListener(event, cb);
      handlerBox.current = cb;
      return Promise.resolve({ remove: removeListener });
    },
  },
}));
const startAppLockTracking = vi.fn<() => void>();
const markUnlocked = vi.fn<() => void>();
vi.mock("./native-app-lock", () => ({
  startAppLockTracking: () => startAppLockTracking(),
  markUnlocked: () => markUnlocked(),
  hasEverBeenBackgrounded: () => appLock.hasEverBeenBackgrounded,
  wasBackgroundedLongEnoughToLock: () => appLock.wasBackgroundedLongEnoughToLock,
}));

function fireAppState(isActive: boolean) {
  act(() => {
    handlerBox.current?.({ isActive });
  });
}

function Probe() {
  const auth = useAuth();
  return <>
    <div>{auth.initialSessionLoading ? "checking" : auth.status}</div>
    <button onClick={() => void auth.refreshSession()}>refresh</button>
    <button onClick={() => auth.retryInitialSession()}>retry</button>
  </>;
}

beforeEach(() => {
  me.mockReset();
  renew.mockReset();
  router.replace.mockReset();
  pathname = "/home";
  nativeShellState.value = false;
  platformSurface.value = false;
  me.mockResolvedValue({ id: "u1", display_name: "Owner", principal_type: "adult" });
  bootstrapNativeSession.mockReset();
  appLock.hasEverBeenBackgrounded = false;
  appLock.wasBackgroundedLongEnoughToLock = false;
  handlerBox.current = null;
  addListener.mockReset();
  removeListener.mockReset();
  startAppLockTracking.mockReset();
  markUnlocked.mockReset();
});

describe("AuthProvider", () => {
  it("does not bootstrap or redirect a browser MFA pre-auth route", async () => {
    // usePathname() excludes the query string; the MFA page reads the
    // transaction separately through useSearchParams().
    pathname = "/mfa";
    me.mockRejectedValue(new (await import("@mykhaya/api-client")).ApiError(401, "Unauthenticated"));

    render(<AuthProvider><Probe /></AuthProvider>);

    await waitFor(() => expect(screen.getByText("signed_out")).toBeInTheDocument());
    expect(me).not.toHaveBeenCalled();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("shows initial bootstrap state, then remains ready without reloading", async () => {
    let resolve!: (value: unknown) => void;
    me.mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<AuthProvider><Probe /></AuthProvider>);
    expect(screen.getByText("checking")).toBeInTheDocument();
    resolve({ id: "u1", display_name: "Owner", principal_type: "adult" });
    await waitFor(() => expect(screen.getByText("ready")).toBeInTheDocument());
    expect(me).toHaveBeenCalledTimes(1);
  });

  it("keeps the page available during background refresh", async () => {
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByText("ready")).toBeInTheDocument());
    let resolve!: (value: unknown) => void;
    me.mockReturnValueOnce(new Promise((r) => { resolve = r; }));
    screen.getByText("refresh").click();
    expect(screen.queryByText("checking")).not.toBeInTheDocument();
    resolve({ id: "u1", display_name: "Owner", principal_type: "adult" });
    await waitFor(() => expect(me).toHaveBeenCalledTimes(2));
  });

  it("does not bootstrap again when navigating between authenticated routes", async () => {
    const view = render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByText("ready")).toBeInTheDocument());
    pathname = "/calendar";
    view.rerender(<AuthProvider><Probe /></AuthProvider>);
    pathname = "/meal-plans";
    view.rerender(<AuthProvider><Probe /></AuthProvider>);
    pathname = "/settings";
    view.rerender(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByText("ready")).toBeInTheDocument());
    expect(me).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("checking")).not.toBeInTheDocument();
  });

  it("restores a native session through the bearer client and keeps it offline on a transient startup failure", async () => {
    nativeShellState.value = true;
    bootstrapNativeSession.mockResolvedValue({ id: "native-u1", display_name: "Owner", principal_type: "adult" });
    const view = render(<AuthProvider><Probe /></AuthProvider>);

    await waitFor(() => expect(screen.getByText("ready")).toBeInTheDocument());
    expect(bootstrapNativeSession).toHaveBeenCalledTimes(1);

    // A fresh provider models the new JS process after a hard-close. A
    // transient Keychain/transport error must not become a login redirect.
    bootstrapNativeSession.mockRejectedValueOnce(new Error("Keychain temporarily unavailable"));
    view.unmount();
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByText("offline")).toBeInTheDocument());
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("does not run consumer auth bootstrap on the PCC surface", async () => {
    platformSurface.value = true;
    pathname = "/users";
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByText("signed_out")).toBeInTheDocument());
    expect(me).not.toHaveBeenCalled();
    expect(bootstrapNativeSession).not.toHaveBeenCalled();
  });
});

// Phase 4: native lifecycle re-lock. These exercise the resume handler as a
// state machine — not just the pure helpers in native-app-lock.ts — so a
// regression in how auth-provider wires appStateChange, statusRef,
// loadSessionRef, or the reauthenticatingOnResume guard together would be
// caught here even though every individual helper still passes its own
// unit tests.
describe("AuthProvider — native lifecycle re-lock", () => {
  async function boot() {
    nativeShellState.value = true;
    bootstrapNativeSession.mockResolvedValue({ id: "native-u1", display_name: "Owner", principal_type: "adult" });
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByText("ready")).toBeInTheDocument());
    expect(startAppLockTracking).toHaveBeenCalled();
    expect(handlerBox.current).not.toBeNull();
    bootstrapNativeSession.mockClear();
  }

  it("a short background dip (<5min) leaves the app ready and never re-bootstraps", async () => {
    await boot();
    appLock.hasEverBeenBackgrounded = true;
    appLock.wasBackgroundedLongEnoughToLock = false;

    fireAppState(false);
    fireAppState(true);

    // Give any (incorrect) async re-auth a chance to start before asserting
    // it didn't.
    await Promise.resolve();
    expect(screen.getByText("ready")).toBeInTheDocument();
    expect(bootstrapNativeSession).not.toHaveBeenCalled();
  });

  it("a spurious isActive:true with no prior background (some platforms fire this on startup) is a no-op, even if the elapsed-time check alone would say lock", async () => {
    await boot();
    appLock.hasEverBeenBackgrounded = false;
    appLock.wasBackgroundedLongEnoughToLock = true; // shouldRequireUnlock(null, ...) default

    fireAppState(true);

    await Promise.resolve();
    expect(screen.getByText("ready")).toBeInTheDocument();
    expect(bootstrapNativeSession).not.toHaveBeenCalled();
  });

  it("a background period past the timeout re-locks and re-authenticates via the same bootstrap path, ending ready again", async () => {
    await boot();
    appLock.hasEverBeenBackgrounded = true;
    appLock.wasBackgroundedLongEnoughToLock = true;
    bootstrapNativeSession.mockResolvedValue({ id: "native-u1", display_name: "Owner", principal_type: "adult" });

    fireAppState(false);
    fireAppState(true);

    await waitFor(() => expect(bootstrapNativeSession).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText("ready")).toBeInTheDocument());
    expect(router.replace).not.toHaveBeenCalled();
    expect(markUnlocked).toHaveBeenCalled();
  });

  it("a cancelled/failed biometric unlock on resume leaves the app locked without touching the stored server session", async () => {
    await boot();
    appLock.hasEverBeenBackgrounded = true;
    appLock.wasBackgroundedLongEnoughToLock = true;
    const { NativeBiometricUnlockError } = await import("./native-auth");
    bootstrapNativeSession.mockRejectedValue(new NativeBiometricUnlockError("cancelled", "Biometric unlock was not completed."));

    fireAppState(false);
    fireAppState(true);

    await waitFor(() => expect(screen.getByText("locked")).toBeInTheDocument());
    expect(router.replace).not.toHaveBeenCalled();

    // A retry (e.g. the lock screen's "Try again") reuses the exact same
    // gate and can still succeed without ever having destroyed the session.
    bootstrapNativeSession.mockResolvedValueOnce({ id: "native-u1", display_name: "Owner", principal_type: "adult" });
    screen.getByText("retry").click();
    await waitFor(() => expect(screen.getByText("ready")).toBeInTheDocument());
  });

  it("a server session revoked while backgrounded wins over any biometric outcome and sends the user to login", async () => {
    await boot();
    appLock.hasEverBeenBackgrounded = true;
    appLock.wasBackgroundedLongEnoughToLock = true;
    bootstrapNativeSession.mockResolvedValue(null);

    fireAppState(false);
    fireAppState(true);

    await waitFor(() => expect(screen.getByText("signed_out")).toBeInTheDocument());
    expect(router.replace).toHaveBeenCalledWith(expect.stringContaining("/login"));
  });

  it("rapid repeated foreground events while a re-auth is already in flight only trigger one bootstrap call", async () => {
    await boot();
    appLock.hasEverBeenBackgrounded = true;
    appLock.wasBackgroundedLongEnoughToLock = true;
    let resolveBootstrap!: (value: unknown) => void;
    bootstrapNativeSession.mockReturnValue(new Promise((r) => { resolveBootstrap = r; }));

    fireAppState(false);
    fireAppState(true);
    // Simulate task-switcher flicker / a picker dialog's own transitions
    // firing more isActive:true events before the in-flight re-auth settles.
    fireAppState(true);
    fireAppState(true);

    expect(bootstrapNativeSession).toHaveBeenCalledTimes(1);
    resolveBootstrap({ id: "native-u1", display_name: "Owner", principal_type: "adult" });
    await waitFor(() => expect(screen.getByText("ready")).toBeInTheDocument());
    expect(bootstrapNativeSession).toHaveBeenCalledTimes(1);
  });

  it("a resume while already locked is a no-op — the lock screen's own controls stay in charge, no auto-retry storm", async () => {
    await boot();
    appLock.hasEverBeenBackgrounded = true;
    appLock.wasBackgroundedLongEnoughToLock = true;
    const { NativeBiometricUnlockError } = await import("./native-auth");
    bootstrapNativeSession.mockRejectedValue(new NativeBiometricUnlockError("cancelled", "Biometric unlock was not completed."));

    fireAppState(false);
    fireAppState(true);
    await waitFor(() => expect(screen.getByText("locked")).toBeInTheDocument());
    bootstrapNativeSession.mockClear();

    // Another background/foreground cycle while still locked must not
    // trigger a second automatic re-auth attempt.
    fireAppState(false);
    fireAppState(true);
    await Promise.resolve();
    expect(bootstrapNativeSession).not.toHaveBeenCalled();
    expect(screen.getByText("locked")).toBeInTheDocument();
  });

  it("does nothing outside the native shell — the listener is never registered for a browser/PWA session", async () => {
    nativeShellState.value = false;
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByText("ready")).toBeInTheDocument());
    expect(startAppLockTracking).not.toHaveBeenCalled();
    expect(addListener).not.toHaveBeenCalled();
  });
});
