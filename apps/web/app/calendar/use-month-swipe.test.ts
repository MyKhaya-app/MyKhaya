import { describe, expect, it } from "vitest";
import {
  AXIS_LOCK_THRESHOLD_PX,
  classifySwipeAxis,
  COMMIT_DISTANCE_PX,
  COMMIT_VELOCITY_PX_MS,
  shouldCommitSwipe,
} from "./use-month-swipe";

// Pure gesture-classification logic behind the Month view's swipe-to-navigate
// interaction — kept dependency-free (no DOM, no React) so the decision
// rules ("is this a swipe?", "did it commit?") can be tested directly rather
// than only indirectly through simulated pointer events.

describe("classifySwipeAxis", () => {
  it("stays undetermined below the axis-lock threshold in both directions", () => {
    expect(classifySwipeAxis(AXIS_LOCK_THRESHOLD_PX - 1, 0)).toBe("undetermined");
    expect(classifySwipeAxis(0, AXIS_LOCK_THRESHOLD_PX - 1)).toBe("undetermined");
    expect(classifySwipeAxis(2, -3)).toBe("undetermined");
  });

  it("classifies clearly horizontal movement as horizontal", () => {
    expect(classifySwipeAxis(40, 2)).toBe("horizontal");
    expect(classifySwipeAxis(-40, -2)).toBe("horizontal");
  });

  it("classifies clearly vertical movement as vertical", () => {
    expect(classifySwipeAxis(2, 40)).toBe("vertical");
    expect(classifySwipeAxis(-2, -40)).toBe("vertical");
  });

  it("treats a near-diagonal movement as vertical (biased toward scrolling)", () => {
    // Equal-ish horizontal/vertical movement must not be captured as a swipe
    // — a page scroll that drifts slightly sideways should keep scrolling.
    expect(classifySwipeAxis(20, 18)).toBe("vertical");
  });
});

describe("shouldCommitSwipe", () => {
  it("commits once distance alone passes the threshold, regardless of speed", () => {
    expect(shouldCommitSwipe(COMMIT_DISTANCE_PX, 10_000)).toBe(true);
    expect(shouldCommitSwipe(-COMMIT_DISTANCE_PX, 10_000)).toBe(true);
  });

  it("does not commit a short, slow movement", () => {
    expect(shouldCommitSwipe(20, 500)).toBe(false);
  });

  it("commits a fast flick that is fast enough even under the distance threshold", () => {
    const dx = 30; // below COMMIT_DISTANCE_PX
    const elapsed = dx / (COMMIT_VELOCITY_PX_MS + 0.1);
    expect(shouldCommitSwipe(dx, elapsed)).toBe(true);
  });

  it("does not commit a short movement that also isn't fast", () => {
    const dx = 15;
    const elapsed = dx / (COMMIT_VELOCITY_PX_MS - 0.1);
    expect(shouldCommitSwipe(dx, elapsed)).toBe(false);
  });

  it("does not commit a movement below the axis-lock threshold even at implausible speed", () => {
    expect(shouldCommitSwipe(AXIS_LOCK_THRESHOLD_PX - 1, 0.001)).toBe(false);
  });

  it("does not commit with zero or negative elapsed time (no distance threshold met)", () => {
    expect(shouldCommitSwipe(30, 0)).toBe(false);
    expect(shouldCommitSwipe(30, -5)).toBe(false);
  });
});
