export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="brand" aria-label="MyKhaya">
      <svg
        className="brand-mark"
        viewBox="0 0 48 50"
        role="img"
        aria-hidden="true"
      >
        <path d="M5 20 24 4l19 16v9L24 13 5 29z" fill="var(--colour-sage)" />
        <rect
          x="8"
          y="29"
          width="12"
          height="10"
          rx="3"
          fill="var(--colour-terracotta)"
        />
        <rect
          x="23"
          y="29"
          width="12"
          height="10"
          rx="3"
          fill="var(--colour-cream)"
        />
        <rect
          x="8"
          y="41"
          width="12"
          height="8"
          rx="3"
          fill="var(--colour-sage)"
        />
        <rect
          x="23"
          y="41"
          width="12"
          height="8"
          rx="3"
          fill="var(--colour-mustard)"
        />
      </svg>
      {!compact && <span>MyKhaya</span>}
    </span>
  );
}
