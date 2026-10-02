/**
 * A purely decorative botanical watermark for the green .app-header — see
 * that class in styles.css (background: var(--colour-forest), overflow
 * hidden, rounded bottom corners). Pulled out as its own component (rather
 * than inlined in AppHeader) so any other dark-green hero surface can reuse
 * the exact same treatment later without copying the markup.
 *
 * Deliberately a hand-drawn inline SVG, not an image asset: it needs to
 * render instantly offline in the native iOS shell with no network
 * dependency, and inline SVG currentColor/opacity is the simplest way to
 * keep it a subtle green-on-green watermark rather than a competing visual
 * element. aria-hidden because it carries no information — CSS
 * background art, not content.
 */
export function HeaderBotanical() {
  return (
    <svg
      className="app-header-botanical"
      viewBox="0 0 160 120"
      aria-hidden="true"
      focusable="false"
    >
      <g fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
        <path d="M158 118 C 120 100, 108 76, 118 50" />
        <path d="M118 50 C 100 58, 84 56, 74 40" />
        <path d="M132 76 C 116 80, 104 74, 98 60" />
      </g>
      <g fill="currentColor">
        <ellipse cx="120" cy="48" rx="15" ry="9" transform="rotate(-38 120 48)" opacity="0.9" />
        <ellipse cx="97" cy="59" rx="12" ry="7" transform="rotate(18 97 59)" opacity="0.75" />
        <ellipse cx="133" cy="75" rx="13" ry="7.5" transform="rotate(-8 133 75)" opacity="0.8" />
        <ellipse cx="146" cy="98" rx="16" ry="9" transform="rotate(-32 146 98)" opacity="0.65" />
      </g>
    </svg>
  );
}
