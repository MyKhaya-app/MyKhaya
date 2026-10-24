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
