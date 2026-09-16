"use client";

import { FormEvent, use, useEffect, useState } from "react";
import Link from "next/link";
import { platformApi } from "@mykhaya/api-client";
import { PlatformShell } from "@/components/platform-shell";
import { readableDate } from "@/components/platform-format";
import { CcPage } from "@/components/control-centre/page-shell";
import { CcPageHeader } from "@/components/control-centre/page-header";
import { CcNotice } from "@/components/control-centre/status-message";
import { CcTable, type CcTableColumn } from "@/components/control-centre/table";
import { CcToolbar } from "@/components/control-centre/toolbar";
import { CcBadge, type CcBadgeTone } from "@/components/control-centre/badge";

// "security", "administrators", "subscriptions", "incidents" and
// "settings" are deliberately not listed here — they now have dedicated
// pages (app/control-centre/security, .../administrators,
// .../subscriptions, .../incidents, .../settings), which Next.js resolves
// in preference to this dynamic route for those exact segments. This
// generic table view remains for sections with no bespoke UI.
const allowed: Record<string, string> = {
  users: "Users",
  homes: "Homes",
  health: "Health and diagnostics",
  jobs: "Jobs and scheduler",
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
  if (typeof value === "string")
    return /^\d{4}-\d{2}-\d{2}T/.test(value) ? readableDate(value) : value;
  if (typeof value === "number" || typeof value === "boolean")
    return String(value);
  return "Unavailable";
}

type PageResponse = {
  items: Record<string, unknown>[];
  page: number;
  page_size: number;
  total: number;
};

function lifecycleTone(value: unknown): CcBadgeTone {
  return value === "active"
    ? "success"
    : value === "disabled"
      ? "danger"
      : "neutral";
}

function lifecycleLabel(value: unknown): string {
  return typeof value === "string"
    ? value.charAt(0).toUpperCase() + value.slice(1)
    : "Unknown";
}

function ManagedList({ section }: { section: "users" | "homes" }) {
  const [data, setData] = useState<PageResponse | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [lifecycle, setLifecycle] = useState("active");
  const [verified, setVerified] = useState("all");
  const [page, setPage] = useState(1);

  useEffect(() => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: "25",
      lifecycle,
    });
    if (appliedQuery.trim()) params.set("q", appliedQuery.trim());
    if (section === "users" && verified !== "all")
      params.set("verified", verified);
    setData(null);
    setError("");
    platformApi
      .get<PageResponse>(`/${section}?${params.toString()}`)
      .then(setData)
      .catch((cause: Error) => setError(cause.message));
  }, [appliedQuery, lifecycle, page, section, verified]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage(1);
    setAppliedQuery(query);
  }

  const title = section === "users" ? "Users" : "Homes";
  const rows = data?.items ?? [];
  const columns: CcTableColumn<Record<string, unknown>>[] =
    section === "users"
      ? [
          {
            key: "name",
            header: "Name",
            render: (row) => <strong>{String(row.display_name)}</strong>,
          },
          {
            key: "email",
            header: "Email",
            render: (row) => <span className="cc-table-truncate" title={String(row.email)}>{String(row.email)}</span>,
          },
          {
            key: "lifecycle",
            header: "Status",
            render: (row) => (
              <CcBadge tone={lifecycleTone(row.lifecycle)}>
                {lifecycleLabel(row.lifecycle)}
              </CcBadge>
            ),
          },
          {
            key: "verified",
            header: "Verification",
            render: (row) => (
              <CcBadge tone={row.verified ? "success" : "warning"}>
                {row.verified ? "Verified" : "Unverified"}
              </CcBadge>
            ),
          },
          {
            key: "home_count",
            header: "Homes",
            align: "right",
            render: (row) =>
              typeof row.home_count === "number" ? row.home_count : 0,
          },
          {
            key: "last_login_at",
            header: "Last login",
            render: (row) =>
              row.last_login_at ? displayValue(row.last_login_at) : "Never",
          },
          {
            key: "last_activity_at",
            header: "Last active",
            render: (row) =>
              row.last_activity_at ? displayValue(row.last_activity_at) : "Never",
          },
          {
            key: "actions",
            header: "Actions",
            render: (row) => (
              <Link
                className="secondary cc-action"
                href={`/users/${String(row.id)}`}
              >
                View
              </Link>
            ),
          },
        ]
      : [
          {
            key: "name",
            header: "Home",
            render: (row) => <Link className="table-link" href={`/homes/${String(row.id)}`}>{String(row.name)}</Link>,
          },
          {
            key: "created",
            header: "Created",
            render: (row) => displayValue(row.created_at),
          },
          {
            key: "owner",
            header: "Home Admin",
            render: (row) => {
              const owner = row.owner as Record<string, unknown> | null;
              return owner ? (
                <strong>{String(owner.display_name)}</strong>
              ) : (
                "Unassigned"
              );
            },
          },
          {
            key: "admin_email",
            header: "Admin Email",
            render: (row) => {
              const owner = row.owner as Record<string, unknown> | null;
              return owner ? <span className="cc-table-truncate" title={String(owner.email)}>{String(owner.email)}</span> : "—";
            },
          },
          {
            key: "lifecycle",
            header: "Status",
            render: (row) => (
              <CcBadge tone={lifecycleTone(row.lifecycle)}>
                {lifecycleLabel(row.lifecycle)}
              </CcBadge>
            ),
          },
          {
            key: "member_count",
            header: "Members",
            align: "right",
            render: (row) =>
              typeof row.member_count === "number" ? row.member_count : 0,
          },
          {
            key: "invitation_count",
            header: "Invitations",
            align: "right",
            render: (row) =>
              typeof row.invitation_count === "number"
                ? row.invitation_count
                : 0,
          },
          {
            key: "actions",
            header: "Actions",
            render: (row) => (
              <Link
                className="secondary cc-action"
                href={`/homes/${String(row.id)}`}
              >
                View
              </Link>
            ),
          },
        ];
  const maxPage = data
    ? Math.max(1, Math.ceil(data.total / data.page_size))
    : 1;
  return (
    <PlatformShell>
      <CcPage wide>
        <CcPageHeader
          eyebrow="People"
          title={title}
          description={`Manage platform ${title.toLowerCase()} with compact operational lists.`}
        />
        <CcToolbar>
          <form className="cc-list-toolbar-form" onSubmit={submit}>
            <label>
              Search {title.toLowerCase()}
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={
                  section === "users" ? "Name or email" : "Home name"
                }
              />
            </label>
            <label>
              Lifecycle
              <select
                value={lifecycle}
                onChange={(event) => {
                  setPage(1);
                  setLifecycle(event.target.value);
                }}
              >
                <option value="active">Active</option>
                <option value="disabled">Disabled</option>
                <option value="archived">Archived</option>
                <option value="all">All</option>
              </select>
            </label>
            {section === "users" && (
              <label>
                Verification
                <select
                  value={verified}
                  onChange={(event) => {
                    setPage(1);
                    setVerified(event.target.value);
                  }}
                >
                  <option value="all">All</option>
                  <option value="true">Verified</option>
                  <option value="false">Unverified</option>
                </select>
              </label>
            )}
            <button type="submit" className="cc-action cc-action-primary">
              Search
            </button>
          </form>
        </CcToolbar>
        {error && (
          <CcNotice tone="error">
            Unable to load {title.toLowerCase()}: {error}
          </CcNotice>
        )}
        {data && (
          <p className="cc-page-meta">
            Showing {rows.length} of {data.total} {title.toLowerCase()}
          </p>
        )}
        <CcTable
          columns={columns}
          rows={data ? rows : null}
          rowKey={(row) => String(row.id)}
          emptyMessage={`No ${title.toLowerCase()} match these filters.`}
          caption={`${title} table`}
        />
        {data && maxPage > 1 && (
          <nav className="cc-pagination" aria-label={`${title} pages`}>
            <button
              type="button"
              className="secondary"
              disabled={page <= 1}
              onClick={() => setPage((value) => value - 1)}
            >
              Previous
            </button>
            <span>
              Page {page} of {maxPage}
            </span>
            <button
              type="button"
              className="secondary"
              disabled={page >= maxPage}
              onClick={() => setPage((value) => value + 1)}
            >
              Next
            </button>
          </nav>
        )}
      </CcPage>
    </PlatformShell>
  );
}

function GenericPlatformSection({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = use(params);
  if (section === "users" || section === "homes")
    return <ManagedList section={section} />;
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
    new Set(
      rows.flatMap((row) =>
        row && typeof row === "object" ? Object.keys(row) : [],
      ),
    ),
  ).slice(0, 8);

  if (!title) return <p>Not found</p>;

  const columns: CcTableColumn<Record<string, unknown>>[] = columnKeys.map(
    (key) => ({
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
    }),
  );

  return (
    <PlatformShell>
      <CcPage wide>
        <CcPageHeader eyebrow="Control Centre" title={title} />
        {error && <CcNotice tone="error">{error}</CcNotice>}
        <CcTable
          columns={columns}
          rows={!payload && !error ? null : (rows as Record<string, unknown>[])}
          rowKey={(row) =>
            typeof row.id === "string" ? row.id : JSON.stringify(row)
          }
          emptyMessage="No records are available."
          caption={`${title} table`}
        />
      </CcPage>
    </PlatformShell>
  );
}

export default function PlatformSection({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = use(params);
  return section === "users" || section === "homes" ? (
    <ManagedList section={section} />
  ) : (
    <GenericPlatformSection params={Promise.resolve({ section })} />
  );
}
