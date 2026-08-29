"use client";

import { useCallback, useRef } from "react";
import {
  classifySwipeAxis,
  COMMIT_DISTANCE_PX,
} from "../calendar/use-month-swipe";

type Phase = "idle" | "pending" | "horizontal" | "vertical";

/** Pointer gesture for the rendered Day content surface. Vertical movement is
 * deliberately left to the native scroll region; only a clearly horizontal
 * gesture is prevented and converted into one day of navigation. */
export function useDaySwipe({
  onSwipeLeft,
  onSwipeRight,
  disabled = false,
}: {
  onSwipeLeft: () => void;
  onSwipeRight: () => void;
  disabled?: boolean;
}) {
  const phase = useRef<Phase>("idle");
  const pointerId = useRef<number | null>(null);
  const start = useRef({ x: 0, y: 0 });
  const lastX = useRef(0);

  const finish = useCallback(
    (canceled: boolean) => {
      const currentPhase = phase.current;
      const dx = lastX.current - start.current.x;
      phase.current = "idle";
      pointerId.current = null;
      if (canceled || currentPhase !== "horizontal") return;
      // Day navigation deliberately requires a meaningful travel distance.
      // Unlike Calendar's month flick, a short Meal Plans movement must never
      // change the selected date while the user is trying to scroll.
      if (Math.abs(dx) < COMMIT_DISTANCE_PX) return;
      if (dx < 0) onSwipeLeft();
      else onSwipeRight();
    },
    [onSwipeLeft, onSwipeRight],
  );

  const onPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (disabled || event.pointerType === "mouse") return;
      phase.current = "pending";
      pointerId.current = event.pointerId;
      start.current = { x: event.clientX, y: event.clientY };
      lastX.current = event.clientX;
      try {
        event.currentTarget.setPointerCapture(event.pointerId);
      } catch {
        // Pointer capture is unavailable in some test/webview environments.
      }
    },
    [disabled],
  );

  const onPointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (pointerId.current !== event.pointerId) return;
      if (phase.current === "idle" || phase.current === "vertical") return;
      const dx = event.clientX - start.current.x;
      const dy = event.clientY - start.current.y;
      if (phase.current === "pending") {
        const axis = classifySwipeAxis(dx, dy);
        if (axis === "undetermined") return;
        phase.current = axis;
        if (axis === "vertical") return;
      }
      if (event.cancelable) event.preventDefault();
      lastX.current = event.clientX;
    },
    [],
  );

  const onPointerUp = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (pointerId.current === event.pointerId) finish(false);
    },
    [finish],
  );

  const onPointerCancel = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (pointerId.current === event.pointerId) finish(true);
    },
    [finish],
  );

  return { onPointerDown, onPointerMove, onPointerUp, onPointerCancel };
}
