// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppHeader } from "./app-header";

// Sign-out transport selection — the same native-source-of-truth split as
// login (see app/login/page.test.tsx): inside Capacitor this must revoke
// the Keychain-backed bearer session, never the browser cookie
// /auth/logout, and vice versa outside it.

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return { ...actual, api: { ...actual.api, post: vi.fn().mockResolvedValue(undefined) } };
});

let nativeShell = false;
vi.mock("./native-runtime", () => ({
  isNativeShell: () => nativeShell,
}));

const nativeLogout = vi.fn<() => Promise<void>>();
vi.mock("./native-auth", () => ({
  nativeLogout: () => nativeLogout(),
}));

vi.mock("./notification-state", () => ({
  useNotifications: () => ({ unreadCount: 0 }),
}));

let desktopShellActive = false;
vi.mock("./use-desktop-shell", () => ({
  useDesktopShellActive: () => desktopShellActive,
}));

const clearSession = vi.fn();
vi.mock("./auth-provider", () => ({
  useAuth: () => ({ clearSession }),
}));

const { api } = await import("@mykhaya/api-client");

const user = {
  id: "u1",
  email: "anthony@example.com",
  display_name: "Anthony Hales",
  email_verified: true,
  birth_month: null,
  birth_day: null,
  birth_year: null,
  avatar_version: null,
  principal_type: "adult",
} as const;

beforeEach(() => {
  vi.clearAllMocks();
  nativeShell = false;
  desktopShellActive = false;
  nativeLogout.mockResolvedValue(undefined);
});

async function renderHeader() {
  return render(<AppHeader user={user} homes={[]} activeHome={null} onSwitchHome={vi.fn()} />);
}

async function openMenu() {
  const typist = userEvent.setup();
  await typist.click(screen.getByRole("button", { name: /open profile menu/i }));
  return typist;
}

describe("AppHeader — sign out", () => {
  it("browser/PWA: revokes the cookie session via /auth/logout, never nativeLogout", async () => {
    nativeShell = false;
    await renderHeader();
    const typist = await openMenu();
    await typist.click(await screen.findByRole("button", { name: /^sign out$/i }));

    expect(api.post).toHaveBeenCalledWith("/auth/logout", {});
    expect(nativeLogout).not.toHaveBeenCalled();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"));
  });

  it("native shell: revokes the Keychain-backed bearer session via nativeLogout, never the cookie endpoint", async () => {
    nativeShell = true;
    await renderHeader();
    const typist = await openMenu();
    await typist.click(await screen.findByRole("button", { name: /^sign out$/i }));

    expect(nativeLogout).toHaveBeenCalledTimes(1);
    expect(api.post).not.toHaveBeenCalledWith("/auth/logout", expect.anything());
    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"));
  });

  it("clears authenticated client state on successful sign out", async () => {
    await renderHeader();
    const typist = await openMenu();
    await typist.click(await screen.findByRole("button", { name: /^sign out$/i }));

    await waitFor(() => expect(clearSession).toHaveBeenCalledTimes(1));
  });

  it("does not touch MFA/TOTP configuration — sign out only calls the existing logout transport", async () => {
    await renderHeader();
    const typist = await openMenu();
    await typist.click(await screen.findByRole("button", { name: /^sign out$/i }));

    // The only API call sign out makes is the existing logout endpoint —
    // nothing under /auth/mfa or /auth/totp is ever touched by this flow.
    const calledPaths = (api.post as ReturnType<typeof vi.fn>).mock.calls.map(
      (call: unknown[]) => call[0] as string,
    );
    expect(calledPaths).toEqual(["/auth/logout"]);
  });

  it("keeps the user authenticated and shows a safe error when logout fails", async () => {
    (api.post as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("network down"));
    await renderHeader();
    const typist = await openMenu();
    await typist.click(await screen.findByRole("button", { name: /^sign out$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/sign out failed/i);
    expect(clearSession).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalledWith("/login");
    // Menu stays open/usable — the sign out control is still present.
    expect(screen.getByRole("button", { name: /^sign out$/i })).toBeInTheDocument();
  });

  it("prevents duplicate sign-out requests while one is already in flight", async () => {
    let resolveLogout: () => void = () => {};
    (api.post as ReturnType<typeof vi.fn>).mockImplementationOnce(
      () => new Promise<void>((resolve) => { resolveLogout = resolve; }),
    );
    await renderHeader();
    const typist = await openMenu();
    const signOutButton = await screen.findByRole("button", { name: /sign out/i });
    await typist.click(signOutButton);
    await typist.click(screen.getByRole("button", { name: /signing out/i }));

    expect(api.post).toHaveBeenCalledTimes(1);
    resolveLogout();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"));
  });
});

describe("AppHeader — desktop account dropdown", () => {
  beforeEach(() => {
    desktopShellActive = true;
  });

  it("opens a compact anchored account dropdown, not the centred Profile sheet", async () => {
    await renderHeader();
    await openMenu();

    const menu = await screen.findByLabelText("Account menu");
    expect(menu).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows the display name and masked email", async () => {
    await renderHeader();
    await openMenu();

    const menu = await screen.findByLabelText("Account menu");
    expect(menu).toHaveTextContent("Anthony Hales");
    expect(menu).toHaveTextContent("a•••@example.com");
    expect(menu).not.toHaveTextContent("anthony@example.com");
  });

  it("sets aria-haspopup/aria-expanded correctly on the avatar trigger", async () => {
    await renderHeader();
    const trigger = screen.getByRole("button", { name: /open profile menu/i });
    expect(trigger).toHaveAttribute("aria-haspopup", "true");
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    const typist = userEvent.setup();
    await typist.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });

  it("clicking the avatar again closes the dropdown", async () => {
    await renderHeader();
    const trigger = screen.getByRole("button", { name: /open profile menu/i });
    const typist = userEvent.setup();
    await typist.click(trigger);
    await screen.findByLabelText("Account menu");
    await typist.click(trigger);

    await waitFor(() => expect(screen.queryByLabelText("Account menu")).not.toBeInTheDocument());
  });

  it("clicking outside closes the dropdown", async () => {
    await renderHeader();
    const typist = await openMenu();
    await screen.findByLabelText("Account menu");
    await typist.click(document.body);

    await waitFor(() => expect(screen.queryByLabelText("Account menu")).not.toBeInTheDocument());
  });

  it("Escape closes the dropdown", async () => {
    await renderHeader();
    const typist = await openMenu();
    await screen.findByLabelText("Account menu");
    await typist.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByLabelText("Account menu")).not.toBeInTheDocument());
  });

  it("Profile link points at the existing Profile destination and closes the menu", async () => {
    await renderHeader();
    const typist = await openMenu();
    const menu = await screen.findByLabelText("Account menu");
    const profileLink = within(menu).getByRole("link", { name: /profile/i });
    expect(profileLink).toHaveAttribute("href", "/settings/profile");
    await typist.click(profileLink);

    await waitFor(() => expect(screen.queryByLabelText("Account menu")).not.toBeInTheDocument());
  });

  it("Settings link points at the existing Settings destination", async () => {
    await renderHeader();
    await openMenu();
    const menu = await screen.findByLabelText("Account menu");
    expect(within(menu).getByRole("link", { name: /^settings$/i })).toHaveAttribute("href", "/settings");
  });

  it("Security link points at the existing consumer Security destination, not PCC", async () => {
    await renderHeader();
    await openMenu();
    const menu = await screen.findByLabelText("Account menu");
    const securityLink = within(menu).getByRole("link", { name: /security/i });
    expect(securityLink).toHaveAttribute("href", "/settings/security");
  });
});

describe("AppHeader — narrow mobile browser", () => {
  it("retains the existing Profile sheet when the desktop shell is not active", async () => {
    desktopShellActive = false;
    await renderHeader();
    await openMenu();

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByLabelText("Account menu")).not.toBeInTheDocument();
  });
});

describe("AppHeader — native iOS", () => {
  it("uses the mobile-style sheet, unaffected by the desktop dropdown work", async () => {
    nativeShell = true;
    desktopShellActive = false; // useDesktopShellActive() is always false inside the native shell
    await renderHeader();
    await openMenu();

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByLabelText("Account menu")).not.toBeInTheDocument();
  });
});

describe("AppHeader — botanical decoration", () => {
  it("renders the leafy watermark hidden from assistive technology, never covering the real controls", () => {
    const { container } = render(
      <AppHeader user={user} homes={[]} activeHome={null} onSwitchHome={vi.fn()} />,
    );

    const decoration = container.querySelector(".app-header-botanical");
    expect(decoration).not.toBeNull();
    expect(decoration).toHaveAttribute("aria-hidden", "true");
    // Purely decorative — it must never be reachable as a named element by
    // its own accessible name, and never intercept taps meant for the real
    // header controls (see the pointer-events: none rule in styles.css).
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByRole("button", { name: /open profile menu/i })).toBeInTheDocument();
  });
});
