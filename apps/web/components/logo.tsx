export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="brand" aria-label="MyKhaya">
      <img className="brand-mark" src="/images/mykhaya-logo.png" alt="" aria-hidden="true" />
      {!compact && <span>MyKhaya</span>}
    </span>
  );
}
