import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Home, Passkey } from "@mykhaya/shared-types";
import Security from "./page";

// Biometric sign-in coverage for the Security settings screen — this is
// the "Enable biometric sign-in" / "Face ID is enabled on this device /
// [Disable]" toggle from the biometric sign-in report, not a list-of-
// credentials-first UX (that lives behind the secondary <details> disclosure
// only when more than one device has enrolled).

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/settings/security",
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

const { api } = await import("@mykhaya/api-client");
const passkeyClient = await import("@/components/passkey-client");

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
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue(meResponse);
  (api.devices as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (api.passkeys as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (passkeyClient.biometricSignInAvailable as ReturnType<typeof vi.fn>).mockResolvedValue(true);
});

describe("Security — Biometric sign-in, not enrolled on this device", () => {
  it("shows Enable biometric sign-in with the platform-guessed label, no credential list by default", async () => {
    render(<Security />);

    await screen.findByRole("heading", { name: /biometric sign-in/i });
    expect(screen.getByRole("button", { name: /enable face id/i })).toBeInTheDocument();
    expect(screen.getByText(/use face id, touch id or your device security/i)).toBeInTheDocument();
    expect(screen.queryByText(/webauthn/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/relying party/i)).not.toBeInTheDocument();
  });

  it("does not show a broken Enable button when no platform authenticator is available", async () => {
    (passkeyClient.biometricSignInAvailable as ReturnType<typeof vi.fn>).mockResolvedValue(false);
    render(<Security />);

    await screen.findByText(/biometric sign-in isn't available/i);
    expect(screen.queryByRole("button", { name: /enable/i })).not.toBeInTheDocument();
  });

  it("enrolling creates a passkey, remembers it as this device's, and sets the login hint", async () => {
    (api.passkeyRegistrationOptions as ReturnType<typeof vi.fn>).mockResolvedValue({
      options_json: "{}",
    });
    (api.passkeyRegistrationVerify as ReturnType<typeof vi.fn>).mockResolvedValue(passkey());
    const user = userEvent.setup();
    render(<Security />);

    await user.click(await screen.findByRole("button", { name: /enable face id/i }));

    await screen.findByText(/face id is enabled on this device/i);
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

    await user.click(await screen.findByRole("button", { name: /enable face id/i }));

    await screen.findByText(/setup was cancelled/i);
  });
});

describe("Security — Biometric sign-in already enabled on this device", () => {
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
    render(<Security />);

    await screen.findByText(/face id is enabled on this device/i);
    expect(screen.getByRole("button", { name: /disable/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /enable/i })).not.toBeInTheDocument();
  });

  it("disabling revokes precisely this device's credential and clears local hints", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    (api.revokePasskey as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<Security />);

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

    await user.click(await screen.findByRole("button", { name: /disable/i }));

    expect(api.revokePasskey).not.toHaveBeenCalled();
    expect(passkeyClient.getEnrolledPasskeyId()).toBe("passkey-1");
  });

  it("other devices' credentials are tucked behind a secondary disclosure, not shown as a primary list", async () => {
    (api.passkeys as ReturnType<typeof vi.fn>).mockResolvedValue([
      passkey({ id: "passkey-1", label: "iPhone" }),
      passkey({ id: "passkey-2", label: "Work laptop" }),
    ]);
    render(<Security />);

    await screen.findByText(/face id is enabled on this device/i);
    expect(screen.getByText("Work laptop")).not.toBeVisible();
    await screen.findByText(/1 other device with biometric sign-in/i);

    const user = userEvent.setup();
    await user.click(screen.getByText(/1 other device with biometric sign-in/i));
    expect(screen.getByText("Work laptop")).toBeInTheDocument();
  });
});
