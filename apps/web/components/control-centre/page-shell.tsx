import type { ReactNode } from "react";

/**
 * Content container for every Control Centre page. `wide` relaxes the max
 * width for table-heavy pages (per the UI sweep: large datasets may
 * legitimately use more of the viewport than a metadata-driven detail page).
 */
export function CcPage({
  children,
  wide = false,
  className = "",
}: {
  children: ReactNode;
  wide?: boolean;
  className?: string;
}) {
  return (
    <main className={`platform-page cc-page ${wide ? "cc-page-wide" : ""} ${className}`.trim()}>
      {children}
    </main>
  );
}
