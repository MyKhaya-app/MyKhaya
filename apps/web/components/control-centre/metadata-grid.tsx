import type { ReactNode } from "react";

/**
 * Compact label/value grid, 2-3 columns wide on desktop collapsing to 1
 * column under ~640px — replaces the old `<dl>` pattern of pinning the
 * label to the far-left edge and the value to the far-right edge of a very
 * wide page. Keeps `<dl>/<dt>/<dd>` semantics for assistive tech.
 */
/**
 * `columns="fixed-2"` switches from the default auto-fit column count
 * (2-3 depending on width) to exactly two columns on desktop — for pages
 * that deliberately pair each item with a specific counterpart on the
 * facing side (e.g. Template/Created, Owner account/Created by) rather
 * than letting the column count depend on viewport width.
 */
export function CcMetadataGrid({
  children,
  dense = false,
  columns = "auto",
}: {
  children: ReactNode;
  dense?: boolean;
  columns?: "auto" | "fixed-2";
}) {
  const columnsClass = columns === "fixed-2" ? "cc-metadata-grid-2col" : "";
  return (
    <dl className={`cc-metadata-grid ${dense ? "cc-metadata-grid-dense" : ""} ${columnsClass}`.trim()}>
      {children}
    </dl>
  );
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
