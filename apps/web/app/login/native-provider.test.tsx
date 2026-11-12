import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Native-shell (iOS) "Continue with Apple" flow on the login screen: the
// API-issued transaction, the AuthenticationServices assertion, the exchange,
// and how each failure is surfaced. The browser flows are covered in
// page.test.tsx.

const push = vi.fn();
const replace = vi.fn();
let searchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  useSearchParams: () => searchParams,
}));

vi.mock("@capacitor/app", () => ({
  App: { addListener: vi.fn(() => Promise.resolve({ remove: vi.fn() })) },
}));
const browserOpen = vi.fn<(...args: unknown[]) => Promise<void>>();
vi.mock("@capacitor/browser", () => ({ Browser: { open: (...args: unknown[]) => browserOpen(...args) } }));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      betaContinuation: vi.fn(async () => ({ pending: false, enrolled: false })),
      publicSignupState: vi.fn(async () => ({
        signup_mode: "normal",
        registration_open: true,
        invitation_required: false,
        normal_signup_available: true,
        beta_joining_available: false,
        waitlist_available: false,
        joinable_count: null,
      })),
      authProviders: vi.fn(async () => ({ providers: [] })),
      publicLegalDocuments: vi.fn(async () => []),
    },
  };
});

let platform: "ios" | "android" = "ios";
vi.mock("@/components/native-runtime", () => ({
  isNativeShell: () => true,
  nativePlatform: () => platform,
}));

type AsyncMock = (...args: unknown[]) => Promise<unknown>;
const nativeExternalStart = vi.fn<AsyncMock>();
const nativeExternalAssertion = vi.fn<AsyncMock>();
const nativeExternalExchange = vi.fn<AsyncMock>();
const nativeExternalBrowserStart = vi.fn<AsyncMock>();
const nativeExternalRecoveryRegister = vi.fn<AsyncMock>();
vi.mock("@/components/native-auth", () => ({
  nativeLogin: vi.fn(),
  nativeExternalStart: (...args: unknown[]) => nativeExternalStart(...args),
  nativeExternalAssertion: (...args: unknown[]) => nativeExternalAssertion(...args),
  nativeExternalExchange: (...args: unknown[]) => nativeExternalExchange(...args),
  nativeExternalBrowserStart: (...args: unknown[]) => nativeExternalBrowserStart(...args),
  nativeExternalRedeem: vi.fn(),
  nativeExternalRecoveryLink: vi.fn(),
  nativeExternalRecoveryRegister: (...args: unknown[]) => nativeExternalRecoveryRegister(...args),
  nativeMfaOptions: vi.fn(async () => ({ methods: ["email"], preferred_method: "email" })),
  nativeMfaStart: vi.fn(),
  nativeMfaVerify: vi.fn(),
  cancelNativeMfa: vi.fn(),
  getLastNativeLoginDiagnostic: () => null,
  runNativeNetworkDiagnostics: vi.fn(async () => []),
}));

const setAuthenticatedUser = vi.fn();
vi.mock("@/components/auth-provider", () => ({
  useAuth: () => ({ user: null, status: "signed_out", setAuthenticatedUser, refresh: vi.fn(), signOut: vi.fn() }),
}));

const { ApiError, api } = await import("@mykhaya/api-client");
const { default: Login } = await import("./page");

const IDENTITY_TOKEN = "eyJ.synthetic-apple-identity-token.sig";
const user = { id: "user-1", display_name: "Anthony", avatar_version: null };

function started() {
  return { transaction_id: "tx-123", nonce: "raw-nonce-abcdefghijklmnop", provider: "apple", client_id: "app.mykhaya.mobile" };
}

function rejection(code: string, nativeCode?: number) {
  return Object.assign(new Error("Apple sign-in could not be completed"), {
    code,
    data: nativeCode === undefined ? {} : { native_code: nativeCode },
  });
}

async function continueWithApple() {
  const person = userEvent.setup();
  render(<Login />);
  await person.click(await screen.findByRole("button", { name: "Continue with Apple" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  platform = "ios";
  searchParams = new URLSearchParams();
  window.localStorage.clear();
  nativeExternalStart.mockResolvedValue(started());
  nativeExternalAssertion.mockResolvedValue({ identity_token: IDENTITY_TOKEN });
  nativeExternalExchange.mockResolvedValue(user);
});

describe("Login — native iOS Sign in with Apple", () => {
  it("signs in through AuthenticationServices and one correlated exchange", async () => {
    await continueWithApple();

    await waitFor(() => expect(push).toHaveBeenCalledWith("/home"));
    // A plain sign-in carries no Beta intent.
    expect(nativeExternalStart).toHaveBeenCalledWith("apple", "login", expect.stringMatching(/^nauth-[0-9a-f]{16}$/), undefined);
    const correlationId = nativeExternalStart.mock.calls[0]![2];
    expect(nativeExternalAssertion).toHaveBeenCalledWith("apple", "raw-nonce-abcdefghijklmnop", "app.mykhaya.mobile");
    expect(nativeExternalExchange).toHaveBeenCalledWith("tx-123", IDENTITY_TOKEN, correlationId);
    expect(setAuthenticatedUser).toHaveBeenCalledWith(user);
    expect(browserOpen).not.toHaveBeenCalled();
  });

  it("returns quietly to sign-in when the person cancels the Apple sheet", async () => {
    const info = vi.spyOn(console, "info").mockImplementation(() => undefined);
    nativeExternalAssertion.mockRejectedValue(rejection("cancelled", 1001));
    await continueWithApple();

    const button = await screen.findByRole("button", { name: "Continue with Apple" });
    await waitFor(() => expect(button).toBeEnabled());
    expect(nativeExternalExchange).not.toHaveBeenCalled();
    expect(screen.queryByText(/could not be completed/)).not.toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
    info.mockRestore();
  });

  it("can retry after cancelling", async () => {
    vi.spyOn(console, "info").mockImplementation(() => undefined);
    nativeExternalAssertion.mockRejectedValueOnce(rejection("cancelled", 1001));
    const person = userEvent.setup();
    render(<Login />);
    const button = await screen.findByRole("button", { name: "Continue with Apple" });
    await person.click(button);
    await waitFor(() => expect(button).toBeEnabled());
    await person.click(button);

    await waitFor(() => expect(push).toHaveBeenCalledWith("/home"));
    expect(nativeExternalStart).toHaveBeenCalledTimes(2);
    expect(nativeExternalStart.mock.calls[0]![2]).not.toBe(nativeExternalStart.mock.calls[1]![2]);
  });

  it.each([
    ["apple_unknown", 1000, /Apple sign-in isn.t available on this device right now/],
    ["apple_failed", 1004, /^Apple sign-in could not be completed\. Please try again or use your password\.$/],
  ])("explains a %s provider failure without exposing internals", async (code, nativeCode, message) => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    nativeExternalAssertion.mockRejectedValue(rejection(code, nativeCode));
    await continueWithApple();

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(nativeExternalExchange).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalledWith(
      "[NATIVE AUTH] provider attempt failed",
      expect.objectContaining({ provider: "apple", stage: "provider", code, native_code: nativeCode }),
    );
    warn.mockRestore();
  });

  it("asks for an app update when the installed app predates the native plugin", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    nativeExternalAssertion.mockRejectedValue(
      Object.assign(new Error('"NativeExternalAuth" plugin is not implemented on ios'), { code: "UNIMPLEMENTED" }),
    );
    await continueWithApple();
    expect(await screen.findByText(/needs the latest version of the MyKhaya app/)).toBeInTheDocument();
  });

  it("shows the server's message when the backend rejects the Apple credential, without logging it", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    nativeExternalExchange.mockRejectedValue(new ApiError(400, "The provider sign-in could not be verified."));
    await continueWithApple();

    expect(await screen.findByText("The provider sign-in could not be verified.")).toBeInTheDocument();
    expect(warn).toHaveBeenCalledWith(
      "[NATIVE AUTH] provider attempt failed",
      expect.objectContaining({ stage: "exchange", category: "server_rejected", status: 400 }),
    );
    const logged = JSON.stringify(warn.mock.calls);
    expect(logged).not.toContain(IDENTITY_TOKEN);
    expect(logged).not.toContain("raw-nonce-abcdefghijklmnop");
    expect(logged).not.toContain("tx-123");
    warn.mockRestore();
  });

  it("shows an expired-attempt message from the API", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    nativeExternalExchange.mockRejectedValue(new ApiError(400, "This sign-in attempt is invalid or has expired."));
    await continueWithApple();
    expect(await screen.findByText("This sign-in attempt is invalid or has expired.")).toBeInTheDocument();
  });

  it("explains when MyKhaya could not be reached", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    nativeExternalStart.mockRejectedValue(new TypeError("Load failed"));
    await continueWithApple();
    expect(await screen.findByText(/couldn't reach MyKhaya/)).toBeInTheDocument();
    expect(nativeExternalAssertion).not.toHaveBeenCalled();
  });

  it("shows the account choice for an unlinked Apple identity instead of signing in", async () => {
    nativeExternalExchange.mockResolvedValue({
      authentication_state: "account_choice",
      transaction_id: "tx-123",
      provider: "apple",
      provider_email: "relay@privaterelay.appleid.com",
      display_name: "Apple user",
      can_register: false,
    });
    await continueWithApple();
    expect(await screen.findByRole("heading", { name: "Continue with Apple" })).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
    expect(setAuthenticatedUser).not.toHaveBeenCalled();
  });
});

describe("Login — native Google keeps its platform flows", () => {
  it("uses the system browser for Google on iOS", async () => {
    nativeExternalBrowserStart.mockResolvedValue({ authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?x=1", transaction_id: "g-1" });
    const person = userEvent.setup();
    render(<Login />);
    await person.click(await screen.findByRole("button", { name: "Continue with Google" }));

    await waitFor(() => expect(browserOpen).toHaveBeenCalledWith({ url: "https://accounts.google.com/o/oauth2/v2/auth?x=1" }));
    expect(nativeExternalBrowserStart).toHaveBeenCalledWith("google", "login", undefined);
    expect(nativeExternalAssertion).not.toHaveBeenCalled();
  });
});

describe("Login — native Founding Beta sign-up", () => {
  const INVITATION = "beta-invitation-token-abcdefghijklmnopqrstuvwxyz";

  it("carries Beta intent and the invitation on the native Apple start", async () => {
    searchParams = new URLSearchParams(`social=apple&beta=1&beta_invitation=${INVITATION}`);
    render(<Login />);
    await waitFor(() => expect(nativeExternalStart).toHaveBeenCalledTimes(1));
    expect(nativeExternalStart).toHaveBeenCalledWith(
      "apple",
      "login",
      expect.stringMatching(/^nauth-[0-9a-f]{16}$/),
      { beta: true, invitationToken: INVITATION },
    );
  });

  it("carries Beta intent on the system-browser start (Google on iOS)", async () => {
    nativeExternalBrowserStart.mockResolvedValue({ authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?x=1", transaction_id: "g-1" });
    searchParams = new URLSearchParams("social=google&beta=1");
    render(<Login />);
    await waitFor(() => expect(nativeExternalBrowserStart).toHaveBeenCalledTimes(1));
    expect(nativeExternalBrowserStart).toHaveBeenCalledWith("google", "login", { beta: true, invitationToken: null });
  });

  it("shows the Beta choice and resumes Beta onboarding after a native Beta account is created", async () => {
    searchParams = new URLSearchParams(`social=apple&beta=1&beta_invitation=${INVITATION}`);
    nativeExternalExchange.mockResolvedValue({
      authentication_state: "account_choice",
      transaction_id: "tx-123",
      provider: "apple",
      provider_email: "relay@privaterelay.appleid.com",
      display_name: "Apple Beta Person",
      can_register: true,
    });
    nativeExternalRecoveryRegister.mockResolvedValue(user);
    (api.betaContinuation as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ pending: true, enrolled: false });
    const person = userEvent.setup();
    render(<Login />);

    expect(
      await screen.findByRole("radio", { name: /I’m new to MyKhaya\s*Founding Beta/ }),
    ).toBeChecked();
    await person.click(await screen.findByRole("button", { name: "Create account" }));

    await waitFor(() => expect(nativeExternalRecoveryRegister).toHaveBeenCalledTimes(1));
    // Beta intent is held server-side from the start request: the
    // registration call itself never carries the invitation.
    expect(nativeExternalRecoveryRegister).toHaveBeenCalledWith({
      transaction_id: "tx-123",
      display_name: "Apple Beta Person",
      legal_acceptances: [],
      platform: "ios",
    });
    expect(JSON.stringify(nativeExternalRecoveryRegister.mock.calls)).not.toContain(INVITATION);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/onboarding?beta=1"));
  });
});
