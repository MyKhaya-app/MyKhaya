import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));
vi.mock("./auth-provider", () => ({
  useAuth: () => ({ status: "ready", user: { id: "u1", display_name: "Megan", principal_type: "adult" } }),
}));
const native = vi.hoisted(() => ({ value: false }));
vi.mock("@/components/native-runtime", () => ({ isNativeShell: () => native.value }));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      publicSignupState: vi.fn(),
      betaEligibility: vi.fn(),
      publicLegalDocuments: vi.fn(),
      joinBeta: vi.fn(),
    },
  };
});
const { api } = await import("@mykhaya/api-client");
const { BetaEnrolment } = await import("./beta-enrolment");

const TESTFLIGHT = "https://testflight.apple.com/join/AbCdEf12";
const APP_STORE = "https://apps.apple.com/gb/app/mykhaya/id1234567890";
const PLAY_TESTING = "https://play.google.com/apps/testing/app.mykhaya";
const PLAY_LISTING = "https://play.google.com/store/apps/details?id=app.mykhaya";
const OTHER_ANDROID = "https://downloads.mykhaya.app/android/beta.apk";

function mockLinks(ios: string | null, android: string | null) {
  (api.publicSignupState as ReturnType<typeof vi.fn>).mockResolvedValue({
    signup_mode: "beta_only",
    registration_open: true,
    invitation_required: false,
    normal_signup_available: false,
    beta_joining_available: true,
    waitlist_available: false,
    joinable_count: 5,
    beta_terms_version: "v1",
    ios_app_url: ios,
    android_app_url: android,
  });
}

/** Walk through enrolment to the "Your Home is now in the Founding Beta" card. */
async function enrol() {
  const user = userEvent.setup();
  render(<BetaEnrolment />);
  await user.type(await screen.findByLabelText("Home name"), "Hales Home");
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "Create Beta Home" }));
  await screen.findByRole("heading", { name: "Your Home is now in the Founding Beta" });
}

const step = () => screen.queryByRole("region", { name: "Next: get MyKhaya on your phone" });

beforeEach(() => {
  vi.clearAllMocks();
  native.value = false;
  (api.betaEligibility as ReturnType<typeof vi.fn>).mockResolvedValue({ eligible: true, home_id: null, home_name: null, reason: null });
  (api.publicLegalDocuments as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (api.joinBeta as ReturnType<typeof vi.fn>).mockResolvedValue({ home_id: "h1", entitlement_source: "founding_beta" });
});

describe("Founding Beta confirmation: get the app step", () => {
  it("shows the heading, one line of copy and the TestFlight button with its note", async () => {
    mockLinks(TESTFLIGHT, null);
    await enrol();
    const region = within(step()!);
    expect(region.getByText(/Install the app and sign in with this account/)).toBeInTheDocument();
    expect(region.getByRole("link", { name: /Install on iPhone/ })).toHaveAttribute("href", TESTFLIGHT);
    expect(region.getByText("You'll need Apple's free TestFlight app.")).toBeInTheDocument();
    // Empty Android link: the muted placeholder, not a link.
    expect(region.getByText("Android coming soon").closest("a")).toBeNull();
    // The way back home stays after the step.
    expect(screen.getByRole("link", { name: "Return home" })).toHaveAttribute("href", "/home");
  });

  it("App Store link: the official badge, linked", async () => {
    mockLinks(APP_STORE, null);
    await enrol();
    expect(within(step()!).getByAltText("Download on the App Store").closest("a")).toHaveAttribute("href", APP_STORE);
  });

  it("Play testing link: Get the Android beta", async () => {
    mockLinks(null, PLAY_TESTING);
    await enrol();
    const region = within(step()!);
    expect(region.getByRole("link", { name: "Get the Android beta" })).toHaveAttribute("href", PLAY_TESTING);
    // Empty iPhone link: nothing for iPhone.
    expect(region.queryByText(/Install on iPhone/)).not.toBeInTheDocument();
    expect(region.queryByAltText("Download on the App Store")).not.toBeInTheDocument();
  });

  it("Play listing: the official Google Play badge", async () => {
    mockLinks(null, PLAY_LISTING);
    await enrol();
    expect(within(step()!).getByAltText("Get it on Google Play").closest("a")).toHaveAttribute("href", PLAY_LISTING);
  });

  it("Other https Android link: Get the Android beta", async () => {
    mockLinks(null, OTHER_ANDROID);
    await enrol();
    expect(within(step()!).getByRole("link", { name: "Get the Android beta" })).toHaveAttribute("href", OTHER_ANDROID);
  });

  it("is hidden when both links are empty", async () => {
    mockLinks(null, null);
    await enrol();
    expect(step()).not.toBeInTheDocument();
  });

  it("is hidden when the card is shown inside the native app", async () => {
    native.value = true;
    mockLinks(TESTFLIGHT, PLAY_TESTING);
    await enrol();
    expect(step()).not.toBeInTheDocument();
  });
});
