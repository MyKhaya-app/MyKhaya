// Media queries for the native shell's two rail layouts (see "Native rail
// presentations" in app/styles.css). Only meaningful inside the native shell;
// AppShell applies them behind isNativeShell().

/** Expanded layout: the iPhone Duo unfolded, an iPad. */
export const NATIVE_WIDE_QUERY = "(min-width: 760px)";

/**
 * The iPhone Duo's outer screen: wider than any iPhone in portrait (they top
 * out at 440pt) yet below the expanded breakpoint, and between 450pt and 800pt
 * tall, which excludes phones in landscape (at most 440pt tall) and iPads
 * (iPad mini is 744 x 1133pt).
 */
export const NATIVE_COMPACT_RAIL_QUERY =
  "(min-width: 450px) and (max-width: 759px) and (min-height: 450px) and (max-height: 800px)";

/**
 * Screens tall enough for the right-hand column system (styles.css, "Native
 * right-hand column"): the pill, page tools, floating Add buttons and rail
 * stacked in one column. An iPhone in landscape is wide enough for the
 * expanded layout but at most ~440pt tall, so it never matches and keeps the
 * short-screen rules.
 */
export const NATIVE_RIGHT_COLUMN_QUERY = "(min-height: 521px)";

/**
 * Whether the screen has a right safe-area inset: with the right-hand column,
 * that is where iOS draws the status indicator as a column (both iPhone Duo
 * screens). An iPad, split-view windows included, has none. Read from the
 * shared --safe-right through a probe, since env() is not readable directly.
 */
export function hasRightSafeAreaInset(): boolean {
  const probe = document.createElement("div");
  probe.style.cssText = "position: fixed; visibility: hidden; pointer-events: none; padding-right: var(--safe-right);";
  document.body.appendChild(probe);
  const inset = parseFloat(getComputedStyle(probe).paddingRight) > 0;
  probe.remove();
  return inset;
}
