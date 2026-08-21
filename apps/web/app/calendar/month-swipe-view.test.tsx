import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render } from "@testing-library/react";
import { MonthSwipeView } from "./month-view";
import { monthCells } from "./calendar-utils";
import { SETTLE_DURATION_MS } from "./use-month-swipe";

// End-to-end coverage for the Month view's swipe-to-navigate gesture,
// exercised through real pointer events against the actual rendered
// component (not just the pure classifier functions in
// use-month-swipe.test.ts) — this is what proves the gesture, the CSS
// transform track, and the commit/snap-back timing actually wire together.

const FOCUS_DATE = new Date(Date.UTC(2026, 5, 15)); // 15 June 2026

function renderSwipeView(overrides: { onNavigate?: ReturnType<typeof vi.fn> } = {}) {
  const onNavigate = overrides.onNavigate ?? vi.fn();
  const onDay = vi.fn();
  const onEvent = vi.fn();
  const { container } = render(
    <MonthSwipeView
      cells={monthCells(FOCUS_DATE)}
      events={[]}
      focusDate={FOCUS_DATE}
      timeZone="UTC"
      onDay={onDay}
      onEvent={onEvent}
      onNavigate={onNavigate}
    />,
  );
  const swipeArea = container.querySelector(".calendar-month-swipe");
  if (!swipeArea) throw new Error("swipe container not rendered");
  return { swipeArea, onNavigate, onDay, onEvent };
}

// jsdom has no PointerEvent constructor (see jsdom#2527), and
// @testing-library's fireEvent.pointer* helpers silently drop
// pointerId/pointerType/clientX/clientY when they fall back to a plain
// Event for an unsupported type — so pointerId.current in the hook would
// never match and every handler would bail out immediately. Building a
// plain Event and assigning the pointer fields directly gives React's
// event system everything it actually reads (it accesses these by name off
// the native event, not via PointerEvent.prototype), without depending on
// a real PointerEvent implementation.
function firePointerEvent(
  element: Element,
  type: "pointerdown" | "pointermove" | "pointerup" | "pointercancel",
  init: { pointerId: number; pointerType: string; clientX: number; clientY: number },
) {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.assign(event, init);
  fireEvent(element, event);
}

function swipe(
  element: Element,
  {
    dx,
    dy = 0,
    steps = 3,
    pointerId = 1,
    pointerType = "touch",
  }: { dx: number; dy?: number; steps?: number; pointerId?: number; pointerType?: string },
) {
  const startX = 200;
  const startY = 200;
  firePointerEvent(element, "pointerdown", { pointerId, pointerType, clientX: startX, clientY: startY });
  for (let step = 1; step <= steps; step += 1) {
    firePointerEvent(element, "pointermove", {
      pointerId,
      pointerType,
      clientX: startX + (dx * step) / steps,
      clientY: startY + (dy * step) / steps,
    });
  }
  firePointerEvent(element, "pointerup", {
    pointerId,
    pointerType,
    clientX: startX + dx,
    clientY: startY + dy,
  });
}

describe("MonthSwipeView — swipe gesture", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("navigates to the next month on a left swipe", () => {
    const { swipeArea, onNavigate } = renderSwipeView();
    swipe(swipeArea, { dx: -100 });
    vi.advanceTimersByTime(SETTLE_DURATION_MS);
    expect(onNavigate).toHaveBeenCalledTimes(1);
    expect(onNavigate).toHaveBeenCalledWith(1);
  });

  it("navigates to the previous month on a right swipe", () => {
    const { swipeArea, onNavigate } = renderSwipeView();
    swipe(swipeArea, { dx: 100 });
    vi.advanceTimersByTime(SETTLE_DURATION_MS);
    expect(onNavigate).toHaveBeenCalledTimes(1);
    expect(onNavigate).toHaveBeenCalledWith(-1);
  });

  it("does not change month for a short, slow horizontal movement", () => {
    const { swipeArea, onNavigate } = renderSwipeView();
    const pointerId = 1;
    firePointerEvent(swipeArea, "pointerdown", { pointerId, pointerType: "touch", clientX: 200, clientY: 200 });
    // Advance real gesture time so this reads as slow, not a fast flick.
    vi.advanceTimersByTime(600);
    firePointerEvent(swipeArea, "pointermove", { pointerId, pointerType: "touch", clientX: 175, clientY: 200 });
    vi.advanceTimersByTime(600);
    firePointerEvent(swipeArea, "pointerup", { pointerId, pointerType: "touch", clientX: 175, clientY: 200 });
    vi.advanceTimersByTime(SETTLE_DURATION_MS);
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("does not change month for a predominantly vertical movement", () => {
    const { swipeArea, onNavigate } = renderSwipeView();
    swipe(swipeArea, { dx: 10, dy: 120 });
    vi.advanceTimersByTime(SETTLE_DURATION_MS);
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("ignores mouse pointer gestures (no odd desktop drag-to-navigate)", () => {
    const { swipeArea, onNavigate } = renderSwipeView();
    swipe(swipeArea, { dx: -150, pointerType: "mouse" });
    vi.advanceTimersByTime(SETTLE_DURATION_MS);
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("cancels cleanly on pointercancel without navigating", () => {
    const { swipeArea, onNavigate } = renderSwipeView();
    const pointerId = 1;
    firePointerEvent(swipeArea, "pointerdown", { pointerId, pointerType: "touch", clientX: 200, clientY: 200 });
    firePointerEvent(swipeArea, "pointermove", { pointerId, pointerType: "touch", clientX: 100, clientY: 200 });
    firePointerEvent(swipeArea, "pointercancel", { pointerId, pointerType: "touch", clientX: 100, clientY: 200 });
    vi.advanceTimersByTime(SETTLE_DURATION_MS);
    expect(onNavigate).not.toHaveBeenCalled();
  });
});

describe("MonthSwipeView — reduced motion", () => {
  const originalMatchMedia = window.matchMedia;

  afterEach(() => {
    window.matchMedia = originalMatchMedia;
  });

  it("still navigates on swipe, immediately and without the animated transition", () => {
    window.matchMedia = ((query: string) => ({
      matches: query.includes("prefers-reduced-motion"),
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;

    const { swipeArea, onNavigate } = renderSwipeView();
    swipe(swipeArea, { dx: -100 });
    // No fake-timer advance: reduced motion must call onNavigate synchronously
    // on release, not after the (skipped) settle animation.
    expect(onNavigate).toHaveBeenCalledTimes(1);
    expect(onNavigate).toHaveBeenCalledWith(1);
  });
});
