import { afterEach, describe, expect, it, vi } from "vitest";

const { browserOpen } = vi.hoisted(() => ({ browserOpen: vi.fn() }));
vi.mock("@capacitor/browser", () => ({
  Browser: { open: browserOpen },
}));

let nativeShell = false;
vi.mock("./native-runtime", () => ({
  isNativeShell: () => nativeShell,
}));

import { openExternalUrl } from "./open-external-url";

describe("openExternalUrl", () => {
  afterEach(() => {
    nativeShell = false;
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it("uses window.open in an ordinary browser tab, never Browser.open", async () => {
    const windowOpen = vi.fn();
    vi.stubGlobal("window", { open: windowOpen });

    await openExternalUrl("https://example.com/product");

    expect(windowOpen).toHaveBeenCalledWith(
      "https://example.com/product",
      "_blank",
      "noopener,noreferrer",
    );
    expect(browserOpen).not.toHaveBeenCalled();
  });

  it("uses Capacitor Browser.open inside the native shell, never window.open", async () => {
    nativeShell = true;
    const windowOpen = vi.fn();
    vi.stubGlobal("window", { open: windowOpen });

    await openExternalUrl("https://example.com/product");

    expect(browserOpen).toHaveBeenCalledWith({ url: "https://example.com/product" });
    expect(windowOpen).not.toHaveBeenCalled();
  });
});
