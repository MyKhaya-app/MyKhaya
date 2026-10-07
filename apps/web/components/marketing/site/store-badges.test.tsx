import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { SignupStateValue } from "@/components/public-signup";

// The homepage badges read the PCC app links from the shared signup-state.
const { state, native } = vi.hoisted(() => ({
  state: { value: undefined as SignupStateValue },
  native: { value: false },
}));
vi.mock("./signup-state-context", () => ({ useSignupStateContext: () => state.value }));
vi.mock("@/components/native-runtime", () => ({ isNativeShell: () => native.value }));

const { StoreBadges } = await import("./store-badges");

const base = {
  signup_mode: "normal",
  registration_open: true,
  invitation_required: false,
  normal_signup_available: true,
  beta_joining_available: false,
  waitlist_available: false,
  joinable_count: null,
} as const;

function withLinks(ios: string | null, android: string | null) {
  state.value = { ...base, ios_app_url: ios, android_app_url: android };
}

beforeEach(() => {
  state.value = undefined;
  native.value = false;
});

describe("Homepage StoreBadges (PCC app links)", () => {
  it("shows both badges unlinked, Google Play with its pill, before the links are known", () => {
    render(<StoreBadges />);
    expect(screen.getByAltText("Download on the App Store").closest("a")).toBeNull();
    expect(screen.getByAltText("Get it on Google Play, coming soon").closest("a")).toBeNull();
    expect(screen.getByText("Coming soon")).toBeInTheDocument();
  });

  it("keeps both badges visible but unlinked when the links are empty", () => {
    withLinks(null, null);
    render(<StoreBadges />);
    expect(screen.getByAltText("Download on the App Store").closest("a")).toBeNull();
    expect(screen.getByAltText("Get it on Google Play, coming soon").closest("a")).toBeNull();
  });

  it("links the App Store listing and the Google Play listing", () => {
    withLinks("https://apps.apple.com/gb/app/mykhaya/id1", "https://play.google.com/store/apps/details?id=app.mykhaya");
    render(<StoreBadges />);
    expect(screen.getByAltText("Download on the App Store").closest("a")).toHaveAttribute(
      "href",
      "https://apps.apple.com/gb/app/mykhaya/id1",
    );
    expect(screen.getByAltText("Get it on Google Play").closest("a")).toHaveAttribute(
      "href",
      "https://play.google.com/store/apps/details?id=app.mykhaya",
    );
    expect(screen.queryByText("Coming soon")).not.toBeInTheDocument();
  });

  it("does not link a TestFlight or Play testing link on the homepage", () => {
    withLinks("https://testflight.apple.com/join/AbCdEf12", "https://play.google.com/apps/testing/app.mykhaya");
    render(<StoreBadges />);
    expect(screen.getByAltText("Download on the App Store").closest("a")).toBeNull();
    expect(screen.getByAltText("Get it on Google Play, coming soon").closest("a")).toBeNull();
    expect(screen.queryByText(/Install on iPhone|Get the Android beta/)).not.toBeInTheDocument();
  });

  it("does not link another https Android link on the homepage", () => {
    withLinks(null, "https://downloads.mykhaya.app/android/beta.apk");
    render(<StoreBadges />);
    expect(screen.getByAltText("Get it on Google Play, coming soon").closest("a")).toBeNull();
  });

  it("is hidden inside the native iOS/Android app", () => {
    native.value = true;
    withLinks("https://apps.apple.com/gb/app/mykhaya/id1", null);
    render(<StoreBadges />);
    expect(screen.queryByRole("group", { name: "Get the app" })).not.toBeInTheDocument();
  });
});
