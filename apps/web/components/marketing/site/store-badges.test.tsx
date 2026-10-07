import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const { links, native } = vi.hoisted(() => ({
  links: { APP_STORE_URL: "", GOOGLE_PLAY_URL: "" },
  native: { value: false },
}));
vi.mock("./site-links", () => ({
  get APP_STORE_URL() {
    return links.APP_STORE_URL;
  },
  get GOOGLE_PLAY_URL() {
    return links.GOOGLE_PLAY_URL;
  },
}));
vi.mock("@/components/native-runtime", () => ({ isNativeShell: () => native.value }));

const { StoreBadges } = await import("./store-badges");

beforeEach(() => {
  links.APP_STORE_URL = "";
  links.GOOGLE_PLAY_URL = "";
  native.value = false;
});

describe("StoreBadges", () => {
  it("shows both badges as plain artwork, with a Coming soon pill on Google Play, while no URLs are set", () => {
    render(<StoreBadges />);
    expect(screen.getByAltText("Download on the App Store").closest("a")).toBeNull();
    expect(screen.getByAltText("Get it on Google Play, coming soon").closest("a")).toBeNull();
    expect(screen.getAllByText("Coming soon")).toHaveLength(1);
  });

  it("links each badge to its listing once the URL is set, and drops the Google Play pill", () => {
    links.APP_STORE_URL = "https://apps.apple.com/app/id1";
    links.GOOGLE_PLAY_URL = "https://play.google.com/store/apps/details?id=app.mykhaya";
    render(<StoreBadges />);
    expect(screen.getByAltText("Download on the App Store").closest("a")).toHaveAttribute("href", links.APP_STORE_URL);
    expect(screen.getByAltText("Get it on Google Play").closest("a")).toHaveAttribute("href", links.GOOGLE_PLAY_URL);
    expect(screen.queryByText("Coming soon")).not.toBeInTheDocument();
  });

  it("is hidden inside the native iOS/Android app", () => {
    native.value = true;
    render(<StoreBadges />);
    expect(screen.queryByRole("group", { name: "Get the app" })).not.toBeInTheDocument();
  });
});
