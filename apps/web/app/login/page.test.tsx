import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
    },
  };
});

vi.mock("@/components/passkey-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/passkey-client")>();
  return {
    ...actual,
    biometricSignInAvailable: vi.fn(async () => true),
    biometricLabel: () => "Face ID",
    authenticateWithPasskey: vi.fn(async () => ({ id: "assertion" })),
  };
});

const { api } = await import("@mykhaya/api-client");
const passkeyClient = await import("@/components/passkey-client");

const user = { id: "user-1", display_name: "Anthony", avatar_version: null } as const;

beforeEach(() => {
  vi.clearAllMocks();
  searchParams = new URLSearchParams();
  window.localStorage.clear();
  (api.homes as ReturnType<typeof vi.fn>).mockResolvedValue([{ id: "home-1" }]);
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
