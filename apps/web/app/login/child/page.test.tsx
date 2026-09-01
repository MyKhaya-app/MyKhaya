import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ChildLogin from "./page";
import { getRememberedChildAccounts, rememberChildAccount } from "@/components/child-login-client";

// Managed child sign-in coverage. Two things under test:
// 1. The Home code field must accept the whole 8-character code MyKhaya
//    actually generates (mykhaya.security.generate_home_code) — a past bug
//    truncated entry well before that.
// 2. A device that has signed a child in before should offer a simplified
//    "Welcome back <name> / PIN only" screen instead of the full form,
//    without ever persisting the PIN itself.

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      childLogin: vi.fn(),
    },
  };
});

let nativeShell = false;
vi.mock("@/components/native-runtime", () => ({
  isNativeShell: () => nativeShell,
}));

const nativeChildLogin = vi.fn<(homeCode: string, username: string, pin: string) => Promise<unknown>>();
vi.mock("@/components/native-auth", () => ({
  nativeChildLogin: (homeCode: string, username: string, pin: string) =>
    nativeChildLogin(homeCode, username, pin),
}));

const { api, ApiError } = await import("@mykhaya/api-client");

const FULL_HOME_CODE = "ABCD2345"; // 8 chars — the real generated length
const child = { id: "child-1", display_name: "Alyssa", avatar_version: null } as const;

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  nativeShell = false;
});

describe("Child sign-in — Home code field", () => {
  it("accepts the full 8-character Home code without truncating it", async () => {
    const typist = userEvent.setup();
    render(<ChildLogin />);

    const homeCodeInput = screen.getByLabelText<HTMLInputElement>("Home code");
    expect(homeCodeInput.maxLength).toBe(8);

    await typist.type(homeCodeInput, FULL_HOME_CODE);

    expect(homeCodeInput.value).toBe(FULL_HOME_CODE);
    expect(homeCodeInput.value).not.toBe(FULL_HOME_CODE.slice(0, 5));
    expect(homeCodeInput.value.length).toBe(8);
  });

  it("submits the full Home code to the API unchanged (normalised to uppercase)", async () => {
    (api.childLogin as ReturnType<typeof vi.fn>).mockResolvedValue(child);
    const typist = userEvent.setup();
    render(<ChildLogin />);

    await typist.type(screen.getByLabelText("Home code"), FULL_HOME_CODE.toLowerCase());
    await typist.type(screen.getByLabelText("Username"), "alyssa");
    await typist.type(screen.getByLabelText("PIN"), "4242");
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() =>
      expect(api.childLogin).toHaveBeenCalledWith({
        home_code: FULL_HOME_CODE,
        username: "alyssa",
        pin: "4242",
      }),
    );
  });
});

describe("Child sign-in — first-time device (no remembered account)", () => {
  it("shows the full Home code / username / PIN form", () => {
    render(<ChildLogin />);

    expect(screen.getByLabelText("Home code")).toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
    expect(screen.getByLabelText("PIN")).toBeInTheDocument();
    expect(screen.queryByText(/welcome back/i)).not.toBeInTheDocument();
  });

  it("successful authentication remembers the Home + username on this device", async () => {
    (api.childLogin as ReturnType<typeof vi.fn>).mockResolvedValue(child);
    const typist = userEvent.setup();
    render(<ChildLogin />);

    await typist.type(screen.getByLabelText("Home code"), FULL_HOME_CODE);
    await typist.type(screen.getByLabelText("Username"), "Alyssa");
    await typist.type(screen.getByLabelText("PIN"), "4242");
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/home"));
    const remembered = getRememberedChildAccounts();
    expect(remembered).toHaveLength(1);
    expect(remembered[0]).toMatchObject({
      homeCode: FULL_HOME_CODE,
      username: "alyssa",
      userId: "child-1",
      displayName: "Alyssa",
    });
  });

  it("failed authentication does not remember anything", async () => {
    (api.childLogin as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(401, "Incorrect sign-in details."),
    );
    const typist = userEvent.setup();
    render(<ChildLogin />);

    await typist.type(screen.getByLabelText("Home code"), FULL_HOME_CODE);
    await typist.type(screen.getByLabelText("Username"), "alyssa");
    await typist.type(screen.getByLabelText("PIN"), "0000");
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));

    await screen.findByText(/incorrect sign-in details/i);
    expect(push).not.toHaveBeenCalled();
    expect(getRememberedChildAccounts()).toEqual([]);
  });

  it("never writes the PIN to localStorage", async () => {
    (api.childLogin as ReturnType<typeof vi.fn>).mockResolvedValue(child);
    const typist = userEvent.setup();
    render(<ChildLogin />);

    await typist.type(screen.getByLabelText("Home code"), FULL_HOME_CODE);
    await typist.type(screen.getByLabelText("Username"), "alyssa");
    await typist.type(screen.getByLabelText("PIN"), "913579");
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/home"));
    const everyStoredValue = Object.keys(window.localStorage)
      .map((key) => window.localStorage.getItem(key))
      .join("\n");
    expect(everyStoredValue).not.toContain("913579");
  });
});

describe("Child sign-in — returning device with one remembered account", () => {
  beforeEach(() => {
    rememberChildAccount({
      homeCode: FULL_HOME_CODE,
      username: "alyssa",
      userId: "child-1",
      displayName: "Alyssa",
      avatarVersion: null,
      lastUsedAt: new Date().toISOString(),
    });
  });

  it("shows a simplified Welcome back screen with the remembered name and Home, PIN only", () => {
    render(<ChildLogin />);

    expect(screen.getByText("Welcome back")).toBeInTheDocument();
    expect(screen.getByText("Alyssa")).toBeInTheDocument();
    expect(screen.getByText(new RegExp(FULL_HOME_CODE))).toBeInTheDocument();
    expect(screen.getByLabelText("PIN")).toBeInTheDocument();
    expect(screen.queryByLabelText("Home code")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Username")).not.toBeInTheDocument();
  });

  it("signs in using the remembered Home code and username, only asking for the PIN", async () => {
    (api.childLogin as ReturnType<typeof vi.fn>).mockResolvedValue(child);
    const typist = userEvent.setup();
    render(<ChildLogin />);

    await typist.type(screen.getByLabelText("PIN"), "4242");
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() =>
      expect(api.childLogin).toHaveBeenCalledWith({
        home_code: FULL_HOME_CODE,
        username: "alyssa",
        pin: "4242",
      }),
    );
    await waitFor(() => expect(push).toHaveBeenCalledWith("/home"));
  });

  it('"Use a different account or Home" reveals the full sign-in form', async () => {
    const typist = userEvent.setup();
    render(<ChildLogin />);

    await typist.click(screen.getByRole("button", { name: /use a different account or home/i }));

    expect(screen.getByLabelText("Home code")).toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
    expect(screen.getByLabelText("PIN")).toBeInTheDocument();
    // The remembered account is untouched — only the displayed screen changed.
    expect(getRememberedChildAccounts()).toHaveLength(1);
  });

  it('"Forget this account" removes the remembered identity and returns to the full form', async () => {
    const typist = userEvent.setup();
    render(<ChildLogin />);

    await typist.click(screen.getByRole("button", { name: /forget this account/i }));

    expect(getRememberedChildAccounts()).toEqual([]);
    expect(screen.getByLabelText("Home code")).toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
    expect(screen.queryByText("Welcome back")).not.toBeInTheDocument();
  });
});

describe("Child sign-in — returning device with multiple remembered accounts", () => {
  beforeEach(() => {
    rememberChildAccount({
      homeCode: FULL_HOME_CODE,
      username: "alyssa",
      userId: "child-1",
      displayName: "Alyssa",
      avatarVersion: null,
      lastUsedAt: new Date(Date.now() - 1000).toISOString(),
    });
    rememberChildAccount({
      homeCode: "WXYZ6789",
      username: "sam",
      userId: "child-2",
      displayName: "Sam",
      avatarVersion: null,
      lastUsedAt: new Date().toISOString(),
    });
  });

  it("offers an account picker instead of guessing which child this is", () => {
    render(<ChildLogin />);

    expect(screen.getByText("Alyssa")).toBeInTheDocument();
    expect(screen.getByText("Sam")).toBeInTheDocument();
    expect(screen.queryByLabelText("PIN")).not.toBeInTheDocument();
  });

  it("selecting an account moves to its PIN-only sign-in screen", async () => {
    const typist = userEvent.setup();
    render(<ChildLogin />);

    await typist.click(screen.getByRole("button", { name: /alyssa/i }));

    expect(screen.getByText("Welcome back")).toBeInTheDocument();
    expect(screen.getByLabelText("PIN")).toBeInTheDocument();
    expect(screen.getByText(new RegExp(FULL_HOME_CODE))).toBeInTheDocument();
  });
});

describe("Child sign-in — native shell uses the native bearer transport", () => {
  it("submits via nativeChildLogin, not api.childLogin, from the manual form", async () => {
    nativeShell = true;
    nativeChildLogin.mockResolvedValue(child);
    const typist = userEvent.setup();
    render(<ChildLogin />);

    await typist.type(screen.getByLabelText("Home code"), FULL_HOME_CODE);
    await typist.type(screen.getByLabelText("Username"), "alyssa");
    await typist.type(screen.getByLabelText("PIN"), "4242");
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/home"));
    expect(nativeChildLogin).toHaveBeenCalledWith(FULL_HOME_CODE, "alyssa", "4242");
    expect(api.childLogin).not.toHaveBeenCalled();
  });

  it("submits via nativeChildLogin from the returning-account PIN screen too", async () => {
    nativeShell = true;
    nativeChildLogin.mockResolvedValue(child);
    rememberChildAccount({
      homeCode: FULL_HOME_CODE,
      username: "alyssa",
      userId: "child-1",
      displayName: "Alyssa",
      avatarVersion: null,
      lastUsedAt: new Date().toISOString(),
    });
    const typist = userEvent.setup();
    render(<ChildLogin />);

    await typist.type(await screen.findByLabelText("PIN"), "4242");
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/home"));
    expect(nativeChildLogin).toHaveBeenCalledWith(FULL_HOME_CODE, "alyssa", "4242");
    expect(api.childLogin).not.toHaveBeenCalled();
  });
});
