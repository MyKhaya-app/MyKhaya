// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { NativePublicShell } from "./native-public-shell";

// Public/login safe-area fix: unlike AppShell's `.native-shell` class
// (scoped to AppShell's own mount lifecycle — never present on /login,
// /register, /calendar-shares/accept, etc.), this class is mounted once
// from the root layout and therefore covers every route, public and
// authenticated alike. See app/styles.css's `.native-public-shell` rules.

let nativeShell = false;
vi.mock("./native-runtime", () => ({
  isNativeShell: () => nativeShell,
}));

beforeEach(() => {
  nativeShell = false;
  document.documentElement.classList.remove("native-public-shell");
});

afterEach(() => {
  document.documentElement.classList.remove("native-public-shell");
});

describe("NativePublicShell", () => {
  it("adds html.native-public-shell inside the Capacitor shell", () => {
    nativeShell = true;
    render(<NativePublicShell />);

    expect(document.documentElement.classList.contains("native-public-shell")).toBe(true);
  });

  it("never adds the class in an ordinary browser/PWA tab", () => {
    nativeShell = false;
    render(<NativePublicShell />);

    expect(document.documentElement.classList.contains("native-public-shell")).toBe(false);
  });

  it("removes the class on unmount", () => {
    nativeShell = true;
    const { unmount } = render(<NativePublicShell />);
    expect(document.documentElement.classList.contains("native-public-shell")).toBe(true);

    unmount();

    expect(document.documentElement.classList.contains("native-public-shell")).toBe(false);
  });

  it("renders nothing visible", () => {
    nativeShell = true;
    const { container } = render(<NativePublicShell />);

    expect(container).toBeEmptyDOMElement();
  });
});
