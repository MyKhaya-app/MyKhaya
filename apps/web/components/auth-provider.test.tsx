// @vitest-environment jsdom
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
vi.mock("./native-auth", () => ({ bootstrapNativeSession, NativeBiometricUnlockError: class NativeBiometricUnlockError extends Error {} }));
vi.mock("./native-push", () => ({
  initializeNativePush: vi.fn().mockResolvedValue(undefined),
  reconcileNativePush: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("./auth-diagnostics", () => ({ recordAuthDiagnostic: vi.fn() }));

function Probe() {
  const auth = useAuth();
  return <><div>{auth.initialSessionLoading ? "checking" : auth.status}</div><button onClick={() => void auth.refreshSession()}>refresh</button></>;
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
});

describe("AuthProvider", () => {
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
