// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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

const { api } = await import("@mykhaya/api-client");

const user = {
  id: "u1",
  email: "anthony@example.com",
  display_name: "Anthony",
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
  nativeLogout.mockResolvedValue(undefined);
});

async function openProfileMenuAndSignOut() {
  const typist = userEvent.setup();
  await typist.click(screen.getByRole("button", { name: /open profile menu/i }));
  await typist.click(await screen.findByRole("button", { name: /sign out/i }));
}

describe("AppHeader — sign out", () => {
  it("browser/PWA: revokes the cookie session via /auth/logout, never nativeLogout", async () => {
    nativeShell = false;
    render(
      <AppHeader user={user} homes={[]} activeHome={null} onSwitchHome={vi.fn()} />,
    );

    await openProfileMenuAndSignOut();

    expect(api.post).toHaveBeenCalledWith("/auth/logout", {});
    expect(nativeLogout).not.toHaveBeenCalled();
    expect(push).toHaveBeenCalledWith("/login");
  });

  it("native shell: revokes the Keychain-backed bearer session via nativeLogout, never the cookie endpoint", async () => {
    nativeShell = true;
    render(
      <AppHeader user={user} homes={[]} activeHome={null} onSwitchHome={vi.fn()} />,
    );

    await openProfileMenuAndSignOut();

    expect(nativeLogout).toHaveBeenCalledTimes(1);
    expect(api.post).not.toHaveBeenCalledWith("/auth/logout", expect.anything());
    expect(push).toHaveBeenCalledWith("/login");
  });
});
