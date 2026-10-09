import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const replace = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));
vi.mock("./auth-provider", () => ({
  useAuth: () => ({
    status: "ready",
    user: { id: "u1", display_name: "Megan", principal_type: "adult" },
    refreshSession: vi.fn().mockResolvedValue(true),
  }),
}));
const refreshHomes = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({ refreshHomes }),
}));
const native = vi.hoisted(() => ({ value: false }));
vi.mock("@/components/native-runtime", () => ({
  isNativeShell: () => native.value,
  nativePlatform: () => (native.value ? "ios" : "web"),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      publicSignupState: vi.fn(),
      betaContinuation: vi.fn(),
      acceptLegalDocument: vi.fn(),
      joinBeta: vi.fn(),
      createCheckoutSession: vi.fn(),
      familyPricing: vi.fn(),
    },
  };
});
const { api, ApiError } = await import("@mykhaya/api-client");
const { BetaEnrolment } = await import("./beta-enrolment");
const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

const TESTFLIGHT = "https://testflight.apple.com/join/AbCdEf12";
const APP_STORE = "https://apps.apple.com/gb/app/mykhaya/id1234567890";
const PLAY_TESTING = "https://play.google.com/apps/testing/app.mykhaya";
const PLAY_LISTING = "https://play.google.com/store/apps/details?id=app.mykhaya";
const OTHER_ANDROID = "https://downloads.mykhaya.app/android/beta.apk";

const TERMS = {
  document_key: "founding_beta_terms",
  display_name: "Founding Beta Terms",
  version_id: "beta-v11",
  version: "1.1",
  satisfied: false,
};

function continuationState(overrides: Record<string, unknown> = {}) {
  return {
    pending: true,
    enrolled: false,
    enrolled_home_id: null,
    terms: TERMS,
    eligible: true,
    home_id: null,
    home_name: null,
    reason: null,
    ...overrides,
  };
}

function signupState(ios: string | null = null, android: string | null = null) {
  return {
    signup_mode: "beta_only",
    registration_open: true,
    invitation_required: false,
    normal_signup_available: false,
    beta_joining_available: true,
    waitlist_available: false,
    joinable_count: 5,
    beta_terms_version: "1.1",
    ios_app_url: ios,
    android_app_url: android,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  replace.mockReset();
  native.value = false;
  mock(api.publicSignupState).mockResolvedValue(signupState());
  mock(api.betaContinuation).mockResolvedValue(continuationState());
  mock(api.acceptLegalDocument).mockResolvedValue({});
  mock(api.joinBeta).mockResolvedValue({ home_id: "h1", entitlement_source: "founding_beta_lifetime" });
});

/** welcome + Terms -> Home -> confirm -> done, for a brand-new Beta account. */
async function completeNewUserJourney() {
  const user = userEvent.setup();
  render(<BetaEnrolment />);
  await screen.findByRole("heading", { name: "Welcome to the MyKhaya Founding Beta" });
  await user.click(screen.getByRole("checkbox", { name: /I accept the Founding Beta Terms/ }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.type(await screen.findByLabelText("Home name"), "Hales Home");
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(await screen.findByRole("button", { name: "Join the Founding Beta" }));
  await screen.findByRole("heading", { name: "Your Home is now in the Founding Beta" });
  return user;
}

describe("Founding Beta continuation", () => {
  it("welcomes the verified user and requires the current Founding Beta Terms first", async () => {
    render(<BetaEnrolment />);
    expect(await screen.findByText("Founding Beta")).toBeInTheDocument();
    expect(screen.getByText("You’re almost there.")).toBeInTheDocument();
    expect(screen.getByText(/complimentary access to MyKhaya Ultimate for the\s+lifetime of the Home/)).toBeInTheDocument();
    expect(screen.getByText("No subscription or payment details are required.")).toBeInTheDocument();
    const terms = screen.getByRole("checkbox", { name: /I accept the Founding Beta Terms \(version 1\.1\)/ });
    expect(terms).not.toBeChecked();
    expect(screen.getByRole("link", { name: "Founding Beta Terms" })).toHaveAttribute("href", "/legal/founding-beta-terms");
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    // No Home question before the Terms.
    expect(screen.queryByLabelText("Home name")).not.toBeInTheDocument();
  });

  it("records the Terms acceptance (beta_enrolment context), then asks for the Home name", async () => {
    const user = userEvent.setup();
    render(<BetaEnrolment />);
    await user.click(await screen.findByRole("checkbox", { name: /I accept the Founding Beta Terms/ }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(api.acceptLegalDocument).toHaveBeenCalledWith({
      document_key: "founding_beta_terms",
      document_version_id: "beta-v11",
      context: "beta_enrolment",
      platform: "web",
    });
    expect(await screen.findByRole("heading", { name: "Create your Home" })).toBeInTheDocument();
    expect(screen.getByText("This Home will receive complimentary MyKhaya Ultimate access as part of the Founding Beta.")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("confirms Home, plan, cost and payment, then joins without asking for the Terms again", async () => {
    await completeNewUserJourney();
    expect(api.acceptLegalDocument).toHaveBeenCalledTimes(1);
    expect(api.joinBeta).toHaveBeenCalledWith({ home_name: "Hales Home", terms_version: undefined, invitation_token: undefined });
    expect(refreshHomes).toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Enter MyKhaya" })).toHaveAttribute("href", "/home");
  });

  it("shows a simple confirmation summary before joining", async () => {
    const user = userEvent.setup();
    render(<BetaEnrolment />);
    await user.click(await screen.findByRole("checkbox", { name: /I accept/ }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.type(await screen.findByLabelText("Home name"), "Hales Home");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("You’re joining the MyKhaya Founding Beta.")).toBeInTheDocument();
    const summary: Record<string, string> = Object.fromEntries(
      [...document.querySelectorAll(".beta-summary > div")].map((row): [string, string] => [
        row.querySelector("dt")!.textContent ?? "",
        row.querySelector("dd")!.textContent ?? "",
      ]),
    );
    expect(summary).toEqual({ Home: "Hales Home", Plan: "Ultimate", Cost: "Complimentary", "Payment required": "No" });
  });

  it("keeps Beta completion active until the refreshed Home state resolves", async () => {
    let resolveHomes!: () => void;
    refreshHomes.mockReturnValueOnce(new Promise<void>((resolve) => { resolveHomes = resolve; }));
    const user = userEvent.setup();
    render(<BetaEnrolment />);
    await user.click(await screen.findByRole("checkbox", { name: /I accept/ }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.type(await screen.findByLabelText("Home name"), "Hales Home");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(await screen.findByRole("button", { name: "Join the Founding Beta" }));
    await waitFor(() => expect(api.joinBeta).toHaveBeenCalled());

    expect(screen.queryByRole("heading", { name: "Your Home is now in the Founding Beta" })).not.toBeInTheDocument();
    expect(screen.queryByText("How would you like to use MyKhaya?")).not.toBeInTheDocument();

    resolveHomes();
    expect(await screen.findByRole("heading", { name: "Your Home is now in the Founding Beta" })).toBeInTheDocument();
    expect(replace).toHaveBeenCalledWith("/home");
  });

  it("never shows plans, prices or payment, and never starts Stripe checkout", async () => {
    await completeNewUserJourney();
    expect(api.createCheckoutSession).not.toHaveBeenCalled();
    expect(api.familyPricing).not.toHaveBeenCalled();
    expect(screen.queryByText(/Choose your MyKhaya plan|Monthly|Annual|£/)).not.toBeInTheDocument();
  });

  it("does not ask again for Beta Terms the user has already accepted (same version)", async () => {
    mock(api.betaContinuation).mockResolvedValue(continuationState({ terms: { ...TERMS, satisfied: true } }));
    const user = userEvent.setup();
    render(<BetaEnrolment />);
    expect(await screen.findByText(/already accepted the current Founding Beta Terms \(version 1\.1\)/)).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(api.acceptLegalDocument).not.toHaveBeenCalled();
    expect(await screen.findByLabelText("Home name")).toBeInTheDocument();
  });

  it("asks once for a new Beta Terms version (old acceptance no longer satisfies it)", async () => {
    mock(api.betaContinuation).mockResolvedValue(
      continuationState({ terms: { ...TERMS, version: "1.2", version_id: "beta-v12", satisfied: false } }),
    );
    render(<BetaEnrolment />);
    expect(await screen.findByRole("checkbox", { name: /version 1\.2/ })).toBeInTheDocument();
  });

  it("goes back to the Terms step if the Beta Terms changed before joining", async () => {
    mock(api.joinBeta).mockRejectedValueOnce(
      new ApiError(409, "Please accept the current Founding Beta Terms to continue.", "beta_terms_required"),
    );
    const user = userEvent.setup();
    render(<BetaEnrolment />);
    await user.click(await screen.findByRole("checkbox", { name: /I accept/ }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.type(await screen.findByLabelText("Home name"), "Hales Home");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    mock(api.betaContinuation).mockResolvedValue(
      continuationState({ terms: { ...TERMS, version: "1.2", version_id: "beta-v12", satisfied: false } }),
    );
    await user.click(await screen.findByRole("button", { name: "Join the Founding Beta" }));
    expect(await screen.findByRole("checkbox", { name: /version 1\.2/ })).toBeInTheDocument();
    expect(screen.getByText("Please accept the current Founding Beta Terms to continue.")).toBeInTheDocument();
  });

  it("enrols an existing Free Home as it is: no new Home, no Home name", async () => {
    mock(api.betaContinuation).mockResolvedValue(
      continuationState({ pending: false, home_id: "home-1", home_name: "Existing Home" }),
    );
    const user = userEvent.setup();
    render(<BetaEnrolment />);
    await user.click(await screen.findByRole("checkbox", { name: /I accept/ }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText(/Your existing Home stays exactly as it is/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Home name")).not.toBeInTheDocument();
    expect(document.querySelector(".beta-summary")).toHaveTextContent("Existing Home");
    await user.click(screen.getByRole("button", { name: "Join the Founding Beta" }));
    await waitFor(() => expect(api.joinBeta).toHaveBeenCalledWith({ home_name: undefined, terms_version: undefined, invitation_token: undefined }));
  });

  it("an existing user with no Home creates a Beta Home", async () => {
    mock(api.betaContinuation).mockResolvedValue(continuationState({ pending: false }));
    await completeNewUserJourney();
    expect(api.joinBeta).toHaveBeenCalledWith(expect.objectContaining({ home_name: "Hales Home" }));
  });

  it("keeps a paid Home out: an ineligible state, nothing submitted", async () => {
    mock(api.betaContinuation).mockResolvedValue(
      continuationState({
        pending: false,
        eligible: false,
        home_id: "home-1",
        home_name: "Paid Home",
        reason: "A paid Home cannot be enrolled through the Founding Beta.",
      }),
    );
    render(<BetaEnrolment />);
    expect(await screen.findByRole("heading", { name: "Your Home already has a paid plan" })).toBeInTheDocument();
    expect(screen.getByText(/subscription is unchanged/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Join the Founding Beta|Continue/ })).not.toBeInTheDocument();
    expect(api.joinBeta).not.toHaveBeenCalled();
  });

  it("an already-enrolled user just goes into MyKhaya", async () => {
    mock(api.betaContinuation).mockResolvedValue(continuationState({ pending: false, enrolled: true, enrolled_home_id: "h1" }));
    render(<BetaEnrolment />);
    expect(await screen.findByRole("heading", { name: "Your Home is already in the Founding Beta" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Enter MyKhaya" })).toHaveAttribute("href", "/home");
  });

  it("shows the server's user-facing reason when joining fails (e.g. Beta full)", async () => {
    mock(api.joinBeta).mockRejectedValueOnce(new ApiError(409, "The Founding Beta is currently full."));
    const user = userEvent.setup();
    render(<BetaEnrolment />);
    await user.click(await screen.findByRole("checkbox", { name: /I accept/ }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.type(await screen.findByLabelText("Home name"), "Hales Home");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(await screen.findByRole("button", { name: "Join the Founding Beta" }));
    expect(await screen.findByText("The Founding Beta is currently full.")).toBeInTheDocument();
  });
});

describe("Founding Beta confirmation: get the app step", () => {
  const step = () => screen.queryByRole("region", { name: "Next: get MyKhaya on your phone" });

  it("shows the heading, one line of copy and the TestFlight button with its note", async () => {
    mock(api.publicSignupState).mockResolvedValue(signupState(TESTFLIGHT, null));
    await completeNewUserJourney();
    const region = within(step()!);
    expect(region.getByText(/Install the app and sign in with this account/)).toBeInTheDocument();
    expect(region.getByRole("link", { name: /Install on iPhone/ })).toHaveAttribute("href", TESTFLIGHT);
    expect(region.getByText("You'll need Apple's free TestFlight app.")).toBeInTheDocument();
    expect(region.getByText("Android coming soon").closest("a")).toBeNull();
  });

  it("App Store link: the official badge, linked", async () => {
    mock(api.publicSignupState).mockResolvedValue(signupState(APP_STORE, null));
    await completeNewUserJourney();
    expect(within(step()!).getByAltText("Download on the App Store").closest("a")).toHaveAttribute("href", APP_STORE);
  });

  it("Play testing link: Get the Android beta", async () => {
    mock(api.publicSignupState).mockResolvedValue(signupState(null, PLAY_TESTING));
    await completeNewUserJourney();
    const region = within(step()!);
    expect(region.getByRole("link", { name: "Get the Android beta" })).toHaveAttribute("href", PLAY_TESTING);
    expect(region.queryByAltText("Download on the App Store")).not.toBeInTheDocument();
  });

  it("Play listing: the official Google Play badge", async () => {
    mock(api.publicSignupState).mockResolvedValue(signupState(null, PLAY_LISTING));
    await completeNewUserJourney();
    expect(within(step()!).getByAltText("Get it on Google Play").closest("a")).toHaveAttribute("href", PLAY_LISTING);
  });

  it("Other https Android link: Get the Android beta", async () => {
    mock(api.publicSignupState).mockResolvedValue(signupState(null, OTHER_ANDROID));
    await completeNewUserJourney();
    expect(within(step()!).getByRole("link", { name: "Get the Android beta" })).toHaveAttribute("href", OTHER_ANDROID);
  });

  it("is hidden when both links are empty", async () => {
    await completeNewUserJourney();
    expect(step()).not.toBeInTheDocument();
  });

  it("is hidden when the card is shown inside the native app", async () => {
    native.value = true;
    mock(api.publicSignupState).mockResolvedValue(signupState(TESTFLIGHT, PLAY_TESTING));
    await completeNewUserJourney();
    expect(step()).not.toBeInTheDocument();
  });
});
