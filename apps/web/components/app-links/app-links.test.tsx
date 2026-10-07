import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { androidLinkKind, iosLinkKind } from "./app-link-kind";

const native = vi.hoisted(() => ({ value: false }));
vi.mock("@/components/native-runtime", () => ({ isNativeShell: () => native.value }));

const { AppLinks, hasAnyAppLink } = await import("./app-links");

export const LINKS = {
  testflight: "https://testflight.apple.com/join/AbCdEf12",
  appStore: "https://apps.apple.com/gb/app/mykhaya/id1234567890",
  playTesting: "https://play.google.com/apps/testing/app.mykhaya",
  playListing: "https://play.google.com/store/apps/details?id=app.mykhaya",
  otherAndroid: "https://downloads.mykhaya.app/android/beta.apk",
};

beforeEach(() => {
  native.value = false;
});

describe("link kinds", () => {
  it("classifies iPhone links", () => {
    expect(iosLinkKind(LINKS.testflight)).toBe("testflight");
    expect(iosLinkKind(LINKS.appStore)).toBe("app-store");
    expect(iosLinkKind("")).toBe("none");
    expect(iosLinkKind(null)).toBe("none");
    expect(iosLinkKind("http://apps.apple.com/app/id1")).toBe("none");
    expect(iosLinkKind("https://example.com/app")).toBe("none");
  });

  it("classifies Android links", () => {
    expect(androidLinkKind(LINKS.playTesting)).toBe("play-testing");
    expect(androidLinkKind(LINKS.playListing)).toBe("play-listing");
    expect(androidLinkKind(LINKS.otherAndroid)).toBe("other");
    expect(androidLinkKind("")).toBe("none");
    expect(androidLinkKind("http://play.google.com/store/apps/details?id=x")).toBe("none");
  });

  it("knows when there is nothing to show", () => {
    expect(hasAnyAppLink("", null)).toBe(false);
    expect(hasAnyAppLink(LINKS.testflight, "")).toBe(true);
    expect(hasAnyAppLink(null, LINKS.otherAndroid)).toBe(true);
  });
});

const group = () => screen.getByRole("group");

describe("AppLinks on the Founding Beta page", () => {
  it("TestFlight: custom Install on iPhone button and the TestFlight note, never Apple's badge", () => {
    render(<AppLinks ios={LINKS.testflight} android="" surface="beta" />);
    const button = within(group()).getByRole("link", { name: /Install on iPhone\s*via TestFlight/ });
    expect(button).toHaveAttribute("href", LINKS.testflight);
    expect(button).toHaveAttribute("target", "_blank");
    expect(screen.getByText("You'll need Apple's free TestFlight app.")).toBeInTheDocument();
    expect(screen.queryByAltText("Download on the App Store")).not.toBeInTheDocument();
  });

  it("App Store: Apple's official badge linking to the listing, no TestFlight note", () => {
    render(<AppLinks ios={LINKS.appStore} android="" surface="beta" />);
    const badge = screen.getByAltText("Download on the App Store");
    expect(badge).toHaveAttribute("height", "40");
    expect(badge).toHaveAttribute("src", "/images/marketing/app-store-badge.png");
    expect(badge.closest("a")).toHaveAttribute("href", LINKS.appStore);
    expect(screen.queryByText(/TestFlight/)).not.toBeInTheDocument();
  });

  it("Play testing: custom Get the Android beta button", () => {
    render(<AppLinks ios="" android={LINKS.playTesting} surface="beta" />);
    expect(screen.getByRole("link", { name: "Get the Android beta" })).toHaveAttribute("href", LINKS.playTesting);
    expect(screen.queryByAltText(/Google Play/)).not.toBeInTheDocument();
  });

  it("Play listing: Google's official badge linking to the listing", () => {
    render(<AppLinks ios="" android={LINKS.playListing} surface="beta" />);
    const badge = screen.getByAltText("Get it on Google Play");
    expect(badge).toHaveAttribute("height", "40");
    expect(badge.closest("a")).toHaveAttribute("href", LINKS.playListing);
    expect(screen.queryByText("Coming soon")).not.toBeInTheDocument();
  });

  it("Other https Android link: custom Get the Android beta button", () => {
    render(<AppLinks ios="" android={LINKS.otherAndroid} surface="beta" />);
    expect(screen.getByRole("link", { name: "Get the Android beta" })).toHaveAttribute("href", LINKS.otherAndroid);
  });

  it("Empty: iPhone hidden, Android shows a non-clickable Android coming soon placeholder", () => {
    render(<AppLinks ios="" android="" surface="beta" />);
    expect(within(group()).queryAllByRole("link")).toHaveLength(0);
    expect(screen.queryByAltText(/App Store/)).not.toBeInTheDocument();
    expect(screen.getByText("Android coming soon").closest("a")).toBeNull();
  });

  it("is hidden inside the native app", () => {
    native.value = true;
    render(<AppLinks ios={LINKS.testflight} android={LINKS.playTesting} surface="beta" />);
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });
});

describe("AppLinks on the homepage", () => {
  it("links the App Store badge only for an App Store listing", () => {
    render(<AppLinks ios={LINKS.appStore} android="" surface="homepage" />);
    expect(screen.getByAltText("Download on the App Store").closest("a")).toHaveAttribute("href", LINKS.appStore);
  });

  it.each([
    ["TestFlight", LINKS.testflight],
    ["empty", ""],
  ])("keeps the App Store badge unlinked for a %s iPhone link", (_label, ios) => {
    render(<AppLinks ios={ios} android="" surface="homepage" />);
    expect(screen.getByAltText("Download on the App Store").closest("a")).toBeNull();
    expect(screen.queryByText(/Install on iPhone/)).not.toBeInTheDocument();
  });

  it("links the Google Play badge, without the pill, only for a Play listing", () => {
    render(<AppLinks ios="" android={LINKS.playListing} surface="homepage" />);
    expect(screen.getByAltText("Get it on Google Play").closest("a")).toHaveAttribute("href", LINKS.playListing);
    expect(screen.queryByText("Coming soon")).not.toBeInTheDocument();
  });

  it.each([
    ["Play testing", LINKS.playTesting],
    ["other https", LINKS.otherAndroid],
    ["empty", ""],
  ])("keeps the unlinked Google Play badge with the Coming soon pill for a %s Android link", (_label, android) => {
    render(<AppLinks ios="" android={android} surface="homepage" />);
    const badge = screen.getByAltText("Get it on Google Play, coming soon");
    expect(badge.closest("a")).toBeNull();
    expect(screen.getByText("Coming soon")).toHaveClass("mk-applink-pill");
    expect(screen.queryByText("Get the Android beta")).not.toBeInTheDocument();
  });

  it("is hidden inside the native app", () => {
    native.value = true;
    render(<AppLinks ios={LINKS.appStore} android={LINKS.playListing} surface="homepage" />);
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });
});
