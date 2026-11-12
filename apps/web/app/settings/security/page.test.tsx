import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Home, Passkey } from "@mykhaya/shared-types";
import Security from "./page";

// Biometric sign-in coverage for the Security settings screen — this is
// the "Enable biometric sign-in" / "Face ID is enabled on this device /
// [Disable]" toggle from the biometric sign-in report, not a list-of-
// credentials-first UX (that lives behind the secondary <details> disclosure
// only when more than one device has enrolled).

const searchParamsState = vi.hoisted(() => ({ value: new URLSearchParams() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/settings/security",
  useSearchParams: () => searchParamsState.value,
}));

function freeHome(): Home {
  return {
    id: "home-1",
    name: "Hales Home",
    role: "owner",
    relationship: "home_admin",
    permission_profile: "home_admin",
    capabilities: [],
    member_count: 1,
    child_login_code: "1234",
  };
}

vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({
    activeHome: freeHome(),
    activeHomeId: "home-1",
    homes: [freeHome()],
    setActiveHomeId: vi.fn(),
    loading: false,
  }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      externalIdentities: vi.fn(),
      authProviders: vi.fn(),
      appleLinkStart: vi.fn(),
      appleRecoveryLink: vi.fn(),
      appleUnlink: vi.fn(),
      googleLinkStart: vi.fn(),
      googleUnlink: vi.fn(),
      me: vi.fn(),
      homes: vi.fn(),
      devices: vi.fn(),
      passkeys: vi.fn(),
      passkeyRegistrationOptions: vi.fn(),
      passkeyRegistrationVerify: vi.fn(),
      renamePasskey: vi.fn(),
      revokePasskey: vi.fn(),
      revokeDevice: vi.fn(),
      revokeOtherDevices: vi.fn(),
      mfaStatus: vi.fn(),
      totpSetup: vi.fn(),
      totpVerify: vi.fn(),
      removeTotp: vi.fn(),
      setMfaPreference: vi.fn(),
      reauthenticate: vi.fn(),
    },
  };
});

vi.mock("@/components/passkey-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/passkey-client")>();
  return {
    ...actual,
    biometricSignInAvailable: vi.fn(async () => true),
    biometricLabel: () => "Face ID",
    createPasskey: vi.fn(async () => ({ id: "registration" })),
  };
});

let nativeShell = false;
vi.mock("@/components/native-runtime", () => ({
  isNativeShell: () => nativeShell,
  nativePlatform: () => (nativeShell ? "ios" : "web"),
}));

// Native linking: capture the deep-link listener so a test can deliver the
// system-browser return, and stub the in-app browser.
const appUrlOpen = vi.hoisted(() => ({ handler: null as ((event: { url: string }) => void) | null }));
vi.mock("@capacitor/app", () => ({
  App: {
    addListener: vi.fn((event: string, handler: (event: { url: string }) => void) => {
      if (event === "appUrlOpen") appUrlOpen.handler = handler;
      return Promise.resolve({ remove: vi.fn() });
    }),
  },
}));
vi.mock("@capacitor/browser", () => ({ Browser: { open: vi.fn(async () => {}) } }));

vi.mock("@/components/native-biometric", () => ({
  biometricLabel: vi.fn(() => "Face ID"),
  deviceNoun: vi.fn(() => "device"),
  getBiometricCapability: vi.fn(async () => ({
    kind: "faceId",
    label: "Face ID",
    available: true,
    lockedOut: false,
    notEnrolled: false,
    reason: "",
  })),
  authenticateWithBiometrics: vi.fn(async () => ({ ok: true })),
  isBiometricCancellation: vi.fn(() => false),
}));

vi.mock("@/components/native-biometric-preference", () => ({
  isBiometricSignInEnabled: vi.fn(async () => false),
  setBiometricSignInEnabled: vi.fn(async () => {}),
}));

// AppShell (rendered by SettingsPage, which every settings page — including
// Security — wraps in) now bootstraps a native session instead of the
// cookie-based api.me() whenever isNativeShell() is true (see
// components/app-shell.tsx) — without this mock, the native-shell tests
// below would exercise the real NativeMyKhayaClient/fetch and land on
// AppShell's "offline" state instead of ever rendering Security's content.
vi.mock("@/components/native-auth", () => ({
  bootstrapNativeSession: vi.fn(),
  nativeExternalStart: vi.fn(),
  nativeExternalAssertion: vi.fn(),
  nativeExternalExchange: vi.fn(),
  nativeExternalBrowserStart: vi.fn(),
  nativeExternalRedeem: vi.fn(),
}));

const { api, ApiError } = await import("@mykhaya/api-client");
const passkeyClient = await import("@/components/passkey-client");
const nativeAuth = await import("@/components/native-auth");
const { bootstrapNativeSession } = nativeAuth;

const meResponse = {
  id: "user-1",
  email: "anthony@example.com",
  display_name: "Anthony",
  email_verified: true,
  birth_month: null,
  birth_day: null,
  birth_year: null,
  avatar_version: null,
  principal_type: "adult",
};

function passkey(overrides: Partial<Passkey> = {}): Passkey {
  return {
    id: "passkey-1",
    label: "iPhone",
    created_at: "2026-01-01T00:00:00Z",
    last_used_at: null,
    authenticator_attachment: "platform",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  nativeShell = false;
  searchParamsState.value = new URLSearchParams();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue(meResponse);
  (bootstrapNativeSession as ReturnType<typeof vi.fn>).mockResolvedValue(meResponse);
  (api.devices as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (api.externalIdentities as ReturnType<typeof vi.fn>).mockResolvedValue({
    password_available: true,
    identities: [],
  });
  (api.passkeys as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (api.authProviders as ReturnType<typeof vi.fn>).mockResolvedValue({
    providers: [
      { provider: "apple", enabled: true },
      { provider: "google", enabled: true },
    ],
  });
  (api.mfaStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
    required: false,
    allowed_methods: ["totp", "email"],
    email_available: true,
    totp_enabled: false,
    can_disable_totp: false,
  });
  (passkeyClient.biometricSignInAvailable as ReturnType<typeof vi.fn>).mockResolvedValue(true);
});

describe("Security — browser passkeys, not enrolled on this device", () => {
  it("shows provider-neutral sign-in methods and starts Apple linking", async () => {
    (api.appleLinkStart as ReturnType<typeof vi.fn>).mockResolvedValue({
      authorization_url: "https://appleid.apple.com/auth/authorize?state=test",
    });
    const user = userEvent.setup();
    render(<Security />);

    await screen.findByText("Sign-in methods");
    expect(screen.getByText("Email and password")).toBeInTheDocument();
    expect(screen.getByText("Apple")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Connect Apple" }));

    expect(api.appleLinkStart).toHaveBeenCalled();
  });

  it("shows one status badge per provider and keeps long addresses contained", async () => {
    (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...meResponse,
      email: "a.very.long.account.address+family.notifications@example.mykhaya.test",
    });
    (api.externalIdentities as ReturnType<typeof vi.fn>).mockResolvedValue({
      password_available: true,
      identities: [{
        provider: "google",
        provider_email: "a.very.long.provider.address+family@example.com",
        provider_email_verified: true,
        linked_at: "2026-01-01T00:00:00Z",
        last_used_at: "2026-01-02T00:00:00Z",
      }],
    });
    render(<Security />);

    expect(await screen.findByText("a.very.long.provider.address+family@example.com")).toBeInTheDocument();
    expect(screen.getAllByText("Connected")).toHaveLength(2);
    expect(screen.getAllByText("Not connected")).toHaveLength(1);
    expect(screen.getByText(/Linked/)).toBeInTheDocument();
  });

  it("explains mandatory browser MFA and marks the preferred method", async () => {
    (api.mfaStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      required: true,
      allowed_methods: ["totp", "email"],
      email_available: true,
      email_destination: "a***@example.com",
      totp_enabled: true,
      can_disable_totp: false,
      usable_methods: ["totp", "email"],
      preferred_method: "email",
    });
    render(<Security />);

    expect(await screen.findByText(/including when using Apple or Google/i)).toBeInTheDocument();
    expect(screen.getByText("Preferred")).toBeInTheDocument();
    expect(screen.getByText(/required by your sign-in policy/i)).toBeInTheDocument();
  });

  it("completes an Apple link after the provider form-post returns without cookies", async () => {
    searchParamsState.value = new URLSearchParams("apple=link_required&transaction=apple-link-tx");
    (api.appleRecoveryLink as ReturnType<typeof vi.fn>).mockResolvedValue({ message: "linked" });
    (api.externalIdentities as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ password_available: true, identities: [] })
      .mockResolvedValueOnce({
        password_available: true,
        identities: [{
          provider: "apple",
          provider_email: null,
          provider_email_verified: true,
          linked_at: "2026-01-01T00:00:00Z",
          last_used_at: null,
        }],
      });
    render(<Security />);

    await waitFor(() => expect(api.appleRecoveryLink).toHaveBeenCalledWith("apple-link-tx"));
    expect(await screen.findByText("Apple sign-in is now connected.")).toBeInTheDocument();
  });

  it("disconnects Apple only after confirmation", async () => {
    (api.externalIdentities as ReturnType<typeof vi.fn>).mockResolvedValue({
      password_available: true,
      identities: [{
          provider: "apple",
          provider_email: "relay@privaterelay.appleid.com",
          provider_email_verified: true,
          linked_at: "2026-01-01T00:00:00Z",
          last_used_at: "2026-01-02T00:00:00Z",
        }],
    });
    (api.appleUnlink as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    render(<Security />);

    await screen.findByText("relay@privaterelay.appleid.com");
    await user.click(screen.getByRole("button", { name: "Disconnect Apple" }));
    expect(api.appleUnlink).toHaveBeenCalled();
    await screen.findByText("Apple sign-in has been disconnected.");
  });

  it("starts Google linking from the provider-neutral sign-in methods card", async () => {
    (api.googleLinkStart as ReturnType<typeof vi.fn>).mockResolvedValue({
      authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?state=test",
    });
    const user = userEvent.setup();
    render(<Security />);

    await screen.findByText("Google");
    await user.click(await screen.findByRole("button", { name: "Connect Google" }));

    expect(api.googleLinkStart).toHaveBeenCalled();
  });

  it("shows passkeys in their own card with a generic Add passkey action behind Manage", async () => {
    const user = userEvent.setup();
    render(<Security />);

    const card = (await screen.findByRole("heading", { name: "Passkeys" })).closest("section")!;
    expect(card).not.toContainElement(screen.getByRole("heading", { name: "Multi-factor authentication" }));
    expect(screen.getByText("No passkeys set up")).toBeInTheDocument();
    const manage = screen.getByRole("button", { name: "Manage passkeys" });
    expect(manage).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "Add passkey" })).not.toBeInTheDocument();
    await user.click(manage);
    expect(manage).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "Add passkey" })).toBeInTheDocument();
    expect(screen.getByText(/use a passkey to sign in securely/i)).toBeInTheDocument();
    expect(screen.queryByText(/webauthn/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/relying party/i)).not.toBeInTheDocument();
  });

  it("does not show a broken Enable button when no platform authenticator is available", async () => {
    (passkeyClient.biometricSignInAvailable as ReturnType<typeof vi.fn>).mockResolvedValue(false);
    const user = userEvent.setup();
    render(<Security />);

    await user.click(await screen.findByRole("button", { name: "Manage passkeys" }));
    await screen.findByText(/passkeys aren.t available/i);
    expect(screen.queryByRole("button", { name: /enable/i })).not.toBeInTheDocument();
  });

  it("starts authenticator setup and confirms it with a six-digit code", async () => {
    (api.totpSetup as ReturnType<typeof vi.fn>).mockResolvedValue({
      provisioning_uri: "otpauth://totp/MyKhaya:test@example.com?secret=ABC",
      manual_key: "ABC",
    });
    (api.totpVerify as ReturnType<typeof vi.fn>).mockResolvedValue({
      required: false,
      allowed_methods: ["totp", "email"],
      email_available: true,
      totp_enabled: true,
      can_disable_totp: true,
    });
    const user = userEvent.setup();
    render(<Security />);

    await user.click(await screen.findByRole("button", { name: /set up authenticator/i }));
    await screen.findByText("ABC");
    await user.type(screen.getByLabelText("Confirmation code"), "123456");
    await user.click(screen.getByRole("button", { name: /confirm setup/i }));

    expect(api.totpVerify).toHaveBeenCalledWith("123456");
    await screen.findByText(/authenticator app is now set up/i);
  });

  it("enrolling creates a passkey, remembers it as this device's, and sets the login hint", async () => {
    (api.passkeyRegistrationOptions as ReturnType<typeof vi.fn>).mockResolvedValue({
      options_json: "{}",
    });
    (api.passkeyRegistrationVerify as ReturnType<typeof vi.fn>).mockResolvedValue(passkey());
    const user = userEvent.setup();
    render(<Security />);

    await user.click(await screen.findByRole("button", { name: "Manage passkeys" }));
    await user.click(await screen.findByRole("button", { name: "Add passkey" }));

    await screen.findByText(/a passkey is enabled on this browser\/device/i);
    expect(passkeyClient.getEnrolledPasskeyId()).toBe("passkey-1");
    expect(passkeyClient.getBiometricHint()).toEqual({
      userId: "user-1",
      displayName: "Anthony",
      avatarVersion: null,
    });
  });

  it("a cancelled enrolment prompt shows a clear message, not a generic error", async () => {
    (api.passkeyRegistrationOptions as ReturnType<typeof vi.fn>).mockResolvedValue({
      options_json: "{}",
    });
    (passkeyClient.createPasskey as ReturnType<typeof vi.fn>).mockRejectedValue(
      new DOMException("cancelled", "NotAllowedError"),
    );
    const user = userEvent.setup();
    render(<Security />);

    await user.click(await screen.findByRole("button", { name: "Manage passkeys" }));
    await user.click(await screen.findByRole("button", { name: "Add passkey" }));

    await screen.findByText(/setup was cancelled/i);
  });
});

describe("Security — browser passkey already enabled on this device", () => {
  beforeEach(() => {
    passkeyClient.setEnrolledPasskeyId("passkey-1");
    passkeyClient.setBiometricHint({
      userId: "user-1",
      displayName: "Anthony",
      avatarVersion: null,
    });
    (api.passkeys as ReturnType<typeof vi.fn>).mockResolvedValue([passkey()]);
  });

  it("shows the enabled state and a Disable control, not a credential list", async () => {
    const user = userEvent.setup();
    render(<Security />);

    expect(await screen.findByText("1 passkey set up")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Manage passkeys" }));

    await screen.findByText(/a passkey is enabled on this browser\/device/i);
    expect(screen.getByRole("button", { name: /disable/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /enable/i })).not.toBeInTheDocument();
  });

  it("disabling revokes precisely this device's credential and clears local hints", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    (api.revokePasskey as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<Security />);

    await user.click(await screen.findByRole("button", { name: "Manage passkeys" }));
    await user.click(await screen.findByRole("button", { name: /disable/i }));

    expect(api.revokePasskey).toHaveBeenCalledWith("passkey-1");
    await screen.findByText(/turned off on this device/i);
    expect(passkeyClient.getEnrolledPasskeyId()).toBeNull();
    expect(passkeyClient.getBiometricHint()).toBeNull();
  });

  it("declining the confirmation leaves the credential untouched", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    render(<Security />);

    await user.click(await screen.findByRole("button", { name: "Manage passkeys" }));
    await user.click(await screen.findByRole("button", { name: /disable/i }));

    expect(api.revokePasskey).not.toHaveBeenCalled();
    expect(passkeyClient.getEnrolledPasskeyId()).toBe("passkey-1");
  });

  it("other devices' credentials stay inside the Manage panel, with rename and remove", async () => {
    (api.passkeys as ReturnType<typeof vi.fn>).mockResolvedValue([
      passkey({ id: "passkey-1", label: "iPhone" }),
      passkey({ id: "passkey-2", label: "Work laptop" }),
    ]);
    (api.revokePasskey as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<Security />);

    expect(await screen.findByText("2 passkeys set up")).toBeInTheDocument();
    expect(screen.getByText("Work laptop")).not.toBeVisible();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Manage passkeys" }));
    expect(screen.getByText("Work laptop")).toBeVisible();
    expect(screen.getByText("Passkeys on other devices")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rename Work laptop" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove Work laptop" }));
    expect(api.revokePasskey).toHaveBeenCalledWith("passkey-2");
    await waitFor(() => expect(screen.queryByText("Work laptop")).not.toBeInTheDocument());
  });
});

describe("Security — native shell shows Quick Sign-In instead of the browser passkey card", () => {
  it("renders Quick Sign-In and hides the WebAuthn passkey card inside the native shell", async () => {
    nativeShell = true;
    render(<Security />);

    await screen.findByRole("button", { name: /enable face id/i });
    expect(screen.queryByText("Biometric sign-in")).not.toBeInTheDocument();
  });

  it("still renders the browser passkey card, not Quick Sign-In, outside the native shell", async () => {
    nativeShell = false;
    render(<Security />);

    await screen.findByText("Passkeys");
    expect(screen.queryByText("Quick Sign-In")).not.toBeInTheDocument();
  });

  it("Quick Sign-In enable flow requires a successful biometric confirmation before recording the preference", async () => {
    nativeShell = true;
    const { authenticateWithBiometrics } = await import("@/components/native-biometric");
    const { setBiometricSignInEnabled } = await import("@/components/native-biometric-preference");
    const user = userEvent.setup();
    render(<Security />);

    await user.click(await screen.findByRole("button", { name: /enable face id/i }));

    expect(authenticateWithBiometrics).toHaveBeenCalled();
    expect(setBiometricSignInEnabled).toHaveBeenCalledWith(true);
    await screen.findByText(/face id is ready/i);
  });

  it("never invokes browser WebAuthn feature-detection inside the native shell — the observed crash trigger", async () => {
    nativeShell = true;
    render(<Security />);

    await screen.findByRole("button", { name: /enable face id/i });
    expect(passkeyClient.biometricSignInAvailable).not.toHaveBeenCalled();
  });

  it("a cancelled biometric prompt never records the preference and shows no error", async () => {
    nativeShell = true;
    const { authenticateWithBiometrics, isBiometricCancellation } = await import(
      "@/components/native-biometric"
    );
    const { setBiometricSignInEnabled } = await import("@/components/native-biometric-preference");
    (authenticateWithBiometrics as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      code: "userCancel",
      message: "cancelled",
    });
    (isBiometricCancellation as ReturnType<typeof vi.fn>).mockReturnValue(true);
    const user = userEvent.setup();
    render(<Security />);

    await user.click(await screen.findByRole("button", { name: /enable face id/i }));

    expect(setBiometricSignInEnabled).not.toHaveBeenCalledWith(true);
    expect(document.querySelector(".notice.error")).not.toBeInTheDocument();
  });
});

function device(overrides: Partial<{
  id: string;
  device_name: string;
  platform: string;
  user_agent: string;
  last_used_at: string;
  current: boolean;
}> = {}) {
  return {
    id: "device-1",
    device_name: "MyKhaya device",
    platform: "Web/PWA",
    user_agent: "Mozilla/5.0",
    last_used_at: "2026-11-05T10:00:00Z",
    current: false,
    ...overrides,
  };
}

const manyDevices = [
  device({ id: "current", platform: "iOS", current: true }),
  ...Array.from({ length: 6 }, (_, index) =>
    device({
      id: `other-${index}`,
      platform: index % 2 ? "iOS" : "Web/PWA",
      last_used_at: `2026-11-0${index + 1}T10:00:00Z`,
    }),
  ),
];

describe("Security — sign-in method rows", () => {
  it("shows Apple's metadata and does not repeat a connection state for a disconnected provider", async () => {
    (api.externalIdentities as ReturnType<typeof vi.fn>).mockResolvedValue({
      password_available: true,
      identities: [{
        provider: "apple",
        provider_email: "me@example.com",
        provider_email_verified: true,
        linked_at: "2026-11-04T00:00:00Z",
        last_used_at: "2026-11-05T00:00:00Z",
      }],
    });
    render(<Security />);

    const apple = (await screen.findByText("Apple")).closest("li")!;
    expect(apple).toHaveTextContent("me@example.com");
    expect(apple).toHaveTextContent(/Linked .*2026/);
    expect(apple).toHaveTextContent(/Last used .*2026/);
    expect(apple).toHaveTextContent("Connected");
    const google = screen.getByText("Google").closest("li")!;
    expect(google.textContent?.match(/Not connected/g)).toHaveLength(1);
    expect(await screen.findByRole("button", { name: "Connect Google" })).toBeInTheDocument();
  });

  it("never offers Connect for a provider the platform has disabled", async () => {
    (api.authProviders as ReturnType<typeof vi.fn>).mockResolvedValue({
      providers: [
        { provider: "apple", enabled: true },
        { provider: "google", enabled: false },
      ],
    });
    render(<Security />);

    await screen.findByRole("button", { name: "Connect Apple" });
    expect(screen.queryByRole("button", { name: "Connect Google" })).not.toBeInTheDocument();
    expect(screen.getByText("Google").closest("li")).toHaveTextContent("Unavailable");
  });

  it("offers no Connect action while provider availability is unresolved or failed", async () => {
    (api.authProviders as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("offline"));
    render(<Security />);

    await screen.findAllByText("Unavailable");
    expect(screen.queryByRole("button", { name: /^Connect/ })).not.toBeInTheDocument();
  });
});

describe("Security — multi-factor authentication", () => {
  it("keeps the preferred-method choice and calls the existing preference API", async () => {
    (api.mfaStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      required: true,
      allowed_methods: ["totp", "email"],
      email_available: true,
      email_destination: "a***@example.com",
      totp_enabled: true,
      can_disable_totp: true,
      usable_methods: ["totp", "email"],
      preferred_method: "email",
    });
    (api.setMfaPreference as ReturnType<typeof vi.fn>).mockResolvedValue({
      required: true,
      allowed_methods: ["totp", "email"],
      email_available: true,
      email_destination: "a***@example.com",
      totp_enabled: true,
      can_disable_totp: true,
      usable_methods: ["totp", "email"],
      preferred_method: "totp",
    });
    const user = userEvent.setup();
    render(<Security />);

    const emailRow = (await screen.findByText("Email verification")).closest("li")!;
    expect(emailRow).toHaveTextContent("a***@example.com");
    expect(emailRow).toHaveTextContent("Preferred");
    expect(screen.getByRole("button", { name: "Disable" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Make preferred" }));

    expect(api.setMfaPreference).toHaveBeenCalledWith("totp");
    await waitFor(() =>
      expect(screen.getByText("Authenticator app").closest("li")).toHaveTextContent("Preferred"),
    );
  });
});

describe("Security — signed-in devices", () => {
  it("highlights the backend-identified current session and shows the real session count", async () => {
    (api.devices as ReturnType<typeof vi.fn>).mockResolvedValue([
      device({ id: "web", platform: "Web/PWA" }),
      device({ id: "phone", platform: "iOS", current: true }),
    ]);
    render(<Security />);

    expect(await screen.findByText("2 sessions")).toBeInTheDocument();
    const current = screen.getByText("This device").closest("li")!;
    expect(current).toHaveClass("security-device-current");
    expect(current).toHaveTextContent("iOS");
    expect(current).toHaveTextContent("Current");
    expect(screen.getByText("Web browser").closest("li")).toHaveTextContent("Web/PWA");
  });

  it("does not guess a current device when the API marks none", async () => {
    (api.devices as ReturnType<typeof vi.fn>).mockResolvedValue([device({ id: "a", platform: "iOS" })]);
    render(<Security />);

    expect(await screen.findByText("1 session")).toBeInTheDocument();
    expect(screen.queryByText("This device")).not.toBeInTheDocument();
    expect(screen.getByText("iOS device")).toBeInTheDocument();
  });

  it("collapses to the current and two most recent sessions, then shows all and fewer without revoking", async () => {
    (api.devices as ReturnType<typeof vi.fn>).mockResolvedValue(manyDevices);
    const user = userEvent.setup();
    render(<Security />);

    expect(await screen.findByText("7 sessions")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Sign out .*last active/ })).toHaveLength(2);
    const toggle = screen.getByRole("button", { name: "Show all devices (4 more)" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await user.click(toggle);
    expect(screen.getAllByRole("button", { name: /^Sign out .*last active/ })).toHaveLength(6);
    await user.click(screen.getByRole("button", { name: "Show fewer devices" }));
    expect(screen.getAllByRole("button", { name: /^Sign out .*last active/ })).toHaveLength(2);
    expect(api.revokeDevice).not.toHaveBeenCalled();
    expect(api.revokeOtherDevices).not.toHaveBeenCalled();
  });

  it("lists the most recently active other sessions first", async () => {
    (api.devices as ReturnType<typeof vi.fn>).mockResolvedValue(manyDevices);
    render(<Security />);

    const buttons = await screen.findAllByRole("button", { name: /^Sign out .*last active/ });
    expect(buttons[0]).toHaveAccessibleName(`Sign out iOS device, last active ${new Date("2026-11-06T10:00:00Z").toLocaleDateString()}`);
  });

  it("signs out one session", async () => {
    (api.devices as ReturnType<typeof vi.fn>).mockResolvedValue([
      device({ id: "current", platform: "iOS", current: true }),
      device({ id: "web", platform: "Web/PWA" }),
    ]);
    (api.revokeDevice as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<Security />);

    await user.click(await screen.findByRole("button", { name: /^Sign out Web browser/ }));
    expect(api.revokeDevice).toHaveBeenCalledWith("web");
    expect(await screen.findByText("1 session")).toBeInTheDocument();
  });

  it("signs out all other sessions only after confirmation", async () => {
    (api.devices as ReturnType<typeof vi.fn>).mockResolvedValue(manyDevices);
    (api.revokeOtherDevices as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    const user = userEvent.setup();
    render(<Security />);

    const button = await screen.findByRole("button", { name: "Sign out all other devices" });
    await user.click(button);
    expect(api.revokeOtherDevices).not.toHaveBeenCalled();
    await user.click(button);
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(api.revokeOtherDevices).toHaveBeenCalled();
    expect(await screen.findByText("1 session")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign out all other devices" })).not.toBeInTheDocument();
  });
});

describe("Security — native shell keeps account security features", () => {
  it("shows MFA and passkey management without offering WebAuthn enrolment", async () => {
    nativeShell = true;
    (api.passkeys as ReturnType<typeof vi.fn>).mockResolvedValue([passkey({ id: "pk", label: "MacBook" })]);
    const user = userEvent.setup();
    render(<Security />);

    expect(await screen.findByRole("heading", { name: "Multi-factor authentication" })).toBeInTheDocument();
    expect(await screen.findByText("Use codes from your authenticator app.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Manage passkeys" }));
    expect(screen.getByText("MacBook")).toBeVisible();
    expect(screen.getByRole("button", { name: "Remove MacBook" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add passkey" })).not.toBeInTheDocument();
    expect(api.authProviders).not.toHaveBeenCalled();
    expect(await screen.findByRole("button", { name: "Connect Apple" })).toBeInTheDocument();
    expect(passkeyClient.biometricSignInAvailable).not.toHaveBeenCalled();
  });
});

describe("Security — native linking when the provider account belongs to someone else", () => {
  const ALREADY_LINKED = (provider: string) =>
    `That ${provider} account is already linked to another MyKhaya account.`;

  it("explains a 409 from the system-browser link (Google on iPhone)", async () => {
    nativeShell = true;
    (nativeAuth.nativeExternalBrowserStart as ReturnType<typeof vi.fn>).mockResolvedValue({
      authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?state=native",
      transaction_id: "google-link-tx",
    });
    (nativeAuth.nativeExternalRedeem as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(409, "Conflict"),
    );
    const user = userEvent.setup();
    render(<Security />);

    await user.click(await screen.findByRole("button", { name: "Connect Google" }));
    await waitFor(() => expect(nativeAuth.nativeExternalBrowserStart).toHaveBeenCalledWith("google", "link"));
    // The browser returns to the app through its deep link.
    await waitFor(() => expect(appUrlOpen.handler).not.toBeNull());
    appUrlOpen.handler!({ url: "mykhaya://auth/callback?transaction=google-link-tx" });

    expect(await screen.findByText(ALREADY_LINKED("Google"))).toBeInTheDocument();
    expect(nativeAuth.nativeExternalRedeem).toHaveBeenCalledWith("google-link-tx");
  });

  it("explains a 409 from the SDK link (Apple on iPhone)", async () => {
    nativeShell = true;
    (nativeAuth.nativeExternalStart as ReturnType<typeof vi.fn>).mockResolvedValue({
      transaction_id: "apple-link-tx",
      nonce: "nonce",
      provider: "apple",
      client_id: "app.mykhaya.mobile",
    });
    (nativeAuth.nativeExternalAssertion as ReturnType<typeof vi.fn>).mockResolvedValue({ identity_token: "token" });
    (nativeAuth.nativeExternalExchange as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(409, "Conflict"),
    );
    const user = userEvent.setup();
    render(<Security />);

    await user.click(await screen.findByRole("button", { name: "Connect Apple" }));

    expect(await screen.findByText(ALREADY_LINKED("Apple"))).toBeInTheDocument();
  });
});
