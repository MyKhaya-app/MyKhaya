/**
 * A small decorative flower/leaf illustration for a green hero band (see
 * .more-hero in styles.css — the "More" screen's header, and any future
 * hero that wants the same treatment; kept generic rather than named after
 * one page). Muted green leaves, a simple white flower, a small warm
 * yellow centre — distinct from HeaderBotanical (header-botanical.tsx),
 * which is a near-invisible green-on-green watermark for the standard
 * .app-header; this one is meant to actually read as a small illustration,
 * just placed and sized so it never competes with the heading or avatar.
 *
 * Inline SVG, not an image asset — renders instantly offline in the native
 * iOS shell with no network dependency. aria-hidden because it carries no
 * information; it's the same purely-decorative treatment as
 * HeaderBotanical.
 */
export function HeroFlower() {
  return (
    <svg
      className="hero-flower"
      viewBox="0 0 140 120"
      aria-hidden="true"
      focusable="false"
    >
      <g fill="none" stroke="#a9c2a2" strokeWidth="3" strokeLinecap="round" opacity="0.8">
        <path d="M112 116 C 96 96, 90 74, 96 54" />
        <path d="M96 76 C 78 82, 64 78, 56 64" />
        <path d="M100 92 C 116 90, 126 80, 130 66" />
      </g>
      <g fill="#a9c2a2" opacity="0.75">
        <ellipse cx="60" cy="63" rx="13" ry="7" transform="rotate(18 60 63)" />
        <ellipse cx="123" cy="68" rx="13" ry="7" transform="rotate(-24 123 68)" />
      </g>
      <g transform="translate(94,40)">
        <g fill="#faf7f1" opacity="0.94">
          <ellipse cx="0" cy="-15" rx="8" ry="12" />
          <ellipse cx="0" cy="15" rx="8" ry="12" />
          <ellipse cx="-15" cy="0" rx="12" ry="8" />
          <ellipse cx="15" cy="0" rx="12" ry="8" />
          <ellipse cx="-10.6" cy="-10.6" rx="8" ry="11" transform="rotate(45 -10.6 -10.6)" />
          <ellipse cx="10.6" cy="10.6" rx="8" ry="11" transform="rotate(45 10.6 10.6)" />
        </g>
        <circle cx="0" cy="0" r="7" fill="#e9b44c" />
      </g>
    </svg>
  );
}
