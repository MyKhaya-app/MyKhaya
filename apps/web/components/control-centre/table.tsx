import type { ReactNode } from "react";

export type CcTableColumn<T> = {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  align?: "left" | "right";
};

/**
 * Consistent Control Centre table treatment: readable spacing, row hover,
 * and built-in loading/empty states so every page doesn't hand-roll its
 * own `<p role="status">Loading…</p>` / `<p className="quiet-state">`
 * pair around the `<table>`.
 */
export function CcTable<T>({
  columns,
  rows,
  rowKey,
  loading = false,
  emptyMessage = "No results.",
  caption,
}: {
  columns: CcTableColumn<T>[];
  rows: T[] | null;
  rowKey: (row: T) => string;
  loading?: boolean;
  emptyMessage?: ReactNode;
  caption?: string;
}) {
  if (loading || rows === null) {
    return <p role="status">Loading…</p>;
  }
  if (rows.length === 0) {
    return <p className="quiet-state">{emptyMessage}</p>;
  }
  return (
    <div className="table-scroll cc-table-scroll" tabIndex={0}>
      <table aria-label={caption}>
        {caption && <caption className="cc-visually-hidden">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} style={column.align === "right" ? { textAlign: "right" } : undefined}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} className="cc-table-row">
              {columns.map((column) => (
                <td key={column.key} style={column.align === "right" ? { textAlign: "right" } : undefined}>
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
