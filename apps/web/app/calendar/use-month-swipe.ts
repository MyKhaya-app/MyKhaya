"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

/** Whether the user has requested reduced motion, kept live across changes
 *  (e.g. a system setting toggled mid-session) rather than read once. */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof window !== "undefined" && window.matchMedia(REDUCED_MOTION_QUERY).matches,
  );
  useEffect(() => {
    if (typeof window === "undefined") return;
    const query = window.matchMedia(REDUCED_MOTION_QUERY);
    const listener = () => setReduced(query.matches);
    query.addEventListener("change", listener);
    return () => query.removeEventListener("change", listener);
  }, []);
  return reduced;
}

// Gesture classification for the Month view's swipe-to-navigate interaction.
// Split out as plain, DOM-free functions so the "is this a swipe?" decision
// can be unit-tested directly, without mounting the calendar grid or faking
// pointer events.

export type SwipeAxis = "undetermined" | "horizontal" | "vertical";

// Below this many px of total movement we can't yet tell whether the finger
// is scrolling or swiping — keeps a stationary/jittery touch from being
// classified at all.
export const AXIS_LOCK_THRESHOLD_PX = 10;

// Horizontal movement must clearly outpace vertical before a gesture is
// treated as a swipe (rather than a diagonal scroll) — biased toward
// "vertical" so page scrolling is never accidentally hijacked.
const HORIZONTAL_BIAS = 1.2;

export function classifySwipeAxis(dx: number, dy: number): SwipeAxis {
  const absDx = Math.abs(dx);
  const absDy = Math.abs(dy);
  if (absDx < AXIS_LOCK_THRESHOLD_PX && absDy < AXIS_LOCK_THRESHOLD_PX) return "undetermined";
  return absDx > absDy * HORIZONTAL_BIAS ? "horizontal" : "vertical";
}

// A swipe commits either by travelling far enough...
export const COMMIT_DISTANCE_PX = 60;
// ...or, for a fast flick that never travels that far, by being fast enough.
export const COMMIT_VELOCITY_PX_MS = 0.5;

export function shouldCommitSwipe(dx: number, elapsedMs: number): boolean {
  const absDx = Math.abs(dx);
  if (absDx >= COMMIT_DISTANCE_PX) return true;
  if (absDx < AXIS_LOCK_THRESHOLD_PX || elapsedMs <= 0) return false;
  return absDx / elapsedMs >= COMMIT_VELOCITY_PX_MS;
}

// How long the "complete the transition" / "snap back" animation takes —
// kept in sync with the inline transition-duration applied to the track.
export const SETTLE_DURATION_MS = 220;

type Phase = "idle" | "pending" | "horizontal" | "vertical";

/**
 * Drives the Month view's swipe-to-navigate track. Owns pointer tracking and
 * the track's CSS transform directly (imperative style writes, not React
 * state) so a drag can follow the finger at 60fps without re-rendering the
 * whole month grid on every pointermove — the grid itself only re-renders
 * once, when `onSwipeLeft`/`onSwipeRight` actually change the focused month.
 *
 * Deliberately touch/pen only: mouse pointerdown is ignored so desktop
 * click-and-drag behaves exactly as it did before (see requirement to avoid
 * "odd mouse-drag behaviour" — trackpad horizontal scroll, where a browser
 * already turns it into a native gesture, is unaffected either way since
 * this hook never intercepts wheel/scroll events).
 */
export function useMonthSwipe({
  onSwipeLeft,
  onSwipeRight,
  disabled = false,
  reducedMotion = false,
}: {
  onSwipeLeft: () => void;
  onSwipeRight: () => void;
  disabled?: boolean;
  reducedMotion?: boolean;
}) {
  const trackRef = useRef<HTMLDivElement | null>(null);
  const phase = useRef<Phase>("idle");
  const pointerId = useRef<number | null>(null);
  const start = useRef({ x: 0, y: 0, time: 0 });
  const lastX = useRef(0);
  const settling = useRef(false);
  const settleTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const restingTransform = "translateX(-33.3333%)";

  const applyTransform = useCallback((value: string, animate: boolean) => {
    const track = trackRef.current;
    if (!track) return;
    track.style.transition = animate ? `transform ${SETTLE_DURATION_MS}ms ease` : "none";
    track.style.transform = value;
  }, []);

  const resetToRest = useCallback(
    (animate: boolean) => {
      applyTransform(restingTransform, animate);
    },
    [applyTransform],
  );

  // Mount-only: sets the track's initial resting position and tears down
  // any in-flight settle timeout on unmount. Deliberately does not
  // re-run when resetToRest's identity changes (it never meaningfully
  // does — applyTransform only closes over the stable trackRef).
  useEffect(() => {
    resetToRest(false);
    return () => {
      if (settleTimeout.current) clearTimeout(settleTimeout.current);
    };
  }, [resetToRest]);

  const endGesture = useCallback(
    (canceled: boolean) => {
      const currentPhase = phase.current;
      phase.current = "idle";
      pointerId.current = null;
      if (currentPhase !== "horizontal") return;

      const dx = canceled ? 0 : lastX.current - start.current.x;
      const elapsed = performance.now() - start.current.time;
      const commit = !canceled && shouldCommitSwipe(dx, elapsed);

      if (reducedMotion) {
        resetToRest(false);
        if (commit) (dx < 0 ? onSwipeLeft : onSwipeRight)();
        return;
      }

      if (!commit) {
        resetToRest(true);
        return;
      }

      settling.current = true;
      // Slide the rest of the way off-screen in the swipe's direction, then
      // swap the month underneath and snap back to centre — the same
      // "complete the transition" motion a native calendar app uses.
      applyTransform(dx < 0 ? "translateX(-66.6667%)" : "translateX(0%)", true);
      settleTimeout.current = setTimeout(() => {
        (dx < 0 ? onSwipeLeft : onSwipeRight)();
        resetToRest(false);
        settling.current = false;
      }, SETTLE_DURATION_MS);
    },
    [applyTransform, onSwipeLeft, onSwipeRight, reducedMotion, resetToRest],
  );

  const onPointerDown = useCallback(
    (event: React.PointerEvent) => {
      if (disabled || settling.current) return;
      if (event.pointerType === "mouse") return;
      phase.current = "pending";
      pointerId.current = event.pointerId;
      start.current = { x: event.clientX, y: event.clientY, time: performance.now() };
      lastX.current = event.clientX;
      try {
        event.currentTarget.setPointerCapture(event.pointerId);
      } catch {
        // Pointer capture is a nice-to-have (keeps the gesture tracking even
        // if the finger leaves the element) — unsupported environments
        // (some browsers, jsdom in tests) just fall back to plain bubbling.
      }
    },
    [disabled],
  );

  const onPointerMove = useCallback(
    (event: React.PointerEvent) => {
      if (pointerId.current !== event.pointerId) return;
      if (phase.current === "idle" || phase.current === "vertical") return;

      const dx = event.clientX - start.current.x;
      const dy = event.clientY - start.current.y;

      if (phase.current === "pending") {
        const axis = classifySwipeAxis(dx, dy);
        if (axis === "undetermined") return;
        phase.current = axis;
        if (axis === "vertical") return; // Let the browser's native pan-y scroll take over.
      }

      // Only reachable once phase is "horizontal": clearly a swipe, so it's
      // now safe to suppress whatever native gesture the browser might
      // otherwise start (e.g. edge-swipe navigation) without having taken
      // over anything during the undetermined/vertical phases above.
      if (event.cancelable) event.preventDefault();
      lastX.current = event.clientX;
      if (!reducedMotion) applyTransform(`calc(-33.3333% + ${dx}px)`, false);
    },
    [applyTransform, reducedMotion],
  );

  const onPointerUp = useCallback(
    (event: React.PointerEvent) => {
      if (pointerId.current !== event.pointerId) return;
      endGesture(false);
    },
    [endGesture],
  );

  const onPointerCancel = useCallback(
    (event: React.PointerEvent) => {
      if (pointerId.current !== event.pointerId) return;
      endGesture(true);
    },
    [endGesture],
  );

  return {
    trackRef,
    containerHandlers: { onPointerDown, onPointerMove, onPointerUp, onPointerCancel },
  };
}
