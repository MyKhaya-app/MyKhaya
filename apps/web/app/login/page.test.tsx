import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Login from "./page";

// Biometric sign-in login-screen coverage — the regression this guards
// against is the old "bolted on" passkey button living permanently below
// the password form. Now: no hint on this device -> plain form only; a
// hint from a prior enrolment -> biometric-first screen, with "Sign in
// another way" as the only route back to the plain form.

const push = vi.fn();
let searchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => searchParams,
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      previewInvitation: vi.fn(),
      previewCalendarShare: vi.fn(),
      post: vi.fn(),
      homes: vi.fn(),
      passkeyLoginOptions: vi.fn(),
      passkeyLoginVerify: vi.fn(),
      betaContinuation: vi.fn(),
      joinBeta: vi.fn(),
      publicSignupState: vi.fn(),
    },
  };
});

let nativeShell = false;
vi.mock("@/components/native-runtime", () => ({
  isNativeShell: () => nativeShell,
}));

const nativeLogin = vi.fn<(email: string, password: string) => Promise<unknown>>();
vi.mock("@/components/native-auth", () => ({
  nativeLogin: (email: string, password: string) => nativeLogin(email, password),
}));

vi.mock("@/components/passkey-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/passkey-client")>();
  return {
    ...actual,
    biometricSignInAvailable: vi.fn(async () => true),
    biometricLabel: () => "Face ID",
    authenticateWithPasskey: vi.fn(async () => ({ id: "assertion" })),
  };
});

const { api, ApiError } = await import("@mykhaya/api-client");
const passkeyClient = await import("@/components/passkey-client");

const user = { id: "user-1", display_name: "Anthony", avatar_version: null } as const;

function signupState(betaJoining: boolean) {
  return {
    signup_mode: betaJoining ? "mixed" : "normal",
    registration_open: true,
    invitation_required: false,
    normal_signup_available: true,
    beta_joining_available: betaJoining,
    waitlist_available: false,
    joinable_count: betaJoining ? 12 : null,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  searchParams = new URLSearchParams();
  window.localStorage.clear();
  nativeShell = false;
  (api.homes as ReturnType<typeof vi.fn>).mockResolvedValue([{ id: "home-1" }]);
  (api.betaContinuation as ReturnType<typeof vi.fn>).mockResolvedValue({
    pending: false,
    enrolled: false,
    enrolled_home_id: null,
    terms: null,
    eligible: true,
    home_id: null,
    home_name: null,
    reason: null,
  });
  (api.publicSignupState as ReturnType<typeof vi.fn>).mockResolvedValue(signupState(false));
  // Re-asserted every test (clearAllMocks clears call history but not a
  // previous test's mockResolvedValue/mockRejectedValue implementation) —
  // these are the "everything is fine" defaults each test starts from.
  (passkeyClient.biometricSignInAvailable as ReturnType<typeof vi.fn>).mockResolvedValue(true);
  (passkeyClient.authenticateWithPasskey as ReturnType<typeof vi.fn>).mockResolvedValue({
    id: "assertion",
  });
});

describe("Login — no prior biometric enrolment on this device", () => {
  it("shows the plain email/password form, with no biometric button anywhere", async () => {
    render(<Login />);

    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^sign in$/i })).toBeInTheDocument();
    expect(screen.queryByText(/use face id/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/sign in with passkey/i)).not.toBeInTheDocument();
    expect(screen.getByText(/forgot password/i)).toBeInTheDocument();
    expect(screen.getByText(/create an account/i)).toBeInTheDocument();
    expect(screen.getByText(/child sign in/i)).toBeInTheDocument();
  });

  it("password sign-in succeeds and remembers this device for next time", async () => {
    (api.post as ReturnType<typeof vi.fn>).mockResolvedValue(user);
    const typist = userEvent.setup();
    render(<Login />);

    await typist.type(screen.getByLabelText("Email"), "anthony@example.com");
    await typist.type(screen.getByLabelText("Password"), "correct horse");
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/home"));
    expect(passkeyClient.getBiometricHint()).toEqual({
      userId: "user-1",
      displayName: "Anthony",
      avatarVersion: null,
    });
  });

  it("routes an MFA-required browser login to the transaction URL", async () => {
    (api.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      authentication_state: "additional_auth_required",
      transaction_id: "opaque-transaction",
    });
    const typist = userEvent.setup();
    render(<Login />);

    await typist.type(screen.getByLabelText("Email"), "anthony@example.com");
    await typist.type(screen.getByLabelText("Password"), "correct horse");
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/mfa?transaction=opaque-transaction"));
  });

  it("shows a safe message when returning from an expired MFA handoff", async () => {
    searchParams = new URLSearchParams("mfa_error=expired");
    render(<Login />);

    expect(await screen.findByText("Your verification session has expired. Please sign in again.")).toBeInTheDocument();
  });
});

describe("Login — biometric sign-in previously enrolled on this device", () => {
  beforeEach(() => {
    passkeyClient.setBiometricHint({
      userId: "user-1",
      displayName: "Anthony",
      avatarVersion: null,
    });
  });

  it("shows the biometric-first screen instead of the password form", async () => {
    render(<Login />);

    await screen.findByText("Anthony");
    expect(screen.getByRole("button", { name: /use face id/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in another way/i })).toBeInTheDocument();
    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });

  it('"Sign in another way" reveals the normal email/password form', async () => {
    const typist = userEvent.setup();
    render(<Login />);

    await typist.click(await screen.findByRole("button", { name: /sign in another way/i }));

    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });

  it("successful biometric sign-in creates a normal session and redirects Home", async () => {
    (api.passkeyLoginOptions as ReturnType<typeof vi.fn>).mockResolvedValue({
      options_json: "{}",
    });
    (api.passkeyLoginVerify as ReturnType<typeof vi.fn>).mockResolvedValue(user);
    const typist = userEvent.setup();
    render(<Login />);

    await typist.click(await screen.findByRole("button", { name: /use face id/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/home"));
    expect(api.passkeyLoginVerify).toHaveBeenCalledWith(JSON.stringify({ id: "assertion" }));
  });

  it("a cancelled biometric prompt falls back to the password form, not an error banner", async () => {
    (api.passkeyLoginOptions as ReturnType<typeof vi.fn>).mockResolvedValue({
      options_json: "{}",
    });
    (passkeyClient.authenticateWithPasskey as ReturnType<typeof vi.fn>).mockRejectedValue(
      new DOMException("cancelled", "NotAllowedError"),
    );
    const typist = userEvent.setup();
    render(<Login />);

    await typist.click(await screen.findByRole("button", { name: /use face id/i }));

    await waitFor(() => expect(screen.getByLabelText("Email")).toBeInTheDocument());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("a failed biometric assertion shows an error and keeps the biometric screen, not a silent redirect", async () => {
    const { ApiError } = await import("@mykhaya/api-client");
    (api.passkeyLoginOptions as ReturnType<typeof vi.fn>).mockResolvedValue({
      options_json: "{}",
    });
    (api.passkeyLoginVerify as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(401, "We couldn't verify this passkey."),
    );
    const typist = userEvent.setup();
    render(<Login />);

    await typist.click(await screen.findByRole("button", { name: /use face id/i }));

    await screen.findByText(/we couldn't verify this passkey/i);
    expect(push).not.toHaveBeenCalled();
  });

  it("falls back to the plain form when this browser no longer supports a platform authenticator", async () => {
    (passkeyClient.biometricSignInAvailable as ReturnType<typeof vi.fn>).mockResolvedValue(false);
    render(<Login />);

    await waitFor(() => expect(screen.getByLabelText("Email")).toBeInTheDocument());
    expect(passkeyClient.getBiometricHint()).toBeNull();
  });
});

// Regression coverage for the audit's calendar-share-token-loss bug: an
// expired session bounced a user mid-invitation to a bare /login with no
// way back to their intended destination. AppShell now attaches ?next=
// when it does that; the login page must restore it after a successful
// sign-in, but only when it is a genuine internal path — never an
// externally supplied redirect target.
describe("Login — post-login destination preservation (?next=)", () => {
  it("returns to the preserved internal destination after signing in", async () => {
    searchParams = new URLSearchParams({
      next: "/calendar-shares/accept?token=abc123",
    });
    (api.post as ReturnType<typeof vi.fn>).mockResolvedValue(user);
    const typist = userEvent.setup();
    render(<Login />);

    await typist.type(screen.getByLabelText("Email"), "anthony@example.com");
    await typist.type(screen.getByLabelText("Password"), "correct horse");
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/calendar-shares/accept?token=abc123"),
    );
    // Must not also have taken the default /home destination.
    expect(push).not.toHaveBeenCalledWith("/home");
  });

  it("falls back to the normal /home destination when next is a protocol-relative URL", async () => {
    searchParams = new URLSearchParams({ next: "//evil.example/phish" });
    (api.post as ReturnType<typeof vi.fn>).mockResolvedValue(user);
    const typist = userEvent.setup();
    render(<Login />);

    await typist.type(screen.getByLabelText("Email"), "anthony@example.com");
    await typist.type(screen.getByLabelText("Password"), "correct horse");
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/home"));
    expect(push).not.toHaveBeenCalledWith("//evil.example/phish");
  });

  it("falls back to the normal /home destination when next is a fully external URL", async () => {
    searchParams = new URLSearchParams({ next: "https://evil.example/phish" });
    (api.post as ReturnType<typeof vi.fn>).mockResolvedValue(user);
    const typist = userEvent.setup();
    render(<Login />);

    await typist.type(screen.getByLabelText("Email"), "anthony@example.com");
    await typist.type(screen.getByLabelText("Password"), "correct horse");
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/home"));
    expect(push).not.toHaveBeenCalledWith("https://evil.example/phish");
  });

  it("prefers an explicit calendar_share destination over next when both are somehow present", async () => {
    searchParams = new URLSearchParams({
      next: "/home",
      calendar_share: "share-token",
    });
    (api.previewCalendarShare as ReturnType<typeof vi.fn>).mockResolvedValue({
      calendar_name: "School",
      source_group_name: "The Smiths",
    });
    (api.post as ReturnType<typeof vi.fn>).mockResolvedValue(user);
    const typist = userEvent.setup();
    render(<Login />);

    await typist.type(screen.getByLabelText("Email"), "anthony@example.com");
    await typist.type(screen.getByLabelText("Password"), "correct horse");
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/calendar-shares/accept?token=share-token"),
    );
  });
});

// Persistent-login fix: inside the native shell, sign-in must go through
// the Keychain-backed bearer transport (components/native-auth.ts), never
// the browser cookie /auth/login — see components/app-shell.tsx's matching
// native bootstrap path for the other half of this lifecycle.
describe("Login — native shell uses the native bearer transport, never the browser cookie flow", () => {
  it("submits via nativeLogin, not api.post('/auth/login'), and never shows the WebAuthn biometric screen even with a prior enrolment hint", async () => {
    nativeShell = true;
    nativeLogin.mockResolvedValue(user);
    passkeyClient.setBiometricHint({
      userId: "user-1",
      displayName: "Anthony",
      avatarVersion: null,
    });
    const typist = userEvent.setup();
    render(<Login />);

    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /use face id/i })).not.toBeInTheDocument();
    await typist.type(screen.getByLabelText("Email"), "anthony@example.com");
    await typist.type(screen.getByLabelText("Password"), "correct horse");
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/home"));
    expect(nativeLogin).toHaveBeenCalledWith("anthony@example.com", "correct horse");
    expect(api.post).not.toHaveBeenCalledWith("/auth/login", expect.anything());
  });

  it("resumes a pending Beta account into Beta onboarding before Home", async () => {
    nativeShell = true;
    nativeLogin.mockResolvedValue(user);
    (api.betaContinuation as ReturnType<typeof vi.fn>).mockResolvedValue({
      pending: true,
      enrolled: false,
      enrolled_home_id: null,
      terms: null,
      eligible: true,
      home_id: null,
      home_name: null,
      reason: null,
    });
    const typist = userEvent.setup();
    render(<Login />);

    await typist.type(screen.getByLabelText("Email"), "anthony@example.com");
    await typist.type(screen.getByLabelText("Password"), "correct horse");
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/onboarding?beta=1"));
    expect(push).not.toHaveBeenCalledWith("/home");
  });

  it("never fetches api.homes() (cookie-only) to decide the post-login destination — always /home", async () => {
    nativeShell = true;
    nativeLogin.mockResolvedValue(user);
    const typist = userEvent.setup();
    render(<Login />);

    await typist.type(screen.getByLabelText("Email"), "anthony@example.com");
    await typist.type(screen.getByLabelText("Password"), "correct horse");
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/home"));
    expect(api.homes).not.toHaveBeenCalled();
  });

  it("a native login storage/network failure shows an error banner and never redirects", async () => {
    nativeShell = true;
    nativeLogin.mockRejectedValue(new Error("Could not persist the session."));
    const typist = userEvent.setup();
    render(<Login />);

    await typist.type(screen.getByLabelText("Email"), "anthony@example.com");
    await typist.type(screen.getByLabelText("Password"), "correct horse");
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));

    await screen.findByText(/we couldn.t sign you in/i);
    expect(push).not.toHaveBeenCalled();
  });
});

describe("Login — browser/PWA still uses the cookie transport when not native", () => {
  it("submits via api.post('/auth/login'), never nativeLogin", async () => {
    nativeShell = false;
    (api.post as ReturnType<typeof vi.fn>).mockResolvedValue(user);
    const typist = userEvent.setup();
    render(<Login />);

    await typist.type(screen.getByLabelText("Email"), "anthony@example.com");
    await typist.type(screen.getByLabelText("Password"), "correct horse");
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/home"));
    expect(api.post).toHaveBeenCalledWith("/auth/login", {
      email: "anthony@example.com",
      password: "correct horse",
    });
    expect(nativeLogin).not.toHaveBeenCalled();
  });
});

describe("Login — one sign-in action is exactly one login request", () => {
  async function fill(typist: ReturnType<typeof userEvent.setup>) {
    await typist.type(screen.getByLabelText("Email"), "anthony@example.com");
    await typist.type(screen.getByLabelText("Password"), "correct horse");
  }

  it("one click on Sign in sends one native login and navigates once", async () => {
    nativeShell = true;
    nativeLogin.mockResolvedValue(user);
    const typist = userEvent.setup();
    render(<Login />);
    await fill(typist);
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(nativeLogin).toHaveBeenCalledTimes(1);
  });

  it("pressing Enter in the password field sends one login", async () => {
    nativeShell = true;
    nativeLogin.mockResolvedValue(user);
    const typist = userEvent.setup();
    render(<Login />);
    await fill(typist);
    await typist.type(screen.getByLabelText("Password"), "{Enter}");

    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(nativeLogin).toHaveBeenCalledTimes(1);
  });

  it("repeated submits while a login is pending are ignored (guard is not just the disabled button)", async () => {
    nativeShell = true;
    let finish!: (value: unknown) => void;
    nativeLogin.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const typist = userEvent.setup();
    render(<Login />);
    await fill(typist);

    const form = screen.getByRole("button", { name: /^sign in$/i }).closest("form") as HTMLFormElement;
    // Two submit events in the same tick: React state (`busy`) has not rendered yet.
    fireEvent.submit(form);
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(nativeLogin).toHaveBeenCalledTimes(1);

    finish(user);
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(nativeLogin).toHaveBeenCalledTimes(1);
  });

  it("a 401 is shown once, is not retried automatically, and leaves the form usable", async () => {
    nativeShell = true;
    nativeLogin.mockRejectedValueOnce(new ApiError(401, "The email or password is not correct."));
    const typist = userEvent.setup();
    render(<Login />);
    await fill(typist);
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));

    await screen.findByText("The email or password is not correct.");
    expect(nativeLogin).toHaveBeenCalledTimes(1);
    expect(push).not.toHaveBeenCalled();
    const button = screen.getByRole("button", { name: /^sign in$/i });
    expect(button).toBeEnabled();

    // The user can try again; that is a second, deliberate attempt.
    nativeLogin.mockResolvedValueOnce(user);
    await typist.click(button);
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(nativeLogin).toHaveBeenCalledTimes(2);
  });
});

describe("Login — Founding Beta continuation", () => {
  async function signIn() {
    (api.post as ReturnType<typeof vi.fn>).mockResolvedValue(user);
    (api.homes as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    const typist = userEvent.setup();
    render(<Login />);
    await typist.type(screen.getByLabelText("Email"), "new-beta@example.com");
    await typist.type(screen.getByLabelText("Password"), "correct horse");
    await typist.click(screen.getByRole("button", { name: /^sign in$/i }));
  }

  it("resumes the Beta continuation on first sign-in from the server-side Beta intent, without ?beta=1", async () => {
    // The emailed verification link carries no Beta marker: the server's
    // record of the Beta registration is what routes the user.
    (api.betaContinuation as ReturnType<typeof vi.fn>).mockResolvedValue({
      pending: true,
      enrolled: false,
      enrolled_home_id: null,
      terms: null,
      eligible: true,
      home_id: null,
      home_name: null,
      reason: null,
    });
    await signIn();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/onboarding?beta=1"));
    expect(push).not.toHaveBeenCalledWith("/onboarding");
    // Enrolment is never done silently at login.
    expect(api.joinBeta).not.toHaveBeenCalled();
  });

  it("keeps a Beta invitation through to the continuation", async () => {
    searchParams = new URLSearchParams({ beta: "1", beta_invitation: "i".repeat(40) });
    await signIn();
    await waitFor(() => expect(push).toHaveBeenCalledWith(`/onboarding?beta=1&invitation=${"i".repeat(40)}`));
  });

  it("a normal (non-Beta) account keeps the normal onboarding destination", async () => {
    await signIn();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/onboarding"));
    expect(push).not.toHaveBeenCalledWith(expect.stringContaining("beta=1"));
  });
});

// The card under the form follows the existing Founding Beta flag
// (publicSignupState().beta_joining_available). Exactly one card renders;
// anything other than a resolved "on" shows the normal card.
describe("Login — Founding Beta / New to MyKhaya card", () => {
  function expectNormalCard() {
    expect(screen.getByRole("region", { name: "Create your Home and get started." })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /create an account/i })).toHaveAttribute("href", "/register");
    expect(screen.queryByText(/founding beta/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("signin-card-beta")).not.toBeInTheDocument();
  }

  it("flag ON: shows only the Founding Beta card, linking to the existing Beta sign-up", async () => {
    (api.publicSignupState as ReturnType<typeof vi.fn>).mockResolvedValue(signupState(true));
    render(<Login />);

    const card = await screen.findByRole("region", { name: "Help shape a calmer home." });
    expect(card).toHaveTextContent("Founding Beta");
    expect(screen.getByRole("link", { name: /join the founding beta/i })).toHaveAttribute("href", "/founding-beta");
    expect(screen.queryByTestId("signin-card-new")).not.toBeInTheDocument();
    expect(screen.queryByText(/new to mykhaya/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /create an account/i })).not.toBeInTheDocument();
  });

  it("native shell, signed out, flag ON: the sign-in screen shows the Founding Beta card", async () => {
    nativeShell = true;
    (api.publicSignupState as ReturnType<typeof vi.fn>).mockResolvedValue(signupState(true));
    render(<Login />);

    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    await screen.findByRole("region", { name: "Help shape a calmer home." });
    expect(screen.getByRole("link", { name: /join the founding beta/i })).toHaveAttribute("href", "/founding-beta");
    expect(screen.queryByTestId("signin-card-new")).not.toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it("flag OFF: shows only the New to MyKhaya card", async () => {
    render(<Login />);

    await waitFor(() => expect(api.publicSignupState).toHaveBeenCalled());
    expectNormalCard();
  });

  it("flag missing from the response: shows only the New to MyKhaya card", async () => {
    const withoutFlag: Partial<ReturnType<typeof signupState>> = signupState(true);
    delete withoutFlag.beta_joining_available;
    (api.publicSignupState as ReturnType<typeof vi.fn>).mockResolvedValue(withoutFlag);
    render(<Login />);

    await waitFor(() => expect(api.publicSignupState).toHaveBeenCalled());
    expectNormalCard();
  });

  it("flag failed to load: shows only the New to MyKhaya card", async () => {
    (api.publicSignupState as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("offline"));
    render(<Login />);

    await waitFor(() => expect(api.publicSignupState).toHaveBeenCalled());
    expectNormalCard();
  });

  it("flag not resolved yet: renders the normal card straight away, not a placeholder", () => {
    (api.publicSignupState as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));
    render(<Login />);

    expectNormalCard();
  });

  it("flag ON with a household invitation: keeps the invitation-carrying Create an account link", async () => {
    searchParams = new URLSearchParams({ invitation: "invite-token" });
    (api.previewInvitation as ReturnType<typeof vi.fn>).mockResolvedValue({
      group_name: "The Smiths",
      invited_by_display_name: "Sam",
      email: "anthony@example.com",
    });
    (api.publicSignupState as ReturnType<typeof vi.fn>).mockResolvedValue(signupState(true));
    render(<Login />);

    await screen.findByText(/continue signing in to join the smiths/i);
    await waitFor(() => expect(api.publicSignupState).toHaveBeenCalled());
    expect(screen.getByRole("link", { name: /create an account/i })).toHaveAttribute(
      "href",
      "/register?invitation=invite-token",
    );
    expect(screen.queryByTestId("signin-card-beta")).not.toBeInTheDocument();
  });

  it("the password toggle shows and hides the password without submitting", async () => {
    const typist = userEvent.setup();
    render(<Login />);
    const password = screen.getByLabelText("Password");

    expect(password).toHaveAttribute("type", "password");
    await typist.click(screen.getByRole("button", { name: "Show password" }));
    expect(password).toHaveAttribute("type", "text");
    await typist.click(screen.getByRole("button", { name: "Hide password" }));
    expect(password).toHaveAttribute("type", "password");
    expect(api.post).not.toHaveBeenCalled();
  });
});

// One case per signup mode, using the field combinations the API actually
// produces (resolve_signup_state in apps/api/mykhaya/routers/founding_beta.py).
describe("Login — card by signup mode", () => {
  const base = {
    registration_open: true,
    invitation_required: false,
    normal_signup_available: false,
    beta_joining_available: false,
    waitlist_available: false,
    joinable_count: null,
  };
  const modes = {
    betaOpen: { ...base, signup_mode: "beta_only", beta_joining_available: true },
    waitlist: { ...base, signup_mode: "beta_only", waitlist_available: true },
    betaFullNoWaitlist: { ...base, signup_mode: "beta_only" },
    normal: { ...base, signup_mode: "normal", normal_signup_available: true },
    mixedBetaOpen: { ...base, signup_mode: "mixed", normal_signup_available: true, beta_joining_available: true },
    mixedBetaFull: { ...base, signup_mode: "mixed", normal_signup_available: true, waitlist_available: true },
    closed: { ...base, signup_mode: "closed", registration_open: false },
    closedWithWaitlist: { ...base, signup_mode: "closed", registration_open: false, waitlist_available: true },
    paused: { ...base, signup_mode: "normal", registration_open: false },
    production: { ...base, signup_mode: "beta_only", invitation_required: true, beta_joining_available: true },
  };

  async function renderIn(mode: keyof typeof modes) {
    (api.publicSignupState as ReturnType<typeof vi.fn>).mockResolvedValue(modes[mode]);
    render(<Login />);
    await waitFor(() => expect(api.publicSignupState).toHaveBeenCalled());
  }

  it.each([
    ["betaOpen", "Beta open"],
    ["waitlist", "waitlist (Beta only, places full)"],
    ["mixedBetaOpen", "mixed with Beta places open"],
    ["production", "production: invitation required with Beta places open"],
  ] as const)("%s (%s): Founding Beta card linking to /founding-beta", async (mode) => {
    await renderIn(mode);
    const link = await screen.findByRole("link", { name: /join the founding beta/i });
    expect(link).toHaveAttribute("href", "/founding-beta");
    expect(screen.queryByTestId("signin-card-new")).not.toBeInTheDocument();
  });

  it.each([
    ["normal", "normal"],
    ["mixedBetaFull", "mixed with Beta full (normal signup still open)"],
    ["betaFullNoWaitlist", "Beta only, full, waitlist off"],
  ] as const)("%s (%s): New to MyKhaya card linking to /register", async (mode) => {
    await renderIn(mode);
    await waitFor(() =>
      expect(screen.getByRole("link", { name: /create an account/i })).toHaveAttribute("href", "/register"),
    );
    expect(screen.queryByTestId("signin-card-beta")).not.toBeInTheDocument();
  });

  it.each([
    ["closed", "closed"],
    ["closedWithWaitlist", "closed with a waitlist"],
    ["paused", "registration paused"],
  ] as const)("%s (%s): no card, only sign in and child sign-in", async (mode) => {
    await renderIn(mode);
    await waitFor(() => expect(screen.queryByTestId("signin-card-new")).not.toBeInTheDocument());
    expect(screen.queryByTestId("signin-card-beta")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /create an account|join the founding beta/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^sign in$/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Child sign in" })).toHaveAttribute("href", "/login/child");
    expect(screen.getByRole("link", { name: "Forgot password?" })).toBeInTheDocument();
  });
});
