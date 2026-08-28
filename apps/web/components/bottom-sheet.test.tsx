// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { BottomSheet } from "./bottom-sheet";

let nativeShell = false;
vi.mock("./native-runtime", () => ({
  isNativeShell: () => nativeShell,
}));

beforeEach(() => {
  nativeShell = false;
  document.body.className = "";
  document.body.removeAttribute("style");
});

afterEach(() => {
  document.body.className = "";
  document.body.removeAttribute("style");
  document.querySelector(".app-content-scroll-region")?.remove();
});

describe("BottomSheet — scroll lock, browser/PWA", () => {
  it("locks document.body (position: fixed) rather than any content region", () => {
    const { unmount } = render(<BottomSheet title="Sheet" onDismiss={vi.fn()} children="x" />);

    expect(document.body.classList.contains("sheet-open")).toBe(true);
    expect(document.body.style.position).toBe("fixed");

    unmount();

    expect(document.body.classList.contains("sheet-open")).toBe(false);
    expect(document.body.style.position).toBe("");
  });
});

describe("BottomSheet — scroll lock, native shell", () => {
  it("locks the .app-content-scroll-region instead of document.body", () => {
    nativeShell = true;
    const region = document.createElement("div");
    region.className = "app-content-scroll-region";
    document.body.appendChild(region);

    const { unmount } = render(<BottomSheet title="Sheet" onDismiss={vi.fn()} children="x" />);

    // body/html never scroll in the native shell (see styles.css), so the
    // browser-only position:fixed body-lock trick must not apply here.
    expect(document.body.style.position).toBe("");
    expect(region.style.overflow).toBe("hidden");

    unmount();

    expect(region.style.overflow).toBe("");
  });

  it("falls back to the browser lock if the scroll region isn't mounted", () => {
    nativeShell = true;
    // No .app-content-scroll-region in the DOM (e.g. a transient auth
    // loading/offline screen that renders no AppShell content) — never
    // crash, just fall back to locking body.
    const { unmount } = render(<BottomSheet title="Sheet" onDismiss={vi.fn()} children="x" />);

    expect(document.body.style.position).toBe("fixed");

    unmount();
  });
});
