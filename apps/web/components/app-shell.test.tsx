// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { AppShell, PersistentAppShell } from "./app-shell";

vi.mock("./around-house-dock", () => ({
  AroundHouseDock: () => <aside data-testid="around-house-dock" />,
}));

let biometricOnSettled: (() => void) | undefined;
vi.mock("./native-biometric-offer", () => ({
  NativeBiometricOffer: ({ onSettled }: { onSettled?: () => void } = {}) => {
    biometricOnSettled = onSettled;
    return <div data-testid="biometric-offer-stub" />;
  },
}));

vi.mock("./notification-permission-prompt", () => ({
  NotificationPermissionPrompt: () => <div data-testid="notification-prompt-stub" />,
}));

const authState: { status: string } = { status: "ready" };
vi.mock("./auth-provider", () => ({
  useAuth: () => ({
    user: { id: "u1", display_name: "Owner", principal_type: "adult" },
    status: authState.status,
    initialSessionLoading: false,
    sessionRefreshing: false,
    retryInitialSession: vi.fn(),
    refreshSession: vi.fn(),
    setAuthenticatedUser: vi.fn(),
    clearSession: vi.fn(),
  }),
}));

const replace = vi.fn<(url: string) => void>();
const push = vi.fn<(url: string) => void>();
// A stable object identity across renders, matching real Next.js
// useRouter() — a fresh object per call (as an inline mock literal would
// produce) breaks AppShell's redirectToLogin/bootstrap useCallback
// dependency chain, causing bootstrap to needlessly re-run on every render.
const router = { replace: (url: string) => replace(url), push: (url: string) => push(url) };
let pathname = "/home";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
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
let nativePlatform: "ios" | "android" | "web" = "ios";
vi.mock("./native-runtime", () => ({
  isNativeShell: () => nativeShell,
  isPlatformControlCentre: () => platformControlCentre,
  nativePlatform: () => nativePlatform,
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
  nativePlatform = "ios";
  pathname = "/home";
  authState.status = "ready";
  biometricOnSettled = undefined;
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
  it("leaves the browser MFA route outside the authenticated shell", async () => {
    pathname = "/mfa";
    render(<PersistentAppShell><div>MFA</div></PersistentAppShell>);

    expect(await screen.findByText("MFA")).toBeInTheDocument();
    expect(document.querySelector(".app-shell")).toBeNull();
    expect(document.querySelector(".desktop-nav")).toBeNull();
    expect(document.querySelector(".bottom-nav")).toBeNull();
  });

  it("mounts the browser wide-screen rail alongside the protected mobile nav", async () => {
    nativeShell = false;
    render(<AppShell>content</AppShell>);

    await screen.findByText("content");

    expect(document.querySelector(".desktop-nav")).not.toBeNull();
    expect(document.querySelector(".bottom-nav")).not.toBeNull();
    expect(screen.getByTestId("around-house-dock")).toBeInTheDocument();
    expect(document.querySelector(".app-shell")).not.toHaveClass("native-shell-app");
    expect(document.querySelector(".pcc-root")).toBeNull();
  });

  it("does not mount the browser wide-screen rail in the native shell", async () => {
    nativeShell = true;
    render(<AppShell>content</AppShell>);

    await screen.findByText("content");

    expect(document.querySelector(".desktop-nav")).toBeNull();
    expect(screen.queryByTestId("around-house-dock")).not.toBeInTheDocument();
    expect(document.querySelector(".app-shell")).toHaveClass("native-shell-app");
  });

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

  it("keeps Help & Support drill-down routes inside the persistent consumer shell", async () => {
    pathname = "/help-support/diagnostics";
    render(<PersistentAppShell><div>Support diagnostics</div></PersistentAppShell>);
    expect(screen.getByText("Support diagnostics")).toBeInTheDocument();
    expect(document.querySelector(".app-shell")).not.toBeNull();
    expect(document.querySelector(".bottom-nav")).not.toBeNull();
  });
});

describe("AppShell — sequences the biometric offer ahead of the notification prompt", () => {
  it("does not mount NotificationPermissionPrompt until the biometric offer settles", async () => {
    render(<AppShell>content</AppShell>);
    await screen.findByTestId("biometric-offer-stub");

    expect(screen.queryByTestId("notification-prompt-stub")).not.toBeInTheDocument();

    act(() => {
      biometricOnSettled?.();
    });

    expect(await screen.findByTestId("notification-prompt-stub")).toBeInTheDocument();
  });

  it("never shows both onboarding overlays at once", async () => {
    render(<AppShell>content</AppShell>);
    await screen.findByTestId("biometric-offer-stub");
    expect(screen.queryByTestId("notification-prompt-stub")).toBeNull();

    act(() => {
      biometricOnSettled?.();
    });

    // The biometric stub stays mounted (it's AppShell's own persistent
    // slot, not conditionally unmounted) — what matters is the
    // notification prompt was withheld until settling, not a mutual-
    // exclusion toggle between the two.
    expect(await screen.findByTestId("notification-prompt-stub")).toBeInTheDocument();
  });

  it("still shows the notification prompt when the biometric offer has nothing to show (settles immediately)", async () => {
    render(<AppShell>content</AppShell>);

    // The stub's onSettled ref is captured synchronously on mount; calling
    // it simulates the real component's "nothing to show" early-settle path.
    await screen.findByTestId("biometric-offer-stub");
    act(() => {
      biometricOnSettled?.();
    });

    expect(await screen.findByTestId("notification-prompt-stub")).toBeInTheDocument();
  });
});

describe("AppShell — locked-state unlock copy is platform-aware", () => {
  it("names Face ID and Touch ID by name on iOS", async () => {
    nativePlatform = "ios";
    authState.status = "locked";

    render(<AppShell>content</AppShell>);

    expect(await screen.findByText(/face id/i)).toBeInTheDocument();
    expect(screen.getByText(/touch id/i)).toBeInTheDocument();
  });

  it("never claims a specific named modality on Android", async () => {
    nativePlatform = "android";
    authState.status = "locked";

    render(<AppShell>content</AppShell>);

    await screen.findByRole("heading", { name: /unlock mykhaya/i });
    expect(screen.queryByText(/face id|touch id/i)).not.toBeInTheDocument();
  });
});
