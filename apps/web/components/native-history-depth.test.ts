// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest";

// This module patches window.history.pushState as a side effect of being
// imported — re-import fresh in each test (vi.resetModules) so patching is
// exercised from a clean, unpatched history.pushState every time, matching
// how it actually runs once per real app load.
async function freshModule() {
  const mod = await import("./native-history-depth");
  return mod;
}

const originalPushState = window.history.pushState.bind(window.history);

beforeEach(() => {
  window.history.pushState = originalPushState;
});

afterEach(async () => {
  const { vi } = await import("vitest");
  vi.resetModules();
  window.history.pushState = originalPushState;
});

describe("canNavigateBack", () => {
  it("starts false — nothing pushed yet since the app loaded", async () => {
    const { canNavigateBack } = await freshModule();
    expect(canNavigateBack()).toBe(false);
  });

  it("becomes true after a pushState navigation (a <Link>/router.push())", async () => {
    const { canNavigateBack } = await freshModule();

    window.history.pushState({}, "", "/settings");

    expect(canNavigateBack()).toBe(true);
  });

  it("becomes false again after popstate (a Back navigation) undoes the one push", async () => {
    const { canNavigateBack } = await freshModule();

    window.history.pushState({}, "", "/settings");
    expect(canNavigateBack()).toBe(true);

    window.dispatchEvent(new PopStateEvent("popstate"));

    expect(canNavigateBack()).toBe(false);
  });

  it("tracks multiple pushes and pops correctly", async () => {
    const { canNavigateBack } = await freshModule();

    window.history.pushState({}, "", "/a");
    window.history.pushState({}, "", "/b");
    window.history.pushState({}, "", "/c");
    expect(canNavigateBack()).toBe(true);

    window.dispatchEvent(new PopStateEvent("popstate"));
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(canNavigateBack()).toBe(true);

    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(canNavigateBack()).toBe(false);
  });

  it("never goes negative on an unexpected extra popstate", async () => {
    const { canNavigateBack } = await freshModule();

    window.dispatchEvent(new PopStateEvent("popstate"));
    window.dispatchEvent(new PopStateEvent("popstate"));

    expect(canNavigateBack()).toBe(false);

    window.history.pushState({}, "", "/settings");
    expect(canNavigateBack()).toBe(true);
  });

  it("does not count replaceState (redirects) as a Back target", async () => {
    const { canNavigateBack } = await freshModule();

    window.history.replaceState({}, "", "/home");

    expect(canNavigateBack()).toBe(false);
  });

  it("still calls through to the real pushState (navigation itself is unaffected)", async () => {
    await freshModule();

    window.history.pushState({ marker: "x" }, "", "/pushed-path");

    expect(window.location.pathname).toBe("/pushed-path");
    expect(window.history.state).toEqual({ marker: "x" });
  });
});
