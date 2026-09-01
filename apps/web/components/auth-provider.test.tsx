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
vi.mock("./native-runtime", () => ({ isNativeShell: () => false }));
vi.mock("./native-auth", () => ({ bootstrapNativeSession: vi.fn() }));
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
  me.mockResolvedValue({ id: "u1", display_name: "Owner", principal_type: "adult" });
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
});
