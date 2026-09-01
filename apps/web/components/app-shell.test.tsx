// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { AppShell } from "./app-shell";

const replace = vi.fn<(url: string) => void>();
const push = vi.fn<(url: string) => void>();
// A stable object identity across renders, matching real Next.js
// useRouter() — a fresh object per call (as an inline mock literal would
// produce) breaks AppShell's redirectToLogin/bootstrap useCallback
// dependency chain, causing bootstrap to needlessly re-run on every render.
const router = { replace: (url: string) => replace(url), push: (url: string) => push(url) };
vi.mock("next/navigation", () => ({
  usePathname: () => "/home",
  useRouter: () => router,
}));

vi.mock("./use-active-home", () => ({
  useActiveHome: () => ({
    homes: [
      {
        id: "home-1",
        name: "Hales Home",
        role: "owner",
        relationship: "home_admin",
        permission_profile: "home_admin",
        capabilities: [],
        member_count: 1,
        child_login_code: "1234",
      },
    ],
    activeHome: null,
    setActiveHomeId: vi.fn(),
    loading: false,
    error: null,
  }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: { ...actual.api, me: vi.fn(), renew: vi.fn() },
  };
});

let nativeShell = false;
vi.mock("./native-runtime", () => ({
  isNativeShell: () => nativeShell,
}));

const bootstrapNativeSession = vi.fn<() => Promise<unknown>>();
vi.mock("./native-auth", () => ({
  bootstrapNativeSession: () => bootstrapNativeSession(),
}));

const { api } = await import("@mykhaya/api-client");

beforeEach(() => {
  vi.clearAllMocks();
  replace.mockClear();
  nativeShell = false;
  document.documentElement.classList.remove("native-shell");
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
    id: "u1",
    display_name: "Owner",
    principal_type: "adult",
  });
  bootstrapNativeSession.mockResolvedValue({
    id: "u1",
    display_name: "Owner",
    principal_type: "adult",
  });
});

afterEach(() => {
  document.documentElement.classList.remove("native-shell");
});

describe("AppShell — native-shell root class", () => {
  it("adds html.native-shell while mounted inside the Capacitor shell", async () => {
    nativeShell = true;
    render(<AppShell>content</AppShell>);

    await screen.findByText("content");

    expect(document.documentElement.classList.contains("native-shell")).toBe(true);
  });

  it("removes html.native-shell on unmount", async () => {
    nativeShell = true;
    const { unmount } = render(<AppShell>content</AppShell>);
    await screen.findByText("content");
    expect(document.documentElement.classList.contains("native-shell")).toBe(true);

    unmount();

    expect(document.documentElement.classList.contains("native-shell")).toBe(false);
  });

  it("never adds html.native-shell in an ordinary browser/PWA tab", async () => {
    nativeShell = false;
    render(<AppShell>content</AppShell>);

    await screen.findByText("content");

    expect(document.documentElement.classList.contains("native-shell")).toBe(false);
  });
});

describe("AppShell — content scroll region", () => {
  it("wraps hero and main content in one explicit scroll-region container", async () => {
    render(<AppShell hero={<div>the hero</div>}>the content</AppShell>);

    await screen.findByText("the content");

    const region = document.querySelector(".app-content-scroll-region");
    expect(region).not.toBeNull();
    expect(region?.textContent).toContain("the hero");
    expect(region?.textContent).toContain("the content");
    // Header and bottom nav are siblings of the scroll region, not inside it —
    // they must never be part of what scrolls.
    expect(region?.querySelector(".app-header")).toBeNull();
    expect(region?.querySelector(".bottom-nav")).toBeNull();
  });

  // The native-shell top-overscroll background fix (styles.css:
  // `html.native-shell .app-content-scroll-region:has(.home-hero)`) depends
  // structurally on a `.home-hero` element being a descendant of
  // `.app-content-scroll-region` — this is what actually keeps that CSS
  // selector's precondition true regardless of native/browser mode, since
  // there's no conditional rendering involved, only CSS scoping.
  it("keeps .home-hero nested inside the scroll region identically in native shell and browser", async () => {
    for (const native of [true, false]) {
      nativeShell = native;
      const { unmount } = render(
        <AppShell hero={<div className="home-hero">greeting</div>}>content</AppShell>,
      );
      await screen.findByText("content");

      const region = document.querySelector(".app-content-scroll-region");
      expect(region?.querySelector(".home-hero")).not.toBeNull();

      unmount();
    }
  });
});

// Persistent-login fix: AppShell now bootstraps a Keychain-backed native
// session (components/native-auth.ts's bootstrapNativeSession) instead of
// the cookie-based api.me()/api.renew() flow whenever isNativeShell() is
// true — this is what makes "terminate the app, reopen it" actually
// restore the signed-in state. See components/native-auth.test.ts for
// bootstrapNativeSession's own unit coverage (Keychain read, 401→renew,
// clear-on-rejection); these tests cover AppShell's state-machine reaction
// to what that function returns.
describe("AppShell — native session bootstrap", () => {
  it("shows the loading state, not a login redirect, while bootstrapNativeSession is still pending", async () => {
    nativeShell = true;
    let resolveBootstrap!: (user: unknown) => void;
    bootstrapNativeSession.mockReturnValue(
      new Promise((resolve) => {
        resolveBootstrap = resolve;
      }),
    );
    render(<AppShell>content</AppShell>);

    expect(await screen.findByRole("status")).toHaveTextContent(/checking your mykhaya session/i);
    expect(replace).not.toHaveBeenCalled();
    expect(screen.queryByText("content")).not.toBeInTheDocument();

    resolveBootstrap({ id: "u1", display_name: "Owner", principal_type: "adult" });
    await screen.findByText("content");
  });

  it("enters the authenticated state and renders content when a stored session is restored", async () => {
    nativeShell = true;
    bootstrapNativeSession.mockResolvedValue({
      id: "u1",
      display_name: "Owner",
      principal_type: "adult",
    });
    render(<AppShell>content</AppShell>);

    await screen.findByText("content");
    expect(replace).not.toHaveBeenCalled();
    expect(api.me).not.toHaveBeenCalled();
  });

  it("redirects to /login, without rendering AppShell content, when there is no valid stored session", async () => {
    nativeShell = true;
    bootstrapNativeSession.mockResolvedValue(null);
    render(<AppShell>content</AppShell>);

    // jsdom's default location is "/" — AppShell preserves it as ?next=
    // exactly like the existing cookie-based redirect path does (it only
    // omits ?next when the destination already is /login itself).
    await vi.waitFor(() => expect(replace).toHaveBeenCalledWith("/login?next=%2F"));
    expect(screen.queryByText("content")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("fails closed into the offline/retry state, not signed-out, on a plugin or network error", async () => {
    nativeShell = true;
    bootstrapNativeSession.mockRejectedValue(new Error("Keychain plugin unavailable"));
    render(<AppShell>content</AppShell>);

    await screen.findByRole("alert");
    expect(screen.getByText(/temporarily unavailable/i)).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("never calls the cookie-based api.me()/api.renew() inside the native shell", async () => {
    nativeShell = true;
    bootstrapNativeSession.mockResolvedValue({
      id: "u1",
      display_name: "Owner",
      principal_type: "adult",
    });
    render(<AppShell>content</AppShell>);

    await screen.findByText("content");
    expect(api.me).not.toHaveBeenCalled();
    expect(api.renew).not.toHaveBeenCalled();
  });

  it("browser/PWA (not native) never calls bootstrapNativeSession", async () => {
    nativeShell = false;
    render(<AppShell>content</AppShell>);

    await screen.findByText("content");
    expect(bootstrapNativeSession).not.toHaveBeenCalled();
    expect(api.me).toHaveBeenCalledTimes(1);
  });
});
