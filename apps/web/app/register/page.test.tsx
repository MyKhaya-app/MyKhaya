import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Register from "./page";

const { push, post, publicLegalDocuments, publicSignupState, nativeRegister, nativeShellState, searchParams } = vi.hoisted(() => ({
  push: vi.fn(),
  post: vi.fn(),
  publicLegalDocuments: vi.fn(),
  publicSignupState: vi.fn(),
  nativeRegister: vi.fn(),
  nativeShellState: { value: false },
  searchParams: { value: "" },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams(searchParams.value),
}));

vi.mock("@/components/native-runtime", () => ({
  isNativeShell: () => nativeShellState.value,
  nativePlatform: () => "ios",
}));

vi.mock("@/components/native-auth", () => ({
  nativeRegister,
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      post,
      publicLegalDocuments,
      publicSignupState,
    },
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  nativeShellState.value = false;
  searchParams.value = "";
  nativeRegister.mockResolvedValue({ message: "Check your inbox.", verification_required: true });
  post.mockResolvedValue({ message: "Check your inbox.", verification_required: true });
  publicLegalDocuments.mockResolvedValue([]);
  publicSignupState.mockResolvedValue({
    signup_mode: "normal",
    registration_open: true,
    invitation_required: false,
    normal_signup_available: true,
    beta_joining_available: false,
    waitlist_available: false,
    joinable_count: null,
  });
});

async function submitRegistration() {
  const user = userEvent.setup();
  render(<Register />);
  await user.type(screen.getByLabelText("Your name"), "New User");
  await user.type(screen.getByLabelText("Email"), "new@example.com");
  await user.type(
    screen.getByLabelText("Password", { exact: false, selector: 'input[name="password"]' }),
    "correct horse battery staple",
  );
  await user.type(screen.getByLabelText("Confirm password"), "correct horse battery staple");
  await user.click(screen.getByRole("button", { name: "Create account" }));
}

describe("registration transport", () => {
  it("uses the native unauthenticated registration path when the shell has no session", async () => {
    nativeShellState.value = true;
    await submitRegistration();

    await waitFor(() => expect(nativeRegister).toHaveBeenCalled());
    expect(post).not.toHaveBeenCalledWith("/auth/register", expect.anything());
    expect(push).toHaveBeenCalledWith("/verify-email");
  });

  it("keeps browser registration on the cookie transport", async () => {
    await submitRegistration();

    await waitFor(() => expect(post).toHaveBeenCalledWith("/auth/register", expect.objectContaining({
      email: "new@example.com",
      display_name: "New User",
    })));
    expect(nativeRegister).not.toHaveBeenCalled();
    expect(push).toHaveBeenCalledWith("/verify-email");
  });
});

describe("Founding Beta registration availability", () => {
  it("enables Beta registration when Beta joining is available in beta-only mode", async () => {
    searchParams.value = "beta=1";
    publicSignupState.mockResolvedValue({
      signup_mode: "beta_only",
      registration_open: true,
      invitation_required: false,
      normal_signup_available: false,
      beta_joining_available: true,
      waitlist_available: false,
      joinable_count: 4,
      beta_terms_version: "2026-01",
    });
    render(<Register />);

    expect(await screen.findByText(/You.re registering for the Founding Beta/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create account" })).toBeEnabled();
    expect(screen.queryByText(/can.t be created from this page/)).not.toBeInTheDocument();
  });
});
