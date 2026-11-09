import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Native-shell sign-in that reaches the consumer MFA policy. The challenge
// must replace the sign-in form, never render above a still-usable
// email/password form or provider buttons.

const push = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@capacitor/app", () => ({
  App: { addListener: vi.fn(() => Promise.resolve({ remove: vi.fn() })) },
}));
vi.mock("@capacitor/browser", () => ({ Browser: { open: vi.fn() } }));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      post: vi.fn(),
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
    },
  };
});

vi.mock("@/components/native-runtime", () => ({
  isNativeShell: () => true,
  nativePlatform: () => "ios",
}));

type AsyncMock = (...args: unknown[]) => Promise<unknown>;
const nativeLogin = vi.fn<AsyncMock>();
const nativeExternalStart = vi.fn<AsyncMock>();
const nativeExternalAssertion = vi.fn<AsyncMock>();
const nativeExternalExchange = vi.fn<AsyncMock>();
const nativeMfaOptions = vi.fn<AsyncMock>();
const nativeMfaStart = vi.fn<AsyncMock>();
const nativeMfaVerify = vi.fn<AsyncMock>();
const cancelNativeMfa = vi.fn<(...args: unknown[]) => void>();
vi.mock("@/components/native-auth", () => ({
  nativeLogin: (...args: unknown[]) => nativeLogin(...args),
  nativeExternalStart: (...args: unknown[]) => nativeExternalStart(...args),
  nativeExternalAssertion: (...args: unknown[]) => nativeExternalAssertion(...args),
  nativeExternalExchange: (...args: unknown[]) => nativeExternalExchange(...args),
  nativeExternalBrowserStart: vi.fn(),
  nativeExternalRedeem: vi.fn(),
  nativeExternalRecoveryLink: vi.fn(),
  nativeExternalRecoveryRegister: vi.fn(),
  nativeMfaOptions: (...args: unknown[]) => nativeMfaOptions(...args),
  nativeMfaStart: (...args: unknown[]) => nativeMfaStart(...args),
  nativeMfaVerify: (...args: unknown[]) => nativeMfaVerify(...args),
  cancelNativeMfa: (...args: unknown[]) => cancelNativeMfa(...args),
  getLastNativeLoginDiagnostic: () => null,
  runNativeNetworkDiagnostics: vi.fn(async () => []),
}));

const setAuthenticatedUser = vi.fn();
vi.mock("@/components/auth-provider", () => ({
  useAuth: () => ({ user: null, status: "signed_out", setAuthenticatedUser, refresh: vi.fn(), signOut: vi.fn() }),
}));

const { api, ApiError } = await import("@mykhaya/api-client");
const { default: Login } = await import("./page");

const user = { id: "user-1", display_name: "Native Person", avatar_version: null };

function continuation(provider: "password" | "apple" | "google") {
  return { authentication_state: "additional_auth_required", transaction_id: `mfa-${provider}`, provider };
}

function expectSignInFormHidden() {
  expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Sign in" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Continue with Apple" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Continue with Google" })).not.toBeInTheDocument();
}

async function signInWithPassword(person: ReturnType<typeof userEvent.setup>) {
  await person.type(await screen.findByLabelText("Email"), "native@example.com");
  await person.type(screen.getByLabelText("Password"), "Correct horse battery staple!");
  await person.click(screen.getByRole("button", { name: "Sign in" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  nativeMfaOptions.mockResolvedValue({ methods: ["email", "totp"], preferred_method: "email" });
  nativeMfaStart.mockResolvedValue({ method: "email", enrolling: false });
  nativeMfaVerify.mockResolvedValue(user);
});

describe("Login — native MFA challenge", () => {
  it("replaces the email/password form after a native password sign-in", async () => {
    nativeLogin.mockResolvedValue(continuation("password"));
    const person = userEvent.setup();
    render(<Login />);

    await signInWithPassword(person);

    expect(await screen.findByRole("heading", { name: "Additional verification required" })).toBeInTheDocument();
    expectSignInFormHidden();
    expect(nativeMfaOptions).toHaveBeenCalledWith("mfa-password");
    // Native MFA stays on the bearer transport; the cookie-based /mfa page is never used.
    expect(push).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("replaces the form after native Apple sign-in reaches MFA", async () => {
    nativeExternalStart.mockResolvedValue({ transaction_id: "tx-1", nonce: "nonce-abcdefghijklmnop", provider: "apple", client_id: "app.mykhaya.mobile" });
    nativeExternalAssertion.mockResolvedValue({ identity_token: "eyJ.synthetic.sig" });
    nativeExternalExchange.mockResolvedValue(continuation("apple"));
    const person = userEvent.setup();
    render(<Login />);

    await person.click(await screen.findByRole("button", { name: "Continue with Apple" }));

    expect(await screen.findByRole("heading", { name: "Additional verification required" })).toBeInTheDocument();
    expectSignInFormHidden();
  });

  it("completes the challenge and signs in", async () => {
    nativeLogin.mockResolvedValue(continuation("password"));
    const person = userEvent.setup();
    render(<Login />);
    await signInWithPassword(person);

    await person.click(await screen.findByRole("button", { name: "Start verification" }));
    await person.type(await screen.findByLabelText("MFA code"), "123456");
    await person.click(screen.getByRole("button", { name: "Verify and continue" }));

    await waitFor(() => expect(setAuthenticatedUser).toHaveBeenCalledWith(user));
    expect(nativeMfaStart).toHaveBeenCalledWith("mfa-password", "email");
    expect(nativeMfaVerify).toHaveBeenCalledWith("mfa-password", "email", "123456");
    await waitFor(() => expect(push).toHaveBeenCalledWith("/home"));
  });

  it("shows a rejected code inside the challenge, with the form still hidden", async () => {
    nativeLogin.mockResolvedValue(continuation("password"));
    nativeMfaVerify.mockRejectedValue(new ApiError(401, "That verification code is invalid."));
    const person = userEvent.setup();
    render(<Login />);
    await signInWithPassword(person);

    await person.click(await screen.findByRole("button", { name: "Start verification" }));
    await person.type(await screen.findByLabelText("MFA code"), "000000");
    await person.click(screen.getByRole("button", { name: "Verify and continue" }));

    const challenge = await screen.findByTestId("native-mfa-challenge");
    expect(await screen.findByText("That verification code is invalid.")).toBeInTheDocument();
    expect(challenge).toContainElement(screen.getByText("That verification code is invalid."));
    expectSignInFormHidden();
    expect(setAuthenticatedUser).not.toHaveBeenCalled();
  });

  it("shows the setup key when the authenticator app must be enrolled", async () => {
    nativeLogin.mockResolvedValue(continuation("password"));
    nativeMfaOptions.mockResolvedValue({ methods: ["totp"], preferred_method: "totp" });
    nativeMfaStart.mockResolvedValue({ method: "totp", enrolling: true, manual_key: "JBSWY3DPEHPK3PXP" });
    const person = userEvent.setup();
    render(<Login />);
    await signInWithPassword(person);

    await person.click(await screen.findByRole("button", { name: "Start verification" }));

    expect(await screen.findByText("JBSWY3DPEHPK3PXP")).toBeInTheDocument();
  });

  it("switches method before starting and locks the choice once started", async () => {
    nativeLogin.mockResolvedValue(continuation("password"));
    nativeMfaStart.mockResolvedValue({ method: "totp", enrolling: false });
    const person = userEvent.setup();
    render(<Login />);
    await signInWithPassword(person);

    const method = await screen.findByLabelText("Verification method");
    expect(method).toHaveValue("email");
    await person.selectOptions(method, "totp");
    await person.click(screen.getByRole("button", { name: "Start verification" }));

    expect(nativeMfaStart).toHaveBeenCalledWith("mfa-password", "totp");
    expect(await screen.findByLabelText("MFA code")).toHaveFocus();
    expect(method).toBeDisabled();
  });

  it("submits the code from the keyboard and only once", async () => {
    nativeLogin.mockResolvedValue(continuation("password"));
    let finish: (value: unknown) => void = () => undefined;
    nativeMfaVerify.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const person = userEvent.setup();
    render(<Login />);
    await signInWithPassword(person);
    await person.click(await screen.findByRole("button", { name: "Start verification" }));

    await person.type(await screen.findByLabelText("MFA code"), "12a3456{Enter}");
    await person.keyboard("{Enter}");

    expect(screen.getByLabelText("MFA code")).toHaveValue("123456");
    await waitFor(() => expect(nativeMfaVerify).toHaveBeenCalledTimes(1));
    expect(nativeMfaVerify).toHaveBeenCalledWith("mfa-password", "email", "123456");
    finish(user);
    await waitFor(() => expect(setAuthenticatedUser).toHaveBeenCalledWith(user));
  });

  it("returns to the sign-in form when the person leaves the challenge", async () => {
    nativeLogin.mockResolvedValue(continuation("password"));
    const person = userEvent.setup();
    render(<Login />);
    await signInWithPassword(person);

    await person.click(await screen.findByRole("button", { name: "Use a different sign-in method" }));

    expect(cancelNativeMfa).toHaveBeenCalledWith("mfa-password");
    expect(await screen.findByLabelText("Email")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Additional verification required" })).not.toBeInTheDocument();
  });
});
