import type { ReactNode } from "react";

/**
 * Compact label/value grid, 2-3 columns wide on desktop collapsing to 1
 * column under ~640px — replaces the old `<dl>` pattern of pinning the
 * label to the far-left edge and the value to the far-right edge of a very
 * wide page. Keeps `<dl>/<dt>/<dd>` semantics for assistive tech.
 */
export function CcMetadataGrid({ children, dense = false }: { children: ReactNode; dense?: boolean }) {
  return <dl className={`cc-metadata-grid ${dense ? "cc-metadata-grid-dense" : ""}`.trim()}>{children}</dl>;
}

export function CcMetadataItem({
  label,
  children,
  span = false,
}: {
  label: ReactNode;
  children: ReactNode;
  span?: boolean;
}) {
  return (
    <div className={span ? "cc-metadata-item-span" : ""}>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
