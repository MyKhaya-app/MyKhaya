"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { readableDate } from "@/components/platform-format";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcNotice } from "@/components/control-centre/status-message";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";

// "security", "administrators", "subscriptions", "incidents" and
// "settings" are deliberately not listed here — they now have dedicated
// pages (app/control-centre/security, .../administrators,
// .../subscriptions, .../incidents, .../settings), which Next.js resolves
// in preference to this dynamic route for those exact segments. This
// generic table view remains for sections with no bespoke UI.
const allowed: Record<string, string> = {
  users: "Users", homes: "Homes", health: "Health and diagnostics", jobs: "Jobs and scheduler",
  audit: "Administrative audit",
};

function flatten(payload: unknown): unknown[] {
  if (Array.isArray(payload)) return payload;
  if (payload && typeof payload === "object") {
    const object = payload as Record<string, unknown>;
    for (const key of ["items", "services", "settings"]) {
      if (Array.isArray(object[key])) return object[key];
    }
  }
  return payload ? [payload] : [];
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "Unavailable";
  if (typeof value === "object") return JSON.stringify(value);
  if (typeof value === "string") return /^\d{4}-\d{2}-\d{2}T/.test(value) ? readableDate(value) : value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "Unavailable";
}

export default function PlatformSection({ params }: { params: Promise<{ section: string }> }) {
  const { section } = use(params);
  const title = allowed[section];
  const [payload, setPayload] = useState<unknown>(null);
  const [error, setError] = useState("");

  async function load() {
    if (title) setPayload(await platformApi.get(`/${section}`));
  }

  useEffect(() => {
    load().catch((cause: Error) => setError(cause.message));
  }, [section, title]);

  const rows = flatten(payload);
  const columnKeys = Array.from(
    new Set(rows.flatMap((row) => (row && typeof row === "object" ? Object.keys(row) : []))),
  ).slice(0, 8);

  if (!title) return <p>Not found</p>;

  const columns: CcTableColumn<Record<string, unknown>>[] = columnKeys.map((key) => ({
    key,
    header: key.replaceAll("_", " "),
    render: (row) => {
      const value = row[key];
      if (key === "id" && (section === "users" || section === "homes")) {
        return (
          <Link className="table-link" href={`/${section}/${String(value)}`}>
            {String(value)}
          </Link>
        );
      }
      return displayValue(value);
    },
  }));

  return (
    <PlatformShell>
      <CcPage wide>
        <CcPageHeader eyebrow="Control Centre" title={title} />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        <CcTable
          columns={columns}
          rows={!payload && !error ? null : (rows as Record<string, unknown>[])}
          rowKey={(row) => (typeof row.id === "string" ? row.id : JSON.stringify(row))}
          emptyMessage="No records are available."
          caption={`${title} table`}
        />
      </CcPage>
    </PlatformShell>
  );
}
