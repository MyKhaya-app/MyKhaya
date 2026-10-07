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

const termsDocument = {
  key: "terms",
  display_name: "MyKhaya Terms & Conditions",
  scope: "global",
  audience: "adult",
  action_verb: "accept",
  acceptance_required: true,
  current_version: "1.0",
  current_version_id: "terms-v1",
};

const betaTermsDocument = {
  key: "founding_beta_terms",
  display_name: "Founding Beta Terms",
  scope: "founding_beta",
  audience: "adult",
  action_verb: "accept",
  acceptance_required: true,
  current_version: "1.1",
  current_version_id: "beta-v1",
};

const informationalDocuments = [
  {
    key: "privacy",
    display_name: "Privacy Notice",
    scope: "global",
    audience: "adult",
    action_verb: "acknowledge",
    acceptance_required: false,
    current_version: "1.0",
    current_version_id: "privacy-v1",
  },
  {
    key: "children_privacy",
    display_name: "Family & Children's Privacy Notice",
    scope: "global",
    audience: "adult",
    action_verb: "acknowledge",
    acceptance_required: false,
    current_version: "1.0",
    current_version_id: "children-v1",
  },
  {
    key: "cookies",
    display_name: "Cookie Policy",
    scope: "global",
    audience: "adult",
    action_verb: "acknowledge",
    acceptance_required: false,
    current_version: "1.0",
    current_version_id: "cookies-v1",
  },
];

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
  it("shows Beta registration when Beta joining is available in beta-only mode", async () => {
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
    expect(screen.getByRole("button", { name: "Create account" })).toBeDisabled();
    expect(screen.getByText(/I accept the Founding Beta Terms/)).toBeInTheDocument();
    expect(screen.queryByText(/can.t be created from this page/)).not.toBeInTheDocument();
  });
});

describe("registration legal acceptance", () => {
  it("requires both MyKhaya Terms and Founding Beta Terms for Beta signup", async () => {
    searchParams.value = "beta=1";
    publicLegalDocuments.mockResolvedValue([
      termsDocument,
      betaTermsDocument,
      ...informationalDocuments,
    ]);
    render(<Register />);

    const submit = await screen.findByRole("button", { name: "Create account" });
    expect(submit).toBeDisabled();
    expect(screen.getByLabelText("I accept the MyKhaya Terms & Conditions (version 1.0)")).toBeInTheDocument();
    expect(screen.getByLabelText("I accept the Founding Beta Terms (version 1.1)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Privacy Notice" })).toHaveAttribute("href", "/legal/privacy");
    expect(screen.getByRole("link", { name: "Cookie Policy" })).toHaveAttribute("href", "/legal/cookies");
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
  });

  it("enables Beta submit only after both contractual checkboxes are accepted", async () => {
    searchParams.value = "beta=1";
    publicSignupState.mockResolvedValue({
      signup_mode: "beta_only",
      registration_open: true,
      invitation_required: false,
      normal_signup_available: false,
      beta_joining_available: true,
      waitlist_available: false,
      joinable_count: 4,
      beta_terms_version: "1.1",
    });
    publicLegalDocuments.mockResolvedValue([termsDocument, betaTermsDocument]);
    render(<Register />);
    const user = userEvent.setup();
    const submit = await screen.findByRole("button", { name: "Create account" });
    const terms = screen.getByLabelText("I accept the MyKhaya Terms & Conditions (version 1.0)");
    const betaTerms = screen.getByLabelText("I accept the Founding Beta Terms (version 1.1)");
    await user.click(terms);
    expect(submit).toBeDisabled();
    await user.click(betaTerms);
    expect(submit).toBeEnabled();
  });

  it("submits a new Beta user's Home name when shared Beta Terms are present", async () => {
    searchParams.value = "beta=1";
    publicSignupState.mockResolvedValue({
      signup_mode: "beta_only",
      registration_open: true,
      invitation_required: false,
      normal_signup_available: false,
      beta_joining_available: true,
      waitlist_available: false,
      joinable_count: 4,
      beta_terms_version: "1.1",
    });
    publicLegalDocuments.mockResolvedValue([termsDocument, betaTermsDocument]);
    render(<Register />);
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Home name"), "New Beta Home");
    await user.type(screen.getByLabelText("Your name"), "New User");
    await user.type(screen.getByLabelText("Email"), "new-beta@example.com");
    await user.type(
      screen.getByLabelText("Password", { exact: false, selector: 'input[name="password"]' }),
      "correct horse battery staple",
    );
    await user.type(screen.getByLabelText("Confirm password"), "correct horse battery staple");
    await user.click(screen.getByLabelText("I accept the MyKhaya Terms & Conditions (version 1.0)"));
    await user.click(screen.getByLabelText("I accept the Founding Beta Terms (version 1.1)"));
    await user.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/auth/register",
        expect.objectContaining({ beta_home_name: "New Beta Home", beta_terms_version: "1.1" }),
      ),
    );
    expect(push).toHaveBeenCalledWith("/verify-email?beta=1");
  });

  it("requires only global Terms for ordinary signup and keeps notices informational", async () => {
    publicLegalDocuments.mockResolvedValue([termsDocument, betaTermsDocument, ...informationalDocuments]);
    render(<Register />);
    const submit = await screen.findByRole("button", { name: "Create account" });
    expect(screen.getByLabelText("I accept the MyKhaya Terms & Conditions (version 1.0)")).toBeInTheDocument();
    expect(screen.queryByLabelText("I accept the Founding Beta Terms (version 1.1)")).not.toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
    expect(submit).toBeDisabled();
    await userEvent.click(screen.getByLabelText("I accept the MyKhaya Terms & Conditions (version 1.0)"));
    expect(submit).toBeEnabled();
  });
});
