// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ApiError, api } from "@mykhaya/api-client";
import MfaPage from "./page";

const replace = vi.fn();
const push = vi.fn();
const setAuthenticatedUser = vi.fn();
let query = "transaction=valid-transaction";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push }),
  useSearchParams: () => new URLSearchParams(query),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return { ...actual, api: { ...actual.api, get: vi.fn(), post: vi.fn() } };
});

vi.mock("@/components/auth-provider", () => ({
  useAuth: () => ({ setAuthenticatedUser }),
}));

vi.mock("qrcode", () => ({
  default: { toDataURL: vi.fn().mockResolvedValue("data:image/png;base64,qr") },
}));

const get = api.get as ReturnType<typeof vi.fn>;
const post = api.post as ReturnType<typeof vi.fn>;

const emailOptions = { methods: ["email"], destination: "a***@example.com", onboarding: false };
const totpOptions = { methods: ["totp"], destination: null, onboarding: false };
const emailStart = { method: "email", destination: "a***@example.com", enrolling: false };
const totpStart = {
  method: "totp",
  provisioning_uri: null,
  manual_key: null,
  enrolling: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  query = "transaction=valid-transaction";
  get.mockResolvedValue(emailOptions);
  post.mockResolvedValue(emailStart);
});

describe("browser MFA continuation", () => {
  it("loads options using the retained transaction query parameter", async () => {
    render(<MfaPage />);

    await waitFor(() => expect(get).toHaveBeenCalledWith(
      "/auth/mfa/options?transaction_id=valid-transaction",
    ));
    expect(screen.getByRole("heading", { name: /verify it/i })).toBeInTheDocument();
  });

  it("starts the only available method automatically", async () => {
    render(<MfaPage />);

    await screen.findByLabelText("Verification code");
    expect(post).toHaveBeenCalledWith("/auth/mfa/start", {
      transaction_id: "valid-transaction",
      method: "email",
    });
    expect(screen.getByRole("button", { name: /resend code in 30s/i })).toBeDisabled();
  });

  it("returns directly to login when the transaction is missing", async () => {
    query = "";
    render(<MfaPage />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login?mfa_error=expired"));
    expect(get).not.toHaveBeenCalled();
  });

  it("returns directly to login when the transaction is expired or consumed", async () => {
    get.mockRejectedValue(new ApiError(400, "This sign-in attempt has expired."));
    render(<MfaPage />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login?mfa_error=expired"));
  });

  it("completes an Email MFA challenge and enters the application", async () => {
    post
      .mockResolvedValueOnce(emailStart)
      .mockResolvedValueOnce({ id: "user-1", display_name: "Owner" });
    render(<MfaPage />);

    await screen.findByText(/verify it/i);
    await screen.findByText(/sent a verification code/i);
    fireEvent.change(screen.getByLabelText("Verification code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));

    await waitFor(() => expect(setAuthenticatedUser).toHaveBeenCalledWith(
      { id: "user-1", display_name: "Owner" },
    ));
    expect(push).toHaveBeenCalledWith("/home");
    expect(post).toHaveBeenLastCalledWith("/auth/mfa/verify", {
      transaction_id: "valid-transaction",
      method: "email",
      code: "123456",
    });
  });

  it("keeps an invalid Email OTP on the MFA screen", async () => {
    post
      .mockResolvedValueOnce(emailStart)
      .mockRejectedValueOnce(new ApiError(401, "That verification code is invalid."));
    render(<MfaPage />);

    await screen.findByText(/sent a verification code/i);
    fireEvent.change(screen.getByLabelText("Verification code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));

    expect(await screen.findByText(/That code isn't correct/)).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });

  it("completes TOTP and keeps an invalid TOTP challenge on the screen", async () => {
    get.mockResolvedValue(totpOptions);
    post
      .mockResolvedValueOnce(totpStart)
      .mockRejectedValueOnce(new ApiError(401, "That verification code is invalid."));
    render(<MfaPage />);

    await screen.findByLabelText("Verification code");
    fireEvent.change(screen.getByLabelText("Verification code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));

    expect(await screen.findByText(/That code isn't correct/)).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });
});
