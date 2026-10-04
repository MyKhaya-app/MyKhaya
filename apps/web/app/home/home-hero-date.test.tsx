import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HomeHeroDate } from "./home-hero-date";

const native = vi.hoisted(() => ({
  enabled: false,
  listener: undefined as ((state: { isActive: boolean }) => void) | undefined,
  remove: vi.fn(),
}));
vi.mock("@/components/native-runtime", () => ({ isNativeShell: () => native.enabled }));
vi.mock("@capacitor/app", () => ({ App: {
  addListener: vi.fn((_event: string, listener: (state: { isActive: boolean }) => void) => {
    native.listener = listener;
    return Promise.resolve({ remove: native.remove });
  }),
} }));

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(2026, 8, 28, 12));
  native.enabled = false;
  native.listener = undefined;
  native.remove.mockClear();
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("Home hero local date", () => {
  it("renders the requested format without adding layout markup", () => {
    const { container } = render(<HomeHeroDate />);
    expect(container.textContent).toBe("Monday, 28 September");
    expect(container.children).toHaveLength(0);
  });

  it("changes at local midnight without a reload", () => {
    vi.setSystemTime(new Date(2026, 8, 28, 23, 59, 59));
    render(<HomeHeroDate />);
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.getByText("Tuesday, 29 September")).toBeTruthy();
  });

  it.each([new Date(2026, 8, 28, 0, 1), new Date(2026, 8, 28, 23, 59)])(
    "uses the device calendar date near day boundaries (%s)", (date) => {
      vi.setSystemTime(date);
      render(<HomeHeroDate />);
      expect(screen.getByText("Monday, 28 September")).toBeTruthy();
    },
  );

  it.each(["focus", "visibilitychange"])("refreshes after browser %s", (event) => {
    render(<HomeHeroDate />);
    vi.setSystemTime(new Date(2026, 8, 30, 9));
    if (event === "focus") fireEvent(window, new Event(event));
    else fireEvent(document, new Event(event));
    expect(screen.getByText("Wednesday, 30 September")).toBeTruthy();
  });

  it("refreshes on native resume and cleans up its listener and timer", async () => {
    native.enabled = true;
    const { unmount } = render(<HomeHeroDate />);
    vi.setSystemTime(new Date(2027, 0, 1, 9));
    act(() => native.listener?.({ isActive: true }));
    expect(screen.getByText("Friday, 1 January")).toBeTruthy();
    unmount();
    await act(async () => { await Promise.resolve(); });
    expect(native.remove).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });
});
