// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { AppShell, PersistentAppShell } from "./app-shell";

vi.mock("./auth-provider", () => ({
  useAuth: () => ({
    user: { id: "u1", display_name: "Owner", principal_type: "adult" },
    status: "ready",
    initialSessionLoading: false,
    sessionRefreshing: false,
    retryInitialSession: vi.fn(),
    refreshSession: vi.fn(),
    setAuthenticatedUser: vi.fn(),
  }),
}));

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
  ActiveHomeProvider: ({ children }: { children: ReactNode }) => children,
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
let platformControlCentre = false;
vi.mock("./native-runtime", () => ({
  isNativeShell: () => nativeShell,
  isPlatformControlCentre: () => platformControlCentre,
}));

const bootstrapNativeSession = vi.fn<() => Promise<unknown>>();
vi.mock("./native-auth", () => ({
  bootstrapNativeSession: () => bootstrapNativeSession(),
  consumeBiometricOfferAfterLogin: () => false,
}));

const { api } = await import("@mykhaya/api-client");

beforeEach(() => {
  vi.clearAllMocks();
  replace.mockClear();
  nativeShell = false;
  platformControlCentre = false;
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

describe("AppShell — authenticated navigation", () => {
  it("keeps the authenticated shell mounted without a session bootstrap screen", async () => {
    render(<AppShell>content</AppShell>);
    expect(await screen.findByText("content")).toBeInTheDocument();
    expect(screen.queryByText(/checking your mykhaya session/i)).not.toBeInTheDocument();
    expect(bootstrapNativeSession).not.toHaveBeenCalled();
  });

  it("keeps the shell mounted while authenticated page content changes", async () => {
    const first = render(<PersistentAppShell><div>Home</div></PersistentAppShell>);
    const header = document.querySelector(".app-header");
    const bottomNav = document.querySelector(".bottom-nav");

    expect(document.querySelector(".app-main")?.textContent).toContain("Home");
    first.rerender(<PersistentAppShell><div>Calendar</div></PersistentAppShell>);
    expect(document.querySelector(".app-main")?.textContent).toContain("Calendar");
    expect(document.querySelectorAll(".app-header")).toHaveLength(1);
    expect(document.querySelectorAll(".bottom-nav")).toHaveLength(1);
    expect(document.querySelector(".app-header")).toBe(header);
    expect(document.querySelector(".bottom-nav")).toBe(bottomNav);
  });

  it("never mounts the consumer AppShell when the PCC surface is selected", async () => {
    platformControlCentre = true;
    render(<PersistentAppShell><div>PCC</div></PersistentAppShell>);
    expect(screen.getByText("PCC")).toBeInTheDocument();
    expect(document.querySelector(".app-header")).toBeNull();
    expect(document.querySelector(".bottom-nav")).toBeNull();
  });
});
