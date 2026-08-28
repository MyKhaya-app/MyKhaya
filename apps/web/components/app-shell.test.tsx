// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { AppShell } from "./app-shell";

vi.mock("next/navigation", () => ({
  usePathname: () => "/home",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
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
    api: { ...actual.api, me: vi.fn() },
  };
});

let nativeShell = false;
vi.mock("./native-runtime", () => ({
  isNativeShell: () => nativeShell,
}));

const { api } = await import("@mykhaya/api-client");

beforeEach(() => {
  vi.clearAllMocks();
  nativeShell = false;
  document.documentElement.classList.remove("native-shell");
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
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
});
