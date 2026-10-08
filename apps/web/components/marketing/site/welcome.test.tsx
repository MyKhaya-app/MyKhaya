// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import Welcome from "./welcome";

const { apiState, authState, nativeState, replace } = vi.hoisted(() => ({
  apiState: { value: null as unknown },
  authState: { status: "initializing", initialSessionLoading: true },
  nativeState: { value: true },
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
vi.mock("@/components/native-runtime", () => ({ isNativeShell: () => nativeState.value }));
vi.mock("@/components/auth-provider", () => ({
  useAuth: () => ({
    ...authState,
    retryInitialSession: vi.fn(),
    retryLegalStatus: vi.fn(),
    legalStatusError: null,
  }),
}));
vi.mock("@/components/marketing/site/signup-state-context", () => ({
  SignupStateProvider: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/components/maintenance", () => ({ MaintenanceScreen: () => <div>maintenance</div> }));
vi.mock("@/components/legal-gate", () => ({ LegalGate: () => <div>legal gate</div> }));
vi.mock("@/components/native-biometric", () => ({ genericUnlockPromptCopy: () => "device authentication" }));
vi.mock("@mykhaya/api-client", () => ({
  api: { publicSignupState: vi.fn(() => Promise.resolve(apiState.value)) },
}));

const betaState = {
  signup_mode: "beta_only",
  registration_open: true,
  invitation_required: false,
  normal_signup_available: false,
  beta_joining_available: true,
  waitlist_available: false,
  joinable_count: 3,
};

beforeEach(() => {
  vi.clearAllMocks();
  replace.mockReset();
  nativeState.value = true;
  authState.status = "initializing";
  authState.initialSessionLoading = true;
  apiState.value = betaState;
});

const { api } = await import("@mykhaya/api-client");

describe("native root, signed out: always the sign-in screen", () => {
  it("waits for session restoration, then opens /login", async () => {
    const view = render(<Welcome><div>marketing fallback</div></Welcome>);

    expect(screen.getByRole("status")).toHaveTextContent(/checking your mykhaya session/i);
    expect(replace).not.toHaveBeenCalled();

    authState.status = "signed_out";
    authState.initialSessionLoading = false;
    view.rerender(<Welcome><div>marketing fallback</div></Welcome>);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(replace).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["Founding Beta only, Beta open", betaState],
    ["Beta waitlist", { ...betaState, beta_joining_available: false, waitlist_available: true }],
    ["normal signup", { ...betaState, signup_mode: "normal", beta_joining_available: false, normal_signup_available: true }],
    ["mixed", { ...betaState, signup_mode: "mixed" }],
    ["closed registration", { ...betaState, signup_mode: "closed", registration_open: false, beta_joining_available: false }],
  ])("%s: opens /login, never /founding-beta or /register", async (_label, state) => {
    apiState.value = state;
    authState.status = "signed_out";
    authState.initialSessionLoading = false;

    render(<Welcome><div>marketing fallback</div></Welcome>);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(replace).not.toHaveBeenCalledWith("/founding-beta");
    expect(replace).not.toHaveBeenCalledWith("/register");
    // The signup mode no longer chooses the native start screen at all.
    expect(api.publicSignupState).not.toHaveBeenCalled();
  });
});

describe("native root, signed in: unchanged", () => {
  it("restores an authenticated native user into MyKhaya", async () => {
    authState.status = "ready";
    authState.initialSessionLoading = false;

    render(<Welcome><div>marketing fallback</div></Welcome>);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/home"));
    expect(replace).not.toHaveBeenCalledWith("/login");
  });
});

describe("web root: unchanged", () => {
  it.each(["signed_out", "ready"])("renders the marketing homepage and never redirects (%s)", async (status) => {
    nativeState.value = false;
    authState.status = status;
    authState.initialSessionLoading = false;

    render(<Welcome><div>marketing fallback</div></Welcome>);

    expect(await screen.findByText("marketing fallback")).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(replace).not.toHaveBeenCalled();
  });
});
