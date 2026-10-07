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
  replace.mockReset();
  nativeState.value = true;
  authState.status = "initializing";
  authState.initialSessionLoading = true;
  apiState.value = betaState;
});

describe("native acquisition entry", () => {
  it("waits for session restoration before evaluating signup mode", async () => {
    const view = render(<Welcome><div>marketing fallback</div></Welcome>);

    expect(screen.getByRole("status")).toHaveTextContent(/checking your mykhaya session/i);
    expect(replace).not.toHaveBeenCalled();

    authState.status = "signed_out";
    authState.initialSessionLoading = false;
    view.rerender(<Welcome><div>marketing fallback</div></Welcome>);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/founding-beta"));
  });

  it("uses the normal native sign-in entry when the server turns Beta off", async () => {
    apiState.value = {
      ...betaState,
      signup_mode: "normal",
      beta_joining_available: false,
    };
    authState.status = "signed_out";
    authState.initialSessionLoading = false;

    render(<Welcome><div>marketing fallback</div></Welcome>);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });

  it.each([
    ["mixed with no Beta places", { ...betaState, signup_mode: "mixed", beta_joining_available: false }, "/login"],
    ["Beta waitlist", { ...betaState, beta_joining_available: false, waitlist_available: true }, "/founding-beta"],
    ["closed registration", { ...betaState, signup_mode: "closed", registration_open: false, beta_joining_available: false, waitlist_available: false }, "/register"],
    ["closed registration with a Beta waitlist", { ...betaState, signup_mode: "closed", registration_open: false, beta_joining_available: false, waitlist_available: true }, "/founding-beta"],
  ])("routes %s from the live server state", async (_label, state, destination) => {
    apiState.value = state;
    authState.status = "signed_out";
    authState.initialSessionLoading = false;

    render(<Welcome><div>marketing fallback</div></Welcome>);

    await waitFor(() => expect(replace).toHaveBeenCalledWith(destination));
  });

  it("restores an authenticated native user into MyKhaya", async () => {
    authState.status = "ready";
    authState.initialSessionLoading = false;

    render(<Welcome><div>marketing fallback</div></Welcome>);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/home"));
  });
});
