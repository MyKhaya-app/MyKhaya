import { beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PublicFoundingBeta } from "./public-founding-beta";

const router = { push: vi.fn(), replace: vi.fn() };
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useSearchParams: () => new URLSearchParams(search),
  usePathname: () => "/founding-beta",
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
    api: { publicSignupState: vi.fn(), publicBetaInvitation: vi.fn(), me: vi.fn() },
  };
});
const { api, ApiError } = await import("@mykhaya/api-client");
const signupState = api.publicSignupState as unknown as ReturnType<typeof vi.fn>;
const me = api.me as unknown as ReturnType<typeof vi.fn>;
const invitationLookup = api.publicBetaInvitation as unknown as ReturnType<typeof vi.fn>;

function state(overrides: Record<string, unknown> = {}) {
  return {
    signup_mode: "beta_only",
    beta_joining_available: true,
    waitlist_available: false,
    joinable_count: 12,
    beta_terms_version: "2026-09",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  search = "";
  native.value = false;
  signupState.mockResolvedValue(state());
});

describe("Founding Beta page", () => {
  it("renders the approved hero, benefits card and terms line", async () => {
    render(<PublicFoundingBeta />);
    expect(screen.getByText("Founding Beta")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Help shape a calmer home." })).toBeInTheDocument();
    expect(screen.getByText("Join a small group of households testing and improving MyKhaya.")).toBeInTheDocument();

    const card = screen.getByRole("region", { name: "What you get" });
    const rows = within(card).getAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      "Complimentary Ultimate for lifeFull access to all features.",
      "No payment card requiredJoin without any payment details.",
      "Limited places while we testA small number of households.",
    ]);

    expect(await screen.findByRole("button", { name: /Join the Beta/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Beta Terms" })).toHaveAttribute("href", "/legal/founding-beta-terms");
    // No consent checkbox here: acceptance stays in registration/enrolment.
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("sends a signed-in visitor to Beta onboarding and a signed-out one to Beta registration", async () => {
    const user = userEvent.setup();
    me.mockResolvedValueOnce({ id: "u1" });
    render(<PublicFoundingBeta />);
    await user.click(await screen.findByRole("button", { name: /Join the Beta/ }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/onboarding?beta=1"));

    me.mockRejectedValueOnce(new ApiError(401, "Not authenticated"));
    await user.click(screen.getByRole("button", { name: /Join the Beta/ }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/register?beta=1"));
  });

  it("carries a Beta invitation through and keeps its reservation notice", async () => {
    search = "invitation=tok-1";
    invitationLookup.mockResolvedValue({ valid: true, expires_at: "2026-10-10T12:00:00Z" });
    signupState.mockResolvedValue(state({ beta_joining_available: false }));
    const user = userEvent.setup();
    me.mockRejectedValueOnce(new ApiError(401, "Not authenticated"));
    render(<PublicFoundingBeta />);
    expect(await screen.findByText(/This place is reserved for you until/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Join the Beta/ }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/register?beta=1&beta_invitation=tok-1"));
  });

  it("offers the waitlist instead when places go to the waitlist first", async () => {
    signupState.mockResolvedValue(state({ beta_joining_available: false, waitlist_available: true }));
    render(<PublicFoundingBeta />);
    expect(await screen.findByRole("link", { name: /Join the waitlist/ })).toHaveAttribute("href", "/waitlist");
    expect(screen.queryByRole("button", { name: /Join the Beta/ })).not.toBeInTheDocument();
  });

  it("says joining is unavailable when neither path is open", async () => {
    signupState.mockResolvedValue(state({ beta_joining_available: false, waitlist_available: false }));
    render(<PublicFoundingBeta />);
    expect(await screen.findByText(/Founding Beta joining is currently unavailable/)).toBeInTheDocument();
  });

  it("sits inside the shared marketing nav and footer, pinned to the light theme", async () => {
    const { container } = render(<PublicFoundingBeta />);
    const scopes = container.querySelectorAll(".mks.mks-scope");
    expect(scopes).toHaveLength(2);
    for (const scope of scopes) expect(scope).toHaveAttribute("data-theme", "light");
    // The page content itself is not inside the marketing scope.
    expect(screen.getByRole("heading", { level: 1 }).closest(".mks")).toBeNull();
    // The nav's sign-up action follows the page's own signup state (Beta).
    const header = screen.getByRole("banner");
    await waitFor(() =>
      expect(within(header).getByRole("link", { name: "Join the Beta" })).toHaveAttribute("href", "/founding-beta"),
    );
    expect(within(screen.getByRole("contentinfo")).getByRole("link", { name: "Support" })).toHaveAttribute("href", "/support");
  });
});

describe("Founding Beta page — invitation-only", () => {
  it("production state (invitation required, places open, no invitation): no Join the Beta, honest unavailable notice", async () => {
    // The API reports no waitlist while places are open, so this is the
    // waitlist-off branch.
    signupState.mockResolvedValue(state({ invitation_required: true, beta_joining_available: true, waitlist_available: false }));
    render(<PublicFoundingBeta />);

    expect(await screen.findByText(/Founding Beta joining is currently unavailable/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Join the Beta/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Founding Beta places are by invitation right now.")).not.toBeInTheDocument();
  });

  it("invitation required with the waitlist open: invitation heading, waitlist copy and a /waitlist button", async () => {
    signupState.mockResolvedValue(state({ invitation_required: true, beta_joining_available: false, waitlist_available: true }));
    render(<PublicFoundingBeta />);

    expect(
      await screen.findByRole("heading", { name: "Founding Beta places are by invitation right now." }),
    ).toBeInTheDocument();
    expect(screen.getByText("Join the waitlist and we’ll let you know when a place opens.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Join the waitlist/ })).toHaveAttribute("href", "/waitlist");
    expect(screen.queryByText(/offered from the waitlist first/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Join the Beta/ })).not.toBeInTheDocument();
  });

  it("invitation required with a valid Beta invitation: Join the Beta is offered", async () => {
    search = "invitation=tok-1";
    invitationLookup.mockResolvedValue({ valid: true, expires_at: "2026-10-10T12:00:00Z" });
    signupState.mockResolvedValue(state({ invitation_required: true, beta_joining_available: true }));
    render(<PublicFoundingBeta />);

    expect(await screen.findByRole("button", { name: /Join the Beta/ })).toBeInTheDocument();
    expect(screen.queryByText(/currently unavailable/)).not.toBeInTheDocument();
  });

  it("invitation required while an invitation link is still being checked: no premature notice", async () => {
    search = "invitation=tok-1";
    invitationLookup.mockReturnValue(new Promise(() => {}));
    signupState.mockResolvedValue(state({ invitation_required: true, beta_joining_available: true }));
    render(<PublicFoundingBeta />);

    await waitFor(() => expect(signupState).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /Join the Beta/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/currently unavailable/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Join the waitlist/ })).not.toBeInTheDocument();
  });

  it("invitation required with an invalid invitation and the waitlist open: the invitation-only waitlist path", async () => {
    search = "invitation=bad";
    invitationLookup.mockResolvedValue({ valid: false, expires_at: null });
    signupState.mockResolvedValue(state({ invitation_required: true, beta_joining_available: false, waitlist_available: true }));
    render(<PublicFoundingBeta />);

    expect(await screen.findByText(/This Beta invitation is invalid/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Founding Beta places are by invitation right now." })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Join the Beta/ })).not.toBeInTheDocument();
  });
});

describe("Founding Beta page — Get the beta app (PCC app links)", () => {
  const TESTFLIGHT = "https://testflight.apple.com/join/AbCdEf12";
  const APP_STORE = "https://apps.apple.com/gb/app/mykhaya/id1234567890";
  const PLAY_TESTING = "https://play.google.com/apps/testing/app.mykhaya";
  const PLAY_LISTING = "https://play.google.com/store/apps/details?id=app.mykhaya";
  const OTHER_ANDROID = "https://downloads.mykhaya.app/android/beta.apk";

  async function block(ios: string | null, android: string | null) {
    signupState.mockResolvedValue(state({ ios_app_url: ios, android_app_url: android }));
    render(<PublicFoundingBeta />);
    return within(await screen.findByRole("region", { name: "Get the beta app" }));
  }

  it("sits under the member/terms lines with its own label and copy", async () => {
    const region = await block(TESTFLIGHT, null);
    expect(region.getByText(/You can join and use MyKhaya from the app too/)).toBeInTheDocument();
    const member = screen.getByText(/Already a member\?/);
    const apps = screen.getByRole("region", { name: "Get the beta app" });
    expect(member.compareDocumentPosition(apps) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("TestFlight: Install on iPhone via TestFlight, with the TestFlight note", async () => {
    const region = await block(TESTFLIGHT, null);
    expect(region.getByRole("link", { name: /Install on iPhone/ })).toHaveAttribute("href", TESTFLIGHT);
    expect(region.getByText("You'll need Apple's free TestFlight app.")).toBeInTheDocument();
    expect(region.queryByAltText("Download on the App Store")).not.toBeInTheDocument();
  });

  it("App Store: the official badge linking to the listing", async () => {
    const region = await block(APP_STORE, null);
    expect(region.getByAltText("Download on the App Store").closest("a")).toHaveAttribute("href", APP_STORE);
    expect(region.queryByText(/TestFlight/)).not.toBeInTheDocument();
  });

  it("Play testing: Get the Android beta", async () => {
    const region = await block(null, PLAY_TESTING);
    expect(region.getByRole("link", { name: "Get the Android beta" })).toHaveAttribute("href", PLAY_TESTING);
  });

  it("Play listing: the official Google Play badge", async () => {
    const region = await block(null, PLAY_LISTING);
    expect(region.getByAltText("Get it on Google Play").closest("a")).toHaveAttribute("href", PLAY_LISTING);
  });

  it("Other https Android link: Get the Android beta", async () => {
    const region = await block(null, OTHER_ANDROID);
    expect(region.getByRole("link", { name: "Get the Android beta" })).toHaveAttribute("href", OTHER_ANDROID);
  });

  it("Empty iPhone link: hidden; empty Android link: Android coming soon placeholder", async () => {
    const region = await block(TESTFLIGHT, null);
    expect(region.getByText("Android coming soon").closest("a")).toBeNull();
    cleanup();
    const iosOnlyEmpty = await block(null, OTHER_ANDROID);
    expect(iosOnlyEmpty.queryByText(/Install on iPhone/)).not.toBeInTheDocument();
    expect(iosOnlyEmpty.queryByAltText("Download on the App Store")).not.toBeInTheDocument();
  });

  it("hides the whole block when both links are empty", async () => {
    signupState.mockResolvedValue(state({ ios_app_url: null, android_app_url: null }));
    render(<PublicFoundingBeta />);
    await waitFor(() => expect(signupState).toHaveBeenCalled());
    await screen.findByRole("button", { name: /Join the Beta/ });
    expect(screen.queryByRole("region", { name: "Get the beta app" })).not.toBeInTheDocument();
  });

  it("hides the block inside the native app", async () => {
    native.value = true;
    signupState.mockResolvedValue(state({ ios_app_url: TESTFLIGHT, android_app_url: PLAY_TESTING }));
    render(<PublicFoundingBeta />);
    await screen.findByRole("button", { name: /Join the Beta/ });
    expect(screen.queryByRole("region", { name: "Get the beta app" })).not.toBeInTheDocument();
  });
});
